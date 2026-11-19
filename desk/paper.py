"""The desk's pretend practice account, for paper mode.

A small pretend account kept in one file on your computer. Auto paper (desk/auto.py) trades ready
signals in it, so you can watch how the desk's rules would have played out without risking money.
It answers simple questions (orders, balances, place, cancel) in the common nested order layout of
desk/orders.py. Nothing in this file talks to any broker, and no real order is ever placed.

How a practice order fills. Prices are Yahoo's free quotes (they can lag by a few seconds to 15
minutes), looked at about every half minute by the desk:
  buy LIMIT     fills when the price is at or under the limit
  sell LIMIT    fills when the price is at or over the limit
  sell STOP     fills when the price is at or under the stop
  sell MARKET   fills at the price
Practice shorts (docs/SHORTING.md), placed only in this account, never at a broker:
  SELL_SHORT LIMIT      fills when the price is at or over the limit; the short's full value is set aside
  BUY_TO_COVER STOP     fills when the price is at or over the stop
  BUY_TO_COVER LIMIT    fills when the price is at or under the limit
  BUY_TO_COVER MARKET   fills at the price
A stock is never long and short here at once, and a cover never buys more than is short.
If the day's low or high moved past a limit or stop between two looks, the order fills at its own
price. A STOP or MARKET fill (a stop-out, a flat-by-the-close sale, a cover) is moved against you by
est_cost_per_share, your slippage guess, because a real one fills at the market; limit fills are not. Orders fill whole, only while the market is open, and every order ends at the close like a DAY
order. Money from a sale can be spent the next trading day, like a cash account. Real fills differ:
this is for practising the steps, not for measuring results.
"""
import copy
import datetime
import json
import os
import threading
import time

from . import orders as O
from . import settings as S
from . import skills
from .paths import data_dir

ACCOUNT = "PAPER"
KEEP_DAYS = 10          # finished orders older than this are dropped from the file
QUOTE_SECONDS = 8       # one look at Yahoo serves the reads that follow it


class PaperError(Exception):
    """A practice-account action that could not be done, in plain words."""


def _legs(o):
    legs = o.get("orderLegCollection")
    return legs[0] if isinstance(legs, list) and legs and isinstance(legs[0], dict) else None


def _alive(top):
    """Is any real order in this tree still open? (The wrapper around a stop-and-target pair is not an order.)"""
    return any(o.get("status") in O.OPEN and _legs(o) for o in _walk(top))


def _walk(o):
    yield o
    for k in o.get("childOrderStrategies") or []:
        yield from _walk(k)


class PaperAccount:
    def __init__(self, desk):
        self.d = desk
        self.clock = time.time
        self.quotes = self._yahoo               # tests swap this
        self._lock = threading.RLock()
        self._seen = (0.0, {})

    # ---- the file ----------------------------------------------------------------
    @staticmethod
    def path():
        return data_dir() / "paper-account.json"

    def _fresh(self):
        return {"cash": round(float(S.load()["starting_balance"]), 2), "positions": {}, "orders": [], "next": 1,
                "unsettled": [], "marks": {}}

    def _load(self):
        """A missing file is a new account. A file that cannot be read is set aside, never silently replaced."""
        f = self.path()
        try:
            text = f.read_text()
        except FileNotFoundError:
            return self._fresh()
        except OSError as e:
            raise PaperError("The paper account's file could not be read (%s). Nothing was changed. Try again." % e)
        try:
            s = json.loads(text)
            if isinstance(s, dict) and isinstance(s.get("orders"), list) and isinstance(s.get("positions"), dict) \
                    and isinstance(s.get("cash"), (int, float)):
                for k, v in self._fresh().items():
                    s.setdefault(k, v)
                return s
        except ValueError:
            pass
        aside = f.with_name("paper-account.bad-%d.json" % int(time.time()))
        os.replace(str(f), str(aside))
        raise PaperError("The paper account's file was damaged, so it was set aside as %s and the paper account "
                          "starts over. Press Refresh." % aside.name)

    def _save(self, s):
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=1))
        os.replace(str(tmp), str(self.path()))

    def reset(self):
        with self._lock:
            self._save(self._fresh())

    # ---- prices ------------------------------------------------------------------
    def _yahoo(self, symbols):
        now = self.d.src.now()
        try:
            r = skills.run("alerts", ["quote"] + sorted(symbols) + ["--json"] + self.d.src.quotes_offline(),
                           self.d.scan_dir(now), timeout=60)
        except Exception:                       # no price is a plain "no price", never a crash
            return {}
        out = {}
        for sym, v in ((r.json or {}).get("quotes") or {}).items() if isinstance(r.json, dict) else []:
            if isinstance(v, dict) and isinstance(v.get("price"), (int, float)) and v["price"] > 0:
                out[sym] = {"price": float(v["price"]), "low": v.get("low"), "high": v.get("high")}
        return out

    def _look(self, symbols, fresh=False):
        """{symbol: {price, low, high}} for the symbols that have a price right now."""
        symbols = {s for s in symbols if s}
        at, have = self._seen
        if fresh or self.clock() - at > QUOTE_SECONDS:
            at, have = self.clock(), {}
        need = symbols - set(have)              # only what this look does not have yet (a miss is remembered too)
        if need:
            got = self.quotes(sorted(need)) or {}
            for sym in need:
                v = got.get(sym)
                p = v.get("price") if isinstance(v, dict) else None
                have[sym] = None
                if isinstance(p, (int, float)) and p > 0:
                    lo, hi = v.get("low"), v.get("high")
                    have[sym] = {"price": float(p),
                                 "low": float(lo) if isinstance(lo, (int, float)) and 0 < lo <= p else float(p),
                                 "high": float(hi) if isinstance(hi, (int, float)) and hi >= p else float(p)}
        self._seen = (at, have)
        return {s: have[s] for s in symbols if have.get(s)}

    def price(self, symbol):
        """One symbol's last price (from the latest look when it is fresh), or None when there is none."""
        with self._lock:
            return (self._look({symbol}).get(symbol) or {}).get("price")

    # ---- filling -----------------------------------------------------------------
    def _fill(self, s, o, px, now):
        leg = _legs(o)
        sym, side, qty = leg["instrument"]["symbol"], leg["instruction"], int(o["quantity"])
        if o.get("orderType") in ("STOP", "MARKET"):     # these go to the market: they pay the slippage guess
            slip = float(S.load().get("est_cost_per_share") or 0)
            px = float(px) + (slip if side in ("BUY", "BUY_TO_COVER") else -slip)
        px = round(max(float(px), 0.01), 2)
        pos = s["positions"].get(sym) or {"qty": 0, "cost": 0.0}
        if side in ("SELL_SHORT", "BUY_TO_COVER") or (side == "BUY" and pos["qty"] < 0):
            return self._fill_short(s, o, sym, side, qty, px, pos, now)
        if side == "BUY":
            s["cash"] = round(s["cash"] - qty * px, 2)
            pos = {"qty": pos["qty"] + qty, "cost": round(pos["cost"] + qty * px, 2)}
        else:
            if pos["qty"] < qty:                # nothing to sell: a practice account never goes short
                o["status"] = "REJECTED"
                return False
            s["cash"] = round(s["cash"] + qty * px, 2)
            s["unsettled"].append({"amount": round(qty * px, 2), "until": self.d.settle_date(now)})
            left = pos["qty"] - qty
            pos = {"qty": left, "cost": round(pos["cost"] * left / pos["qty"], 2)}
        if pos["qty"]:
            s["positions"][sym] = pos
        else:
            s["positions"].pop(sym, None)
        o.update(status="FILLED", filledQuantity=qty, remainingQuantity=0,
                 orderActivityCollection=[{"executionLegs": [{"quantity": qty, "price": px}]}])
        self._log_fill(o, "bought" if side == "BUY" else "sold", sym, qty, px, now)
        return True

    def _log_fill(self, o, did, sym, qty, px, now):
        try:                                    # every practice fill is in the paper journal's log, for the review
            self.d.j.add_event("paper", "Practice account: %s %d %s at %.2f (%s, order %s)."
                               % (did, qty, sym, px, str(o.get("orderType")).lower(), o.get("orderId")), now, sym)
        except Exception:
            pass

    def _fill_short(self, s, o, sym, side, qty, px, pos, now):
        """A practice short. Selling short sets the full value aside, like the journal does (no leverage);
        covering returns it plus or minus the result. A short position is a negative qty; its cost is the
        cash set aside. A plain BUY never covers: a cover must say BUY_TO_COVER."""
        if side == "SELL_SHORT" and pos["qty"] <= 0 and s["cash"] * S.leverage(S.load()) + 1e-9 >= qty * px:
            s["cash"] = round(s["cash"] - qty * px, 2)
            pos = {"qty": pos["qty"] - qty, "cost": round(pos["cost"] + qty * px, 2)}
        elif side == "BUY_TO_COVER" and -pos["qty"] >= qty:
            held = -pos["qty"]
            aside = pos["cost"] * qty / held
            back = round(2 * aside - qty * px, 2)          # the value set aside, plus (entry - cover) x shares
            s["cash"] = round(s["cash"] + back, 2)
            if back > 0:
                s["unsettled"].append({"amount": back, "until": self.d.settle_date(now)})
            left = held - qty
            pos = {"qty": -left, "cost": round(pos["cost"] - aside, 2)}
        else:                                   # long and short at once, a cover with nothing short, or no cash
            o["status"] = "REJECTED"
            return False
        if pos["qty"]:
            s["positions"][sym] = pos
        else:
            s["positions"].pop(sym, None)
        o.update(status="FILLED", filledQuantity=qty, remainingQuantity=0,
                 orderActivityCollection=[{"executionLegs": [{"quantity": qty, "price": px}]}])
        self._log_fill(o, "sold short" if side == "SELL_SHORT" else "bought to cover", sym, qty, px, now)
        return True

    @staticmethod
    def _fill_price(o, quote, mark):
        """The price this working order fills at now, or None."""
        leg, kind = _legs(o), o.get("orderType")
        side, p = leg["instruction"], quote["price"]
        new_low = quote["low"] if mark and quote["low"] < mark["low"] - 1e-9 else None
        new_high = quote["high"] if mark and quote["high"] > mark["high"] + 1e-9 else None
        if kind == "MARKET":
            return p if side in ("SELL", "BUY_TO_COVER") else None
        if kind == "STOP" and side == "BUY_TO_COVER":
            stop = float(o["stopPrice"])
            return p if p >= stop - 1e-9 else stop if new_high is not None and new_high >= stop - 1e-9 else None
        if kind == "LIMIT":
            lim = float(o["price"])
            if side in ("BUY", "BUY_TO_COVER"):
                return p if p <= lim + 1e-9 else lim if new_low is not None and new_low <= lim + 1e-9 else None
            return p if p >= lim - 1e-9 else lim if new_high is not None and new_high >= lim - 1e-9 else None
        if kind == "STOP" and side == "SELL":
            stop = float(o["stopPrice"])
            return p if p <= stop + 1e-9 else stop if new_low is not None and new_low <= stop + 1e-9 else None
        return None

    def _settle(self, s, fresh=False):
        now = self.d.src.now()
        day = now[:10]
        for top in s["orders"]:
            for o in _walk(top):
                if o.get("status") in O.OPEN and str(o.get("day") or day) < day:
                    o["status"] = "EXPIRED"     # every order is a DAY order
        s["unsettled"] = [u for u in s["unsettled"] if str(u.get("until")) > day]
        cut = (datetime.date.fromisoformat(day) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        s["orders"] = [t for t in s["orders"] if str(t.get("day") or day) >= cut
                       or _alive(t)]
        working = [o for t in s["orders"] for o in _walk(t) if o.get("status") == "WORKING" and _legs(o)]
        if not working or not self.d.clock(now).get("open"):
            return
        syms = {_legs(o)["instrument"]["symbol"] for o in working}
        quotes = self._look(syms, fresh)

        def mark(sym):
            m = s["marks"].get(sym)
            return m if isinstance(m, dict) and m.get("date") == day else None

        def step(o):
            """Fills what can fill. A stop or target that goes live in this pass waits for the next look."""
            leg = _legs(o)
            kids = o.get("childOrderStrategies") or []
            if leg is None:                     # the pair: a stop and a target that cancel each other
                # if both were reached between two looks, the stop wins: the careful answer
                for k in sorted(kids, key=lambda k: k.get("orderType") != "STOP"):
                    if k.get("status") == "WORKING" and _legs(k):
                        qt = quotes.get(_legs(k)["instrument"]["symbol"])
                        px = self._fill_price(k, qt, mark(_legs(k)["instrument"]["symbol"])) if qt else None
                        if px is not None and self._fill(s, k, px, now):
                            for other in kids:
                                if other is not k and other.get("status") in O.OPEN:
                                    other["status"] = "CANCELED"
                            break
                return
            if o.get("status") == "FILLED":
                for k in kids:
                    step(k)
                return
            if o.get("status") != "WORKING":
                return
            sym = leg["instrument"]["symbol"]
            qt = quotes.get(sym)
            px = self._fill_price(o, qt, mark(sym)) if qt else None
            if px is None:
                return
            if self._fill(s, o, px, now):
                for k in kids:
                    for c in _walk(k):
                        if c.get("status") == "AWAITING_PARENT_ORDER":
                            c["status"] = "WORKING"
            else:
                for k in kids:
                    for c in _walk(k):
                        c["status"] = "CANCELED"

        for top in s["orders"]:
            step(top)
        for sym, qt in quotes.items():
            s["marks"][sym] = {"date": day, "low": qt["low"], "high": qt["high"]}

    def settle(self):
        """The desk's half-minute look: fills whatever the price has reached. Does nothing with no open order."""
        with self._lock:
            s = self._load()
            if not any(_alive(t) for t in s["orders"]):
                return False
            self._settle(s, fresh=True)
            self._save(s)
            return True

    # ---- the account's questions: status, orders, balances, place, cancel -------------
    def status(self):
        return {"signed_in": True, "paper": True}

    def account_hash(self, pick=""):
        return ACCOUNT

    def orders(self, account_hash=ACCOUNT, hours=None):
        with self._lock:
            s = self._load()
            self._settle(s)
            self._save(s)
            return copy.deepcopy(s["orders"])

    def snapshot(self, account_hash=ACCOUNT):
        with self._lock:
            s = self._load()
            quotes = self._look(set(s["positions"])) if s["positions"] else {}
            positions, worth = [], 0.0
            for sym, p in sorted(s["positions"].items()):
                avg = round(p["cost"] / abs(p["qty"]), 4) if p["qty"] else None
                px = (quotes.get(sym) or {}).get("price") or avg or 0
                if p["qty"] < 0:                # a practice short: what is set aside, plus or minus the result
                    value = round(2 * p["cost"] + p["qty"] * px, 2)
                else:
                    value = round(p["qty"] * px, 2)
                worth += value
                positions.append({"symbol": sym, "qty": p["qty"], "avg_price": avg, "value": value,
                                  "side": "short" if p["qty"] < 0 else "long"})
            tied = sum(float(o.get("price") or 0) * int(o.get("remainingQuantity") or 0)
                       for t in s["orders"] for o in _walk(t)
                       if _legs(o) and _legs(o)["instruction"] in ("BUY", "SELL_SHORT") and o.get("status") in O.OPEN)
            waiting = round(sum(float(u.get("amount") or 0) for u in s["unsettled"]), 2)
            return {"account": "Paper (practice)", "type": "CASH", "value": round(s["cash"] + worth, 2),
                    "cash": s["cash"],   # paper buys with leverage x the account (settings.PAPER_LEVERAGE); 1x it is plain cash
                    "available": round(max(0.0, S.leverage(S.load()) * (s["cash"] + worth) - worth - waiting - tied), 2),
                    "unsettled": waiting, "positions": positions, "accounts": [], "at": self.clock()}

    def place_order(self, account_hash, order):
        if account_hash != ACCOUNT:
            raise PaperError("That is not the paper account. Nothing was placed.")
        try:
            return self._place(order)
        except PaperError:
            raise
        except Exception as e:                  # the file is only written at the very end, so nothing was placed
            raise PaperError("The paper account hit a problem (%s). Nothing was placed." % type(e).__name__)

    def _place(self, order):
        with self._lock:
            s = self._load()
            o = copy.deepcopy(order)
            top = _legs(o)
            if top is None:
                raise PaperError("The paper account only takes one order, or one buy with its stop and target.")
            sym = str(top["instrument"]["symbol"])
            quote = self._look({sym}, fresh=True).get(sym)
            if not quote:
                raise PaperError("No price could be found for %s right now, so the paper account cannot take "
                                  "this order. Nothing was placed." % sym)
            self._settle(s)
            now = self.d.src.now()
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.clock()))
            for n in _walk(o):
                n["orderId"] = s["next"]
                s["next"] += 1
                n["status"] = "WORKING" if n is o else "AWAITING_PARENT_ORDER"
                n["enteredTime"], n["day"] = stamp, now[:10]
                leg = _legs(n)
                if leg:
                    n["quantity"] = int(leg["quantity"])
                    n["filledQuantity"], n["remainingQuantity"] = 0, int(leg["quantity"])
            s["orders"].append(o)
            # start from now: a low or high set earlier today must not fill an order placed after it
            s["marks"][sym] = {"date": now[:10], "low": quote["low"], "high": quote["high"]}
            self._settle(s)
            self._save(s)
            return str(o["orderId"])

    def cancel_order(self, account_hash, order_id):
        if account_hash != ACCOUNT:
            raise PaperError("That is not the paper account. Nothing was cancelled.")
        with self._lock:
            s = self._load()
            self._settle(s)
            for top in s["orders"]:
                for o in _walk(top):
                    if str(o.get("orderId")) == str(order_id) and _legs(o):
                        if o.get("status") not in O.OPEN:
                            self._save(s)
                            raise PaperError("That paper order is already %s, so it cannot be cancelled."
                                              % str(o.get("status")).lower())
                        for c in _walk(o):
                            if c.get("status") in O.OPEN or not _legs(c):
                                c["status"] = "CANCELED"
                        self._save(s)
                        return
            raise PaperError("That order is not in the paper account.")


# ---- practice shorts -------------------------------------------------------------
def short_bracket(symbol, qty, limit, stop, target):
    """A practice short in the common order shape, for THIS account only: SELL_SHORT at limit (DAY); when it
    fills, BUY_TO_COVER at the stop (above) or at the target (below), one cancelling the other.
    desk/orders.py has no short order, so a short can only ever be practice."""
    sym = str(symbol or "").upper()
    if not O.TICKER.match(sym):
        raise ValueError("not a stock ticker: %r" % (symbol,))
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise ValueError("shares must be a whole number of 1 or more")
    lim, stp, tgt = (round(float(x), 2) for x in (limit, stop, target))
    if not 0 < tgt < lim < stp:
        raise ValueError("a short needs the target under the sell price and the stop over it")

    def leg(ins):
        return [{"instruction": ins, "quantity": qty, "instrument": {"symbol": sym, "assetType": "EQUITY"}}]
    cover_stop = {"orderType": "STOP", "session": "NORMAL", "stopPrice": "%.2f" % stp, "duration": "DAY",
                  "orderStrategyType": "SINGLE", "orderLegCollection": leg("BUY_TO_COVER")}
    cover_target = {"orderType": "LIMIT", "session": "NORMAL", "price": "%.2f" % tgt, "duration": "DAY",
                    "orderStrategyType": "SINGLE", "orderLegCollection": leg("BUY_TO_COVER")}
    return {"orderType": "LIMIT", "session": "NORMAL", "price": "%.2f" % lim, "duration": "DAY",
            "orderStrategyType": "TRIGGER", "orderLegCollection": leg("SELL_SHORT"),
            "childOrderStrategies": [{"orderStrategyType": "OCO", "childOrderStrategies": [cover_stop, cover_target]}]}


PRACTICE_SIDES = ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")


def rows(raw):
    """The practice account's orders as flat rows, practice shorts included (desk/auto.py reads these)."""
    return O.rows(raw, PRACTICE_SIDES)


def cover_market(symbol, qty):
    """Buy back a practice short at the market (flat by the close). Practice account only."""
    sym = str(symbol or "").upper()
    if not O.TICKER.match(sym) or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise ValueError("a cover needs a ticker and a whole number of shares")
    return {"orderType": "MARKET", "session": "NORMAL", "duration": "DAY", "orderStrategyType": "SINGLE",
            "orderLegCollection": [{"instruction": "BUY_TO_COVER", "quantity": qty,
                                    "instrument": {"symbol": sym, "assetType": "EQUITY"}}]}

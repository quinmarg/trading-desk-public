"""Auto paper: in paper mode, the desk takes each ready signal by itself into the practice account.

Rules that never bend:
- Paper mode only. In live mode tick() returns before it reads or writes anything.
- The practice account only (desk/paper.py, account "PAPER"). This file never talks to a broker;
  tests/test_auto.py checks that, and the practice account refuses any other account.
- The same checks a person's "I placed it" meets: the desk's halt rules (pause, entry window, trades per
  day, daily loss, settled cash), the loss per trade and the cash, all from the paper journal.
- Every entry and exit is written to the paper journal with note "auto", and every step is an event, so
  a review can compare the desk's own trades with yours.

How a trade runs: the slip's bracket order (BUY LIMIT, then a STOP and a target LIMIT) goes into the
practice account, which fills it from free delayed quotes. A short slip (docs/SHORTING.md) goes in as
its mirror: SELL_SHORT LIMIT, then a BUY_TO_COVER STOP above and LIMIT below (paper.short_bracket),
only while short signals are switched on; it is covered at the market at the flat-by time. A buy not filled by the slip's good-until time
is cancelled. At the flat-by time an open trade is sold at the market. Turning the switch off stops new
trades; the ones already running are finished by these same rules.
"""
from . import orders as O
from . import paper as P
from . import pipeline as P_
from . import settings as S
from .journal import JournalError

AUTO = "auto"           # trades.note for the desk's own trades
KEY = "auto_paper"      # the paper journal's record of every signal auto paper looked at
LIVE_STATES = ("working", "open")


def _closed_word(e):
    return "bought to cover" if e.get("side") == "short" else "sold"


class AutoPaper:
    def __init__(self, desk):
        self.d = desk

    # ---- the record --------------------------------------------------------------
    def book(self):
        return dict(self.d.j.get(KEY) or {})

    def claimed(self, signal_id):
        """Is auto paper trading this signal right now? (Then a person's fill or skip would double it.)"""
        e = self.book().get(str(signal_id)) or {}
        return e.get("state") in LIVE_STATES

    def summary(self, st):
        b = self.book() if st["mode"] == "paper" else {}
        return {"on": bool(st["auto_paper"]), "paper": st["mode"] == "paper",
                "working": sum(1 for e in b.values() if e.get("state") == "working"),
                "open": sum(1 for e in b.values() if e.get("state") == "open")}

    def _event(self, text, now, sym, key=None):
        self.d.j.add_event("auto", "Auto paper: " + text, now, sym, key=key)

    # ---- one pass ------------------------------------------------------------------
    def tick(self):
        """Follows the trades it has, then takes new ready signals. Returns what it did, or None in live."""
        with self.d.lock:                                   # a switch to live waits for this pass to end
            st = S.load()
            if st["mode"] != "paper":
                return None
            acct = self.d.paper
            if not isinstance(acct, P.PaperAccount) or acct.account_hash() != P.ACCOUNT:
                raise RuntimeError("auto paper only trades the practice account")
            now = self.d.src.now()
            book, out = self.book(), {"placed": 0, "filled": 0, "closed": 0, "cancelled": 0, "declined": 0}
            self._follow(acct, book, st, now, out)
            if st["auto_paper"]:
                self._take_new(acct, book, st, now, out)
                if out["placed"]:
                    self._follow(acct, book, st, now, out)  # a buy at or under the limit fills at once
            self.d.j.put(KEY, book)
            return out

    def _rows(self, acct):
        return {r["id"]: r for r in P.rows(acct.orders(P.ACCOUNT))}

    def _follow(self, acct, book, st, now, out):
        mine = {sid: e for sid, e in book.items() if e.get("state") in LIVE_STATES}
        if not mine:
            return
        rows = self._rows(acct)
        for sid, e in mine.items():
            sig = self.d.j.signal(int(sid)) or {}
            p, sym = sig.get("payload") or {}, e["symbol"]
            buy = rows.get(str(e["order_id"]))
            if e["state"] == "working":
                if buy is None or (buy["status"] != "FILLED" and not buy["open"]):
                    e["state"] = "unfilled"
                    self._event("the buy for %s ended unfilled (%s)." % (sym, (buy or {}).get("status", "gone").lower()),
                                now, sym)
                    continue
                if buy["status"] != "FILLED":
                    if now[11:16] > str(p.get("valid_until") or "99:99") or now[:10] > e["at"][:10]:
                        self._cancel(acct, buy["id"])
                        e["state"] = "unfilled"
                        out["cancelled"] += 1
                        self._event("%s did not come back to %.2f by %s, so the buy was cancelled."
                                    % (sym, p["limit"], p.get("valid_until")), now, sym)
                    continue
                price = round(buy["avg_fill"] or p["limit"], 2)
                try:
                    tid = self.d.j.open_trade(sym, e["qty"], price, p["stop"], p["target"], now, int(sid),
                                              p.get("flat_by"), note=AUTO, side=e.get("side") or "long")
                except JournalError as err:              # cannot happen after the checks below; never leave it
                    e.update(state="refused", why=str(err))
                    self._flatten(acct, e, rows)
                    self._event("the paper journal refused the fill for %s (%s), so it was sold again." % (sym, err),
                                now, sym)
                    continue
                e.update(state="open", trade_id=tid, entry=price, filled_at=now)
                out["filled"] += 1
                self._event("%s %d %s at %.2f. Stop %.2f, target %.2f, out by %s."
                            % ("sold short" if e.get("side") == "short" else "bought", e["qty"], sym, price,
                               p["stop"], p["target"], p.get("flat_by")), now, sym)
            if e["state"] != "open":
                continue
            kids = [r for r in rows.values() if r["parent"] == str(e["order_id"])]
            done = rows.get(str(e.get("flat_order"))) if e.get("flat_order") else None
            done = done if done and done["status"] == "FILLED" else next((r for r in kids if r["status"] == "FILLED"), None)
            if done:
                reason = "flat" if str(done["id"]) == str(e.get("flat_order")) else "stop" if done["type"] == "STOP" else "target"
                price = round(done["avg_fill"] or done["price"] or done["stop"], 2)
                pnl = self.d.j.close_trade(e["trade_id"], price, reason, now, self.d.settle_date(now))
                e.update(state="closed", exit=price, reason=reason, pnl=pnl, closed_at=now)
                out["closed"] += 1
                self._event("%s %d %s at %.2f (%s). %s $%.2f." % (_closed_word(e), e["qty"], sym, price, reason,
                                                                 "Made" if pnl >= 0 else "Lost", abs(pnl)), now, sym)
                continue
            flat_by = min(str(p.get("flat_by") or st["flat_by"]), self.d.day_flat_by(st, now))   # early close: 12:55
            late = now[:10] > str(e.get("filled_at") or e["at"])[:10] or now[11:16] >= flat_by
            if late and not e.get("flat_order") and self.d.clock(now).get("open"):
                oid = self._flatten(acct, e, rows)
                if oid:
                    self._event("%s is still open at %s: %s at the market."
                                % (sym, flat_by, "buying to cover" if e.get("side") == "short" else "selling"), now, sym)
                    rows = self._rows(acct)
                    fo = rows.get(str(oid))
                    if fo and fo["status"] == "FILLED":
                        price = round(fo["avg_fill"], 2)
                        pnl = self.d.j.close_trade(e["trade_id"], price, "flat", now, self.d.settle_date(now))
                        e.update(state="closed", exit=price, reason="flat", pnl=pnl, closed_at=now)
                        out["closed"] += 1
                        self._event("%s %d %s at %.2f (flat by the close). %s $%.2f."
                                    % (_closed_word(e), e["qty"], sym, price, "Made" if pnl >= 0 else "Lost", abs(pnl)),
                                    now, sym)

    def _cancel(self, acct, order_id):
        try:
            acct.cancel_order(P.ACCOUNT, order_id)
        except P.PaperError:                           # already filled or gone: the next pass sees it
            pass

    def _flatten(self, acct, e, rows):
        """Cancels the stop and target, then sells the shares (or covers the short) at the market.
        Returns that order's id or None."""
        for r in rows.values():
            if r["parent"] == str(e["order_id"]) and r["open"]:
                self._cancel(acct, r["id"])
        out = P.cover_market(e["symbol"], int(e["qty"])) if e.get("side") == "short" \
            else O.single(e["symbol"], "SELL", int(e["qty"]), "MARKET")
        try:
            oid = acct.place_order(P.ACCOUNT, out)
        except P.PaperError:                           # no price right now: try again on the next pass
            return None
        e["flat_order"] = oid
        return oid

    def _take_new(self, acct, book, st, now, out):
        if self.d.halt_reason(st, now):
            return
        working = [e for e in book.values() if e.get("state") == "working"]
        held = round(sum(float(e.get("cost") or 0) for e in working), 2)
        # your own risk when Claude's day cut would refuse a one-share-floor slip (pipeline.own_risk, T3)
        lim = S.limits(P_.own_risk(st, self.d.j, now[:10]) or st, self.d.j.equity())
        # weak = the Time Machine odds are under your floor; practice only, so it may take them to learn
        statuses = ("ready", "weak") if st["auto_paper_weak"] else ("ready",)
        for s in sorted(self.d.j.signals(date=now[:10], statuses=statuses), key=lambda s: s["id"]):
            sid, p = str(s["id"]), s["payload"]
            if sid in book:
                continue
            sym = p["symbol"]
            if p.get("valid_until") and now[11:16] > str(p["valid_until"]):
                continue                                # the monitor marks it expired
            short = p.get("side") == "short"
            if short and st["directions"] == "long":
                continue                                # short signals switched off: leave it, the slip says so
            why = None
            day = self.d.j.day(now[:10])
            qty = int(p.get("qty") or 0)
            # a short sets aside its value at the stop, the most it can be worth before it is out (desk/shorts.py)
            cost = round(qty * (p["stop"] if short else p["limit"]), 2)
            risk = round(qty * abs(p["limit"] - p["stop"]), 2)
            if self.d.halt_reason(st, now):
                return
            if day["trades"] + len(working) >= S.trades_cap(st):
                why = "%d of %d trades today already" % (day["trades"] + len(working), S.trades_cap(st))
            elif qty < 1:
                why = "no size"
            elif risk > lim["max_loss_per_trade"] + 0.005:
                why = "risk $%.2f is over the $%.2f limit a trade" % (risk, lim["max_loss_per_trade"])
            elif cost > self.d.spendable(st, now) - held + 0.005:
                why = "costs $%.2f and $%.2f of settled cash is free" % (cost, max(0.0, self.d.spendable(st, now) - held))
            if not why:                                 # the move already failed: the buy would fill and stop out at once
                px = acct.price(sym)
                if px is not None and (px >= p["stop"] if short else px <= p["stop"]):
                    why = "the price %.2f is already at or past the stop %.2f" % (px, p["stop"])
            if why:
                book[sid] = {"state": "declined", "symbol": sym, "why": why, "at": now}
                out["declined"] += 1
                self._event("left %s alone: %s." % (sym, why), now, sym)
                continue
            try:
                order = P.short_bracket(sym, qty, p["limit"], p["stop"], p["target"]) if short \
                    else O.bracket(sym, qty, p["limit"], p["stop"], p["target"])
                oid = acct.place_order(P.ACCOUNT, order)
            except (ValueError, P.PaperError) as err:
                self._event("could not place %s (%s). It tries again on the next pass." % (sym, err), now, sym,
                            key="auto-noplace-%s" % sid)
                continue
            book[sid] = {"state": "working", "order_id": str(oid), "symbol": sym, "qty": qty, "cost": cost, "at": now,
                         "side": "short" if short else "long"}
            working.append(book[sid])
            held = round(held + cost, 2)
            out["placed"] += 1
            if short:
                self._event("placed a practice SELL SHORT %d %s LIMIT %.2f, then BUY TO COVER STOP %.2f / LIMIT %.2f, "
                            "good until %s." % (qty, sym, p["limit"], p["stop"], p["target"], p.get("valid_until")), now, sym)
            else:
                self._event("placed BUY %d %s LIMIT %.2f, then STOP %.2f / LIMIT %.2f, good until %s."
                            % (qty, sym, p["limit"], p["stop"], p["target"], p.get("valid_until")), now, sym)

    # ---- when a person steps in ------------------------------------------------------
    def release(self, signal_id, why):
        """Cancels auto paper's waiting buy for a signal (you skipped it). An open trade is left to its rules."""
        with self.d.lock:
            book = self.book()
            e = book.get(str(signal_id))
            if not e or e.get("state") != "working":
                return False
            self._cancel(self.d.paper, e["order_id"])
            e["state"] = "cancelled"
            self.d.j.put(KEY, book)
            self._event("cancelled the buy for %s (%s)." % (e["symbol"], why), self.d.src.now(), e["symbol"])
            return True

    def cancel_working(self, why):
        """Cancels every waiting buy (before a switch to live). Returns how many."""
        with self.d.lock:
            n = 0
            for sid, e in self.book().items():
                if e.get("state") == "working":
                    n += self.release(sid, why)
            return n

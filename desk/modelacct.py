"""Separate practice accounts for the desk's two SPY models (docs/MODELS.md, "Their own paper accounts").

Each model (desk/combo.py, desk/winter3x.py) owns one folder, data/accounts/<name>/:
  model.json   the model's record: every trading day it ran, what its rule said, and the fill it got
  journal.db   the same journal file every desk account has: the cash ledger and the trades, rebuilt from model.json
               on every run, so the Graph tab and anyone reading the journal see the account's real trades

The account is worked out again from the recorded days on every run (a replay), so it can never drift from the rules.
How it is made as close to a real U.S. cash brokerage account as the research found (docs/MODELS.md has the sources):
  - it starts with the same cash as your practice account (settings: starting_balance) and buys fractional shares:
    large U.S. brokers sell fractional shares of thousands of stocks and ETFs, $1 or more, no commission;
  - a trade is a market order at the first price after 9:35 New York, plus the guide's cost a side (3 bp SPY, 5 bp
    UPRO), which is more than SPY's and UPRO's real spread and covers the SEC fee on sales;
  - idle cash earns a typical broker's bank sweep rate (SWEEP_APY), not the T-bill rate the guides' backtests assumed, and
    the month's interest is paid into cash when the next month starts;
  - a dividend is earned by the shares held at the close before the ex-date and paid in cash on the pay date
    (owed until then); the winter 3x book reinvests it on the pay date (free dividend reinvestment, as large brokers offer);
  - money from a sale settles the next trading day (T+1). A cash account may buy with it at once; selling that
    purchase before the money settles would be a good-faith violation, which is counted and shown (the rules trade at
    most once a day, so it should stay at zero).
Practice money only. Nothing here can place an order anywhere, live or practice.
"""
import datetime
import math
import sqlite3

from .paths import home_dir
from .skills import read_json, write_json

SWEEP_APY = 0.01      # % a year: a large broker's default bank sweep for a plain brokerage account (2026-11-10); set yours
SWEEP_CHECKED = "2026-11-19"
MIN_ORDER = 1.0       # a typical fractional-share minimum, dollars
SHARE_DP = 5          # fractional shares are kept to 5 decimals, rounded down


def folder(name):
    return home_dir() / "accounts" / name


def path(name):
    return folder(name) / "model.json"


def load(name):
    return read_json(path(name), None) or {}


def save(name, state):
    write_json(path(name), state)


def _floor(x):
    return math.floor(x * 10 ** SHARE_DP + 1e-9) / 10 ** SHARE_DP


def _next_open(day):
    from . import combo
    return combo.next_open(day)


def pay_date(symbol, ex):
    """When a dividend with this ex-date is paid. SPY pays on the last trading day of the month after its ex-date month
    (ex in March, paid at the end of April). shortcut: other funds (UPRO) are taken as paid a week after the ex-date,
    near ProShares' usual gap; read the fund's own schedule if a pay date ever matters to the cent."""
    from . import combo
    d = datetime.date.fromisoformat(ex)
    if symbol == "SPY":
        y, m = (d.year + (d.month + 1 > 12), (d.month % 12) + 1)
        last = datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)
        while not combo.is_open(last.isoformat()):
            last -= datetime.timedelta(days=1)
        return last.isoformat()
    p = (d + datetime.timedelta(days=7)).isoformat()
    return p if combo.is_open(p) else _next_open(p)


def _dd(xs):
    peak, worst = xs[0], 0.0
    for x in xs:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1)
    return round(100 * worst, 2)


def replay(days, closes, divs, start, costs, drip=False, sweep_apy=SWEEP_APY, bench="SPY"):
    """Work the account out from the recorded days.

    days: [{date, target: {symbol: weight}, fills: {symbol: price}, fill_at, how}] oldest first. The account trades
    to the day's target at the day's fills when the target differs from the day before (the guides' rule).
    closes / divs: {symbol: {date: close}} / {symbol: {ex-date: $ a share}}. costs: {symbol: bp a side}.
    Returns the account: cash, positions, orders, round-trip trades, ledger, curve against buy-and-hold `bench`."""
    cash, pos, owed, unsettled = float(start), {}, [], []
    orders, trades, ledger, curve, gfv = [], [], [], [], []
    interest = accrued = dividends = paid_costs = 0.0
    bh, bh_owed, prev = 0.0, [], None
    first = days[0]["date"] if days else None
    if first:
        ledger.append({"date": first, "kind": "deposit", "amount": round(start, 2), "settles_on": first,
                       "note": "starting balance (same as your practice account)"})

    def px(sym, day, d):
        return closes.get(sym, {}).get(day, d["fills"].get(sym))

    def order(d, sym, side, qty, price):
        nonlocal cash, paid_costs
        amount = qty * price
        cost = amount * costs.get(sym, 0.0) / 1e4
        paid_costs += cost
        settled = cash - sum(u["amount"] for u in unsettled)
        if side == "buy":
            cash -= amount + cost
            p = pos.setdefault(sym, {"qty": 0.0, "cost": 0.0, "since": d["fill_at"], "paid_by": None})
            p["qty"] = round(p["qty"] + qty, SHARE_DP)
            p["cost"] += amount + cost
            if settled < amount + cost - 0.005 and unsettled:     # paid partly with money that has not settled yet
                p["paid_by"] = max([p["paid_by"] or ""] + [u["until"] for u in unsettled])
            ledger.append({"date": d["date"], "kind": "buy", "amount": -round(amount + cost, 2),
                           "settles_on": d["date"], "note": "buy %s %s at %.2f" % (qty, sym, price)})
        else:
            p = pos[sym]
            if p["paid_by"] and d["date"] < p["paid_by"]:
                gfv.append({"date": d["date"], "symbol": sym, "until": p["paid_by"]})
            basis = p["cost"] * qty / p["qty"]
            back = amount - cost
            cash += back
            until = _next_open(d["date"])
            unsettled.append({"amount": back, "until": until})
            trades.append({"symbol": sym, "qty": qty, "entry_price": round(basis / qty, 4), "entry_at": p["since"],
                           "exit_price": price, "exit_at": d["fill_at"], "pnl": round(back - basis, 2)})
            p["qty"] = round(p["qty"] - qty, SHARE_DP)
            p["cost"] -= basis
            if p["qty"] <= 0:
                pos.pop(sym)
            ledger.append({"date": d["date"], "kind": "sell", "amount": round(back, 2), "settles_on": until,
                           "note": "sell %s %s at %.2f" % (qty, sym, price)})
        orders.append({"date": d["date"], "at": d["fill_at"], "how": d.get("how", "live"), "symbol": sym,
                       "side": side, "qty": qty, "price": round(price, 4), "amount": round(amount, 2),
                       "cost": round(cost, 2), "type": "MARKET (fractional, dollar-based)"})

    for n, d in enumerate(days):
        day, fills = d["date"], d["fills"]
        unsettled[:] = [u for u in unsettled if u["until"] > day]
        if accrued and day[:7] != days[n - 1]["date"][:7]:      # the sweep pays the month's interest into cash
            cash += accrued
            ledger.append({"date": day, "kind": "interest", "amount": round(accrued, 2), "settles_on": day,
                           "note": "bank sweep interest for %s" % days[n - 1]["date"][:7]})
            accrued = 0.0
        if n and cash > 0 and sweep_apy:
            i = cash * sweep_apy / 100.0 / 252
            interest += i
            accrued += i
        for sym, p in pos.items():                                # shares held at the close before the ex-date
            a = p["qty"] * divs.get(sym, {}).get(day, 0.0)
            if a > 0:
                owed.append({"symbol": sym, "amount": a, "pay": pay_date(sym, day), "ex": day})
        b = bh * divs.get(bench, {}).get(day, 0.0)
        if b > 0:
            bh_owed.append({"amount": b, "pay": pay_date(bench, day)})
        for o in [o for o in owed if o["pay"] <= day]:
            owed.remove(o)
            cash += o["amount"]
            dividends += o["amount"]
            ledger.append({"date": day, "kind": "dividend", "amount": round(o["amount"], 2), "settles_on": day,
                           "note": "%s dividend, ex %s" % (o["symbol"], o["ex"])})
            if drip and o["symbol"] in pos and o["symbol"] in fills:    # reinvested at the pay date's price, no cost
                q = _floor(o["amount"] / fills[o["symbol"]])
                if q > 0:
                    cash -= q * fills[o["symbol"]]
                    p = pos[o["symbol"]]
                    p["qty"] = round(p["qty"] + q, SHARE_DP)
                    p["cost"] += q * fills[o["symbol"]]
                    ledger.append({"date": day, "kind": "reinvest", "amount": -round(q * fills[o["symbol"]], 2),
                                   "settles_on": day, "note": "dividend reinvested: %s %s" % (q, o["symbol"])})
        for o in [o for o in bh_owed if o["pay"] <= day]:
            bh_owed.remove(o)
            bh += o["amount"] / px(bench, day, d)
        if bh == 0.0:
            bh = start / (fills[bench] * (1 + costs.get(bench, 0.0) / 1e4))
        target = d["target"]
        if target != prev:
            worth = cash + accrued + sum(o["amount"] for o in owed) + sum(p["qty"] * fills[s] for s, p in pos.items())
            for sym in sorted(pos):                               # sells first, so a switch can use the money
                want = target.get(sym, 0.0) * worth / fills[sym]
                q = pos[sym]["qty"] if want <= 0 else _floor(pos[sym]["qty"] - want)
                if q > 0 and q * fills[sym] >= MIN_ORDER:
                    order(d, sym, "sell", q, fills[sym])
            for sym, w in sorted(target.items()):
                if w <= 0:
                    continue
                have = pos.get(sym, {}).get("qty", 0.0) * fills[sym]
                spend = min(w * worth - have, cash) / (1 + costs.get(sym, 0.0) / 1e4)
                q = _floor(spend / fills[sym])
                if q > 0 and q * fills[sym] >= MIN_ORDER:
                    order(d, sym, "buy", q, fills[sym])
            prev = target
        eq = cash + accrued + sum(o["amount"] for o in owed) + sum(p["qty"] * px(s, day, d) for s, p in pos.items())
        spy = bh * px(bench, day, d) + sum(o["amount"] for o in bh_owed)
        curve.append({"date": day, "equity": round(eq, 2), "spy": round(spy, 2)})
    if not curve:
        return None
    last, today = curve[-1], days[-1]["date"]
    for t in trades:
        t["note"] = "model"
    open_trades = [{"symbol": s, "qty": p["qty"], "entry_price": round(p["cost"] / p["qty"], 4), "entry_at": p["since"]}
                   for s, p in sorted(pos.items())]
    waiting = sum(u["amount"] for u in unsettled if u["until"] > today)
    return {"start": round(start, 2), "equity": last["equity"], "spy": last["spy"], "cash": round(cash, 2),
            "settled_cash": round(cash - waiting, 2),
            "unsettled": [{"amount": round(u["amount"], 2), "until": u["until"]} for u in unsettled if u["until"] > today],
            "owed": [{"symbol": o["symbol"], "amount": round(o["amount"], 2), "pay": o["pay"]} for o in owed],
            "positions": [{"symbol": s, "qty": p["qty"], "avg_price": round(p["cost"] / p["qty"], 4),
                           "value": round(p["qty"] * px(s, today, days[-1]), 2)} for s, p in sorted(pos.items())],
            "holding": "+".join(sorted(pos)) or "cash", "orders": orders, "trades": trades, "open_trades": open_trades,
            "ledger": ledger, "curve": curve, "good_faith_violations": gfv,
            "interest": round(interest, 2), "interest_owed": round(accrued, 2), "dividends": round(dividends, 2), "costs": round(paid_costs, 2),
            "sweep_apy": sweep_apy, "return_pct": round(100 * (last["equity"] / start - 1), 2),
            "spy_return_pct": round(100 * (last["spy"] / start - 1), 2),
            "max_dd_pct": _dd([c["equity"] for c in curve]), "spy_max_dd_pct": _dd([c["spy"] for c in curve])}


def write_journal(name, acct):
    """Rebuild data/accounts/<name>/journal.db from the replay: the ledger, the closed round trips and what is open.
    The model owns this journal; nothing else writes to it."""
    from .journal import Journal
    folder(name).mkdir(parents=True, exist_ok=True)
    j = Journal(folder(name) / "journal.db")
    try:
        with j._tx() as db:
            db.execute("DELETE FROM trades")
            db.execute("DELETE FROM ledger")
            for r in acct["ledger"]:
                db.execute("INSERT INTO ledger(ts,date,kind,amount,settles_on,note) VALUES(?,?,?,?,?,?)",
                           (r["date"] + " 09:35", r["date"], r["kind"], r["amount"], r["settles_on"], r["note"]))
            for t in acct["trades"]:
                db.execute("INSERT INTO trades(date,symbol,qty,entry_price,entry_at,stop,target,status,exit_price,"
                           "exit_at,exit_reason,pnl,note) VALUES(?,?,?,?,?,0,0,'closed',?,?,'manual',?,?)",
                           (t["exit_at"][:10], t["symbol"], t["qty"], t["entry_price"], t["entry_at"], t["exit_price"],
                            t["exit_at"], t["pnl"], "model: %s" % name))
            for t in acct["open_trades"]:
                db.execute("INSERT INTO trades(date,symbol,qty,entry_price,entry_at,stop,target,status,note) "
                           "VALUES(?,?,?,?,?,0,0,'open',?)",
                           (t["entry_at"][:10], t["symbol"], t["qty"], t["entry_price"], t["entry_at"], "model: %s" % name))
            db.execute("INSERT INTO kv(key,value) VALUES('seeded','true') ON CONFLICT(key) DO NOTHING")
    finally:
        j.close()


def journal_trades(name):
    """The account's trades as its journal holds them, newest first ([] before the first run). Read-only."""
    f = folder(name) / "journal.db"
    if not f.exists():
        return []
    db = sqlite3.connect(f.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM trades ORDER BY id DESC")]
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()


def migrate(name, start=None):
    """Move an old single-file book (data/<name>.json, a $10,000 record with no account) into its own account folder.
    Keeps the recorded days, so the forward record continues from its first day; the next run works the account out
    again at the practice account's starting cash. The old file is kept, renamed <name>.json.migrated.
    Returns what it did, or None when there is nothing to move."""
    old = home_dir() / ("%s.json" % name)
    if not old.exists() or path(name).exists():
        return None
    s = read_json(old, None)
    if not isinstance(s, dict):
        return None
    if start is None:
        from . import settings as S
        start = float(S.load()["starting_balance"])
    keep = {k: s[k] for k in ("days", "next", "checked", "error", "spy") if k in s}
    keep["start_equity"] = float(start)
    keep["migrated_from"] = {"file": old.name, "start_equity": s.get("start_equity"), "at": s.get("checked")}
    save(name, keep)
    old.rename(old.with_name(old.name + ".migrated"))
    return {"account": name, "days": len(keep.get("days") or []), "start_equity": start}

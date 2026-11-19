"""The winter 3x book: a third paper book, the best finalist of research/beat_spy (added to the desk on request).

Rule, decided from SPY's close before the day (adjusted closes, the same 200-day average as desk/combo.py):
  SPY above its 200-day average and the day in November to April  -> all in UPRO (3x S&P 500, daily reset)
  SPY above its 200-day average and the day in May to October     -> all in SPY
  SPY at or below its 200-day average                             -> cash, earning the 13-week T-bill (^IRX)

It did NOT pass its sealed test (research/beat_spy/REPORT.md): in 2010-2026 it made 14.2 % a year against SPY's
13.8 % and the combined book's 11.1 %, with a worst drop of -48 % against -34 % and -26 %, p = 0.47 (luck can't be
ruled out), and it lost to SPY after tax. UPRO fell about 77 % in five weeks in 2020. So this is a forward practice
record only: it never places an order.

Its own practice account (desk/modelacct.py, data/accounts/winter3x/), run as desk/combo.py's: the practice account's
starting cash, fractional shares, a market order at the first price after 9:35 New York plus 3 bp a side on SPY and
5 bp on UPRO, a switch sells first and buys with the (unsettled, T+1) proceeds as a cash account may, dividends
reinvested on their pay date (free dividend reinvestment), idle cash at a typical broker's bank sweep rate. Missed
days are backfilled at that day's open. UPRO's 0.88 % a year fee is already inside its price. The card compares it
with the combined account and buy-and-hold SPY over the same days. State: data/accounts/winter3x/. Read-only Yahoo
GETs, two a run (SPY, UPRO).
"""
from . import combo, modelacct

NAME = "winter3x"
COSTS = {"SPY": 3.0, "UPRO": 5.0}           # basis points a side
TEST = {"period": "2010-2026 (sealed test, run once)", "book": 14.2, "combo": 11.1, "spy": 13.8,
        "book_dd": -48.4, "combo_dd": -26.2, "spy_dd": -33.7, "p": 0.47}


def path():
    return modelacct.path(NAME)


def fetch(symbol, timeout=20):
    return combo.fetch(timeout=timeout, symbol=symbol)


def hold_for(state, day):
    """What to hold on `day`, from the indicators() row of the close before it."""
    if not state["bull"]:
        return "cash"
    return "UPRO" if int(day[5:7]) in combo.WINTER else "SPY"


def book(days, prices, divs, start):
    """The account, worked out from the recorded days (desk/modelacct.py): all in the day's holding at its fills when
    the holding changes, dividends reinvested on their pay date. prices: {sym: {date: close}}; divs: {sym: {date: $}}."""
    return modelacct.replay([dict(d, target={} if d["hold"] == "cash" else {d["hold"]: 1.0}) for d in days],
                            prices, divs, start, COSTS, drip=True)


def load():
    modelacct.migrate(NAME)            # once: an old data/winter3x.json book moves into its own account folder
    return modelacct.load(NAME)


def due(now, state=None):
    return combo.due(now, load() if state is None else state)


def run(now, data=None):
    """Bring the account up to `now`. data: {"SPY": (rows, divs, live), "UPRO": (...)} as combo.parse gives; fetched
    when None. Returns the saved state."""
    s = load()
    start = combo.start_equity(s)
    data = data or {k: fetch(k) for k in ("SPY", "UPRO")}
    rows = data["SPY"][0]
    opens = {k: {r["date"]: r["o"] for r in v[0]} for k, v in data.items()}
    closes = {k: {r["date"]: r["c"] for r in v[0]} for k, v in data.items()}
    divs = {k: v[1] for k, v in data.items()}
    live = {k: v[2] for k, v in data.items()}
    today = now[:10]
    days = list(s.get("days") or [])
    first = days[-1]["date"] if days else None
    marks = combo.indicators([r["adj"] for r in rows])
    for i, r in enumerate(rows):
        d = r["date"]
        if i == 0 or (first is None and d != today) or (first is not None and d <= first) or d > today:
            continue
        if marks[i - 1]["sma200"] is None:
            continue
        if d == today:
            if not (now[11:16] >= combo.RUN_FROM and combo.is_open(today)):
                continue
            if not all(live[k] and live[k][1][:10] == today for k in live):
                continue                                  # no price from today yet: try again later
            fills, at, how = {k: live[k][0] for k in live}, live["SPY"][1], "live"
        else:
            if not all(d in opens[k] for k in opens):
                continue
            fills, at, how = {k: opens[k][d] for k in opens}, d + " 09:30", "backfill"
        days.append({"date": d, "hold": hold_for(marks[i - 1], d), "fills": {k: round(v, 4) for k, v in fills.items()},
                     "fill_at": at, "how": how})
    acct = book(days, closes, divs, start) if days else None
    closed = [i for i, r in enumerate(rows) if r["date"] < today or (r["date"] == today and now[11:16] >= "16:00")]
    last_i = closed[-1] if closed else None
    nxt = None
    if last_i is not None and marks[last_i]["sma200"] is not None:
        nd = combo.next_open(rows[last_i]["date"])
        nxt = {"date": nd, "hold": hold_for(marks[last_i], nd), "from_close_of": rows[last_i]["date"]}
    m = marks[last_i] if last_i is not None else {}
    s.update({"days": days, "account": acct, "next": nxt, "checked": now, "error": None, "spy": {"as_of": rows[last_i]["date"] if last_i is not None else None,
                                     "close": rows[last_i]["c"] if last_i is not None else None,
                                     "sma200": round(m["sma200"], 2) if m.get("sma200") else None}})
    modelacct.save(NAME, s)
    if acct:
        modelacct.write_journal(NAME, acct)
    return s


def note_error(now, err):
    s = load()
    s.update({"checked": now, "error": str(err)[:200]})
    modelacct.save(NAME, s)
    return s


def vs_combo(start):
    """The combined account's return over the same days as this one, or None if it started later than this one."""
    curve = (combo.load().get("account") or {}).get("curve") or []
    if not curve or curve[0]["date"] > start:
        return None
    before = [c for c in curve if c["date"] < start]
    base = before[-1]["equity"] if before else combo.load()["account"]["start"]
    return {"return_pct": round(100 * (curve[-1]["equity"] / base - 1), 2), "since": start}


def view():
    """What /api/winter3x and the Desk card show. Reads files only: no network."""
    s = load()
    base = {"paper_only": True, "test": TEST, "checked": s.get("checked"), "error": s.get("error"), "next": s.get("next")}
    if not s.get("days") or not s.get("account"):
        return dict(base, started=False,
                    note="The winter 3x account starts on the first trading day the desk runs after 9:35 New York.")
    a, start = s["account"], s["days"][0]["date"]
    return dict(base, started=True, start=start, today=s["days"][-1], spy=s.get("spy"), combo=vs_combo(start),
                account={k: v for k, v in a.items() if k not in ("ledger", "curve", "trades", "orders")},
                orders=a["orders"][-10:], days=len(s["days"]), migrated_from=s.get("migrated_from"),
                backfilled=sum(1 for d in s["days"] if d.get("how") == "backfill"), curve=a["curve"][-260:])


NAMES = {"UPRO": "UPRO (3x)", "SPY": "SPY (1x)", "cash": "cash (bank sweep)"}


def lines(v=None):
    v = view() if v is None else v
    t0 = v["test"]
    test = ("  Sealed test %s: this rule %.1f%%/yr (worst %.1f%%), combined book %.1f%% (%.1f%%), SPY %.1f%% (%.1f%%); "
            "p = %.2f, so luck can't be ruled out." % (t0["period"], t0["book"], t0["book_dd"], t0["combo"],
                                                       t0["combo_dd"], t0["spy"], t0["spy_dd"], t0["p"]))
    if not v.get("started"):
        return ["  Not started yet. %s" % v["note"], test] + (["  Last try: %s" % v["error"]] if v.get("error") else [])
    d, c = v["today"], v.get("combo")
    out = ["  Its own practice account since %s (%d trading days, %d backfilled). Practice money only: it never places "
           "an order." % (v["start"], v["days"], v["backfilled"])]
    out += combo.account_lines(v["account"], v.get("orders") or [])
    out.append("  Same days: combined account %s." % (("%+.2f%%" % c["return_pct"]) if c else "n/a"))
    out.append("  %s: in %s (%s, %s)." % (d["date"], NAMES[d["hold"]], d["how"], d["fill_at"][11:]))
    n = v.get("next")
    if n and n["date"] != d["date"]:
        out.append("  Next (%s), from the %s close: %s." % (n["date"], n["from_close_of"], NAMES[n["hold"]]))
    if v.get("error"):
        out.append("  Last try failed: %s" % v["error"])
    out.append(test)
    return out

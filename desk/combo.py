"""The combined SPY model: a second paper book beside the opening-range desk (docs/MODELS.md).

Three votes on SPY, each 0 or 1, and the book holds their average (0, 1/3, 2/3 or all in):

  dip-buyer   1 above the 200-day average, or in a dip: RSI(2) under 10, held until the close is back over
              the 5-day average;
  Halloween   1 from November to April, or above the 200-day average;
  turn of month  1 on the last trading day of a month and the first 3 of the next, or above the 200-day average.

It comes from a friend's model lab (rounds 1-5, sealed tests; 2026-11-19). The lab's
own numbers, 2000-2026: 7.07% a year against SPY's 8.00%, max drawdown -31% against -55%. Most of that period
was seen data, so the clean test is this book, forward.

Rules of the book:
- a day's weight is decided from the close before it (adjusted closes, so dividends count in the averages) and
  that day's place in the NYSE calendar;
- it runs once a trading day from 9:35 New York. Today fills at the first price after it runs (Yahoo's latest
  price then), not at an open that is already past. Days the desk was off are backfilled at that day's open
  and marked "backfill";
- the book is in real SPY prices, fractional shares, 3 basis points a side, and dividends are paid in cash
  on the ex-date (buy-and-hold SPY reinvests them at that day's fill). Cash not in SPY earns the 13-week
  T-bill rate (Yahoo ^IRX, the day before), as a sweep account would; without it a timing model is
  short-changed about 1 % a year whenever it is out;
- paper only. It never places an order, live or practice.

State: data/combo.json. Read-only Yahoo GETs, two a run (SPY, ^IRX).
"""
import datetime
import importlib.util
import json
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from . import charts
from .paths import VENDOR, home_dir
from .skills import read_json, write_json

NY = ZoneInfo("America/New_York")
SYMBOL = "SPY"
START_EQUITY = 10000.0
COST_BPS = 3.0                 # a side, as in the lab
RUN_FROM = "09:35"
WINTER = (11, 12, 1, 2, 3, 4)  # Halloween: November to April
DIP_RSI = 10.0


def path():
    return home_dir() / "combo.json"


# ---------------------------------------------------------------- the NYSE calendar

def _vendor_calendar():
    """The desk's own NYSE holiday list (the Price Alerts skill), or None when it cannot be read."""
    try:
        spec = importlib.util.spec_from_file_location("trader_alerts_cal", VENDOR / "trader-alerts" / "alerts.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return set(mod.NYSE_HOLIDAYS), tuple(mod.CALENDAR_YEARS)
    except Exception:
        return None


_VENDOR = _vendor_calendar()


def _easter(y):
    """Gregorian Easter Sunday (Anonymous / Meeus algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    return datetime.date(y, month, (h + l - 7 * m + 33 * month + 19) % 32)


def _nth(y, month, weekday, n):
    """The n-th weekday (0 = Monday) of a month; n = -1 for the last."""
    if n > 0:
        d = datetime.date(y, month, 1)
        return d + datetime.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
    d = datetime.date(y + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    return d - datetime.timedelta(days=1) if d.weekday() == 5 else d + datetime.timedelta(days=1) if d.weekday() == 6 else d


def computed_holidays(y):
    """NYSE full-day holidays by the exchange's standing rules. A New Year's Day on a Saturday is not moved to
    Friday (NYSE rule 7.2). shortcut: one-off closures (a national day of mourning, a storm) are not knowable in
    advance; the book only asks about today and tomorrow, and Yahoo's own daily bars are the record for the past."""
    out = {datetime.date(y, 1, 1) if datetime.date(y, 1, 1).weekday() != 5 else None,
           _nth(y, 1, 0, 3), _nth(y, 2, 0, 3), _easter(y) - datetime.timedelta(days=2), _nth(y, 5, 0, -1),
           _observed(datetime.date(y, 7, 4)), _nth(y, 9, 0, 1), _nth(y, 11, 3, 4), _observed(datetime.date(y, 12, 25))}
    if datetime.date(y, 1, 1).weekday() == 6:
        out.add(datetime.date(y, 1, 2))
    if y >= 2022:
        out.add(_observed(datetime.date(y, 6, 19)))
    out.discard(None)
    return {d.isoformat() for d in out}


def is_open(day):
    """Is the NYSE open on this date ("YYYY-MM-DD")? The desk's vendored list for the years it covers, the standing
    rules after that (the health panel already warns when the vendored list runs out)."""
    d = datetime.date.fromisoformat(day)
    if d.weekday() >= 5:
        return False
    if _VENDOR and d.year in _VENDOR[1]:
        return day not in _VENDOR[0]
    return day not in computed_holidays(d.year)


def _step(day, k):
    d = datetime.date.fromisoformat(day)
    while True:
        d += datetime.timedelta(days=k)
        if is_open(d.isoformat()):
            return d.isoformat()


def next_open(day):
    return _step(day, 1)


def turn_of_month(day):
    """The last trading day of a month, or one of the first 3 of a month."""
    if next_open(day)[:7] != day[:7]:
        return True
    n, d = 0, day
    while d[:7] == day[:7]:
        n += 1
        if n > 3:
            return False
        d = _step(d, -1)
    return True


# ---------------------------------------------------------------- the votes

def indicators(adj):
    """Per close: (above the 200-day average, in a dip after that close). Wilder RSI(2) and plain averages, the
    same definitions as the lab. A dip starts when RSI(2) is under 10 and lasts while the close stays at or under
    its 5-day average."""
    out, up, dn, dip = [], None, None, False
    for i, c in enumerate(adj):
        rsi = None
        if i:
            g, l = max(c - adj[i - 1], 0.0), max(adj[i - 1] - c, 0.0)
            up = g if up is None else (up + g) / 2.0
            dn = l if dn is None else (dn + l) / 2.0
            rsi = 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)
        s5 = sum(adj[i - 4:i + 1]) / 5.0 if i >= 4 else None
        s200 = sum(adj[i - 199:i + 1]) / 200.0 if i >= 199 else None
        dip = rsi is not None and s5 is not None and (rsi < DIP_RSI or (dip and c <= s5))
        out.append({"bull": s200 is not None and c > s200, "dip": dip, "rsi": rsi, "sma5": s5, "sma200": s200})
    return out


def votes(state, day):
    """The three votes for `day`, from the state after the close before it (an indicators() row)."""
    bull = state["bull"]
    v = {"dip": int(bull or state["dip"]), "halloween": int(bull or int(day[5:7]) in WINTER),
         "turn": int(bull or turn_of_month(day))}
    return v, round(sum(v.values()) / 3.0, 4)


# ---------------------------------------------------------------- data

def parse(doc):
    """A Yahoo v8 daily chart with events=div,split -> (rows, dividends, live).
    rows: [{date, o, c, adj}] oldest first; dividends: {ex-date: $ a share}; live: (price, "YYYY-MM-DD HH:MM") or None."""
    try:
        res = doc["chart"]["result"][0]
        ts, q = res["timestamp"], res["indicators"]["quote"][0]
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError):
        raise charts.ChartError("no daily chart with adjusted closes for %s" % SYMBOL)
    rows = []
    for i, t in enumerate(ts):
        try:
            o, c, a = q["open"][i], q["close"][i], adj[i]
        except (KeyError, IndexError):
            continue
        if None in (o, c, a) or min(o, c, a) <= 0:
            continue
        rows.append({"date": datetime.datetime.fromtimestamp(int(t), NY).strftime("%Y-%m-%d"),
                     "o": round(float(o), 4), "c": round(float(c), 4), "adj": float(a)})
    divs = {}
    for e in ((res.get("events") or {}).get("dividends") or {}).values():
        d = datetime.datetime.fromtimestamp(int(e["date"]), NY).strftime("%Y-%m-%d")
        divs[d] = divs.get(d, 0.0) + float(e["amount"])
    meta, live = res.get("meta") or {}, None
    if meta.get("regularMarketPrice") and meta.get("regularMarketTime"):
        live = (float(meta["regularMarketPrice"]),
                datetime.datetime.fromtimestamp(int(meta["regularMarketTime"]), NY).strftime("%Y-%m-%d %H:%M"))
    return rows, divs, live


def fetch(timeout=20, symbol=SYMBOL):
    """Two years of daily bars with dividends: one read-only GET (tests stub this). symbol "^IRX" gives the
    13-week T-bill rate in % as its close."""
    q = "/v8/finance/chart/%s?range=2y&interval=1d&events=div%%2Csplit" % symbol.replace("^", "%5E")
    last = "no answer"
    for host in charts.HOSTS:
        req = urllib.request.Request("https://%s%s" % (host, q), method="GET",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return parse(json.loads(r.read().decode("utf-8")))
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(e)
    raise charts.ChartError("Yahoo did not answer for %s (%s)" % (symbol, last))


# ---------------------------------------------------------------- the book

def book(days, rows, divs, start_equity=START_EQUITY, cost_bps=COST_BPS, rates=None):
    """Replay the recorded days: a day's interest on cash at the rate known the day before, dividends on the
    ex-date, trade to the day's weight at its fill when the weight changed, mark at the close (or the fill, for a
    day with no close yet). rates: {date: T-bill % a year}. Returns (curve, totals)."""
    close = {r["date"]: r["c"] for r in rows}
    known = sorted((rates or {}).items())
    cash, sh, bh, w_prev, curve, interest = start_equity, 0.0, None, None, [], 0.0
    for n, d in enumerate(days):
        f, div = d["fill"], divs.get(d["date"], 0.0)
        if n and cash > 0:
            r = [v for k, v in known if k < d["date"]]
            if r:
                interest += cash * r[-1] / 100.0 / 252
                cash += cash * r[-1] / 100.0 / 252
        cash += sh * div
        if bh is None:
            bh = start_equity / f
        else:
            bh += bh * div / f
        if d["weight"] != w_prev:
            target = d["weight"] * (cash + sh * f) / f
            cash -= (target - sh) * f + abs(target - sh) * f * cost_bps / 1e4
            sh, w_prev = target, d["weight"]
        px = close.get(d["date"], f)
        curve.append({"date": d["date"], "equity": round(cash + sh * px, 2), "spy": round(bh * px, 2)})
    tot = None
    if curve:
        def dd(xs):
            peak, worst = xs[0], 0.0
            for x in xs:
                peak = max(peak, x)
                worst = min(worst, x / peak - 1)
            return round(100 * worst, 2)
        last = curve[-1]
        tot = {"equity": last["equity"], "spy": last["spy"], "shares": round(sh, 4), "cash": round(cash, 2),
               "interest": round(interest, 2),
               "return_pct": round(100 * (last["equity"] / start_equity - 1), 2),
               "spy_return_pct": round(100 * (last["spy"] / start_equity - 1), 2),
               "max_dd_pct": dd([c["equity"] for c in curve]), "spy_max_dd_pct": dd([c["spy"] for c in curve])}
    return curve, tot


# ---------------------------------------------------------------- running it

def load():
    return read_json(path(), None) or {}


def due(now, state=None):
    """Should the book run now ("YYYY-MM-DD HH:MM", New York)? From 9:35 on a trading day until today is in, and
    once more after 16:05 so today is marked at its close."""
    s = load() if state is None else state
    if not (is_open(now[:10]) and now[11:16] >= RUN_FROM):
        return False
    if (s.get("days") or [{}])[-1].get("date") != now[:10]:
        return True
    return now[11:16] >= "16:05" and str(s.get("checked") or "") < now[:10] + " 16:05"


def run(now, data=None, rates=None):
    """Bring the book up to `now`: backfill missed days at their open, today at the first price after this run.
    data: (rows, dividends, live) as parse() gives; fetched when None. Returns the saved state."""
    s = load()
    rows, divs, live = data if data is not None else fetch()
    if rates is None:
        try:
            rates = {r["date"]: r["c"] for r in fetch(symbol="^IRX")[0]}
        except Exception:                                 # no rate today: the book runs, cash just earns nothing
            rates = {}
    today = now[:10]
    days = list(s.get("days") or [])
    first = days[-1]["date"] if days else None
    idx = {r["date"]: i for i, r in enumerate(rows)}
    marks = indicators([r["adj"] for r in rows])
    for i, r in enumerate(rows):
        d = r["date"]
        if (first is None and d != today) or (first is not None and d <= first) or d > today or i == 0:
            continue
        if marks[i - 1]["sma200"] is None:
            continue
        if d == today and not (now[11:16] >= RUN_FROM and is_open(today)):
            continue
        v, w = votes(marks[i - 1], d)
        if d == today:
            if not live or live[1][:10] != today:
                continue                                  # no price from today yet: try again later
            fill, at, how = live[0], live[1], "live"
        else:
            fill, at, how = r["o"], d + " 09:30", "backfill"
        days.append({"date": d, "votes": v, "weight": w, "fill": round(fill, 4), "fill_at": at, "how": how})
    curve, tot = book(days, rows, divs, rates=rates)
    closed = [i for i, r in enumerate(rows) if r["date"] < today or (r["date"] == today and now[11:16] >= "16:00")]
    last_i = closed[-1] if closed else None
    nxt = None
    if last_i is not None and marks[last_i]["sma200"] is not None:
        nd = next_open(rows[last_i]["date"])
        v, w = votes(marks[last_i], nd)
        nxt = {"date": nd, "votes": v, "weight": w, "from_close_of": rows[last_i]["date"]}
    m = marks[last_i] if last_i is not None else {}
    s.update({"symbol": SYMBOL, "start_equity": START_EQUITY, "cost_bps": COST_BPS, "days": days, "curve": curve,
              "totals": tot, "next": nxt, "checked": now, "error": None,
              "spy": {"as_of": rows[last_i]["date"] if last_i is not None else None,
                      "close": rows[last_i]["c"] if last_i is not None else None,
                      "rsi2": round(m["rsi"], 1) if m.get("rsi") is not None else None,
                      "sma200": round(m["sma200"], 2) if m.get("sma200") else None,
                      "sma5": round(m["sma5"], 2) if m.get("sma5") else None}})
    write_json(path(), s)
    return s


def note_error(now, err):
    """A failed run is kept on the card, so a quiet Yahoo is visible."""
    s = load()
    s.update({"checked": now, "error": str(err)[:200]})
    write_json(path(), s)
    return s


def view():
    """What /api/combo and the Desk card show. Reads the file only: no network."""
    s = load()
    if not s.get("days"):
        return {"started": False, "error": s.get("error"), "checked": s.get("checked"), "next": s.get("next"),
                "note": "The combined SPY book starts on the first trading day the desk runs after 9:35 New York."}
    return {"started": True, "start": s["days"][0]["date"], "today": s["days"][-1], "next": s.get("next"),
            "totals": s.get("totals"), "spy": s.get("spy"), "checked": s.get("checked"), "error": s.get("error"),
            "days": len(s["days"]), "backfilled": sum(1 for d in s["days"] if d.get("how") == "backfill"),
            "curve": s.get("curve", [])[-260:], "paper_only": True}


def lines(v=None):
    """The book as plain text, for the review and `python3 -m desk combo`."""
    v = view() if v is None else v
    if not v.get("started"):
        return ["  Not started yet. %s" % v["note"]] + (["  Last try: %s" % v["error"]] if v.get("error") else [])
    t, d = v["totals"], v["today"]
    vt = lambda x: ", ".join("%s %s" % (k, "yes" if x[k] else "no") for k in ("dip", "halloween", "turn"))
    out = ["  Since %s (%d trading days, %d backfilled at the open). Paper only: it never places an order."
           % (v["start"], v["days"], v["backfilled"]),
           "  Book $%s (%+.2f%%, $%.2f of it T-bill interest on cash), buy-and-hold SPY $%s (%+.2f%%). "
           "Worst drop %.2f%% against SPY's %.2f%%."
           % (format(t["equity"], ",.2f"), t["return_pct"], t.get("interest", 0.0), format(t["spy"], ",.2f"),
              t["spy_return_pct"], t["max_dd_pct"], t["spy_max_dd_pct"]),
           "  %s: %d%% in SPY (%s), filled at $%.2f (%s, %s)."
           % (d["date"], round(100 * d["weight"]), vt(d["votes"]), d["fill"], d["how"], d["fill_at"][11:])]
    n = v.get("next")
    if n and n["date"] != d["date"]:
        out.append("  Next (%s), from the %s close: %d%% (%s)." % (n["date"], n["from_close_of"], round(100 * n["weight"]),
                                                                  vt(n["votes"])))
    if v.get("error"):
        out.append("  Last try failed: %s" % v["error"])
    out.append("  Judge it after 6 to 12 months against SPY; a few weeks say nothing.")
    return out

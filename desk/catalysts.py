"""Catalysts: the public news and events that move stocks, ranked, so the morning pick can favour them.

Gathered before the open (and each hour of the trading day), read-only, free, no key, no account:
  - Yahoo's trending tickers and its most-active, gainers and losers screeners (the move and its volume)
  - Nasdaq's IPO calendar (upcoming and recently priced deals) and earnings calendar (today, next trading day)
  - your own watch lines (Settings, `catalyst_watch`: "TTWO GTA 6 launches 2026-11-19", one per line)
  - for the top names: the News skill's headlines and SEC filings (confirmations and links), and a year of
    daily bars (ATR, last session's move and volume) from the same Yahoo chart the morning pick reads
Each event becomes a row per ticker, plus clear second-order names (PEERS). A row gets a score from 0 to
100 (fresh 30, big 25, confirmed 25, chart 20) and says whether the opening-range rules can trade it yet.
The best tradeable rows get reserved places on the one morning list (desk/autolist.py). It is a list of
reasons to look, never a signal: a trade still needs its breakout.

All web text is data. It is cut to one line and shown, never followed.
"""
import datetime
import json
import math
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import autolist
from . import backtest
from . import charts
from . import skills
from .agent import clean

NASDAQ = "https://api.nasdaq.com/api"
UA = "Mozilla/5.0"           # what desk/charts.py sends; Yahoo answers a full browser name without cookies with 429
TRENDING = "https://%s/v1/finance/trending/US?count=25"
ENRICH = 25                  # rows that get headlines and a chart read
KEEP = 60                    # rows kept for the dashboard
MIN_SCORE = 40               # under this a catalyst takes no reserved place on the morning list
ALERT_SCORE = 70             # a phone alert needs at least this (Settings, Catalyst alerts)
HISTORY_DAYS = backtest.FEATURE_DAYS + 1   # daily bars the morning pick needs before it can rate a stock
MIN_EARN_CAP = 2e9           # smaller companies' earnings are left out
SPAC = re.compile(r"\b(acquisition|spac)\b", re.I)
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")

# Clear second-order names: (ticker, why). shortcut: hand-kept and small, grow it when a catalyst keeps
# missing an obvious peer.
PEERS = {
    "TTWO": [("EA", "video game peer of"), ("RBLX", "video game peer of"), ("GME", "sells the games of")],
    "EA": [("TTWO", "video game peer of")],
    "ANT": [("AMZN", "large investor in"), ("GOOGL", "investor in"), ("NVDA", "AI chip maker for")],
    "NVDA": [("AMD", "chip peer of"), ("AVGO", "AI chip peer of"), ("SMH", "chip ETF holding")],
    "AMD": [("NVDA", "chip peer of")],
    "TSLA": [("RIVN", "EV peer of"), ("LCID", "EV peer of")],
    "COIN": [("HOOD", "crypto trading peer of"), ("MSTR", "bitcoin stock like")],
    "MSTR": [("COIN", "bitcoin stock like"), ("MARA", "bitcoin miner, moves with")],
    "PLTR": [("BBAI", "AI software peer of"), ("AI", "AI software peer of")],
    "WMT": [("TGT", "retail peer of"), ("COST", "retail peer of")],
    "TGT": [("WMT", "retail peer of")],
    "CRWD": [("PANW", "security peer of"), ("ZS", "security peer of"), ("NET", "security peer of")],
    "PANW": [("CRWD", "security peer of"), ("ZS", "security peer of")],
}


class CatalystError(ValueError):
    pass


def get_json(url, timeout=15):
    """One read-only GET. Raises CatalystError."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise CatalystError("%s did not answer (%s)" % (urllib.parse.urlsplit(url).netloc, e))


def event(symbol, kind, title, size, when=None, link="", source=""):
    return {"symbol": symbol, "kind": kind, "title": clean(title, 200), "size": round(max(0.0, min(1.0, size)), 3),
            "when": when, "link": link if str(link).startswith("https://") else "", "source": source}


def _money(text):
    try:
        return float(re.sub(r"[^0-9.]", "", str(text or "")) or 0)
    except ValueError:
        return 0.0


def _iso(mdy):
    try:
        return datetime.datetime.strptime(str(mdy).strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def add_weekdays(date, n):
    """date plus n weekdays. shortcut: ignores market holidays, so it can be a day early around one."""
    d = datetime.date.fromisoformat(date)
    while n > 0:
        d += datetime.timedelta(days=1)
        n -= d.weekday() < 5
    return d.isoformat()


def fresh(when, today):
    """1 for today or no date; an event up to a week ahead still counts, a past one fades over 3 days."""
    if not when:
        return 1.0
    days = (datetime.date.fromisoformat(when) - datetime.date.fromisoformat(today)).days
    return max(0.0, 1 - days / 7.0) if days >= 0 else max(0.0, 1 + days / 3.0)


# ---------------------------------------------------------------- sources
def trending(get=get_json):
    last = None
    for host in charts.HOSTS:
        try:
            d = get(TRENDING % host)
            break
        except CatalystError as e:
            last = e
    else:
        raise last
    quotes = ((d.get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
    syms = [str(q.get("symbol") or "").upper() for q in quotes]
    return [event(s, "trending", "Trending on Yahoo Finance", 0.4, link="https://finance.yahoo.com/quote/%s" % s,
                  source="Yahoo trending") for s in syms if autolist.TICKER.fullmatch(s)]


def movers(quotes, name):
    """One Yahoo screener's quotes -> events sized by the move and its volume against normal."""
    out = []
    for q in quotes:
        sym = str(q.get("symbol") or "").upper()
        if q.get("quoteType") != "EQUITY" or not autolist.TICKER.fullmatch(sym):
            continue
        chg = float(q.get("regularMarketChangePercent") or 0)
        vol, avg = float(q.get("regularMarketVolume") or 0), float(q.get("averageDailyVolume3Month") or 0)
        rvol = vol / avg if avg else 0.0
        out.append(event(sym, "mover", "Moved %+.1f%% on %.1fx its usual volume (Yahoo %s)" % (chg, rvol, name.replace("_", " ")),
                         0.6 * min(1, abs(chg) / 15) + 0.4 * min(1, rvol / 5),
                         link="https://finance.yahoo.com/quote/%s" % sym, source="Yahoo " + name.replace("_", " ")))
    return out


def _ipo(r, when, what):
    sym = str(r.get("proposedTickerSymbol") or "").upper()
    name = clean(r.get("companyName"), 80)
    if not when or not autolist.TICKER.fullmatch(sym) or SPAC.search(name):
        return None
    offer = _money(r.get("dollarValueOfSharesOffered"))
    return event(sym, "ipo", "IPO: %s %s %s (%s a share, about $%s raised)" % (
        name, what, when, "$" + str(r.get("proposedSharePrice") or "?"),
        ("%.1f billion" % (offer / 1e9)) if offer >= 1e9 else ("%d million" % round(offer / 1e6))),
        math.log10(max(offer, 1e7) / 1e7) / 4, when=when,
        link="https://www.nasdaq.com/market-activity/ipos", source="Nasdaq IPO calendar")


def ipos(today, get=get_json):
    """Upcoming deals and those priced in the last 30 days (this month, and next month from the 20th)."""
    d0 = datetime.date.fromisoformat(today)
    months = [today[:7]] + ([(d0.replace(day=1) + datetime.timedelta(days=32)).strftime("%Y-%m")] if d0.day >= 20 else [])
    out = []
    for m in months:
        d = get("%s/ipo/calendar?date=%s" % (NASDAQ, m)).get("data") or {}
        for r in ((d.get("upcoming") or {}).get("upcomingTable") or {}).get("rows") or []:
            out.append(_ipo(r, _iso(r.get("expectedPriceDate")), "expected to start trading"))
        for r in (d.get("priced") or {}).get("rows") or []:
            when = _iso(r.get("pricedDate"))
            if when and (d0 - datetime.date.fromisoformat(when)).days <= 30:
                out.append(_ipo(r, when, "priced"))
    return [e for e in out if e]


def earnings(today, get=get_json):
    """Companies worth $2 billion or more reporting today or on the next weekday."""
    out = []
    for day in (today, add_weekdays(today, 1)):
        rows = (get("%s/calendar/earnings?date=%s" % (NASDAQ, day)).get("data") or {}).get("rows") or []
        for r in rows:
            sym, cap = str(r.get("symbol") or "").upper(), _money(r.get("marketCap"))
            if cap < MIN_EARN_CAP or not autolist.TICKER.fullmatch(sym):
                continue
            at = {"time-pre-market": "before the open", "time-after-hours": "after the close"}.get(r.get("time"), "time not given")
            out.append(event(sym, "earnings", "Earnings %s %s (%s, worth $%.0f billion)" % (day, at, clean(r.get("name"), 60), cap / 1e9),
                             math.log10(cap / 1e9) / 3, when=day,
                             link="https://www.nasdaq.com/market-activity/earnings", source="Nasdaq earnings calendar"))
    return out


def watched(text, today):
    """Your watch lines: 'TICKER what is happening', with an optional YYYY-MM-DD date in the text."""
    out = []
    for line in str(text or "").splitlines():
        parts = line.split(None, 1)
        if not parts or not autolist.TICKER.fullmatch(parts[0].upper()):
            continue
        note = parts[1] if len(parts) > 1 else "on your watch list"
        m = DATE.search(note)
        out.append(event(parts[0].upper(), "watch", note, 0.7, when=m.group(1) if m else None, source="your watch list"))
    return out


def peers(events):
    return [event(sym, "peer", "%s %s: %s" % (why, e["symbol"], e["title"]), e["size"] * 0.5, when=e["when"],
                  link=e["link"], source="second-order of " + e["symbol"])
            for e in events if e["kind"] != "peer" for sym, why in PEERS.get(e["symbol"], ())]


def headlines(symbols, st, wd, run=skills.run):
    """{symbol: [{title, source, kind, time, link}]} from the News skill (and SEC filings with an SEC contact)."""
    def one(sym):
        args = ["--tickers", sym, "--all", "--hours", st["news_hours"], "--no-moves", "--json"]
        if not st["sec_user_agent"]:
            args.append("--no-sec")
        r = run("news", args, wd / sym, timeout=60)
        items = (r.json or {}).get("items") if isinstance(r.json, dict) else None
        return sym, [{"title": clean(i.get("title"), 160), "source": clean(i.get("source") or "news", 40),
                      "kind": clean(i.get("kind"), 12), "time": clean(i.get("time"), 25),
                      "link": str(i.get("link") or "") if str(i.get("link") or "").startswith("https://") else ""}
                     for i in (items or [])[:5] if clean(i.get("title"), 160)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, symbols))


# ---------------------------------------------------------------- one row per ticker
def group(events, today):
    rows = {}
    for e in events:
        r = rows.setdefault(e["symbol"], {"symbol": e["symbol"], "events": []})
        if all((x["kind"], x["title"]) != (e["kind"], e["title"]) for x in r["events"]):
            r["events"].append(e)
    for r in rows.values():
        r["events"].sort(key=lambda e: (e["kind"] == "peer", -e["size"] * fresh(e["when"], today)))
        top = r["events"][0]
        r.update(reason=top["title"], kind=top["kind"], when=top["when"], source=top["source"],
                 link=next((e["link"] for e in r["events"] if e["link"]), ""),
                 kinds=sorted({e["kind"] for e in r["events"]}))
    return list(rows.values())


def chart(bars, today):
    """Last session's numbers from daily bars: ATR %, move %, volume against its 14-day average."""
    prior = [b for b in bars if b["date"] < today]
    if len(prior) < 2:
        return None
    last, prev = prior[-1], prior[-2]
    vols = [b.get("v", 0) for b in prior[-backtest.FEATURE_DAYS - 1:-1]]
    avg = sum(vols) / len(vols) if vols else 0
    atr = backtest.atr_pct(prior, today)
    return {"atr_pct": round(atr, 1) if atr is not None else None, "change_pct": round((last["c"] / prev["c"] - 1) * 100, 1),
            "rvol": round(last.get("v", 0) / avg, 1) if avg else None, "days": len(prior)}


def confirmations(row):
    own = len([k for k in row["kinds"] if k != "peer"]) or 1
    news = row.get("headlines") or []
    return min(4, own + (len(news) >= 2) + any(n.get("kind") == "filing" for n in news))


def score(row, today):
    c = row.get("chart") or {}
    ch = 0.5 * min(1, (c.get("atr_pct") or 0) / 8) + 0.25 * min(1, abs(c.get("change_pct") or 0) / 10) \
        + 0.25 * min(1, max(0, (c.get("rvol") or 1) - 1) / 2)
    f = max(fresh(e["when"], today) for e in row["events"])
    size = max(e["size"] for e in row["events"])
    return int(round(100 * (0.3 * f + 0.25 * size + 0.25 * confirmations(row) / 4 + 0.2 * ch)))


def tradeable(row, bars, today, min_price):
    """(can the opening-range rules trade it, why not, the day it becomes eligible)."""
    ok, why = autolist.rate(row["symbol"], bars, today, min_price, 0) if bars else (None, "no daily data")
    if ok:
        return True, "Tradeable with the opening-range rules", None
    ipo = next((e for e in row["events"] if e["kind"] == "ipo"), None)
    if why == "under 15 days of history" or (not bars and ipo):
        first = bars[0]["date"] if bars else max(ipo["when"], today)
        day = add_weekdays(first, HISTORY_DAYS)
        return False, "Watch, not tradeable yet: new listing, the rules need %d days of history (about %s)" % (HISTORY_DAYS, day), day
    return False, "Not tradeable here: %s" % why, None


def cached(fetch):
    """fetch with a memo, so the catalysts and the morning pick read each chart once."""
    memo = {}

    def f(*a):
        if a not in memo:
            try:
                memo[a] = fetch(*a)
            except charts.ChartError as e:
                memo[a] = e
        if isinstance(memo[a], Exception):
            raise memo[a]
        return memo[a]
    return f


def gather(st, now, wd, fetch=charts.fetch, get=get_json, screen=autolist.screen, news=headlines, pause=0.3):
    """Today's catalysts: {date, at, items (best first), errors, counts}. One source down leaves the others."""
    today, events, errors = now[:10], [], []

    def take(name, fn):
        try:
            events.extend(fn())
        except Exception as e:
            errors.append("%s: %s" % (name, str(e)[:160]))
    take("Yahoo trending", lambda: trending(get))
    for name in autolist.SCREENS:
        take("Yahoo " + name.replace("_", " "), lambda n=name: movers(screen(n), n))
    take("Nasdaq IPO calendar", lambda: ipos(today, get))
    take("Nasdaq earnings calendar", lambda: earnings(today, get))
    events += watched(st["catalyst_watch"], today)
    events += peers(events)
    rows = [r for r in group(events, today) if r["symbol"] not in st["blocked"]]
    for r in rows:
        r["score"] = score(r, today)
    rows.sort(key=lambda r: ("watch" not in r["kinds"], -r["score"], r["symbol"]))     # your lines are always checked
    top = rows[:ENRICH]
    try:
        found = news([r["symbol"] for r in top], st, wd)
    except Exception as e:
        found = {}
        errors.append("News skill: %s" % str(e)[:160])
    for i, r in enumerate(top):
        if pause and i:
            time.sleep(pause)
        try:
            bars = fetch(r["symbol"], "1y", "1d")["bars"]
        except charts.ChartError:
            bars = []
        r["headlines"], r["chart"] = found.get(r["symbol"]) or [], chart(bars, today)
        r["tradeable"], r["status"], r["eligible_on"] = tradeable(r, bars, today, st["min_price"])
        r["score"] = score(r, today)
    for r in rows[ENRICH:]:
        r.update(headlines=[], chart=None, tradeable=False, eligible_on=None,
                 status="Not checked: ranked under the top %d" % ENRICH)
    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    counts = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return {"date": today, "at": now, "items": rows[:KEEP], "errors": errors, "counts": counts}


def todays(cats, date):
    """Today's rows, or [] when the last gather was another day."""
    return (cats or {}).get("items") or [] if (cats or {}).get("date") == date else []


def for_list(items, n):
    """The catalysts that may take reserved places on the morning list, best first, at most n."""
    return [r for r in items if r.get("tradeable") and r["score"] >= MIN_SCORE][:n]


def mark(cats, scan_list):
    """Notes on each row whether it made today's scan list."""
    listed = {r["symbol"] for r in (scan_list or {}).get("symbols") or []} \
        if scan_list and scan_list.get("date") == (cats or {}).get("date") and not scan_list.get("error") else set()
    for r in (cats or {}).get("items") or []:
        r["on_list"] = r["symbol"] in listed
    return cats


def log_row(r):
    """What the review keeps per catalyst per day."""
    return {k: r.get(k) for k in ("symbol", "score", "kind", "reason", "link", "tradeable", "on_list", "eligible_on")}

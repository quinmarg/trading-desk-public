"""Candles for the desk's own maths (the short side, desk/shorts.py).

The vendored skills fetch and read their own charts, but the ones that find
and plan an entry are long-only, so the short side needs the candles itself.
Demo: the skills' saved 5-minute files. Live: the same free Yahoo chart
address the skills use. GET only, two fixed hosts, nothing is ever sent.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
OPEN_MIN, CLOSE_MIN = 9 * 60 + 30, 16 * 60


class ChartError(ValueError):
    pass


def parse(doc, symbol=""):
    """A Yahoo v8 chart document -> {symbol, prev_close, bars}. Bars with no price are dropped.
    A bar: {date, start "HH:MM", minute (after midnight, New York), o, h, l, c, v}."""
    try:
        res = doc["chart"]["result"][0]
        meta, ts = res.get("meta") or {}, res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        raise ChartError("no chart data%s" % (" for %s" % symbol if symbol else ""))
    got = str(meta.get("symbol") or "").upper()
    if symbol and got and got != symbol.upper():
        raise ChartError("the chart holds %s, not %s" % (got, symbol.upper()))
    bars = []
    for i, t in enumerate(ts):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            v = (q.get("volume") or [None] * len(ts))[i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        et = datetime.datetime.fromtimestamp(int(t), NY)
        bars.append({"date": et.strftime("%Y-%m-%d"), "start": et.strftime("%H:%M"),
                     "minute": et.hour * 60 + et.minute,
                     "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0)})
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return {"symbol": got or symbol.upper(), "prev_close": float(prev) if prev else None, "bars": bars}


def fetch(symbol, rng, interval, timeout=15, prepost=False):
    """One read-only GET of Yahoo's chart for a ticker. Tries the second host when the first fails.
    prepost=True adds the extended-hours bars (the Desk's chart draws the premarket high and low from them)."""
    symbol = symbol.strip().upper()
    if not (0 < len(symbol) <= 7 and symbol.replace(".", "").isalpha()):
        raise ChartError("%r is not a ticker" % symbol)
    path = "/v8/finance/chart/%s?%s" % (urllib.parse.quote(symbol),
                                         urllib.parse.urlencode(dict({"range": rng, "interval": interval},
                                                                   **({"includePrePost": "true"} if prepost else {}))))
    last = "no answer"
    for host in HOSTS:
        req = urllib.request.Request("https://%s%s" % (host, path), method="GET",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return parse(json.loads(r.read().decode("utf-8")), symbol)
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(e)
    raise ChartError("Yahoo did not answer for %s (%s)" % (symbol, last))


def intraday(source, symbol):
    """Today's 5-minute chart. Demo reads the saved file; live asks Yahoo."""
    if source.demo:
        folder = source.chart_offline(symbol)[1]
        try:
            return parse(json.loads((folder / ("%s.json" % symbol.upper())).read_text()), symbol)
        except OSError:
            raise ChartError("no saved chart for %s in the demo files" % symbol.upper())
    return fetch(symbol, "1d", "5m")


def daily_bars(source, symbol):
    """About a year of daily bars ({date, o, h, l, c, ...}), oldest first, or None when there are none (the demo has
    no daily file). The last bar can be today's, still forming."""
    if source.demo:
        return None
    return fetch(symbol, "1y", "1d")["bars"]


def session_bars(chart, now, bar_minutes=5):
    """The regular-session bars of the day in `now` ("YYYY-MM-DD HH:MM", New York) that have
    finished by then. A bar that is still forming is left out: it has not closed."""
    now_min = int(now[11:13]) * 60 + int(now[14:16])
    return [b for b in chart["bars"]
            if b["date"] == now[:10] and OPEN_MIN <= b["minute"] < CLOSE_MIN and b["minute"] + bar_minutes <= now_min]


def sma(values, n):
    """The average of the last n values, or None when there are fewer than n."""
    if not values or len(values) < n:
        return None
    return sum(values[-n:]) / float(n)

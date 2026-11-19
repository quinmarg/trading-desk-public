"""Is this stock "in play" right now? The volatility screen (docs/VOLATILITY.md).

Two measures, both known by the time a breakout fires and both from the free Yahoo charts the desk
already reads:
- ATR %: the 14-day average true range of the daily bars before today, as a % of yesterday's close.
- Relative volume: today's opening-range volume over the average opening-range volume of the last 14
  full sessions (same minutes of the day), the "stocks in play" measure from Zarattini, Barbon and Aziz.

A signal under the floors is graded weak, never blocked, so it is still logged and replayed after the
close and the review can say whether the screen was right. Read-only: two GETs per stock per day, cached.
"""
from . import backtest
from . import charts
from . import settings as S

_cache = {}     # (symbol, date) -> measures; one fetch of each chart per stock per day


def measures(symbol, today, or_minutes, fetch=charts.fetch):
    """{"atr_pct", "rvol"} for `today` ("YYYY-MM-DD"), either None when the data is too short."""
    key = (symbol, today, or_minutes)
    if key in _cache:
        return _cache[key]
    daily = fetch(symbol, "1y", "1d")["bars"]
    intraday = fetch(symbol, "60d", "5m")["bars"]
    n = or_minutes // 5
    days = {}
    for b in intraday:
        slot = (b["minute"] - backtest.OPEN_MIN) // 5
        if 0 <= slot < n and (b["minute"] - backtest.OPEN_MIN) % 5 == 0:
            days.setdefault(b["date"], {})[slot] = b["v"]
    past = [sum(v.values()) for d, v in sorted(days.items()) if d < today and len(v) == n][-backtest.FEATURE_DAYS:]
    now = days.get(today, {})
    rvol = None
    if len(past) == backtest.FEATURE_DAYS and len(now) == n and sum(past) > 0:
        rvol = round(sum(now.values()) / (sum(past) / len(past)), 2)
    atr = backtest.atr_pct(daily, today)
    out = {"atr_pct": round(atr, 2) if atr is not None else None, "rvol": rvol}
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = out
    return out


def check(sig, st, source, fetch=charts.fetch):
    """Adds sig["vol"] and returns a problem sentence when the stock fails the screen in force, else None.
    The demo has no 60-day files for most stocks, so there the screen only notes that it did not run."""
    floors = S.screen(st)
    if not any(floors.values()):
        return None
    if source.demo:
        sig["warnings"].append("The demo files have no daily or 60-day history, so the volatility screen did not run.")
        return None
    try:
        m = measures(sig["symbol"], sig["date"], st["or_minutes"], fetch)
    except charts.ChartError as e:
        m = {"atr_pct": None, "rvol": None, "error": str(e)[:120]}
    sig["vol"] = dict(m, **floors)
    why = []
    if floors["min_atr_pct"]:
        if m["atr_pct"] is None:
            why.append("its daily range (ATR %) could not be measured")
        elif m["atr_pct"] < floors["min_atr_pct"]:
            why.append("it moves %.1f%% a day on average (ATR), under the %g%% floor" % (m["atr_pct"], floors["min_atr_pct"]))
    if floors["min_rvol"]:
        if m["rvol"] is None:
            why.append("its opening volume could not be compared with the last %d days" % backtest.FEATURE_DAYS)
        elif m["rvol"] < floors["min_rvol"]:
            why.append("its opening volume is %.2fx normal, under the %gx floor" % (m["rvol"], floors["min_rvol"]))
    sig["vol"]["in_play"] = not why
    if not why:
        return None
    return "Not in play: %s." % "; ".join(why)


def skips_floor(sig, st):
    """Paper mode only: an in-play signal is not held back by the odds floor. On in-play days the Time Machine,
    whose pool is mostly ordinary days, rated the target far less likely than it was (docs/VOLATILITY.md)."""
    return st.get("mode") == "paper" and bool((sig.get("vol") or {}).get("in_play"))

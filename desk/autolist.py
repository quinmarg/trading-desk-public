"""The desk picks its own scan list each morning: mostly high-fluctuation stocks (docs/VOLATILITY.md).

Before the open it reads a year of daily bars for every stock in POOL plus your own watchlist (one
read-only GET each), keeps the ones that trade enough and cost at least your lowest share price, and
ranks them by ATR % (the 14-day average daily range as a % of the price). The top MAX_LIST become the
day's scan list. Whether a stock is in play TODAY (its opening volume) is checked per signal by
desk/volscreen.py, so the list is not redone during the day.

Candidates: POOL, your watchlist, your always-scan tickers (`core_watchlist`) and today's names on
Yahoo's free most-active, gainers and losers screeners. The always-scan tickers are always on the
list; the `auto_watchlist_movers` most volatile of the rest join them. With `watchlist_agent` on,
Claude reads those candidates' headlines and picks from them instead (desk/agent.py); if it fails,
the formula's picks stand.

Catalysts (desk/catalysts.py): the best tradeable ones, scored 40 or more, take up to `catalyst_slots`
of the picked places first, whatever their daily range, with the catalyst as the reason. The rest of the
places go to the most volatile. It is still one list.

Setting `auto_list`: "paper" (default) uses it in paper mode only, "on" in both modes, "off" never.
When it is off, or the pick fails or finds too few stocks, the desk scans your watchlist.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from . import agent
from . import backtest
from . import charts
from .paths import data_dir

# Liquid US stocks, calm and wild, so the ranking (not this list) decides what is volatile.
POOL = tuple("""F SOFI PLTR AAL T INTC PFE BAC SNAP RIVN HOOD UBER AMD NIO CCL KO CSCO VZ GM DAL PYPL DKNG MARA SMCI
NVDA AAPL TSLA AMZN MU COIN MSTR RIOT CLSK HUT CIFR WULF IREN UPST AFRM IONQ RGTI QBTS SOUN ACHR JOBY RKLB
ASTS HIMS CVNA APP AI PLUG OKLO SMR LUNR RDDT GME AMC ENPH FSLR MRNA ROKU SHOP NET CRWD ARM AVGO META
LCID OPEN RUN CELH TTD DELL ORCL SNOW U PATH BBAI SERV NBIS CRWV TEM ALAB VST CEG XYZ RBLX""".split())

MIN_LIST = 5                # fewer than this and the desk falls back to your watchlist
MIN_DOLLAR_VOL_M = 100.0    # $ millions traded a day (14-day average): tighter spreads, real fills
MIN_ATR_PCT = 3.0           # the volatility screen's floor; under it a stock is not a high-fluctuation stock


def enabled(st):
    return st.get("auto_list") == "on" or (st.get("auto_list") == "paper" and st.get("mode") == "paper")


SCREENS = ("most_actives", "day_gainers", "day_losers")
TICKER = re.compile(r"[A-Z]{1,5}")


def screen(name, count=25, timeout=15):
    """One Yahoo predefined screener -> its quotes. GET only, no key. Raises charts.ChartError when no host answers."""
    path = "/v1/finance/screener/predefined/saved?" + urllib.parse.urlencode({"scrIds": name, "count": count})
    last = "no answer"
    for host in charts.HOSTS:
        req = urllib.request.Request("https://%s%s" % (host, path), method="GET",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            return ((d.get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
        except (OSError, ValueError, AttributeError, IndexError) as e:
            last = str(e)
    raise charts.ChartError("Yahoo screener %s did not answer (%s)" % (name, last))


def movers(screen):
    """Today's names on the screeners: ({symbol: [screen names]}, errors). One screener down leaves the others."""
    found, errors = {}, []
    for name in SCREENS:
        try:
            quotes = screen(name)
        except Exception as e:
            errors.append(str(e)[:160])
            continue
        for q in quotes:
            sym = str(q.get("symbol") or "").upper()
            if q.get("quoteType") == "EQUITY" and TICKER.fullmatch(sym) and name not in found.get(sym, []):
                found.setdefault(sym, []).append(name)
    return found, errors


def rate(symbol, daily, today, min_price, floor=MIN_ATR_PCT):
    """One stock's line for the list, or (None, why it was left out)."""
    prior = [b for b in daily if b["date"] < today]
    atr = backtest.atr_pct(prior, today)
    if atr is None:
        return None, "under 15 days of history"
    last = prior[-1]
    dv = sum(b["c"] * b.get("v", 0) for b in prior[-backtest.FEATURE_DAYS:]) / backtest.FEATURE_DAYS / 1e6
    if last["c"] < min_price:
        return None, "under your lowest share price"
    if dv < MIN_DOLLAR_VOL_M:
        return None, "under $%d million traded a day" % MIN_DOLLAR_VOL_M
    if atr < floor:
        return None, "moves under %g%% a day" % floor
    return {"symbol": symbol, "atr_pct": round(atr, 1), "price": round(last["c"], 2), "dollar_vol_m": round(dv),
            "why": "moves %.1f%% a day on average, $%s million traded a day, $%.2f" % (atr, format(round(dv), ","), last["c"])}, None


def pick(st, now, fetch=charts.fetch, pause=0.3, screen=screen, wd=None, ask=agent.ask_claude, news=agent.headlines,
         catalysts=()):
    """Today's list: {date, at, symbols: [{symbol, atr_pct, price, dollar_vol_m, why, from, catalyst?}], looked_at,
    left_out, by ("formula" or "claude"), summary, errors, error}. The always-scan tickers come first, then the
    catalysts (rows from desk/catalysts.py, best first), then the most volatile."""
    today = now[:10]
    n = st["auto_watchlist_movers"]
    cats = {r["symbol"]: r for r in catalysts}
    found, errors = movers(screen)
    core = [s for s in st["core_watchlist"] if s not in st["blocked"]]
    names = [s for s in dict.fromkeys(core + list(cats) + list(POOL) + list(st["watchlist"]) + list(found)) if s not in st["blocked"]]
    always, rated, left, failed = [], [], {}, 0
    for i, sym in enumerate(names):
        if pause and i:
            time.sleep(pause)
        try:
            row, why = rate(sym, fetch(sym, "1y", "1d")["bars"], today, st["min_price"], 0 if sym in core or sym in cats else MIN_ATR_PCT)
        except charts.ChartError:
            row, why = None, "no daily data"
            failed += 1
        cat = cats.get(sym)
        if row and cat:                  # the news is the reason; the numbers follow
            row["why"] = "Catalyst (%d/100): %s. %s" % (cat["score"], cat["reason"].rstrip("."), row["why"])
            row["catalyst"] = {"score": cat["score"], "reason": cat["reason"], "link": cat.get("link") or ""}
        if sym in core:                  # yours: on the list whatever the numbers say
            row = row or {"symbol": sym, "atr_pct": None, "price": None, "dollar_vol_m": None, "why": why}
            row["why"] = "On your always-scan list. " + row["why"]
            always.append(dict(row, **{"from": ["yours"] + (["catalyst"] if cat else [])}))
        elif row:
            src = [n.replace("_", " ") for n in found.get(sym, [])]
            if src:
                row["why"] += "; on Yahoo's %s today" % " and ".join(src)
            rated.append(dict(row, **{"from": src + (["catalyst"] if cat else [])}))
        else:
            left[why] = left.get(why, 0) + 1
    boosted = sorted((r for r in rated if r.get("catalyst")), key=lambda r: -r["catalyst"]["score"])[:min(n, st["catalyst_slots"])]
    rated = sorted((r for r in rated if r not in boosted and r["atr_pct"] >= MIN_ATR_PCT), key=lambda r: -r["atr_pct"])
    m = n - len(boosted)
    chosen, by, summary = boosted + rated[:m], "formula", ""
    if st.get("watchlist_agent") and m and rated:
        try:
            picks, summary = agent.pick(st, rated[:max(agent.POOL, m)], m, core, wd or data_dir() / "work" / today / "_agent", ask, news)
            if len(core) + len(boosted) + len(picks) < MIN_LIST:
                raise RuntimeError("claude kept only %d stocks" % len(picks))
            chosen, by = boosted + picks, "claude"
        except Exception as e:           # Claude missing, signed out or odd: the formula's list stands
            errors.append("agent: %s; used the formula's picks" % str(e)[:200])
            summary = ""
    out = {"date": today, "at": now, "symbols": always + chosen, "looked_at": len(names), "left_out": left,
           "by": by, "summary": summary, "errors": errors, "error": None}
    if len(out["symbols"]) < MIN_LIST:
        out["error"] = "Only %d stocks passed (%d had no data), so the desk scans your watchlist today." % (
            len(out["symbols"]), failed)
    return out


def active(st, today_list, today):
    """True when today's picked list is on for this mode and usable."""
    return bool(enabled(st) and today_list and today_list.get("date") == today and not today_list.get("error"))


def symbols(st, today_list, today):
    """What to scan: today's picked list when it is active, else your watchlist."""
    return [r["symbol"] for r in today_list["symbols"]] if active(st, today_list, today) else list(st["watchlist"])

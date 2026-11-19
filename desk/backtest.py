"""Backtest the desk's opening-range rule over the last 60 days of 5-minute bars (docs/VOLATILITY.md).

For every stock and every full session it finds the desk's breakout (long) and breakdown (short), builds
the slip's numbers the way the desk does (stop, 2R target, chase limit, 10-minute validity, flat by 15:55),
replays it with desk/outcome.replay, and grades it with the Time Machine skill's own simulator using only
the sessions BEFORE that day (walk-forward, like the live desk). Each signal also carries the measures a
volatility screen can use at the moment it fires: ATR % and the opening range's relative volume.

Read-only: one GET per stock for 60 days of 5-minute bars and one for a year of daily bars, cached on disk.
It never touches a journal, an order or a setting.
"""
import gzip
import hashlib
import importlib.util
import json
import math
import time

from . import charts
from . import outcome
from .paths import ROOT

TM_PATH = ROOT / "vendor" / "day-trader-skill" / "trader-timemachine" / "timemachine.py"
OPEN_MIN, BARS = 9 * 60 + 30, 78
FEATURE_DAYS = 14          # ATR and relative volume look back this many sessions


def _tm():
    spec = importlib.util.spec_from_file_location("trader_timemachine", TM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- data

def load(symbol, cache, fetch=True, pause=1.5):
    """{"intraday": 60d of 5m bars, "daily": 1y of daily bars}, each as desk/charts.parse returns it, cached."""
    out = {}
    for key, rng, iv in (("intraday", "60d", "5m"), ("daily", "1y", "1d")):
        f = cache / ("%s-%s%s.json.gz" % (symbol, rng, iv))
        if f.exists():
            with gzip.open(f, "rt") as fh:
                out[key] = json.load(fh)
            continue
        if not fetch:
            raise charts.ChartError("no cached %s %s" % (symbol, key))
        doc = charts.fetch(symbol, rng, iv, timeout=30)
        cache.mkdir(parents=True, exist_ok=True)
        with gzip.open(f, "wt") as fh:
            json.dump(doc, fh)
        out[key] = doc
        time.sleep(pause)           # be polite to the free endpoint
    return out


def sessions(chart):
    """[(date, [78 bars])], full regular sessions only, oldest first."""
    days = {}
    for b in chart["bars"]:
        if OPEN_MIN <= b["minute"] < 16 * 60 and (b["minute"] - OPEN_MIN) % 5 == 0:
            days.setdefault(b["date"], {})[(b["minute"] - OPEN_MIN) // 5] = b
    return [(d, [s[i] for i in range(BARS)]) for d, s in sorted(days.items()) if len(s) == BARS]


def atr_pct(daily, date, n=FEATURE_DAYS):
    """ATR(n) of the daily bars before `date`, as % of the last close before it. None without enough days."""
    prior = [b for b in daily if b["date"] < date]
    if len(prior) < n + 1:
        return None
    trs = [max(b["h"], p["c"]) - min(b["l"], p["c"]) for p, b in zip(prior[-n - 1:-1], prior[-n:])]
    return 100.0 * sum(trs) / n / prior[-1]["c"]


def sma_before(daily, date, n=200):
    closes = [b["c"] for b in daily if b["date"] < date]
    return sum(closes[-n:]) / n if len(closes) >= n else None


def stable_half(symbol):
    """'A' or 'B', fixed by the ticker's name alone, so the split cannot be tuned."""
    return "AB"[hashlib.md5(symbol.encode()).digest()[0] % 2]


# ---------------------------------------------------------------- one day

def _floor(x):
    return math.floor(x * 100 + 1e-6) / 100


def _ceil(x):
    return math.ceil(x * 100 - 1e-6) / 100


def _hhmm(minute):
    return "%02d:%02d" % (minute // 60, minute % 60)


def plan_day(D, side, rule):
    """The desk's slip for one session and side, or None when nothing triggers. D: 78 bars."""
    n = rule["or_minutes"] // 5
    oh, ol = max(b["h"] for b in D[:n]), min(b["l"] for b in D[:n])
    last_close = 15 * 60 + 30          # no_entries_after
    for k in range(n, BARS):
        b = D[k]
        hit = b["c"] > oh + 1e-9 if side == "long" else b["c"] < ol - 1e-9
        if not hit:
            continue
        if b["minute"] + 5 > last_close:
            return None
        e = round(b["c"], 2)
        sr = rule["stop"]
        if sr == "or-mid":
            stop = (oh + ol) / 2
        elif sr == "or-low":
            stop = ol if side == "long" else oh
        elif sr.startswith("atr:"):        # K x the daily ATR in dollars (rule["atr_usd"] is set per day)
            stop = e - float(sr[4:]) * rule["atr_usd"] if side == "long" else e + float(sr[4:]) * rule["atr_usd"]
        else:
            raise ValueError(sr)
        stop = _floor(stop) if side == "long" else _ceil(stop)
        risk = round(e - stop if side == "long" else stop - e, 2)
        if risk <= 0 or risk < e * rule["min_stop_pct"] / 100:
            return {"k": k, "blocked": "stop too close"}
        tr = rule["target_r"]
        target = round(e + tr * risk, 2) if side == "long" else round(e - tr * risk, 2)
        limit = _floor(e + rule["chase_r"] * risk) if side == "long" else _ceil(e - rule["chase_r"] * risk)
        close_min = b["minute"] + 5
        return {"k": k, "entry": e, "stop": stop, "target": target, "limit": limit, "risk": risk, "side": side,
                "trigger_close_time": _hhmm(close_min), "valid_until": _hhmm(close_min + rule["valid_min"]),
                "flat_by": rule["flat_by"], "or_high": oh, "or_low": ol}
    return None


def odds(tm, prior, p, until="15:55", replays=2000):
    """The Time Machine's simulator on the sessions before the day, as the live desk would have seen it."""
    if len(prior) < tm.MIN_SESSIONS:
        return None
    last = (int(until[:2]) * 60 + int(until[3:]) - OPEN_MIN) // 5 - 1
    if last <= p["k"]:
        return None
    mc = tm.simulate(tm.build_pool(prior[-59:]), p["entry"], p["stop"], p["target"], p["k"], last,
                     replays=replays, seed=19, window=2, side="buy" if p["side"] == "long" else "sell")
    decided = mc["p_target"] + mc["p_stop"]
    edge = None if decided <= 0 else round(100 * (mc["p_target"] / decided - 1 / (1 + mc["r_at_target"])), 1)
    return {"p_target": mc["p_target"], "p_stop": mc["p_stop"], "edge": edge}


DEFAULT_RULE = {"or_minutes": 15, "stop": "or-mid", "target_r": 2.0, "chase_r": 0.2, "valid_min": 10,
                "flat_by": "15:55", "min_stop_pct": 0.3}


def signals(symbol, data, rule=None, replays=2000, tm=None):
    """Every signal the rule makes on this stock's 60 days, with the replay, the odds and the screen measures."""
    rule = dict(DEFAULT_RULE, **(rule or {}))
    tm = tm or _tm()
    days = sessions(data["intraday"])
    daily = data["daily"]["bars"]
    n = rule["or_minutes"] // 5
    out = []
    for i, (date, D) in enumerate(days):
        if i < FEATURE_DAYS:
            continue
        atrp = atr_pct(daily, date)
        prev = [b for b in daily if b["date"] < date]
        if atrp is None or not prev:
            continue
        prev_close = prev[-1]["c"]
        or_vol = sum(b["v"] for b in D[:n])
        past = [sum(b["v"] for b in X[:n]) for _, X in days[i - FEATURE_DAYS:i]]
        rvol = or_vol / (sum(past) / len(past)) if sum(past) > 0 else None
        feats = {"atr_pct": round(atrp, 2), "rvol": round(rvol, 2) if rvol else None,
                 "gap_pct": round(100 * (D[0]["o"] / prev_close - 1), 2), "price": D[0]["o"],
                 "dollar_vol": round(sum(b["v"] * b["c"] for b in days[i - 1][1]) / 1e6, 1)}
        r = dict(rule, atr_usd=atrp / 100 * prev_close)
        for side in ("long", "short"):
            p = plan_day(D, side, r)
            if not p or p.get("blocked"):
                continue
            if side == "short":
                low_so_far = min(b["l"] for b in D[:p["k"] + 1])
                if low_so_far <= prev_close * 0.9:
                    continue                        # the desk blocks a short once the stock is down 10 % (SSR)
                avg = sma_before(daily, date)
                if avg is None or p["entry"] >= avg:
                    continue                        # the desk only shorts under the 200-day average
            res = outcome.replay(p, D)
            if res["result"] in (outcome.NO_FILL, outcome.NO_PLAN):
                continue
            risk = abs(res["entry"] - p["stop"])
            out.append(dict(feats, symbol=symbol, date=date, side=side, result=res["result"], r=res["r"],
                            risk=round(risk, 2), entry=res["entry"], bar=p["k"],
                            odds=odds(tm, days[:i], p, rule["flat_by"], replays) if replays else None))
    return out


# ---------------------------------------------------------------- scoring

def score(rows, cost=0.01, edge_floor=-5.0, bp=0.0):
    """Win rate, average R and profit factor after `cost` dollars a share plus `bp` basis points of the price
    a side (in and out together), counting only signals the desk would grade ready (odds known, edge at or
    over the floor). edge_floor=None counts every signal."""
    ready = [x for x in rows if x["odds"] and x["odds"]["edge"] is not None and x["odds"]["edge"] >= edge_floor] \
        if edge_floor is not None else rows
    rs = [x["r"] - (cost + 2 * bp / 1e4 * x["entry"]) / x["risk"] for x in ready if x["risk"] > 0 and x["r"] is not None]
    wins = sum(1 for r in rs if r > 0)
    gain, loss = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": len(rs), "win_rate": round(100.0 * wins / len(rs), 1) if rs else None,
            "target_rate": round(100.0 * sum(1 for x in ready if x["result"] == outcome.TARGET) / len(ready), 1) if ready else None,
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "pf": round(gain / loss, 2) if loss > 0 else None, "total_r": round(sum(rs), 1)}


BANDS = ((0, 20), (20, 30), (30, 40), (40, 50), (50, 101))


def calibration(rows, min_n=20):
    """Per band of the Time Machine's target-first odds: predicted against what the replay did."""
    out = []
    for lo, hi in BANDS:
        b = [x for x in rows if x["odds"] and lo <= 100 * x["odds"]["p_target"] < hi]
        if not b:
            continue
        pred = 100.0 * sum(x["odds"]["p_target"] for x in b) / len(b)
        act = 100.0 * sum(1 for x in b if x["result"] == outcome.TARGET) / len(b)
        out.append({"band": "%d-%d%%" % (lo, min(hi, 100)), "n": len(b), "predicted": round(pred, 1),
                    "actual": round(act, 1), "gap": round(act - pred, 1), "counts": len(b) >= min_n})
    return out


def split(rows, cut_date):
    """train = half A before cut_date; held-out = everything else (B always, and A from cut_date on)."""
    train = [x for x in rows if stable_half(x["symbol"]) == "A" and x["date"] < cut_date]
    test = [x for x in rows if not (stable_half(x["symbol"]) == "A" and x["date"] < cut_date)]
    return train, test

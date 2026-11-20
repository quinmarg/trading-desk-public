"""Runs the tests declared in docs/IMPROVE-2026-11-20.md on a scratch cache (DESK_DATA=<scratch> python3 research/improve_2026_11_20.py <repo> <desk symbols file> <out.json>). Read-only."""
import json, random, sys
from multiprocessing import Pool
sys.path.insert(0, sys.argv[1])
from desk import autolist, backtest as B
from desk.paths import data_dir
CUT = "2026-11-20"                      # sessions up to 2026-11-19 only
COST, BP = 0.01, 5.0
SPY = None

def rows_for(args):
    sym, valid = args
    try:
        data = B.load(sym, data_dir() / "backtest", fetch=False)
        rs = B.signals(sym, data, {"valid_min": valid}, replays=0, spy=None, ssr_model=True)
        return [dict(r, valid=valid) for r in rs if r["date"] < CUT]
    except Exception as e:
        print("skip", sym, e, file=sys.stderr); return []

def net(x):
    return x["r"] - (COST + 2 * BP / 1e4 * x["entry"]) / x["risk"]

def stats(rs, boot=2000):
    rs = [x for x in rs if x.get("filled", True) and x["r"] is not None and x["risk"] > 0]
    if not rs: return {"n": 0}
    v = [net(x) for x in rs]
    g, l = sum(a for a in v if a > 0), -sum(a for a in v if a < 0)
    days = {}
    for x, a in zip(rs, v): days.setdefault(x["date"], []).append(a)
    keys = list(days); rnd = random.Random(7); means = []
    for _ in range(boot):
        pick = [a for k in (rnd.choice(keys) for _ in keys) for a in days[k]]
        means.append(sum(pick) / len(pick))
    means.sort()
    return {"n": len(v), "avg": round(sum(v) / len(v), 3), "pf": round(g / l, 2) if l else None, "total": round(sum(v), 1),
            "lo": round(means[int(.025 * boot)], 3), "hi": round(means[int(.975 * boot)], 3), "days": len(keys),
            "win": round(100 * sum(1 for a in v if a > 0) / len(v), 1)}

def inplay(x): return (x["rvol"] or 0) >= 1.5 and x["atr_pct"] >= 3.0

if __name__ == "__main__":
    pool = list(autolist.POOL)
    desk = [s for s in open(sys.argv[2]).read().split() if s not in pool]
    with Pool(7) as p:
        U = {}
        for name, syms in (("pool", pool), ("desk", desk)):
            for valid in (10, 20):
                U[(name, valid)] = [r for rr in p.map(rows_for, [(s, valid) for s in syms]) for r in rr]
    out = {}
    for name in ("pool", "desk"):
        R = U[(name, 10)]
        normal = [x for x in R if not x["ssr"]]
        o = out[name] = {}
        for side in ("long", "short"):
            S_ = [x for x in normal if x["side"] == side]
            o["T1 %s in play" % side] = stats([x for x in S_ if inplay(x)])
            o["T1/T5 %s not in play" % side] = stats([x for x in S_ if not inplay(x)])
        o["T2 ssr shorts, all"] = stats([x for x in R if x["ssr"]])
        o["T2 ssr shorts, in play"] = stats([x for x in R if x["ssr"] and inplay(x)])
        o["T2 ssr shorts, today trigger"] = stats([x for x in R if x["ssr"] == "today"])
        o["T2 ssr shorts, yesterday trigger"] = stats([x for x in R if x["ssr"] == "yesterday"])
        o["T2 ssr shorts, signals (filled or not)"] = {"n": sum(1 for x in R if x["ssr"])}
        # T4: fills that happen only with the 20-minute window (same signal key, unfilled at 10)
        k10 = {(x["symbol"], x["date"], x["side"]): x for x in R if not x["ssr"]}
        extra = [x for x in U[(name, 20)] if not x["ssr"] and x.get("filled", True) and x["r"] is not None
                 and not k10.get((x["symbol"], x["date"], x["side"]), {}).get("filled", False)]
        o["T4 extra fills with 20 min, all"] = stats(extra)
        o["T4 extra fills with 20 min, in play"] = stats([x for x in extra if inplay(x)])
        o["B0 paper rule (in play, no ssr)"] = stats([x for x in normal if inplay(x)])
    json.dump(out, open(sys.argv[3], "w"), indent=1)
    for name, o in out.items():
        print("==", name)
        for k, v in o.items(): print("  %-42s %s" % (k, v))

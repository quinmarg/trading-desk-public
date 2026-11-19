"""Backtest the opening-range rule across a pool of stocks (docs/VOLATILITY.md).

    python3 tools/vol_backtest.py fetch                 # cache 60d 5m + 1y daily bars for the pool
    python3 tools/vol_backtest.py rows --name base      # every signal under the desk's current rule
    python3 tools/vol_backtest.py rows --name atr --stop atr:0.1 --target-r 2
    python3 tools/vol_backtest.py report base           # scores, before/after a screen, train vs held-out

Cache and results live in $DESK_DATA/backtest (default data/backtest). Read-only otherwise.
"""
import argparse
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desk import autolist  # noqa: E402
from desk import backtest as B  # noqa: E402
from desk.paths import data_dir  # noqa: E402

POOL = autolist.POOL       # the same pool the desk picks its daily scan list from


def cache():
    return data_dir() / "backtest"


def cmd_fetch(a):
    bad = []
    for i, s in enumerate(POOL + ["SPY"]):      # SPY for the market fields only; it is not in the pool
        try:
            B.load(s, cache())
            print("%2d/%d %s ok" % (i + 1, len(POOL), s), flush=True)
        except Exception as e:      # one missing ticker must not stop the rest
            bad.append(s)
            print("%2d/%d %s FAILED %s" % (i + 1, len(POOL), s, e), flush=True)
    print("done; failed:", " ".join(bad) or "none")


def _spy():
    """SPY's sessions for the market fields, or None when it is not cached (python3 tools/vol_backtest.py fetch)."""
    try:
        return dict(B.sessions(B.load("SPY", cache(), fetch=False)["intraday"]))
    except Exception:
        return None


def _one(args):
    sym, rule, replays = args
    try:
        return B.signals(sym, B.load(sym, cache(), fetch=False), rule, replays, spy=_spy())
    except Exception as e:
        print("skip %s: %s" % (sym, e), file=sys.stderr)
        return []


def cmd_rows(a):
    rule = {"or_minutes": a.or_minutes, "stop": a.stop, "target_r": a.target_r}
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as p:
        rows = [r for part in p.map(_one, [(s, rule, a.replays) for s in POOL]) for r in part]
    out = cache() / ("rows-%s.json" % a.name)
    out.write_text(json.dumps({"rule": rule, "rows": rows}))
    print("%d signals -> %s" % (len(rows), out))


def screen(rows, atr=0.0, rvol=0.0, side=None, by=None):
    """by: last entry time as a bar index (11 = the bar closing 10:30)."""
    return [x for x in rows if x["atr_pct"] >= atr and (x["rvol"] or 0) >= rvol and (side is None or x["side"] == side)
            and (by is None or x["bar"] <= by)]


def line(name, s):
    return "%-34s n=%4d  win %5s%%  target %5s%%  avgR %6s  PF %5s  totalR %6s" % (
        name, s["n"], s["win_rate"], s["target_rate"], s["avg_r"], s["pf"], s["total_r"])


def cmd_report(a):
    doc = json.loads((cache() / ("rows-%s.json" % a.name)).read_text())
    rows = doc["rows"]
    dates = sorted({x["date"] for x in rows if x["odds"]})   # only graded days can be ready
    cut = dates[int(len(dates) * 0.6)]
    train, test = B.split(rows, cut)
    print("rule:", doc["rule"], " cut:", cut, " days:", dates[0], "to", dates[-1])
    grid = [(0, 0), (3, 0), (5, 0), (0, 1), (0, 1.2), (0, 1.5), (0, 2), (3, 1), (3, 1.2), (3, 1.5), (5, 1), (5, 1.5)]
    parts = (("TRAIN", train), ("HELD-OUT", test)) if a.show_test else (("TRAIN", train),)   # pick on TRAIN only
    for label, part in (parts if a.grid else ()):
        print("\n== %s (%d signals before the odds floor)" % (label, len(part)))
        for side in (None, "long", "short"):
            for atr, rv in grid:
                rs = screen(part, atr, rv, side)
                print(line("%s atr>=%g rvol>=%g" % (side or "both", atr, rv), B.score(rs, a.cost)))
    if a.atr is not None:
        for label, part in parts:
            rs = screen(part, a.atr, a.rvol, a.side, a.by)
            print("\n== %s calibration, atr>=%g rvol>=%g %s by bar %s" % (label, a.atr, a.rvol, a.side or "both", a.by))
            for c in B.calibration([x for x in rs if x["odds"] and x["odds"]["edge"] is not None and x["odds"]["edge"] >= -5]):
                print("  ", c)
            for cost, bp in ((0.01, 0), (0.03, 0), (0.01, 2), (0.01, 5)):
                print(line("   cost $%.2f/share + %gbp a side" % (cost, bp), B.score(rs, cost, bp=bp)))
            print(line("   no odds floor (every signal)", B.score(rs, a.cost, edge_floor=None)))


def cmd_compare(a):
    """Every variant against every screen, TRAIN only unless --show-test: ready signals, $0.01 a share."""
    for name in a.names:
        rows = json.loads((cache() / ("rows-%s.json" % name)).read_text())["rows"]
        dates = sorted({x["date"] for x in rows if x["odds"]})
        train, test = B.split(rows, dates[int(len(dates) * 0.6)])
        part = test if a.show_test else train
        for atr, rv, side, by in ((0, 0, None, None), (0, 1, None, None), (0, 1.2, None, None), (0, 1.5, None, None),
                                  (3, 1, None, None), (3, 1.2, None, None), (0, 1, "long", None),
                                  (0, 1, "short", None), (0, 1, None, 11)):
            label = "%-12s atr>=%g rvol>=%g %s%s" % (name, atr, rv, side or "both", " by10:30" if by else "")
            print(line(label, B.score(screen(part, atr, rv, side, by), 0.01)))
        print()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    r = sub.add_parser("rows")
    r.add_argument("--name", required=True)
    r.add_argument("--or-minutes", type=int, default=15)
    r.add_argument("--stop", default="or-mid")
    r.add_argument("--target-r", type=float, default=2.0)
    r.add_argument("--replays", type=int, default=2000)
    p = sub.add_parser("report")
    p.add_argument("name")
    p.add_argument("--cost", type=float, default=0.01)
    p.add_argument("--atr", type=float)
    p.add_argument("--rvol", type=float, default=0.0)
    p.add_argument("--side")
    p.add_argument("--by", type=int)
    p.add_argument("--show-test", action="store_true", help="also score the held-out set (once the rule is chosen)")
    p.add_argument("--grid", action="store_true", help="also print the screen grid")
    c = sub.add_parser("compare")
    c.add_argument("names", nargs="+")
    c.add_argument("--show-test", action="store_true")
    a = ap.parse_args()
    {"fetch": cmd_fetch, "rows": cmd_rows, "report": cmd_report, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()

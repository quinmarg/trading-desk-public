"""The one-time test of the sealed finalists. Refuses to run twice, and refuses if the sealed code changed.

Declared before it ran (2026-11-19), on top of dev.py's rule:
- held-out US: SPY 2010-01-04 .. 2026-11-18, each strategy running continuously from 1961 (so it enters 2010
  in whatever state its rule had), equity rebased at the start. p = one-sided stationary bootstrap of the daily
  log return over buy-and-hold, times 3 (Bonferroni, three finalists).
- walk-forward: every year 2000..2026 the dev rule (F1 and F3 versions) is re-applied to 1961..the end of the
  year before, using only that past, and the pick trades the next year. 5 bp a side extra when the pick changes.
- foreign: the indices in data.FOREIGN (not used by the friend's lab), price only, cash earns 0, fills at the
  next close, costs doubled (less liquid markets); win = log return over buy-and-hold above 0. data.OTHER_US
  (Russell 2000, Nasdaq) reported apart: they move with SPY.
- tax view: 22 % on short-term gains and interest, 15 % on long-term gains and dividends, paid each year,
  nothing at the end; from 2010-01-04 in cash. Shown beside the pre-tax numbers, not used for PASS.
Run: python3 -m research.beat_spy.test
"""
import json
import sys
import time

from . import data
from . import dev
from . import engine as E

OUT = dev.HERE / "out"
LOCK = OUT / "test.lock"
RESULT = OUT / "test_result.json"
FOREIGN_COST = 2.0
CHART_FROM = "1993-02-01"


def cut_stats(res, days, idx, a, b):
    ks = [k for k, j in enumerate(idx) if a <= days[j]["date"] <= b]
    x, y = ks[0], ks[-1] + 1
    sub = {"eq": [], "ret": res["ret"][x:y], "exp": res["exp"][x:y], "trades": 0}
    v = 1.0
    for r in sub["ret"]:
        v *= 1 + r
        sub["eq"].append(v)
    if "trade_days" in res:
        sub["trades"] = sum(1 for k in res["trade_days"] if x <= k < y)
    st = E.stats(sub, days, idx[x:y])
    return st, sub


def main(dry=False):
    """dry: every step on development data only (held-out = 2005-2009, walk-forward 2000-2009, foreign indices
    cut at 2009), no lock, output to out/dry_run.json. Proves the code runs before the one real run."""
    global LOCK, RESULT
    if dry:
        LOCK, RESULT = OUT / "dry.lock", OUT / "dry_run.json"
    elif LOCK.exists() or RESULT.exists():
        sys.exit("The held-out test already ran (%s). It runs once; read out/test_result.json." % LOCK)
    seal = json.loads(dev.SEAL.read_text())
    if seal["fingerprint"] != dev.fingerprint():
        sys.exit("engine.py, dev.py or data.py changed since the seal; the test would not test what was sealed.")
    LOCK.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + " test started\n")
    t0 = time.time()
    E.SPREAD = seal["spread"]
    a_test, b_test = ("2005-01-03", dev.DEV_END) if dry else seal["test"]
    days = [d for d in E.us_market() if d["date"] <= b_test]
    cfgs = dev.grid()
    sg = E.Signals(days)
    idx = E.window(days, dev.WIN_B[0], b_test)
    sims = {}
    for i, c in enumerate(cfgs + [dev.BENCH]):
        sims[i] = E.simulate(days, E.signal(c, sg), idx)
    bench = sims.pop(len(cfgs))
    key = {json.dumps(c, sort_keys=True): i for i, c in enumerate(cfgs)}
    fins = [(f["tag"], f["name"], key[json.dumps(f["cfg"], sort_keys=True)]) for f in seal["finalists"]]
    combo_i = key[json.dumps({"family": "combo", "L": 1.0}, sort_keys=True)]
    out = {"ran": time.strftime("%Y-%m-%d %H:%M"), "seal_fingerprint": seal["fingerprint"], "test": seal["test"]}

    # 1) held-out SPY
    book = [("SPY buy and hold", None, bench), ("Combined model (1x)", "combo", sims[combo_i])]
    book += [(tag + ": " + nm, tag, sims[i]) for tag, nm, i in fins]
    held = {}
    for label, tag, res in book:
        st, sub = cut_stats(res, days, idx, a_test, b_test)
        bsub = cut_stats(bench, days, idx, a_test, b_test)[1]
        lx = E.log_excess(sub["ret"], bsub["ret"])
        p = E.boot_p(lx) if res is not bench else None
        held[label] = dict(st, excess_log_yr=252 * sum(lx) / len(lx), p=p,
                           p_bonf=min(1.0, 3 * p) if (p is not None and tag and tag.startswith("F")) else None)
        # the same from 2000 (seen data for the combined model and for published rules)
        st0, _ = cut_stats(res, days, idx, "2000-01-03", b_test)
        held[label]["from_2000"] = st0
        st_dev, _ = cut_stats(res, days, idx, *dev.WIN_A)
        held[label]["dev_A"] = st_dev
    out["held_out"] = held

    # 2) tax view, from 2010 in cash
    tidx = E.window(days, a_test, b_test)
    taxed = {}
    for label, cfg in [("SPY buy and hold", dev.BENCH), ("Combined model (1x)", {"family": "combo", "L": 1.0})] + \
            [(f["tag"] + ": " + f["name"], f["cfg"]) for f in seal["finalists"]]:
        r = E.simulate(days, E.signal(cfg, sg), tidx, tax=E.TAX)
        taxed[label] = dict(E.stats(r, days, tidx), tax_paid_per_dollar=r["tax_paid"])
    out["after_tax_2010"] = taxed

    # 3) walk-forward
    pos = {days[j]["date"]: k for k, j in enumerate(idx)}
    wf = {"F1": {}, "F2": {}, "F3": {}}
    picks = {"F1": [], "F2": [], "F3": []}
    for y in range(2000, int(b_test[:4]) + 1):
        rows = dev.evaluate(days, idx, sims, bench, cfgs, [dev.WIN_B, ("1993-02-01", "%d-12-31" % (y - 1))])
        chosen = dict(zip(("F1", "F2", "F3"), dev.select(rows)))
        ks = [k for d, k in pos.items() if d[:4] == str(y)]
        for tag, f in chosen.items():
            i = f["i"] if f else None
            prev = picks[tag][-1][1] if picks[tag] else None
            picks[tag].append((y, i, f["name"] if f else "buy and hold (none eligible)"))
            for n, k in enumerate(ks):
                r = sims[i]["ret"][k] if i is not None else bench["ret"][k]
                if n == 0 and prev != i and len(picks[tag]) > 1:
                    r -= 2 * 5e-4
                wf[tag][days[idx[k]]["date"]] = r
        print("walk-forward %d: F1 %s | F3 %s" % (y, picks["F1"][-1][2], picks["F3"][-1][2]), flush=True)
    out["walk_forward"] = {"picks": picks}
    for tag in wf:
        for a in ("2000-01-03", a_test):
            ds = [d for d in sorted(wf[tag]) if d >= a]
            r = [wf[tag][d] for d in ds]
            br = [bench["ret"][pos[d]] for d in ds]
            st = dev.window_stats(r, [days[idx[pos[d]]]["rf"] / 252 for d in ds])
            lx = E.log_excess(r, br)
            out["walk_forward"]["%s from %s" % (tag, a[:4])] = dict(
                st, excess_log_yr=252 * sum(lx) / len(lx), p=E.boot_p(lx))

    # 4) foreign and other US indices
    fx = {}
    for group, syms in (("foreign", data.FOREIGN), ("other_us", data.OTHER_US)):
        for sym in syms:
            m = [d for d in E.index_market(sym) if not dry or d["date"] <= dev.DEV_END]
            if len(m) < 600:
                continue
            msg = E.Signals(m)
            midx = list(range(300, len(m)))
            mb = E.simulate(m, E.signal(dev.BENCH, msg), midx, cost_mult=FOREIGN_COST)
            row = {"group": group, "from": m[300]["date"], "to": m[-1]["date"],
                   "bh": E.stats(mb, m, midx)}
            for label, cfg in [("combo", {"family": "combo", "L": 1.0})] + [(f["tag"][:2], f["cfg"]) for f in seal["finalists"]]:
                r = E.simulate(m, E.signal(cfg, msg), midx, cost_mult=FOREIGN_COST)
                lx = E.log_excess(r["ret"], mb["ret"])
                row[label] = dict(E.stats(r, m, midx), excess_log_yr=252 * sum(lx) / len(lx))
            fx[sym] = row
            print("index %s done" % sym, flush=True)
    out["indices"] = fx

    # 5) the leveraged-fund model against the real funds, whole life
    out["fund_check_full"] = {k: {"years": v[0], "real_cagr": v[1], "synthetic_cagr": v[2]}
                              for k, v in E.validate_funds(days, "2006-06-21", b_test).items()}

    # 6) the declared PASS rule
    verdict = {}
    for tag, nm, i in fins:
        h = held[tag + ": " + nm]
        wins = [fx[s][tag[:2]]["excess_log_yr"] > 0 for s in data.FOREIGN if s in fx]
        wfx = out["walk_forward"]["%s from %s" % (tag[:2], a_test[:4])]["excess_log_yr"]
        verdict[tag] = {"held_out_beats": h["excess_log_yr"] > 0, "p_bonf": h["p_bonf"],
                        "foreign_wins": "%d of %d" % (sum(wins), len(wins)),
                        "walk_forward_beats": wfx > 0,
                        "PASS": h["excess_log_yr"] > 0 and h["p_bonf"] < 0.05 and wfx > 0 and sum(wins) >= 2 * len(wins) / 3}
    out["verdict"] = verdict

    # 7) curves for the chart (from CHART_FROM, rebased to $10,000)
    k0 = pos[next(d for d in pos if d >= CHART_FROM)]
    curves = {"dates": [days[j]["date"] for j in idx[k0:]]}
    for label, tag, res in book:
        v, pts = 10000.0, []
        for r in res["ret"][k0:]:
            v *= 1 + r
            pts.append(round(v, 2))
        curves[label] = pts
    for tag in ("F1", "F3"):
        v, pts = 10000.0, []
        for d in curves["dates"]:
            v *= 1 + (wf[tag].get(d, 0.0) if d >= "2000-01-03" else bench["ret"][pos[d]])
            pts.append(round(v, 2))
        curves["walk-forward " + tag] = pts
    out["curves"] = curves
    RESULT.write_text(json.dumps(out, indent=1))
    LOCK.write_text(LOCK.read_text() + time.strftime("%Y-%m-%d %H:%M:%S") + " finished in %.0fs\n" % (time.time() - t0))
    print(json.dumps({k: v for k, v in out.items() if k != "curves"}, indent=1)[:20000])


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)

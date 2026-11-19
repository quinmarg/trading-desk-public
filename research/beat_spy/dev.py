"""Development: every candidate on data up to 2009-12-31 only, finalists picked by the fixed rule, sealed to JSON.

Everything that decides the outcome is declared here, before any result was seen (2026-11-19):

DATA     US stocks 1961-01-03 .. 2009-12-31, nothing later is even loaded (DEV_END):
           window B 1961-1992: ^GSPC + Shiller dividends, fills at the next close (no real opens);
           window A 1993-02-01 .. 2009-12-31: SPY with dividends, fills at the next open.
COSTS    SPY 3 bp a side, 2x/3x funds 5 bp, bonds 2 bp; leveraged funds pay 0.88 %/yr (ProShares SSO/UPRO gross,
         2026-11-19) plus borrowing at T-bill + SPREAD, daily reset; SPREAD is calibrated so the synthetic 2x
         matches real SSO over its development life (2006-06-21 .. 2009-12-31), nothing later. Cash earns ^IRX.
         Rebalance only when exposure is 10 points off target. Taxes off in selection (shown both ways later).
FAMILIES the GRID below: 222 configurations, all counted as trials for the multiple-testing checks.
RULE     eligible = worst drop no deeper than buy-and-hold's in window A AND in window B (with all costs);
         F1 "most return"     eligible, highest yearly log return over buy-and-hold across A+B;
         F2 "best Sharpe"     eligible, beats buy-and-hold across A+B, highest Sharpe across A+B (not F1);
         F3 "no leverage"     eligible, never above 1x, highest yearly log return over buy-and-hold (not F1, F2).
PASS     (to be added to the desk, judged in test.py): on SPY 2010-01-04 .. 2026-11-18 after costs the finalist
         beats buy-and-hold with a bootstrap p (one-sided, Bonferroni x3) under 0.05, AND the yearly walk-forward
         beats buy-and-hold over 2010-2026, AND it beats the index (excess over cash) on at least 2/3 of the
         unused foreign indices.
Run: python3 -m research.beat_spy.dev   (refuses to overwrite out/sealed.json)
"""
import hashlib
import json
import math
import sys
import time
from pathlib import Path

from . import data
from . import engine as E

HERE = Path(__file__).resolve().parent
SEAL = HERE / "out" / "sealed.json"
DEV_END = "2009-12-31"
WIN_B = ("1961-01-03", "1992-12-31")
WIN_A = ("1993-02-01", DEV_END)
TEST = ("2010-01-04", "2026-11-18")

LEV = (1.0, 1.5, 2.0, 3.0)


def grid():
    g = [{"family": "hold", "L": L} for L in (1.25, 1.5, 2.0, 3.0)]
    g += [{"family": "sma", "n": n, "band": b, "L": L, "off": o}
          for n in (50, 100, 150, 200, 250) for b in (0.0, 0.01, 0.02) for L in LEV for o in ("cash", "bonds")]
    g += [{"family": "dual", "m": m, "L": L, "off": o} for m in (3, 6, 9, 12) for L in LEV for o in ("cash", "bonds")]
    g += [{"family": "vt", "target": t, "d": d, "cap": c, "filt": f}
          for t in (0.10, 0.15, 0.20) for d in (20, 60) for c in LEV for f in (False, True)]
    g += [{"family": "combo", "L": L} for L in LEV]
    g += [{"family": "season", "Lw": w, "Ls": s, "filt": f}
          for w, s in ((1, 0), (1.5, 0.5), (2, 1), (2, 0), (3, 1)) for f in (False, True)]
    g += [{"family": "tom", "Lt": t, "b": b} for t, b in ((1, 0), (2, 1), (3, 1), (2, 0))]
    return g


BENCH = {"family": "hold", "L": 1.0}


def max_exp(c):
    return max(c.get(k, 0) for k in ("L", "cap", "Lw", "Lt", "b", "Ls"))


def name(c):
    f = c["family"]
    if f == "hold":
        return "hold %gx" % c["L"]
    if f == "sma":
        return "%gx above %d-day avg (band %g%%), else %s" % (c["L"], c["n"], 100 * c["band"], c["off"])
    if f == "dual":
        return "%gx when %d-month return beats T-bills, else %s" % (c["L"], c["m"], c["off"])
    if f == "vt":
        return "vol target %d%% (%d-day), cap %gx%s" % (100 * c["target"], c["d"], c["cap"],
                                                        ", out below 200-day avg" if c["filt"] else "")
    if f == "combo":
        return "Combined model x%g" % c["L"]
    if f == "season":
        return "%gx Nov-Apr, %gx May-Oct%s" % (c["Lw"], c["Ls"], ", out below 200-day avg" if c["filt"] else "")
    return "%gx turn of month, %gx otherwise" % (c["Lt"], c["b"])


def calibrate_spread(days):
    """Bisect SPREAD so the synthetic 2x earns what real SSO did over 2006-06-21 .. DEV_END."""
    lo, hi = 0.0, 0.05
    for _ in range(40):
        E.SPREAD = (lo + hi) / 2
        yrs, real, syn = E.validate_funds(days, "2006-06-21", DEV_END)["SSO"]
        lo, hi = (E.SPREAD, hi) if syn > real else (lo, E.SPREAD)
    return round(E.SPREAD, 5)


def window_stats(rets, rfs):
    """CAGR, worst drop and Sharpe of a list of day returns."""
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    ex = [r - f for r, f in zip(rets, rfs)]
    m = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (len(ex) - 1)) or 1e-12
    return {"cagr": eq ** (252.0 / len(rets)) - 1, "max_dd": dd, "sharpe": m / sd * math.sqrt(252), "end": eq}


def run_all(days, cfgs, start, end):
    """Each config simulated once, continuously over [start, end]. Returns (idx, {i: sim result})."""
    sg = E.Signals(days)
    idx = E.window(days, start, end)
    return idx, {i: E.simulate(days, E.signal(c, sg), idx) for i, c in enumerate(cfgs)}


def evaluate(days, idx, sims, bench, cfgs, windows):
    """Per-config training numbers over `windows` (list of (start, end)), against buy-and-hold."""
    pos = {days[j]["date"]: k for k, j in enumerate(idx)}
    cuts = []
    for a, b in windows:
        ks = [k for d, k in pos.items() if a <= d <= b]
        cuts.append((min(ks), max(ks) + 1))
    rfs = [days[j]["rf"] / 252 for j in idx]
    rows = []
    bwin = [window_stats(bench["ret"][x:y], rfs[x:y]) for x, y in cuts]
    for i, c in enumerate(cfgs):
        r = sims[i]["ret"]
        allr = [v for x, y in cuts for v in r[x:y]]
        allb = [v for x, y in cuts for v in bench["ret"][x:y]]
        allf = [v for x, y in cuts for v in rfs[x:y]]
        lx = E.log_excess(allr, allb)
        ws = [window_stats(r[x:y], rfs[x:y]) for x, y in cuts]
        rows.append({"i": i, "cfg": c, "name": name(c), "ex": 252 * sum(lx) / len(lx),
                     "sharpe": window_stats(allr, allf)["sharpe"], "dd": [w["max_dd"] for w in ws],
                     "cagr": [w["cagr"] for w in ws], "bh_dd": [w["max_dd"] for w in bwin],
                     "bh_cagr": [w["cagr"] for w in bwin], "maxexp": max_exp(c), "lx": lx})
    return rows


def select(rows):
    """The fixed rule (module docstring). Returns [F1, F2, F3] rows (some may be None)."""
    ok = [r for r in rows if all(d >= b for d, b in zip(r["dd"], r["bh_dd"]))]
    f1 = max(ok, key=lambda r: r["ex"], default=None)
    rest = [r for r in ok if r is not f1 and r["ex"] > 0]
    f2 = max(rest, key=lambda r: r["sharpe"], default=None)
    rest = [r for r in ok if r not in (f1, f2) and r["maxexp"] <= 1]
    f3 = max(rest, key=lambda r: r["ex"], default=None)
    return [f1, f2, f3]


def fingerprint():
    h = hashlib.sha256()
    for f in ("engine.py", "dev.py", "data.py"):
        h.update((HERE / f).read_bytes())
    return h.hexdigest()[:16]


def main():
    if SEAL.exists():
        sys.exit("out/sealed.json exists: the finalists are sealed. Development cannot be rerun into it.")
    t0 = time.time()
    days = [d for d in E.us_market(fetch=True) if d["date"] <= DEV_END]
    assert days[-1]["date"] <= DEV_END
    spread = calibrate_spread(days)
    fund_check = E.validate_funds(days, "2006-06-21", DEV_END)
    cfgs = grid()
    idx, sims = run_all(days, cfgs + [BENCH], WIN_B[0], DEV_END)
    bench = sims.pop(len(cfgs))
    rows = evaluate(days, idx, sims, bench, cfgs, [WIN_B, WIN_A])
    fin = select(rows)
    srs = [E.moments(r["lx"])[0] for r in rows]
    rc_p = E.reality_check([r["lx"] for r in rows])
    out = []
    for tag, r in zip(("F1 most return", "F2 best Sharpe", "F3 no leverage"), fin):
        if r is None:
            continue
        dsr, sr0 = E.deflated_sharpe(r["lx"], srs)
        out.append({"tag": tag, "cfg": r["cfg"], "name": r["name"], "dev_excess_log_yr": r["ex"],
                    "dev_sharpe": r["sharpe"], "dev_cagr_B_A": r["cagr"], "dev_dd_B_A": r["dd"],
                    "dev_boot_p": E.boot_p(r["lx"]), "deflated_sharpe_prob": dsr, "dsr_p": 1 - dsr})
    combo = next(r for r in rows if r["cfg"] == {"family": "combo", "L": 1.0})
    seal = {"sealed": time.strftime("%Y-%m-%d %H:%M"), "fingerprint": fingerprint(), "dev_end": DEV_END,
            "windows": {"B": WIN_B, "A": WIN_A}, "test": TEST, "spread": spread, "fee": E.FEE, "costs_bp": E.COSTS,
            "tol": E.TOL, "trials": len(cfgs), "reality_check_p": rc_p,
            "fund_check_dev": {k: {"years": v[0], "real_cagr": v[1], "synthetic_cagr": v[2]} for k, v in fund_check.items()},
            "buy_hold_dev": {"cagr_B_A": rows[0]["bh_cagr"], "dd_B_A": rows[0]["bh_dd"]},
            "combo_dev": {"excess_log_yr": combo["ex"], "cagr_B_A": combo["cagr"], "dd_B_A": combo["dd"],
                          "sharpe": combo["sharpe"]},
            "eligible": sum(1 for r in rows if all(d >= b for d, b in zip(r["dd"], r["bh_dd"]))),
            "finalists": out}
    SEAL.parent.mkdir(exist_ok=True)
    SEAL.write_text(json.dumps(seal, indent=1))
    table = sorted(rows, key=lambda r: -r["ex"])
    (HERE / "out" / "dev_table.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "lx"} for r in table], indent=0))
    print("sealed %s in %.0fs; spread %.3f%%; RC p %.3f" % (SEAL, time.time() - t0, 100 * spread, rc_p))
    print(json.dumps(seal, indent=1))


if __name__ == "__main__":
    main()

"""Descriptive only, NOT a test: how far above SPY simple leverage got in 2010-2026 and 2026 so far, and what it cost
in worst drops (including 1961-2009, when 1987 happened). Uses data the sealed test already used, so nothing here
picks a model. Run: python3 -m research.beat_spy.frontier
"""
import json

from . import dev
from . import engine as E

ROWS = [("SPY buy and hold", dev.BENCH),
        ("1.5x hold (SPY + SSO)", {"family": "hold", "L": 1.5}),
        ("2x hold (SSO)", {"family": "hold", "L": 2.0}),
        ("3x hold (UPRO)", {"family": "hold", "L": 3.0}),
        ("2x above 200-day, else cash", {"family": "sma", "n": 200, "band": 0.0, "L": 2.0, "off": "cash"}),
        ("3x above 200-day, else cash", {"family": "sma", "n": 200, "band": 0.0, "L": 3.0, "off": "cash"}),
        ("F1 sealed: 3x Nov-Apr, 1x May-Oct", {"family": "season", "Lw": 3, "Ls": 1, "filt": True})]


def main():
    seal = json.loads(dev.SEAL.read_text())
    E.SPREAD = seal["spread"]
    days = [d for d in E.us_market() if d["date"] <= seal["test"][1]]
    sg = E.Signals(days)
    idx = E.window(days, dev.WIN_B[0], seal["test"][1])
    pos = {days[j]["date"]: k for k, j in enumerate(idx)}
    out = []
    bench = None
    for label, cfg in ROWS:
        r = E.simulate(days, E.signal(cfg, sg), idx)["ret"]
        bench = bench or r
        row = {"rule": label}
        for tag, a, b in (("1961-2009", "1961-01-03", "2009-12-31"), ("2010-2026", "2010-01-04", seal["test"][1]),
                          ("2026 YTD", "2026-01-02", seal["test"][1])):
            ks = [pos[d] for d in pos if a <= d <= b]
            st = dev.window_stats(r[ks[0]:ks[-1] + 1], [days[idx[k]]["rf"] / 252 for k in ks])
            bst = dev.window_stats(bench[ks[0]:ks[-1] + 1], [0.0] * len(ks))
            yr = tag == "2026 YTD"
            row[tag] = {"ret": st["end"] - 1 if yr else st["cagr"], "vs_spy": (st["end"] - bst["end"]) if yr else
                        st["cagr"] - bst["cagr"], "worst": st["max_dd"]}
        out.append(row)
    (dev.HERE / "out" / "frontier.json").write_text(json.dumps(out, indent=1))
    print("%-36s | %-24s | %-24s | %s" % ("rule", "1961-2009 a yr / worst", "2010-2026 a yr / worst", "2026 YTD / vs SPY"))
    for o in out:
        a, b, c = o["1961-2009"], o["2010-2026"], o["2026 YTD"]
        print("%-36s | %6.1f%% (%+5.1f) %6.0f%% | %6.1f%% (%+5.1f) %6.0f%% | %6.1f%% (%+5.1f)" % (
            o["rule"], 100 * a["ret"], 100 * a["vs_spy"], 100 * a["worst"], 100 * b["ret"], 100 * b["vs_spy"],
            100 * b["worst"], 100 * c["ret"], 100 * c["vs_spy"]))


if __name__ == "__main__":
    main()

"""Four books from 2000 at $10,000: the S&P 500, the friend's model, the combined model (the desk's book before this
work) and the winter 3x book now on the desk. Reads the cached Yahoo data and out/test_result.json; no new test.

- S&P 500 and the two combined-model versions: exactly as research/compare_models.py (the desk's own book code).
- Winter 3x: the research engine's replay (synthetic 3x fund with ProShares' fee and swap financing calibrated to real
  SSO, T-bill cash, dividends reinvested), from the sealed test's file, rebased to $10,000 on the same first day.
Run: python3 -m research.beat_spy.compare4  ->  research/beat_spy/out/compare4.html
"""
import json

from desk import combo
from research import compare_models as CM
from . import data, dev
from .report import svg

OUT = dev.HERE / "out"


def main():
    rows, divs, _ = combo.parse(data.raw("SPY", fetch=False))
    rates = {b["date"]: b["c"] for b in data.bars("^IRX", fetch=False)}
    end = json.loads((OUT / "sealed.json").read_text())["test"][1]
    rows = [r for r in rows if r["date"] <= end]
    ours, _ = CM.run(rows, divs, rates, "adj")
    his, _ = CM.run(rows, {}, None, "c")
    res = json.loads((OUT / "test_result.json").read_text())["curves"]
    f1key = next(k for k in res if k.startswith("F1"))
    w3 = dict(zip(res["dates"], res[f1key]))
    dates = [c["date"] for c in ours if c["date"] in w3]
    base = w3[dates[0]]
    pick = lambda curve, k: {c["date"]: c[k] for c in curve}
    o, h = pick(ours, "equity"), pick(his, "equity")
    spy = pick(ours, "spy")
    series = [("S&P 500 (SPY, buy and hold)", "#8E97A8", 1.8, [spy[d] for d in dates]),
              ("Friend's model", "#C77DFF", 1.6, [h[d] for d in dates]),
              ("Your model before (combined book)", "#5B8CFF", 2.0, [o[d] for d in dates]),
              ("Winter 3x book (on the desk now)", "#F0B93A", 2.2, [10000 * w3[d] / base for d in dates])]
    stats = [CM.stats([{"v": v} for v in pts], "v") for _, _, _, pts in series]
    chart = svg(dates, [{"label": n, "color": c, "width": w, "dash": False, "pts": p} for n, c, w, p in series], "2010-01-04")
    chart = chart.replace("development (1993-2009)", "picked on data before 2010")
    key = "".join('<span><i style="background:%s"></i>%s</span>' % (c, n) for n, c, _, _ in series)
    trs = "".join('<tr><td><i style="background:%s"></i>%s</td><td>$%s</td><td>%s%%</td><td>%s%%</td><td>%s</td></tr>' % (
        c, n, format(s["end"], ","), s["cagr"], s["max_dd"], s["sharpe"]) for (n, c, _, _), s in zip(series, stats))
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Four models compared</title><style>
:root{--bg:#13161d;--panel:#1a1e27;--text:#eef1f6;--text2:#aab2c2;--line:rgba(200,210,235,.12)}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 40px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
p{color:var(--text2);margin:0 0 14px;max-width:76ch}svg{width:100%%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.g{stroke:var(--line)}.t{fill:var(--text2);font-size:12px}.held{fill:rgba(240,185,58,.07)}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;margin:10px 0 0;color:var(--text2);font-size:13px}
.key span i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.wrap{overflow-x:auto}table{width:100%%;border-collapse:collapse;margin-top:16px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}
th{color:var(--text2);font-weight:500;font-size:13px}td i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px}
</style></head><body><main><h1>$10,000 in each, %s to %s</h1>
<p>Log scale. The S&amp;P 500, a friend's version of the combined model (raw closes, no dividends, no interest),
your combined model as the desk ran it before this work, and the winter 3x book now on the desk (UPRO November to April,
SPY May to October, cash below the 200-day average). Next-day-open fills and costs, T-bill interest on cash.
The winter 3x rule was picked on data before 2010; the shaded years are its one honest test, where it did not
reliably beat the S&amp;P (p = 0.47) and fell much further. From 2000 it was a little ahead by 2009, pulled far ahead in
2010&ndash;2014, and has lost ground to the S&amp;P since 2015. A replay of the past, not a promise, and not advice.</p>
%s<div class="key">%s</div>
<div class="wrap"><table><tr><th>Book</th><th>End value</th><th>Yearly return</th><th>Worst drop</th><th>Sharpe</th></tr>%s</table></div>
</main></body></html>""" % (dates[0], dates[-1], chart, key, trs)
    (OUT / "compare4.html").write_text(html)
    print(OUT / "compare4.html")
    for (n, *_), s in zip(series, stats):
        print("%-36s %s" % (n, s))


if __name__ == "__main__":
    main()

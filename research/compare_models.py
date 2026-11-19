"""Replay the desk's combined SPY book, the friend's version of it and buy-and-hold SPY from 2000, and draw them.

The desk's book (desk/combo.py as it runs): signals on dividend-adjusted closes, dividends paid, T-bill interest on cash.
The friend's book (as the friend's notes describe their desk/combo.py): the same three votes on raw closes, no dividends, no
interest. SPY: buy and hold, dividends reinvested. All fill at the next day's open, 3 bp a side.
Read-only: two GETs to Yahoo. Run: python3 research/compare_models.py  ->  research/out/compare.html
"""
import json
import math
import time
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import combo  # noqa: E402

START = "2000-01-03"


def get(symbol):
    # range=max returns monthly bars; an explicit period keeps them daily
    q = "/v8/finance/chart/%s?period1=725846400&period2=%d&interval=1d&events=div%%2Csplit" % (
        symbol.replace("^", "%5E"), int(time.time()))
    req = urllib.request.Request("https://query2.finance.yahoo.com" + q, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return combo.parse(json.loads(r.read().decode()))


def run(rows, divs, rates, key):
    ind = combo.indicators([r[key] for r in rows])
    days = [{"date": rows[i]["date"], "weight": combo.votes(ind[i - 1], rows[i]["date"])[1], "fill": rows[i]["o"]}
            for i in range(200, len(rows)) if rows[i]["date"] >= START]
    return combo.book(days, rows, divs, rates=rates)


def stats(curve, k):
    a, b = curve[0][k], curve[-1][k]
    yrs = (len(curve) - 1) / 252.0
    peak, dd, rets = a, 0.0, []
    for p, c in zip(curve, curve[1:]):
        rets.append(c[k] / p[k] - 1)
    for c in curve:
        peak = max(peak, c[k])
        dd = min(dd, c[k] / peak - 1)
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    return {"end": round(b), "cagr": round(100 * ((b / a) ** (1 / yrs) - 1), 2), "max_dd": round(100 * dd, 1),
            "sharpe": round(m / sd * math.sqrt(252), 2)}


def svg(series, w=900, h=420, pad=(64, 16, 28, 34)):
    L, R, T, B = pad
    lo = min(min(v for _, v in s["pts"]) for s in series)
    hi = max(max(v for _, v in s["pts"]) for s in series)
    n = len(series[0]["pts"])
    X = lambda i: L + i * (w - L - R) / (n - 1)
    Y = lambda v: T + (math.log(hi) - math.log(v)) / (math.log(hi) - math.log(lo)) * (h - T - B)
    grid = ""
    for v in (10000, 20000, 40000, 80000, 160000):
        if lo <= v <= hi:
            grid += '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="g"/><text x="%d" y="%.1f" class="t" text-anchor="end">$%dk</text>' % (
                L, w - R, Y(v), Y(v), L - 8, Y(v) + 4, v // 1000)
    years = ""
    for i, (d, _) in enumerate(series[0]["pts"]):
        if d[5:10] <= "01-07" and (i == 0 or series[0]["pts"][i - 1][0][:4] != d[:4]) and int(d[:4]) % 4 == 0:
            years += '<text x="%.1f" y="%d" class="t" text-anchor="middle">%s</text>' % (X(i), h - 10, d[:4])
    lines ="".join('<polyline fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" points="%s"/>' % (
        s["color"], s["width"], " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, (_, v) in enumerate(s["pts"]) if i % 3 == 0 or i == n - 1))
        for s in series)
    return '<svg viewBox="0 0 %d %d" role="img" aria-label="Growth of $10,000, log scale">%s%s%s</svg>' % (w, h, grid, years, lines)


def main():
    rows, divs, _ = get("SPY")
    irx, _, _ = get("^IRX")
    rates = {r["date"]: r["c"] for r in irx}
    ours, _ = run(rows, divs, rates, "adj")
    his, _ = run(rows, {}, None, "c")
    spy = [{"date": c["date"], "v": c["spy"]} for c in ours]
    s_ours, s_his = stats(ours, "equity"), stats(his, "equity")
    s_spy = stats([{"v": c["v"]} for c in spy], "v")
    series = [{"name": "S&P 500 (SPY, buy and hold)", "color": "#8E97A8", "width": 1.6, "pts": [(c["date"], c["v"]) for c in spy], "s": s_spy},
              {"name": "Friend's model", "color": "#F0B93A", "width": 1.6, "pts": [(c["date"], c["equity"]) for c in his], "s": s_his},
              {"name": "Your model", "color": "#5B8CFF", "width": 2.2, "pts": [(c["date"], c["equity"]) for c in ours], "s": s_ours}]
    period = "%s to %s" % (ours[0]["date"], ours[-1]["date"])
    rowsh = "".join('<tr><td><i style="background:%s"></i>%s</td><td>$%s</td><td>%s%%</td><td>%s%%</td><td>%s</td></tr>' % (
        s["color"], s["name"], format(s["s"]["end"], ","), s["s"]["cagr"], s["s"]["max_dd"], s["s"]["sharpe"]) for s in series[::-1])
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model comparison</title><style>
:root{--bg:#13161d;--panel:#1a1e27;--text:#eef1f6;--text2:#aab2c2;--line:rgba(200,210,235,.12)}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 40px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
p{color:var(--text2);margin:0 0 16px;max-width:72ch}svg{width:100%%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.g{stroke:var(--line)}.t{fill:var(--text2);font-size:12px}table{width:100%%;border-collapse:collapse;margin-top:16px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}th{color:var(--text2);font-weight:500;font-size:13px}
td i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px}
</style></head><body><main><h1>$10,000 in each, %s</h1>
<p>Growth on a log scale, so equal steps are equal percentage moves. Replayed on free Yahoo daily data, filled at the next open with 3 bp a side.
Your model: the desk's combined SPY book (dip, Halloween and turn-of-month votes on dividend-adjusted closes, dividends paid, T-bill interest on cash).
Friend's model: the same votes as the friend's notes describe them, on raw closes, no dividends, no interest. A replay of the past, not a promise.</p>
%s<table><tr><th>Book</th><th>End value</th><th>Yearly return</th><th>Worst drop</th><th>Sharpe</th></tr>%s</table></main></body></html>""" % (
        period, svg(series), rowsh)
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    (out / "compare.html").write_text(html)
    print(period)
    for s in series[::-1]:
        print("%-28s %s" % (s["name"], s["s"]))


if __name__ == "__main__":
    main()

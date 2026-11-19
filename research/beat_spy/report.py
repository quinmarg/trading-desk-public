"""Draw out/beat_spy.html from out/sealed.json and out/test_result.json (no network, no new test).
Run: python3 -m research.beat_spy.report
"""
import json
import math

from . import dev

OUT = dev.HERE / "out"

SERIES = [  # (key in curves, label, colour, width, dashed)
    ("SPY buy and hold", "S&P 500 (SPY, buy and hold)", "#8E97A8", 1.8, False),
    ("Combined model (1x)", "Your combined model", "#5B8CFF", 2.0, False),
    ("F1", "F1: 3x Nov-Apr, 1x May-Oct, cash below 200-day", "#F0B93A", 2.0, False),
    ("F2", "F2: SPY above 250-day, else Treasuries", "#3FBF8F", 1.8, False),
    ("walk-forward F1", "F1 rule, re-picked yearly (walk-forward)", "#F0B93A", 1.4, True),
]


def svg(dates, series, shade_from, w=900, h=440, pad=(64, 16, 28, 34)):
    L, R, T, B = pad
    lo = min(min(s["pts"]) for s in series)
    hi = max(max(s["pts"]) for s in series)
    n = len(dates)
    X = lambda i: L + i * (w - L - R) / (n - 1)
    Y = lambda v: T + (math.log(hi) - math.log(v)) / (math.log(hi) - math.log(lo)) * (h - T - B)
    k = next(i for i, d in enumerate(dates) if d >= shade_from)
    out = ['<rect x="%.1f" y="%d" width="%.1f" height="%d" class="held"/>' % (X(k), T, w - R - X(k), h - T - B),
           '<text x="%.1f" y="%d" class="t">held out: rules never saw it</text>' % (X(k) + 8, T + 16),
           '<text x="%.1f" y="%d" class="t">development (1993-2009)</text>' % (L + 8, T + 16)]
    v = 10000
    while v <= hi * 1.01:
        if v >= lo:
            out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="g"/><text x="%d" y="%.1f" class="t" '
                       'text-anchor="end">$%sk</text>' % (L, w - R, Y(v), Y(v), L - 8, Y(v) + 4, format(v // 1000, ",")))
        v *= 2
    for i, d in enumerate(dates):
        if i and d[:4] != dates[i - 1][:4] and int(d[:4]) % 4 == 0:
            out.append('<text x="%.1f" y="%d" class="t" text-anchor="middle">%s</text>' % (X(i), h - 10, d[:4]))
    for s in series:
        pts = " ".join("%.1f,%.1f" % (X(i), Y(p)) for i, p in enumerate(s["pts"]) if i % 3 == 0 or i == n - 1)
        out.append('<polyline fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s points="%s"/>' % (
            s["color"], s["width"], ' stroke-dasharray="5 4"' if s["dash"] else "", pts))
    return '<svg viewBox="0 0 %d %d" role="img" aria-label="Growth of $10,000 on a log scale, 1993 to 2026">%s</svg>' % (
        w, h, "".join(out))


def pct(x, d=1):
    return "%.*f%%" % (d, 100 * x)


def main():
    seal = json.loads((OUT / "sealed.json").read_text())
    res = json.loads((OUT / "test_result.json").read_text())
    cur, held = res["curves"], res["held_out"]
    long = {k.split(":")[0]: k for k in held}
    pick = {"F1": long["F1 most return"], "F2": long["F2 best Sharpe"]}
    series = []
    for key, label, color, width, dash in SERIES:
        ck = pick.get(key, key)
        series.append({"label": label, "color": color, "width": width, "dash": dash, "pts": cur[ck]})
    dates = cur["dates"]
    tax = res["after_tax_2010"]
    rows = []
    for key, label, color, _, dash in SERIES:
        if key.startswith("walk"):
            s = res["walk_forward"]["F1 from 2010"]
            rows.append((color, dash, label, s["cagr"], s["max_dd"], s["sharpe"], s["excess_log_yr"], s["p"], None,
                         None, None))
            continue
        k = pick.get(key, key)
        s = held[k]
        p = s["p_bonf"] if s["p_bonf"] is not None else s["p"]
        rows.append((color, dash, label, s["cagr"], s["max_dd"], s["sharpe"], s["excess_log_yr"], p,
                     tax[k]["cagr"], s["dev_A"]["cagr"], s["dev_A"]["max_dd"]))
    trs = "".join(
        '<tr><td><i style="background:%s%s"></i>%s</td><td>%s</td><td>%s</td><td>%.2f</td><td>%s</td><td>%s</td>'
        '<td>%s</td><td>%s</td></tr>' % (
            c, ";opacity:.6" if dash else "", lab, pct(cg), pct(dd), sh,
            ("%+.1f" % (100 * ex)) if ex else "–", ("%.2f" % p) if p is not None else "–",
            pct(tx) if tx is not None else "–",
            (pct(dc) + " / " + pct(dd2, 0)) if dc is not None else "–")
        for c, dash, lab, cg, dd, sh, ex, p, tx, dc, dd2 in rows)
    fin = seal["finalists"]
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beat the S&amp;P test</title><style>
:root{--bg:#13161d;--panel:#1a1e27;--text:#eef1f6;--text2:#aab2c2;--line:rgba(200,210,235,.12)}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 40px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
h2{font-size:16px;font-weight:600;margin:28px 0 6px}
p{color:var(--text2);margin:0 0 14px;max-width:76ch}svg{width:100%%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.g{stroke:var(--line)}.t{fill:var(--text2);font-size:12px}.held{fill:rgba(240,185,58,.07)}
.wrap{overflow-x:auto}table{width:100%%;border-collapse:collapse;margin-top:12px;font-variant-numeric:tabular-nums;font-size:14px}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;margin:10px 0 0;color:var(--text2);font-size:13px}
.key span i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
td:first-child{min-width:190px}th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}
th{color:var(--text2);font-weight:500;font-size:12.5px}td i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px}
strong{color:var(--text)}
</style></head><body><main><h1>Can a rule beat the S&amp;P? $10,000 in each, %s to %s</h1>
<p><strong>No rule clearly beat buy-and-hold on years it never saw.</strong> %d rules were tried on 1961&ndash;2009 only, three
finalists were sealed, then tested once on 2010&ndash;2026 (shaded). The best one, 3x leverage in winter, beat SPY by %s a year
before tax with a worse crash, and the edge is indistinguishable from luck (p = %.2f). After tax it lost.
Your combined model gave up %s a year in the held-out years for a smaller worst drop.</p>
<p>Log scale, so equal steps are equal percentage moves. Free Yahoo daily data; fills at the next open; 3 bp a side on SPY,
5 bp on the 2x/3x funds; leveraged funds pay %.2f%% a year in fees plus borrowing at T-bills + %.2f%%, reset daily; cash earns
T-bills; dividends reinvested. The walk-forward line re-picks its rule every January from past data only.</p>
%s
<div class="key">%s</div>
<h2>Held-out years, 2010&ndash;2026</h2>
<div class="wrap"><table><tr><th>Book</th><th>Yearly return</th><th>Worst drop</th><th>Sharpe</th><th>vs SPY, pts a year</th>
<th>p-value</th><th>After tax</th><th>1993&ndash;2009 yearly / worst</th></tr>%s</table></div>
<p style="margin-top:10px">p-value: the chance of a lead this big over SPY by luck alone (one-sided block bootstrap; finalists
multiplied by 3 for testing three). Under 0.05 would count. "vs SPY" is the yearly log-return gap. After tax: 22%% on short-term
gains and interest, 15%% on long-term gains and dividends, paid yearly from 2010 (a Roth IRA would pay none). A replay of the past,
not a promise, and not advice.</p></main></body></html>""" % (
        dates[0], dates[-1], seal["trials"], ("%+.1f points" % (100 * held[pick["F1"]]["excess_log_yr"])),
        held[pick["F1"]]["p"], "%.1f points" % (-100 * held["Combined model (1x)"]["excess_log_yr"]),
        100 * seal["fee"], 100 * seal["spread"], svg(dates, series, seal["test"][0]),
        "".join('<span><i style="background:%s%s"></i>%s</span>' % (s["color"], ";opacity:.6" if s["dash"] else "", s["label"])
                for s in series), trs)
    (OUT / "beat_spy.html").write_text(html)
    print(OUT / "beat_spy.html")


if __name__ == "__main__":
    main()

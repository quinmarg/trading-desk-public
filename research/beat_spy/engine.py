"""The beat-SPY simulator and statistics. Standard library only.

A market is a list of days {date, r, on, div, rf, rb}:
  r    total-return change of the index from the previous close (dividends in)
  on   the overnight part (previous close -> today's open), or None when the feed has no real opens
  div  the dividend part of r (for the tax option)
  rf   the T-bill rate for today, a year (known the day before)
  rb   intermediate-Treasury total return today (VFITX, or built from the 10-year yield before 1991)

A strategy's target exposure for day j is decided from closes up to j-1 (sig[j-1]). With real opens it fills at
day j's open: the overnight move belongs to the old holdings, the rest of the day to the new. Without opens it
fills at day j's close (one full day later; conservative).

Vehicles: exposure e is held as SPY ("1"), a daily-reset 2x fund ("2"), a 3x fund ("3"), the rest in cash or
bonds. 1 < e <= 2 mixes SPY and 2x; 2 < e <= 3 mixes 2x and 3x. A synthetic L-times fund's day is
  L * r - (L - 1) * (rf + SPREAD) / 252 - FEE / 252
which is how a swap-based fund like SSO or UPRO earns (check: validate_funds()).
"""
import bisect
import math
import random
from statistics import NormalDist

from . import data

N = NormalDist()
WINTER = (11, 12, 1, 2, 3, 4)


# ---------------------------------------------------------------- building markets

def _rate_lookup(rows):
    """{date: % a year} -> f(date) = the last rate strictly before that date (known the day before)."""
    ds = [r["date"] for r in rows]
    vs = [r["c"] for r in rows]

    def f(d):
        i = bisect.bisect_left(ds, d) - 1
        return vs[i] / 100.0 if i >= 0 else 0.0
    return f


def us_market(fetch=False):
    """US stocks 1960 on: ^GSPC with Shiller's monthly dividend yield added (no real opens) until SPY starts on
    1993-01-29, then SPY's own adjusted prices and opens. Cash at ^IRX; bonds VFITX from 1991-11, before that
    a 6-year-duration bond built from ^TNX."""
    gs = [b for b in data.bars("^GSPC", fetch) if "1960-01-04" <= b["date"] < "1993-01-29"]
    spy = data.bars("SPY", fetch)
    dy = data.shiller_yield(fetch)
    rf = _rate_lookup(data.bars("^IRX", fetch))
    tnx = {b["date"]: b["c"] for b in data.bars("^TNX", fetch)}
    vf = {b["date"]: b["adj"] for b in data.bars("VFITX", fetch)}
    days, prev_y, prev_vf = [], None, None
    for k, b in enumerate(gs):
        if k == 0:
            continue
        p = gs[k - 1]
        d = dy.get(b["date"][:7], 0.03) / 252.0
        days.append({"date": b["date"], "r": b["c"] / p["c"] - 1 + d, "on": None, "div": d})
    first = spy[0]
    days.append({"date": first["date"], "r": 0.0, "on": None, "div": 0.0})   # splice day: flat (one day)
    for k in range(1, len(spy)):
        b, p = spy[k], spy[k - 1]
        on = None
        if b["o"] is not None:
            on = b["o"] * b["adj"] / b["c"] / p["adj"] - 1
        days.append({"date": b["date"], "r": b["adj"] / p["adj"] - 1, "on": on,
                     "div": b["div"] / p["c"] if b["div"] else 0.0})
    for d in days:
        d["rf"] = rf(d["date"])
        y = tnx.get(d["date"])
        if d["date"] in vf and prev_vf is not None:
            d["rb"] = vf[d["date"]] / prev_vf - 1
        elif y is not None and prev_y is not None:
            d["rb"] = prev_y / 100.0 / 252 - 6.0 * (y - prev_y) / 100.0
        else:
            d["rb"] = d["rf"] / 252
        if y is not None:
            prev_y = y
        if d["date"] in vf:
            prev_vf = vf[d["date"]]
    return days


def index_market(sym, fetch=False):
    """A foreign (or other) price index: no dividends, cash earns 0 (its own rate is not in the free data), fills
    at the next close (many index feeds have no real opens). So strategy and buy-and-hold are compared on price
    alone, in excess-of-cash terms."""
    bs = data.bars(sym, fetch)
    return [{"date": b["date"], "r": b["c"] / p["c"] - 1, "on": None, "div": 0.0, "rf": 0.0, "rb": 0.0}
            for p, b in zip(bs, bs[1:])]


def window(days, start, end):
    return [i for i, d in enumerate(days) if start <= d["date"] <= end]


# ---------------------------------------------------------------- signals

def levels(days):
    lv, x = [], 1.0
    for d in days:
        x *= 1 + d["r"]
        lv.append(x)
    return lv


class Signals:
    """Indicators from closes only. Every array is indexed by the close it is known at."""

    def __init__(self, days):
        self.days = days
        self.px = levels(days)
        self.n = len(days)
        self._sma, self._vol, self._mom = {}, {}, {}
        dates = [d["date"] for d in days]
        self.month = [int(d[5:7]) for d in dates]
        last = [i + 1 == len(dates) or dates[i + 1][:7] != dates[i][:7] for i in range(len(dates))]
        self.month_end = last
        tom = []
        for i in range(len(dates)):
            k, j = 0, i
            while j >= 0 and dates[j][:7] == dates[i][:7]:
                k, j = k + 1, j - 1
            tom.append(last[i] or k <= 3)
        self.tom = tom
        from desk import combo                      # the desk's own dip / 200-day rule, so the book matches
        self.ind = combo.indicators(self.px)
        self.cum_rf = [0.0]
        for d in days:
            self.cum_rf.append(self.cum_rf[-1] + d["rf"] / 252)

    def sma(self, n):
        if n not in self._sma:
            out, s = [None] * self.n, 0.0
            for i, p in enumerate(self.px):
                s += p
                if i >= n:
                    s -= self.px[i - n]
                if i >= n - 1:
                    out[i] = s / n
            self._sma[n] = out
        return self._sma[n]

    def vol(self, n):
        if n not in self._vol:
            out, q = [None] * self.n, 0.0
            r = [d["r"] for d in self.days]
            for i in range(self.n):
                q += r[i] * r[i]
                if i >= n:
                    q -= r[i - n] * r[i - n]
                if i >= n - 1:
                    out[i] = math.sqrt(max(q, 1e-12) / n * 252)
            self._vol[n] = out
        return self._vol[n]


def signal(cfg, sg):
    """Target (exposure, off asset) per close: sig[i] is what to hold on day i+1. None before warm-up."""
    fam, n = cfg["family"], sg.n
    out = [None] * n
    off = cfg.get("off", "cash")
    if fam == "hold":
        return [(cfg["L"], off)] * n
    if fam == "sma":
        sm, band, inn = sg.sma(cfg["n"]), cfg["band"], False
        for i in range(n):
            if sm[i] is None:
                continue
            if sg.px[i] > sm[i] * (1 + band):
                inn = True
            elif sg.px[i] < sm[i] * (1 - band):
                inn = False
            out[i] = (cfg["L"] if inn else 0.0, off)
        return out
    if fam == "dual":
        look, cur = 21 * cfg["m"], None
        for i in range(n):
            if i >= look and (cur is None or sg.month_end[i]):
                ret = sg.px[i] / sg.px[i - look] - 1
                cash = math.exp(sg.cum_rf[i + 1] - sg.cum_rf[i + 1 - look]) - 1
                cur = (cfg["L"] if ret > cash else 0.0, off)
            out[i] = cur
        return out
    if fam == "vt":
        v, sm = sg.vol(cfg["d"]), sg.sma(200)
        for i in range(n):
            if v[i] is None or sm[i] is None:
                continue
            e = min(cfg["cap"], cfg["target"] / v[i])
            if cfg["filt"] and sg.px[i] <= sm[i]:
                e = 0.0
            out[i] = (round(e, 2), off)
        return out
    if fam == "combo":
        for i in range(n - 1):
            s = sg.ind[i]
            if s["sma200"] is None:
                continue
            bull = s["bull"]
            w = (int(bull or s["dip"]) + int(bull or sg.month[i + 1] in WINTER) + int(bull or sg.tom[i + 1])) / 3.0
            out[i] = (w * cfg["L"], off)
        return out
    if fam == "season":
        sm = sg.sma(200)
        for i in range(n - 1):
            if sm[i] is None:
                continue
            e = cfg["Lw"] if sg.month[i + 1] in WINTER else cfg["Ls"]
            if cfg["filt"] and sg.px[i] <= sm[i]:
                e = 0.0
            out[i] = (e, off)
        return out
    if fam == "tom":
        for i in range(n - 1):
            out[i] = (cfg["Lt"] if sg.tom[i + 1] else cfg["b"], off)
        return out
    raise ValueError(fam)


# ---------------------------------------------------------------- the simulator

COSTS = {"1": 3.0, "2": 5.0, "3": 5.0, "bonds": 2.0}   # basis points a side
FEE = 0.0088                                           # SSO and UPRO gross expense ratio, ProShares 2026-11-19
SPREAD = 0.005                                         # swap financing over T-bills, a year
TOL = 0.10                                             # rebalance only when exposure is 10 points off target
TAX = {"st": 0.22, "lt": 0.15, "div": 0.15, "int": 0.22}


def fund_day(L, r, rf, fee=None, spread=None):
    fee = FEE if fee is None else fee
    spread = SPREAD if spread is None else spread
    return r if L == 1 else L * r - (L - 1) * (rf + spread) / 252 - fee / 252


def targets(e, off):
    if e <= 1:
        w = {"1": e} if e > 0 else {}
        if e < 1:
            w[off] = 1 - e
    elif e <= 2:
        w = {"1": 2 - e, "2": e - 1}
    else:
        w = {"2": 3 - e, "3": e - 2}
    return {k: v for k, v in w.items() if v > 1e-9}


def simulate(days, sig, idx, costs=None, fee=None, spread=None, tax=None, cost_mult=1.0):
    """Run over the day indices idx (consecutive). Starts all in cash at the first day's fill.
    Returns {"eq": [equity after each day], "ret": [day returns], "exp": [exposure held], "trades": n, ...}."""
    costs = costs or COSTS
    price = {"1": 1.0, "2": 1.0, "3": 1.0, "bonds": 1.0}
    units = {k: 0.0 for k in price}
    lots = {k: [] for k in price}                  # FIFO: [date, units, cost per unit]
    cash, eq, rets, exps, trades, trade_days = 1.0, [], [], [], 0, []
    yr = {"st": 0.0, "lt": 0.0, "div": 0.0, "int": 0.0}
    carry = 0.0
    tax_paid = 0.0
    for j in idx:
        d = days[j]
        want = sig[j - 1] if j > 0 else None
        if want is None:
            want = (0.0, "cash")
        e_t, off = want
        open_fill = d["on"] is not None
        rday = {L: fund_day(int(L), d["r"], d["rf"], fee, spread) for L in ("1", "2", "3")}
        # 1) overnight on old holdings (open fills only)
        if open_fill:
            for L in ("1", "2", "3"):
                price[L] *= 1 + int(L) * d["on"]
        else:
            # whole day on old holdings, then trade at the close
            for L in ("1", "2", "3"):
                price[L] *= 1 + rday[L]
            price["bonds"] *= 1 + d["rb"]
            if tax:
                yr["int"] += cash * d["rf"] / 252
                yr["div"] += units["1"] * price["1"] * d["div"]
            cash *= 1 + d["rf"] / 252
        # 2) trade to target
        E = cash + sum(units[k] * price[k] for k in price)
        cur_e = sum(int(L) * units[L] * price[L] for L in ("1", "2", "3")) / E
        tw = targets(e_t, off)
        have = {k for k in price if units[k] * price[k] > 1e-9 * E}
        need = {k for k in tw if k != "cash"}
        if abs(e_t - cur_e) > TOL or have != need or (e_t == 0 and cur_e > 0):
            trades += 1
            trade_days.append(len(eq))
            moves = [(tw.get(k, 0.0) * E - units[k] * price[k], k) for k in price]
            for dv, k in sorted(moves):                   # sells first, then buys
                if abs(dv) < 1e-12:
                    continue
                c = costs[k] * cost_mult / 1e4
                cash -= dv - abs(dv) * c if dv < 0 else dv   # a sell pays its cost from the proceeds,
                du = dv / price[k] * (1 - c if dv > 0 else 1)  # a buy from the shares it gets
                if tax:
                    if du > 0:
                        lots[k].append([d["date"], du, price[k]])
                    else:
                        sell = -du
                        while sell > 1e-15 and lots[k]:
                            lot = lots[k][0]
                            q = min(sell, lot[1])
                            g = q * (price[k] - lot[2])
                            held = (_days_between(lot[0], d["date"]) > 365)
                            yr["lt" if held else "st"] += g
                            lot[1] -= q
                            sell -= q
                            if lot[1] <= 1e-15:
                                lots[k].pop(0)
                units[k] += du
        # 3) the rest of the day on new holdings
        if open_fill:
            for L in ("1", "2", "3"):
                f = (1 + rday[L]) / (1 + int(L) * d["on"])
                price[L] *= f
            price["bonds"] *= 1 + d["rb"]
            if tax:
                yr["int"] += cash * d["rf"] / 252
                yr["div"] += units["1"] * price["1"] * d["div"]
            cash *= 1 + d["rf"] / 252
        # 4) taxes on the last trading day of the year, paid from cash (sell pro rata if short)
        if tax and (j + 1 >= len(days) or days[j + 1]["date"][:4] != d["date"][:4] or j == idx[-1]):
            gains = yr["st"] + yr["lt"] + carry
            t = tax["int"] * yr["int"] + tax["div"] * yr["div"]
            if gains > 0:
                st = max(0.0, min(gains, yr["st"] + min(0.0, yr["lt"] + carry)))
                t += tax["st"] * st + tax["lt"] * (gains - st)
                carry = 0.0
            else:
                carry = gains
            if t > 0:
                tax_paid += t
                if cash >= t:
                    cash -= t
                else:
                    E2 = cash + sum(units[k] * price[k] for k in price)
                    f = 1 - t / E2
                    cash *= f
                    for k in units:
                        units[k] *= f
                        for lot in lots[k]:
                            lot[1] *= f
            yr = {"st": 0.0, "lt": 0.0, "div": 0.0, "int": 0.0}
        E_end = cash + sum(units[k] * price[k] for k in price)
        rets.append(E_end / (eq[-1] if eq else 1.0) - 1)
        eq.append(E_end)
        exps.append(sum(int(L) * units[L] * price[L] for L in ("1", "2", "3")) / E_end)
    return {"eq": eq, "ret": rets, "exp": exps, "trades": trades, "trade_days": trade_days, "tax_paid": tax_paid,
            "dates": [days[j]["date"] for j in idx]}


def _days_between(a, b):
    import datetime
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


# ---------------------------------------------------------------- statistics

def stats(res, days=None, idx=None):
    eq, r = res["eq"], res["ret"]
    yrs = len(r) / 252.0
    peak, dd = 1.0, 0.0
    for x in eq:
        peak = max(peak, x)
        dd = min(dd, x / peak - 1)
    rf = [days[j]["rf"] / 252 for j in idx] if days is not None else [0.0] * len(r)
    ex = [a - b for a, b in zip(r, rf)]
    m = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (len(ex) - 1)) or 1e-12
    return {"cagr": eq[-1] ** (1 / yrs) - 1, "max_dd": dd, "sharpe": m / sd * math.sqrt(252),
            "vol": sd * math.sqrt(252), "trades_yr": res["trades"] / yrs,
            "avg_exp": sum(res["exp"]) / len(res["exp"]), "end": eq[-1]}


def log_excess(a, b):
    return [math.log1p(x) - math.log1p(y) for x, y in zip(a, b)]


def _blocks(n, mean_len, rng):
    out, t = [], 0
    while t < n:
        s = rng.randrange(n)
        L = min(n - t, 1 + int(rng.expovariate(1.0 / mean_len)))
        out.append((s, L))
        t += L
    return out


def _seg(pref, n, s, L):
    e = s + L
    if e <= n:
        return pref[e] - pref[s]
    return pref[n] - pref[s] + pref[e - n]


def boot_p(x, B=2000, mean_len=21, seed=7):
    """One-sided p for mean(x) > 0: stationary bootstrap (Politis-Romano) of the centred series."""
    n = len(x)
    m = sum(x) / n
    pref = [0.0]
    for v in x:
        pref.append(pref[-1] + v - m)
    rng, hit = random.Random(seed), 0
    for _ in range(B):
        s = sum(_seg(pref, n, a, L) for a, L in _blocks(n, mean_len, rng)) / n
        hit += s >= m
    return (hit + 1) / (B + 1)


def reality_check(series, B=500, mean_len=21, seed=11):
    """White's (2000) Reality Check: p for 'the best of these K strategies beats the benchmark', all K series
    being daily excess over the benchmark on the same days. Statistic max_k sqrt(n) * mean_k."""
    n = len(series[0])
    means = [sum(x) / n for x in series]
    prefs = []
    for x, m in zip(series, means):
        p = [0.0]
        for v in x:
            p.append(p[-1] + v - m)
        prefs.append(p)
    stat = math.sqrt(n) * max(means)
    rng, hit = random.Random(seed), 0
    for _ in range(B):
        bl = _blocks(n, mean_len, rng)
        best = max(sum(_seg(p, n, a, L) for a, L in bl) for p in prefs) / n
        hit += math.sqrt(n) * best >= stat
    return (hit + 1) / (B + 1)


def moments(x):
    n = len(x)
    m = sum(x) / n
    v = sum((a - m) ** 2 for a in x) / (n - 1)
    sd = math.sqrt(v) or 1e-12
    sk = sum(((a - m) / sd) ** 3 for a in x) / n
    ku = sum(((a - m) / sd) ** 4 for a in x) / n
    return m / sd, sk, ku


def deflated_sharpe(x, trial_srs):
    """Bailey & Lopez de Prado (2014). x: the chosen strategy's daily excess series; trial_srs: the daily Sharpe of
    every configuration tried. Returns the probability that the true Sharpe is above the best expected by luck."""
    sr, sk, ku = moments(x)
    k = len(trial_srs)
    mu = sum(trial_srs) / k
    var = sum((s - mu) ** 2 for s in trial_srs) / (k - 1)
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * N.inv_cdf(1 - 1.0 / k) + g * N.inv_cdf(1 - 1.0 / (k * math.e)))
    z = (sr - sr0) * math.sqrt(len(x) - 1) / math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4 * sr * sr))
    return N.cdf(z), sr0


# ---------------------------------------------------------------- the leveraged-fund check

def validate_funds(days, start, end, fetch=False):
    """Synthetic 2x and 3x against real SSO and UPRO, close to close with dividends, over [start, end].
    Returns {sym: (years, real CAGR, synthetic CAGR)}."""
    out = {}
    for sym, L in (("SSO", 2), ("UPRO", 3)):
        real = {b["date"]: b["adj"] for b in data.bars(sym, fetch)}
        idx = [j for j in window(days, start, end) if days[j]["date"] in real]
        if len(idx) < 30:
            continue
        syn = 1.0
        for j in idx[1:]:
            syn *= 1 + fund_day(L, days[j]["r"], days[j]["rf"])
        yrs = (len(idx) - 1) / 252.0
        rr = real[days[idx[-1]]["date"]] / real[days[idx[0]]["date"]]
        out[sym] = (yrs, rr ** (1 / yrs) - 1, syn ** (1 / yrs) - 1)
    return out

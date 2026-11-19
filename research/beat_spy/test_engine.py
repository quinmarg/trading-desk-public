"""python3 -m unittest research.beat_spy.test_engine  (no network; the desk-copy check needs the cache)."""
import math
import random
import unittest

from . import data
from . import engine as E
from .dev import grid


def fake(n=700, seed=1, opens=True):
    rng, out, d = random.Random(seed), [], 0
    import datetime
    day = datetime.date(2001, 1, 1)
    while len(out) < n:
        day += datetime.timedelta(days=1)
        if day.weekday() >= 5:
            continue
        r = rng.gauss(0.0004, 0.012)
        on = r * 0.3 if opens else None
        out.append({"date": day.isoformat(), "r": r, "on": on, "div": 0.0, "rf": 0.02, "rb": 0.0001})
    return out


class Engine(unittest.TestCase):
    def test_signals_never_look_ahead(self):
        days = fake()
        for c in grid()[::7] + [{"family": "combo", "L": 1.0}]:
            a = E.signal(c, E.Signals(days))
            cut = 500
            changed = [dict(d) for d in days]
            for d in changed[cut + 1:]:
                d["r"] = -d["r"] * 3
            b = E.signal(c, E.Signals(changed))
            self.assertEqual(a[:cut + 1], b[:cut + 1], c)

    def test_fund_day(self):
        self.assertAlmostEqual(E.fund_day(1, 0.01, 0.05), 0.01)
        self.assertAlmostEqual(E.fund_day(2, 0.01, 0.05, fee=0.01, spread=0.0), 0.02 - 0.05 / 252 - 0.01 / 252)
        self.assertAlmostEqual(E.fund_day(3, -0.2047, 0.0, fee=0.0, spread=0.0), -0.6141)   # 1987-10-19

    def test_targets(self):
        self.assertEqual(E.targets(0.5, "cash"), {"1": 0.5, "cash": 0.5})
        self.assertEqual(E.targets(1.5, "cash"), {"1": 0.5, "2": 0.5})
        self.assertEqual(E.targets(3.0, "bonds"), {"3": 1.0})
        self.assertEqual(E.targets(0.0, "bonds"), {"bonds": 1.0})

    def test_hold_matches_index(self):
        for opens in (True, False):
            days = fake(opens=opens)
            idx = list(range(1, len(days)))
            res = E.simulate(days, [(1.0, "cash")] * len(days), idx)
            want = math.prod(1 + days[j]["r"] for j in idx)
            if not opens:                      # first day still in cash, then the close fill
                want = want / (1 + days[1]["r"]) * (1 + 0.02 / 252)
            else:                               # first overnight move missed
                want = want / (1 + days[1]["on"])
            self.assertAlmostEqual(res["eq"][-1], want * (1 - 3e-4), places=6)

    def test_open_fill_splits_the_day(self):
        days = fake(n=3)
        days[2]["r"], days[2]["on"] = 0.10, 0.04
        sig = [(0.0, "cash"), (1.0, "cash"), (1.0, "cash")]
        res = E.simulate(days, sig, [1, 2], costs={"1": 0, "2": 0, "3": 0, "bonds": 0})
        cash = 1 + 0.02 / 252
        self.assertAlmostEqual(res["eq"][-1], cash * 1.10 / 1.04, places=9)   # bought at the open, not the close

    def test_bootstrap_and_deflated_sharpe(self):
        rng = random.Random(3)
        good = [rng.gauss(0.002, 0.01) for _ in range(2000)]
        noise = [rng.gauss(0.0, 0.01) for _ in range(2000)]
        self.assertLess(E.boot_p(good, B=300), 0.01)
        self.assertGreater(E.boot_p([x - sum(noise) / len(noise) for x in noise], B=300), 0.2)
        srs = [E.moments([rng.gauss(0, 0.01) for _ in range(500)])[0] for _ in range(50)]
        p_few, _ = E.deflated_sharpe(good, srs[:5])
        p_many, _ = E.deflated_sharpe(good, srs)
        self.assertGreaterEqual(p_few, p_many)
        self.assertLess(E.reality_check([good, noise], B=200), 0.05)

    def test_turn_of_month(self):
        days = fake(n=60)
        sg = E.Signals(days)
        for i, d in enumerate(days):
            first3 = sum(1 for x in days[:i + 1] if x["date"][:7] == d["date"][:7]) <= 3
            last = i + 1 < len(days) and days[i + 1]["date"][:7] != d["date"][:7]
            if i + 1 < len(days):
                self.assertEqual(sg.tom[i], first3 or last, d["date"])

    def test_combo_matches_the_desk(self):
        try:
            days = [d for d in E.us_market() if "2024-01-01" <= d["date"] <= "2026-10-30"]
        except FileNotFoundError:
            self.skipTest("no cache")
        from desk import combo
        sg = E.Signals(days)
        sig = E.signal({"family": "combo", "L": 1.0}, sg)
        for i in range(250, len(days) - 1):
            _, w = combo.votes(sg.ind[i], days[i + 1]["date"])
            self.assertAlmostEqual(sig[i][0], w, places=3, msg=days[i + 1]["date"])


if __name__ == "__main__":
    unittest.main()

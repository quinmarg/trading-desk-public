import unittest

from desk import settings as S
from desk import stamp
from desk import volscreen
from desk.charts import ChartError


def fake_fetch(today_or_vol=3000, days=15, daily_range=2.0):
    """15 past sessions with 1000 shares in each opening-range bar, then today; daily bars with a fixed range."""
    def fetch(symbol, rng, interval):
        if interval == "1d":
            return {"bars": [{"date": "2026-10-%02d" % (d + 1), "h": 10 + daily_range / 2, "l": 10 - daily_range / 2,
                              "c": 10.0} for d in range(days + 1)]}
        bars = []
        for d in range(days + 1):
            date = "2026-10-%02d" % (d + 1)
            for i in range(78):
                m = 9 * 60 + 30 + 5 * i
                v = (today_or_vol if d == days else 1000) if i < 3 else 50
                bars.append({"date": date, "minute": m, "v": v})
        return {"bars": bars}
    return fetch


class Src:
    demo = False


class Measures(unittest.TestCase):
    def setUp(self):
        volscreen._cache.clear()

    def test_rvol_and_atr(self):
        m = volscreen.measures("XYZ", "2026-10-16", 15, fake_fetch(today_or_vol=3000))
        self.assertEqual(m["rvol"], 3.0)
        self.assertAlmostEqual(m["atr_pct"], 20.0)

    def test_too_little_history(self):
        m = volscreen.measures("XYZ", "2026-10-10", 15, fake_fetch())
        self.assertIsNone(m["rvol"])
        self.assertIsNone(m["atr_pct"])


class Screen(unittest.TestCase):
    def setUp(self):
        volscreen._cache.clear()

    def sig(self):
        return {"symbol": "XYZ", "date": "2026-10-16", "warnings": []}

    def test_live_is_off_by_default(self):
        st = S.validate({"mode": "live"})
        self.assertEqual(S.screen(st), {"min_rvol": 0.0, "min_atr_pct": 0.0})
        self.assertIsNone(volscreen.check(self.sig(), st, Src(), fetch=None))     # never fetches when off

    def test_paper_uses_paper_floor_or_higher_own(self):
        self.assertEqual(S.screen(S.validate({"mode": "paper"})), S.PAPER_SCREEN)
        st = S.validate({"mode": "paper", "min_rvol": 9.0})
        self.assertEqual(S.screen(st)["min_rvol"], 9.0)

    def test_quiet_stock_is_not_in_play(self):
        st = S.validate({"mode": "live", "min_rvol": 1.5})
        sig = self.sig()
        why = volscreen.check(sig, st, Src(), fake_fetch(today_or_vol=1000))
        self.assertIn("1.00x normal, under the 1.5x floor", why)
        self.assertEqual(sig["vol"]["rvol"], 1.0)

    def test_busy_stock_passes(self):
        st = S.validate({"mode": "live", "min_rvol": 1.5, "min_atr_pct": 5})
        self.assertIsNone(volscreen.check(self.sig(), st, Src(), fake_fetch(today_or_vol=3000)))

    def test_no_data_is_not_in_play(self):
        def broken(*a):
            raise ChartError("down")
        st = S.validate({"mode": "live", "min_rvol": 1.5})
        self.assertIn("could not be compared", volscreen.check(self.sig(), st, Src(), broken))

    def test_demo_does_not_block(self):
        class Demo:
            demo = True
        sig = self.sig()
        self.assertIsNone(volscreen.check(sig, S.validate({"mode": "live", "min_rvol": 2}), Demo(), fetch=None))
        self.assertTrue(sig["warnings"])

    def test_in_play_skips_odds_floor_in_paper_only(self):
        sig = self.sig()
        st = S.validate({"mode": "paper", "min_rvol": 1.5})
        self.assertIsNone(volscreen.check(sig, st, Src(), fake_fetch(today_or_vol=3000)))
        self.assertTrue(sig["vol"]["in_play"])
        self.assertTrue(volscreen.skips_floor(sig, st))
        self.assertFalse(volscreen.skips_floor(sig, S.validate({"mode": "live", "min_rvol": 1.5})))
        quiet = self.sig()
        volscreen._cache.clear()
        volscreen.check(quiet, st, Src(), fake_fetch(today_or_vol=1000))
        self.assertFalse(volscreen.skips_floor(quiet, st))
        self.assertFalse(volscreen.skips_floor(self.sig(), st))          # screen did not run: floor applies

    def test_rule_set_code_changes_only_when_on(self):
        live = S.validate({"mode": "live"})
        self.assertNotIn("min_rvol", stamp.rules(live))
        self.assertEqual(stamp.rules(S.validate({"mode": "live", "min_rvol": 2}))["min_rvol"], 2.0)


if __name__ == "__main__":
    unittest.main()

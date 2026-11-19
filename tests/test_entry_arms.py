"""The shadow entry arms (desk/outcome.shadow): logging only, replayed after the close beside the real slip."""
from desk import charts, outcome
from desk import review as R
from tests.test_desk import DemoCase


def bars(rows):
    """(start "HH:MM", o, h, l, c, volume) -> 5-minute bars."""
    return [{"date": "2026-10-19", "start": t, "minute": int(t[:2]) * 60 + int(t[3:]), "o": o, "h": h, "l": l, "c": c, "v": v}
            for t, o, h, l, c, v in rows]


# a 15-minute range of 9.00-10.00, a breakout candle closing 10.20 at 9:55, then a dip to the VWAP and a run to the target
DAY = bars([("09:30", 9.5, 10.0, 9.0, 9.8, 1000), ("09:35", 9.8, 9.9, 9.4, 9.6, 1000), ("09:40", 9.6, 9.9, 9.5, 9.9, 1000),
            ("09:45", 9.9, 10.1, 9.85, 10.05, 1000), ("09:50", 10.05, 10.25, 10.0, 10.2, 1000),
            ("09:55", 10.2, 10.3, 10.15, 10.25, 1000), ("10:00", 10.25, 10.3, 10.0, 10.05, 1000),
            ("10:05", 10.05, 10.1, 9.83, 9.9, 1000), ("10:10", 9.9, 11.7, 9.9, 11.6, 1000)])
P = {"symbol": "X", "limit": 10.34, "stop": 9.5, "target": 11.6, "trigger_close_time": "09:55", "valid_until": "10:05",
     "flat_by": "15:55", "opening_range": {"high": 10.0, "low": 9.0}}


class Shadow(DemoCase):
    def test_vwap_is_the_session_average_up_to_the_trigger_candle(self):
        # typical prices 9.6, 9.6333, 9.7667, 10.0, 10.15 at equal volume
        self.assertAlmostEqual(outcome.vwap_at(DAY, 9 * 60 + 55), 9.83, 6)
        self.assertIsNone(outcome.vwap_at(DAY, 9 * 60 + 30))

    def test_each_arm_buys_its_own_level_and_keeps_the_slips_stop_and_target(self):
        real = outcome.replay(P, DAY)
        self.assertEqual((real["result"], real["entry"]), ("target", 10.2))
        arms = outcome.shadow(P, DAY)
        self.assertEqual((arms["retest"]["limit"], arms["retest"]["entry"], arms["retest"]["result"]), (10.0, 10.0, "target"))
        self.assertEqual((arms["vwap"]["limit"], arms["vwap"]["entry"], arms["vwap"]["result"]), (9.83, 9.83, "target"))
        # R in the real slip's risk (10.34 - 9.50 = 0.84), so the arms compare share for share
        self.assertEqual(arms["retest"]["r_orig"], round(1.6 / 0.84, 2))
        self.assertEqual(arms["vwap"]["r_orig"], round(1.77 / 0.84, 2))

    def test_the_vwap_limit_rests_60_minutes_not_the_slips_10(self):
        late = DAY[:7] + bars([("10:30", 10.0, 10.0, 9.83, 9.9, 1000), ("11:00", 9.9, 11.7, 9.9, 11.6, 1000)])
        self.assertEqual(outcome.shadow(P, late)["vwap"]["entry"], 9.83)                  # 35 minutes after the trigger
        later = DAY[:7] + bars([("11:00", 10.0, 10.0, 9.83, 9.9, 1000)])
        self.assertEqual(outcome.shadow(P, later)["vwap"]["result"], outcome.NO_FILL)     # 65 minutes: too late

    def test_shorts_and_slips_without_a_plan_get_no_shadow(self):
        self.assertEqual(outcome.shadow(dict(P, side="short"), DAY), {})
        self.assertEqual(outcome.shadow({"symbol": "X"}, DAY), {})

    def test_a_level_above_the_slips_limit_is_capped_and_one_under_the_stop_is_no_plan(self):
        arms = outcome.shadow(dict(P, opening_range={"high": 10.9, "low": 9.0}), DAY)
        self.assertEqual(arms["retest"]["limit"], 10.34)                   # never pays more than the real slip
        arms = outcome.shadow(dict(P, stop=9.9, target=11.6), DAY)
        self.assertEqual(arms["vwap"]["result"], outcome.NO_PLAN)           # VWAP 9.83 sits under a 9.90 stop

    def test_after_the_close_the_arms_are_logged_and_the_review_compares_them(self):
        d = self.desk()
        a = d.j.add_signal("2026-10-19", "X", "orb", "expired", dict(P), "2026-10-19 09:55")
        d.j.add_signal("2026-10-19", "Y", "orb", "blocked", {"symbol": "Y", "problems": ["x"]}, "2026-10-19 09:55")
        real = charts.intraday
        charts.intraday = lambda src, sym: {"bars": DAY}
        self.addCleanup(setattr, charts, "intraday", real)
        d.record_outcomes("2026-10-19")
        got = {(s["signal_id"], s["arm"]): s for s in d.j.shadows()}
        # the blocked one has no plan: no arms. "SPY" read the same day here: at 9:55 it closed 10.20, over its VWAP 9.83
        self.assertEqual(sorted(got), [(a, "retest"), (a, "spy_with"), (a, "vwap")])
        self.assertEqual((got[(a, "vwap")]["entry"], got[(a, "vwap")]["status"]), (9.83, "expired"))
        ea = d.review()["summary"]["entry_arms"]
        self.assertEqual(ea["days"], 1)
        self.assertFalse(ea["enough"])
        self.assertEqual({k: v["total_r"] for k, v in ea["arms"].items()},
                         {"slip": round(1.4 / 0.84, 2), "vwap": round(1.77 / 0.84, 2), "retest": round(1.6 / 0.84, 2),
                          "spy_with": round(1.4 / 0.84, 2), "spy_against": None})
        text = d.review()["text"]
        self.assertIn("ENTRY STYLE A/B", text)
        self.assertIn("Wait for 20 or more", text)
        self.assertIn("COMBINED SPY MODEL", text)
        # nothing about the real signal or its outcome moved
        self.assertEqual(d.j.signal(a)["payload"]["limit"], 10.34)
        self.assertEqual(d.j.outcomes()[0]["entry"], 10.2)

    def test_c4_tags_the_real_slip_by_spys_side_of_its_vwap(self):
        down = bars([("09:30", 50, 50, 49, 49.5, 100), ("09:50", 49.5, 49.6, 48, 48.1, 900)])
        arms = outcome.shadow(P, DAY, spy=down)
        self.assertNotIn("spy_with", arms)
        self.assertEqual((arms["spy_against"]["entry"], arms["spy_against"]["r_orig"]), (10.2, round(1.4 / 0.84, 2)))
        self.assertNotIn("spy_with", outcome.shadow(P, DAY))                     # no SPY day: no tag

    def test_the_review_counts_only_long_slips_that_were_good_to_buy(self):
        sh = [{"signal_id": 1, "arm": "vwap", "date": "d", "status": "blocked", "result": "no fill", "r_orig": None}]
        self.assertEqual(R.entry_arms([], sh, {})["arms"]["vwap"]["signals"], 0)

import unittest
import unittest.mock

from desk import backtest as B
from desk import outcome


def day(prices, date="2026-10-20", vol=1000):
    """78 bars; prices[i] = (o, h, l, c), later bars repeat the last one."""
    bars = []
    for i in range(78):
        o, h, l, c = prices[min(i, len(prices) - 1)]
        m = B.OPEN_MIN + 5 * i
        bars.append({"date": date, "start": "%02d:%02d" % (m // 60, m % 60), "minute": m,
                     "o": o, "h": h, "l": l, "c": c, "v": vol})
    return bars


class PlanDay(unittest.TestCase):
    def test_long_breakout_uses_desk_numbers(self):
        D = day([(100, 101, 99, 100)] * 3 + [(100, 101.6, 100, 101.5), (101.5, 106, 101.4, 105.5)])
        p = B.plan_day(D, "long", B.DEFAULT_RULE)
        self.assertEqual(p["k"], 3)
        self.assertEqual(p["entry"], 101.5)
        self.assertEqual(p["stop"], 100.0)                  # middle of the 99 to 101 range
        self.assertEqual(p["target"], 104.5)                # 2R
        self.assertEqual(p["limit"], 101.8)                 # entry + 0.2R
        self.assertEqual((p["trigger_close_time"], p["valid_until"]), ("09:50", "10:00"))
        r = outcome.replay(p, D)
        self.assertEqual(r["result"], outcome.TARGET)

    def test_short_mirror(self):
        D = day([(100, 101, 99, 100)] * 3 + [(100, 100, 98.4, 98.5)])
        p = B.plan_day(D, "short", B.DEFAULT_RULE)
        self.assertEqual((p["entry"], p["stop"], p["target"]), (98.5, 100.0, 95.5))

    def test_no_trigger_and_late_trigger(self):
        self.assertIsNone(B.plan_day(day([(100, 101, 99, 100)]), "long", B.DEFAULT_RULE))
        late = [(100, 101, 99, 100)] * 72 + [(100, 102, 100, 101.5)]   # first close above at 15:30-15:35
        self.assertIsNone(B.plan_day(day(late), "long", B.DEFAULT_RULE))

    def test_stop_too_close_is_blocked(self):
        D = day([(100, 100.1, 99.95, 100)] * 3 + [(100, 100.2, 100, 100.15)])
        self.assertEqual(B.plan_day(D, "long", B.DEFAULT_RULE)["blocked"], "stop too close")

    def test_atr_stop(self):
        D = day([(100, 101, 99, 100)] * 3 + [(100, 101.6, 100, 101.5)])
        p = B.plan_day(D, "long", dict(B.DEFAULT_RULE, stop="atr:0.5", atr_usd=4.0))
        self.assertEqual(p["stop"], 99.5)


class Measures(unittest.TestCase):
    def test_atr_pct_uses_only_days_before(self):
        daily = [{"date": "2026-10-%02d" % (i + 1), "h": 11, "l": 9, "c": 10} for i in range(16)]
        self.assertAlmostEqual(B.atr_pct(daily, "2026-10-16"), 20.0)      # TR 2 on a close of 10
        self.assertIsNone(B.atr_pct(daily, "2026-10-10"))
        daily[-1]["h"] = 100                                              # the day itself never counts
        self.assertAlmostEqual(B.atr_pct(daily, "2026-10-16"), 20.0)

    def test_split_is_fixed_by_name(self):
        rows = [{"symbol": s, "date": d} for s in ("AAPL", "TSLA", "F", "AMD") for d in ("2026-10-01", "2026-11-01")]
        train, test = B.split(rows, "2026-10-15")
        self.assertEqual(len(train) + len(test), len(rows))
        self.assertTrue(all(B.stable_half(x["symbol"]) == "A" and x["date"] < "2026-10-15" for x in train))
        self.assertTrue(all(x not in train for x in test))


class Scoring(unittest.TestCase):
    def row(self, r, result, p=0.4, edge=0.0, risk=1.0):
        return {"r": r, "result": result, "risk": risk, "entry": 100.0, "odds": {"p_target": p, "edge": edge}}

    def test_score_counts_cost_and_floor(self):
        rows = [self.row(2.0, outcome.TARGET), self.row(-1.0, outcome.STOP), self.row(-1.0, outcome.STOP),
                self.row(2.0, outcome.TARGET, edge=-20)]                   # under the floor: weak, left out
        s = B.score(rows, cost=0.1)
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["avg_r"], round((1.9 - 1.1 - 1.1) / 3, 3))
        self.assertEqual(s["pf"], round(1.9 / 2.2, 2))
        self.assertEqual(s["target_rate"], 33.3)

    def test_calibration_bands(self):
        rows = [self.row(2, outcome.TARGET, p=0.35)] * 4 + [self.row(-1, outcome.STOP, p=0.35)] * 6
        c = B.calibration(rows, min_n=5)
        self.assertEqual(c, [{"band": "30-40%", "n": 10, "predicted": 35.0, "actual": 40.0, "gap": 5.0, "counts": True}])


if __name__ == "__main__":
    unittest.main()


class Rule201Fill(unittest.TestCase):
    """SEC Rule 201: a restricted short rests a cent over the trigger close and fills only when a bar trades through it
    (docs/IMPROVE-2026-11-20.md, T2)."""

    def plan(self):
        D = day([(100, 101, 99, 100)] * 3 + [(100, 100, 98.4, 98.5)] + [(98.5, 98.5, 97, 97.2)] * 3)
        p = B.plan_day(D, "short", B.DEFAULT_RULE)
        return D, p

    def test_a_falling_stock_never_lifts_the_limit_so_there_is_no_fill(self):
        D, p = self.plan()
        self.assertEqual(outcome.ssr_limit(p["entry"]), 98.51)
        self.assertEqual(outcome.replay_ssr(p, D)["result"], outcome.NO_FILL)
        self.assertNotEqual(outcome.replay(p, D)["result"], outcome.NO_FILL)   # the plain short would have filled

    def test_a_bounce_through_the_limit_fills_at_the_limit_never_better(self):
        D, p = self.plan()
        D[4].update(o=98.5, h=99.0, l=98.3, c=98.4)           # buyers lift it: the bar trades 98.52 or more
        for b in D[5:]:
            b.update(o=97, h=97.5, l=95, c=95.2)
        r = outcome.replay_ssr(p, D)
        self.assertEqual(r["entry"], 98.51)
        self.assertEqual(r["result"], outcome.TARGET)          # target 2R under the plan's entry
        self.assertAlmostEqual(r["r"], (98.51 - r["exit"]) / (p["stop"] - 98.51), places=2)

    def test_a_bar_touching_the_limit_without_trading_through_does_not_fill(self):
        D, p = self.plan()
        D[4].update(o=98.5, h=98.51, l=98.3, c=98.4)
        self.assertEqual(outcome.replay_ssr(p, D)["result"], outcome.NO_FILL)

    def test_the_backtest_leaves_restricted_shorts_out_unless_asked_and_marks_them(self):
        daily = [{"date": "2026-%02d-%02d" % (1 + i // 28, 1 + i % 28), "o": 130, "h": 131, "l": 129, "c": 130}
                 for i in range(250)]                        # 200-day average about 130: the short is under it
        daily[-1].update(l=105.0, c=100.0)                    # down 19 % yesterday: restricted today too
        one = [(100, 101, 99, 100)] * 3 + [(100, 100, 98.4, 98.5), (98.5, 99.0, 98.3, 98.4)] + [(97, 97.5, 95, 95.2)] * 3
        days = [("2026-10-%02d" % (2 + i), day(one, "2026-10-%02d" % (2 + i))) for i in range(B.FEATURE_DAYS + 1)]
        data = {"intraday": None, "daily": {"bars": daily}}
        with unittest.mock.patch.object(B, "sessions", return_value=days):
            plain = B.signals("X", data, replays=0)
            kept = B.signals("X", data, replays=0, ssr_model=True)
        self.assertFalse([r for r in plain if r["side"] == "short"])
        shorts = [r for r in kept if r["side"] == "short"]
        self.assertEqual([(r["ssr"], r["entry"]) for r in shorts], [("yesterday", 98.51)])

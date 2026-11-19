import unittest
from desk import settings as S
from tests.base import DeskCase


class Settings(DeskCase):
    def test_defaults_are_valid_and_load_without_a_file(self):
        self.assertEqual(S.load(), S.validate({}))
        self.assertEqual(S.load()["account_type"], "cash")

    def test_save_round_trips(self):
        S.save({"risk_per_trade_pct": 1, "watchlist": "tsla, f  amd"})
        s = S.load()
        self.assertEqual(s["risk_per_trade_pct"], 1.0)
        self.assertEqual(s["watchlist"], ["TSLA", "F", "AMD"])

    def test_update_changes_one_key(self):
        S.update({"max_trades_per_day": 3})
        self.assertEqual(S.load()["max_trades_per_day"], 3)
        self.assertEqual(S.load()["target_r"], 2.0)

    def test_refusals(self):
        bad = [{"nope": 1}, {"risk_per_trade_pct": 50}, {"risk_per_trade_pct": "x"}, {"risk_per_trade_pct": True},
               {"account_type": "ira"}, {"flat_by": "25:00"}, {"no_entries_before": "16:00"},
               {"stop_rule": "tight"}, {"stop_rule": "pct:0"}, {"max_daily_loss_pct": 1, "risk_per_trade_pct": 2},
               {"watchlist": ["TS LA!"]}, {"scan_universe": "yes"}, {"max_trades_per_day": -1}]
        for b in bad:
            with self.assertRaises(S.SettingsError, msg=str(b)):
                S.validate(b)

    def test_a_bad_save_keeps_the_old_file(self):
        S.save({"target_r": 3})
        with self.assertRaises(S.SettingsError):
            S.update({"target_r": 99})
        self.assertEqual(S.load()["target_r"], 3.0)

    def test_limits_scale_with_the_account(self):
        s = S.validate({})
        small, big = S.limits(s, 400), S.limits(s, 40000)
        self.assertEqual(small["max_loss_per_trade"], 8.0)
        self.assertEqual(small["max_daily_loss"], 16.0)
        self.assertEqual(big["max_loss_per_trade"], 800.0)
        self.assertEqual(big["cash_buffer"], 2000.0)

    def test_skills_config_never_allows_margin_shorts_or_options(self):
        c = S.skills_config(S.validate({}), 400)
        self.assertEqual((c["allow_margin"], c["allow_short"], c["allow_options"], c["require_stop"]),
                         (False, False, False, True))
        self.assertEqual(c["budget"], 400)
        self.assertEqual(c["max_loss_per_trade_usd"], 8.0)
        self.assertNotIn("sec_user_agent", c)


class TradesCap(unittest.TestCase):
    def test_live_uses_the_setting_paper_has_none(self):
        self.assertEqual(S.trades_cap({"mode": "live", "max_trades_per_day": 2}), 2)
        self.assertEqual(S.trades_cap({"mode": "paper", "max_trades_per_day": 2}), S.PAPER_TRADES_CAP)
        self.assertEqual(S.trades_cap({"mode": "live", "max_trades_per_day": 0}), S.PAPER_TRADES_CAP)   # 0 = no cap
        self.assertGreaterEqual(S.PAPER_TRADES_CAP, 50)


class PaperBold(unittest.TestCase):
    def test_paper_bets_bigger_live_keeps_your_limits(self):
        st = S.validate({})
        live = S.limits(dict(st, mode="live"), 400)
        paper = S.limits(dict(st, mode="paper"), 400)
        self.assertEqual(live["max_loss_per_trade"], 8.0)
        self.assertEqual(paper["max_loss_per_trade"], 8.0)                 # risk a trade and a day: your Settings, both modes
        self.assertEqual(paper["max_daily_loss"], live["max_daily_loss"])
        self.assertEqual(paper["cash_buffer"], 0.0)
        self.assertEqual(live["cash_buffer"], 20.0)
        self.assertEqual(S.risk(dict(st, mode="paper"))["max_drawdown_pct"], 50.0)
        self.assertEqual(S.risk(dict(st, mode="live"))["max_drawdown_pct"], st["max_drawdown_pct"])

    def test_paper_buys_with_4x_the_account(self):
        st = S.validate({})
        self.assertEqual(S.leverage(dict(st, mode="live")), 1.0)
        self.assertEqual(S.leverage(dict(st, mode="paper")), 4.0)
        self.assertEqual(S.limits(dict(st, mode="paper"), 400)["max_position"], 1600.0)
        self.assertEqual(S.limits(dict(st, mode="live"), 400)["max_position"], 380.0)

from desk import changes
from desk import settings as S
from desk.engine import DeskError
from tests.test_desk import DemoCase


class Changes(DemoCase):
    def test_diff_in_words(self):
        old = S.validate({})
        new = S.validate({"risk_per_trade_pct": 1, "paused": True, "watchlist": ["F", "ZZZ"],
                          "sec_user_agent": "Someone someone@example.com"})
        d = dict(changes.diff(old, new))
        self.assertEqual(d["risk_per_trade_pct"], "Setting changed: risk_per_trade_pct from 2 to 1.")
        self.assertEqual(d["paused"], "Setting changed: paused from off to on.")
        self.assertIn("added ZZZ", d["watchlist"])
        self.assertIn("removed SOFI", d["watchlist"])
        self.assertNotIn("example.com", d["sec_user_agent"])          # private values are never logged
        self.assertEqual(changes.diff(old, old), [])

    def test_a_saved_change_lands_in_the_event_log_once(self):
        d = self.desk()
        d.change_settings({"target_r": 3, "max_trades_per_day": 0})    # the second is not a change
        ev = [e["message"] for e in d.j.events() if e["kind"] == "settings"]
        self.assertEqual(ev, ["Setting changed: target_r from 2 to 3."])
        with self.assertRaises(S.SettingsError):
            d.change_settings({"target_r": 99})
        self.assertEqual(len([e for e in d.j.events() if e["kind"] == "settings"]), 1)

    def test_mode_cannot_be_changed_from_the_form(self):
        with self.assertRaises(DeskError):
            self.desk().change_settings({"mode": "live"})


class Pause(DemoCase):
    def test_pause_stops_new_signals_and_fills_but_not_alerts(self):
        d = self.desk()
        d.scan()
        ready = d.j.signals(statuses=("ready",))[0]
        d.change_settings({"paused": True})
        s = d.scan()
        self.assertIn("Paused by you", s["halt"])
        self.assertEqual(s["evaluated"], 0)
        with self.assertRaises(DeskError):
            d.take(ready["id"], 1, ready["payload"]["limit"])
        d.monitor()                                                    # still runs
        d.change_settings({"paused": False})
        self.assertIsNone(d.halt_reason(S.load(), d.src.now()))
        self.assertEqual(len([e for e in d.j.events() if e["kind"] == "settings"]), 2)

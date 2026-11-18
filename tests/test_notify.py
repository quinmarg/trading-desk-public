"""Phone alerts through ntfy (desk/notify.py). No network: urlopen is patched."""
import json
from unittest import mock

from desk import notify
from desk import settings as S
from desk.engine import Desk, DeskError
from desk.journal import Journal
from desk.source import Demo
from tests.base import DeskCase

SIG = {"symbol": "TSLA", "qty": 1, "limit": 365.35, "stop": 358.32, "target": 377.36, "valid_until": "10:25",
       "reward_risk": 1.7, "max_loss": 7.03, "odds": {"edge_points": 2.5}, "warnings": ["Earnings soon."],
       "news": [{"title": "Tesla one", "source": "Reuters", "link": "https://example.com/1"},
                {"title": "Tesla two", "source": "AP", "link": ""},
                {"title": "Tesla three", "source": "Yahoo", "link": "https://example.com/3"},
                {"title": "Tesla four", "source": "Yahoo", "link": "https://example.com/4"}]}


def sent(urlopen):
    """The JSON bodies posted through the patched urlopen."""
    return [json.loads(c.args[0].data) for c in urlopen.call_args_list]


class Notify(DeskCase):
    def send(self, sig=SIG, demo=False, **settings):
        st = S.validate(dict({"ntfy_topic": "my-desk_123"}, **settings))
        with mock.patch("urllib.request.urlopen") as urlopen:
            t = notify.send_signal(sig, st, st["mode"], demo)
            if t:
                t.join(5)
        return urlopen

    def test_a_ready_signal_posts_one_json_body(self):
        u = self.send()
        self.assertEqual(u.call_count, 1)
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_method(), u.call_args.kwargs["timeout"]), ("https://ntfy.sh", "POST", 10))
        b = sent(u)[0]
        self.assertEqual(b["topic"], "my-desk_123")
        self.assertEqual(b["title"], "[PAPER] BUY TSLA ≤ 365.35")
        self.assertEqual(b["click"], "https://example.com/1")
        self.assertLessEqual(len(b["actions"]), 3)
        self.assertEqual([a["label"] for a in b["actions"]], ["Article", "Article", "Chart"])
        self.assertEqual(b["actions"][-1]["url"], "https://finance.yahoo.com/quote/TSLA")
        self.assertIn("Buy 1 at 365.35 or lower. Stop 358.32. Target 377.36. Good until 10:25.", b["message"])
        self.assertIn("Time Machine edge +2.5 points.", b["message"])
        self.assertIn("• Tesla three (Yahoo)\nhttps://example.com/3", b["message"])
        self.assertNotIn("Tesla four", b["message"])                     # three headlines at most

    def test_live_title_and_no_links_falls_back_to_the_dashboard(self):
        b = sent(self.send(dict(SIG, news=[]), mode="live"))[0]
        self.assertTrue(b["title"].startswith("[LIVE] "))
        self.assertEqual(b["click"], "http://127.0.0.1:8787")
        self.assertEqual([a["label"] for a in b["actions"]], ["Chart"])

    def test_a_short_says_sell_short_not_buy(self):
        b = notify.message(dict(SIG, side="short", paper_only=True), "paper")
        self.assertEqual(b["title"], "[PAPER] SHORT TSLA ≥ 365.35")
        self.assertTrue(b["message"].startswith("Sell short 1 at 365.35 or higher."))
        self.assertIn("Practice only", b["message"])
        self.assertEqual(b["tags"], ["chart_with_downwards_trend"])

    def test_empty_topic_or_demo_sends_nothing(self):
        self.assertEqual(self.send(ntfy_topic="").call_count, 0)
        self.assertEqual(self.send(demo=True).call_count, 0)

    def test_a_failing_push_never_raises(self):
        st = S.validate({"ntfy_topic": "x"})
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")), self.assertLogs("desk.notify", "WARNING"):
            notify.send_signal(SIG, st, "paper", False).join(5)
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertIsNone(notify.send_signal({}, st, "paper", False))   # a broken payload is dropped too

    def test_bad_topic_and_server_are_refused(self):
        for b in [{"ntfy_topic": "has space"}, {"ntfy_topic": "a/b"}, {"ntfy_topic": "x" * 65},
                  {"ntfy_server": "http://ntfy.sh"}, {"ntfy_server": "ntfy.sh"}, {"ntfy_server": "https://"}]:
            with self.assertRaises(S.SettingsError, msg=str(b)):
                S.validate(b)
        self.assertEqual(S.validate({"ntfy_topic": " ok-1_A "})["ntfy_topic"], "ok-1_A")


class ScanNotifies(DeskCase):
    """Only a new ready signal pushes, and only once."""

    def scan(self, status):
        S.save({"ntfy_topic": "x"})
        j = Journal()
        self.addCleanup(j.close)
        d = Desk(j, Demo("2026-10-19 10:15"))
        with mock.patch("desk.engine.pipeline.evaluate", return_value=(status, dict(SIG))), \
                mock.patch("desk.engine.notify.send_signal") as send:
            send.new = sum(d.scan()["new_signals"] for _ in range(3))   # later scans see the same breakouts again
        return send

    def test_ready_pushes_once(self):
        send = self.scan("ready")
        self.assertGreaterEqual(send.new, 1)
        self.assertEqual(send.call_count, send.new)
        self.assertEqual(send.call_args.args[2:], ("paper", True))      # demo: send_signal itself then sends nothing

    def test_weak_and_blocked_never_push(self):
        for status in ("weak", "blocked"):
            self.assertEqual(self.scan(status).call_count, 0, status)

    def test_the_test_button_refuses_in_the_demo(self):
        j = Journal()
        self.addCleanup(j.close)
        with self.assertRaises(DeskError):
            Desk(j, Demo("2026-10-19 10:15")).test_alert()

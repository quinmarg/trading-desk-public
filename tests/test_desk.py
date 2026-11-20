from unittest import mock
import pathlib
"""The whole desk on the skills' saved data from 2026-10-19: no network."""
import json
import threading
import urllib.error
import urllib.request

from desk import pipeline
from desk import settings as S
from desk.engine import Desk, DeskError
from desk.journal import Journal
from desk.scheduler import Scheduler
from desk.server import serve
from desk.source import Demo
from tests.base import DeskCase


class DemoCase(DeskCase):
    def desk(self, now="2026-10-19 10:15", **settings):
        S.save(settings)
        j = Journal()
        self.addCleanup(j.close)
        return Desk(j, Demo(now))


class Pipeline(DemoCase):
    def test_tsla_numbers_match_the_skills_own_example(self):
        d = self.desk(target_r=1, chase_r=0, min_edge_points=-50)
        status, sig = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        self.assertEqual(status, "ready")
        self.assertEqual((sig["entry"], sig["stop"], sig["target"]), (364.18, 358.32, 370.04))
        self.assertEqual((sig["qty"], sig["max_loss"]), (1, 5.86))
        self.assertEqual(sig["valid_until"], "10:25")
        o = sig["odds"]
        self.assertEqual((o["p_target"], o["p_stop"], o["replays"], o["sessions"]), (0.2917, 0.242, 10000, 59))   # replays stop at 3:55 PM, the flat-by time
        self.assertEqual(sig["risk"]["verdict"], "PASS")
        self.assertTrue(sig["ticket"]["ready"])
        self.assertIn("LIMIT, price 364.18", sig["ticket"]["steps"][2])

    def test_limit_ceiling_sits_chase_r_above_the_entry_and_sizing_uses_it(self):
        d = self.desk()
        status, sig = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        self.assertEqual(sig["limit"], 365.35)                 # 364.18 + 0.2 x 5.86, floored
        self.assertEqual(sig["max_loss"], 7.03)                # 365.35 - 358.32, one share
        self.assertEqual(status, "weak")                       # 2R on TSLA that morning: poor odds

    def test_not_triggered_is_not_a_signal(self):
        d = self.desk(now="2026-10-19 10:12")
        status, why = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        self.assertIsNone(status)
        self.assertIn("waiting", why)

    def test_an_old_trigger_is_missed(self):
        d = self.desk(now="2026-10-19 10:40")
        status, sig = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        self.assertEqual(status, "missed")

    def test_a_stop_too_wide_for_the_account_is_blocked(self):
        d = self.desk(risk_per_trade_pct=1, max_daily_loss_pct=2)   # $4 max loss, TSLA risks 7.03 a share
        status, sig = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        self.assertEqual(status, "blocked")
        self.assertEqual(sig["qty"], 0)

    def test_edge_points(self):
        self.assertEqual(pipeline.edge_points(0.3, 0.3, 1), 0.0)
        self.assertEqual(pipeline.edge_points(0.2, 0.2, 2), 16.7)
        self.assertIsNone(pipeline.edge_points(0, 0, 2))


class Engine(DemoCase):
    def test_scan_makes_signals_once(self):
        d = self.desk()
        s = d.scan()
        self.assertIsNone(s["halt"])
        self.assertEqual((s["hits"], s["evaluated"]), (41, 8))
        self.assertGreaterEqual(s["too_expensive"], 1)
        self.assertEqual(len(d.j.signals()), 8)                  # at most 8 full evaluations a pass
        s2 = d.scan()
        self.assertEqual((s2["already"], s2["evaluated"], len(d.j.signals())), (8, 4, 12))
        s3 = d.scan()
        self.assertEqual((s3["already"], s3["evaluated"], s3["new_signals"], len(d.j.signals())), (12, 0, 0, 12))
        for sig in d.j.signals(statuses=("ready",)):
            p = sig["payload"]
            self.assertLessEqual(p["cost"], 380.0)
            self.assertLessEqual(p["max_loss"], 8.0)
            self.assertLess(p["stop"], p["limit"])
            self.assertLess(p["limit"], p["target"])

    def test_halts(self):
        self.assertIn("closed", self.desk(now="2026-10-18 10:15").scan()["halt"])       # Sunday
        self.assertIn("before", self.desk(now="2026-10-19 09:40").scan()["halt"])
        self.assertIn("late", self.desk(now="2026-10-19 15:31").scan()["halt"])

    @mock.patch.object(S, "trades_cap", lambda st: st["max_trades_per_day"])   # live-mode cap; paper has none
    def test_take_then_exit_then_the_day_is_done(self):
        d = self.desk(max_trades_per_day=1)
        d.scan()
        sig = next(s for s in d.j.signals(statuses=("ready",)) if s["symbol"] == "W")
        p = sig["payload"]
        with self.assertRaises(DeskError):
            d.take(sig["id"], p["qty"] + 1, p["limit"])
        with self.assertRaises(DeskError):
            d.take(sig["id"], p["qty"], p["target"] - 0.01)      # a fill that far up breaks the loss limit
        with self.assertRaises(DeskError):
            d.take(sig["id"], p["qty"], "abc")
        tid = d.take(sig["id"], p["qty"], p["limit"])
        with self.assertRaises(DeskError):
            d.take(sig["id"], 1, p["limit"])                     # already taken
        self.assertIn("1 of 1 trades", d.halt_reason(S.load(), d.src.now()))
        other = next(s for s in d.j.signals(statuses=("ready",)))
        with self.assertRaises(DeskError):                       # the day's cap also stops a second fill
            d.take(other["id"], 1, other["payload"]["limit"])
        self.assertTrue(all(s["off"] for s in d.state()["signals"] if s["status"] == "ready"))
        self.assertEqual(d.exit(tid, p["stop"], "stop"), round((p["stop"] - p["limit"]) * p["qty"], 2))
        st = d.state()
        self.assertEqual(st["account"]["unsettled"], [])                  # paper mode: a sale is usable at once
        self.assertEqual(st["stats"]["losses"], 1)
        with self.assertRaises(DeskError):
            d.exit(tid, p["stop"], "stop")

    def test_typed_money_can_have_dollar_signs_commas_and_spaces(self):
        d = self.desk()
        for typed, expect in (("$1,234.56", 1234.56), (" 1,000 ", 1000.0), ("$400", 400.0), (512.5, 512.5)):
            d.cash_move("set", typed)
            self.assertEqual(d.state()["account"]["cash"], expect, typed)
        for junk in ("", "  ", "$", "abc", "1.2.3", "nan", "inf", None, "1,00,0x"):
            with self.assertRaises(DeskError, msg=repr(junk)):
                d.cash_move("set", junk)
        self.assertEqual(d.state()["account"]["cash"], 512.5)
        d.scan()
        sig = next(s for s in d.j.signals(statuses=("ready",)) if s["symbol"] == "W")
        tid = d.take(sig["id"], sig["payload"]["qty"], "$%s" % sig["payload"]["limit"])
        self.assertEqual(d.exit(tid, " $%s " % sig["payload"]["stop"], "stop"),
                         round((sig["payload"]["stop"] - sig["payload"]["limit"]) * sig["payload"]["qty"], 2))

    def test_daily_loss_limit_halts(self):
        d = self.desk(max_trades_per_day=5)
        tid = d.j.open_trade("F", 20, 12.0, 11.2, 13.6, d.src.now())
        d.exit(tid, 11.2, "stop")                                 # -$16, the daily limit at $400
        self.assertIn("daily loss limit", d.halt_reason(S.load(), d.src.now()))

    def test_settlement_skips_the_weekend_and_margin_settles_at_once(self):
        d = self.desk()
        self.assertEqual(d.settle_date("2026-10-23 11:00"), "2026-10-23")   # paper mode: no wait
        S.save(dict(S.load(), mode="live"))                                 # live: the cash-account wait
        self.assertEqual(d.settle_date("2026-10-23 11:00"), "2026-10-26")   # Friday -> Monday
        S.update({"account_type": "margin"})
        self.assertEqual(d.settle_date("2026-10-23 11:00"), "2026-10-23")

    def test_monitor_expires_signals_and_rings_flat_by_close(self):
        d = self.desk(watchlist=["TSLA"], target_r=1, chase_r=0, min_edge_points=-50)
        status, sig = pipeline.evaluate("TSLA", S.load(), d.j, d.src)
        sid = d.j.add_signal("2026-10-19", "TSLA", "orb", status, sig, d.src.now())
        other = d.j.add_signal("2026-10-19", "ZZZ", "orb", "ready", {"valid_until": "10:25"}, d.src.now())
        d.take(sid, 1, 364.18)
        d.src.set_now("2026-10-19 15:56")
        d.monitor()
        d.monitor()
        self.assertEqual(d.j.signal(other)["status"], "expired")
        flats = [e for e in d.j.events() if e["kind"] == "flat"]
        self.assertEqual(len(flats), 1)                           # rings once
        self.assertEqual(d.state()["open_trades"][0]["last"], 366.48)

    def test_skip(self):
        d = self.desk()
        sid = d.j.add_signal("2026-10-19", "ZZZ", "orb", "ready", {}, d.src.now())
        d.skip(sid)
        with self.assertRaises(DeskError):
            d.skip(sid)

    def test_research(self):
        d = self.desk()
        e = d.earnings("aapl")
        self.assertEqual((e["entity"], e["rows"][0]["eps_diluted"]), ("Apple Inc.", 2.02))
        with self.assertRaises(DeskError):
            d.earnings("../x")
        self.assertEqual(d.congress()["filings"][0]["name"], "Hon. Nancy Pelosi")
        self.assertTrue(d.premarket()["hits"])

    def test_scheduler_tick_scans_once_per_slot(self):
        d = self.desk()
        logs = []
        sch = Scheduler(d, log=logs.append)
        sch.tick(wall=1000.0)
        sch.tick(wall=1005.0)
        self.assertEqual(len([l for l in logs if "scan:" in l]), 1)
        self.assertTrue(d.j.get("premarket")["hits"])


class UniverseList(DemoCase):
    def test_the_scanner_takes_the_universe_command_the_desk_sends(self):
        # Found in the 2026-11-11 audit: the desk passed --quiet, which `scan.py universe` rejects, so the
        # list was never written and "scan every US stock" could not work.
        from desk import engine, skills
        from desk.paths import FIXTURES
        out = pathlib.Path(self.tmp) / "universe.txt"
        r = skills.run("scanner", engine.universe_args(out) + ["--offline", FIXTURES / "trader-scanner" / "symdir"], self.tmp)
        self.assertEqual(r.rc, 0, r.message)
        self.assertGreater(len(out.read_text().splitlines()), 5)


class Server(DemoCase):
    def setUp(self):
        super().setUp()
        self.d = self.desk()
        self.httpd = serve(self.d, None, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json", "X-Desk": "1"} if headers is None else headers
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=None if body is None else json.dumps(body).encode(), headers=h if body is not None else (headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_state_and_page(self):
        code, body = self.call("/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["account"]["equity"], 400)
        code, body = self.call("/")
        self.assertIn(b"Trading Desk", body)

    def test_chart_and_plan_routes(self):
        code, body = self.call("/api/chart?symbol=AAPL&interval=5m")
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertTrue(d["bars"] and d["vwap"])
        self.assertIn("Range high", [v["title"] for v in d["levels"]])
        self.assertEqual(self.call("/api/chart?symbol=AAPL&interval=1m")[0], 400)     # the demo has 5-minute charts only
        self.assertEqual(self.call("/api/chart?symbol=AAPL&interval=7m")[0], 400)
        self.assertEqual(self.call("/api/plan", {})[0], 400)                           # no game plan in the demo
        self.assertIn("game_plan", json.loads(self.call("/api/state")[1]))

    def test_guards(self):
        self.assertEqual(self.call("/api/skip", {"signal_id": 1}, headers={"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.call("/api/skip", {"signal_id": 1}, headers={"Content-Type": "text/plain", "X-Desk": "1"})[0], 403)
        self.assertEqual(self.call("/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("/../desk/server.py")[0], 404)
        self.assertEqual(self.call("/api/settings", {"changes": {"risk_per_trade_pct": 90}})[0], 400)
        self.assertEqual(self.call("/api/nope", {})[0], 404)

    def test_a_bad_event_id_is_a_plain_400_not_a_crash(self):
        code, body = self.call("/api/seen", {"id": "abc"})
        self.assertEqual(code, 400)
        self.assertNotIn(b"pressed Send", body)
        self.assertEqual(self.call("/api/seen", {"id": 1})[0], 200)

    def test_scan_and_settings_over_http(self):
        code, body = self.call("/api/scan", {})
        self.assertEqual(json.loads(body)["scan"]["hits"], 41)
        self.assertEqual(self.call("/api/settings", {"changes": {"max_trades_per_day": 4}})[0], 200)
        self.assertEqual(S.load()["max_trades_per_day"], 4)


class SchedulerCalendar(DeskCase):
    """The hourly Claude look and catalysts run only on days the market opens, and only until it closes."""

    def sched(self, now, close):
        d = mock.Mock()
        d.src.demo, d.src.now.return_value = False, now
        d.session_close.return_value = close
        d.planning.return_value = False
        d.j.get.return_value = None
        d.scan.return_value = None
        d.auto.tick.return_value = None
        # these tests are about the clock: never start the model books' background threads (they write files)
        from desk import scheduler as sch_mod
        for book in (sch_mod.combo, sch_mod.winter3x):
            p = mock.patch.object(book, "due", return_value=False)
            p.start()
            self.addCleanup(p.stop)
        return d, Scheduler(d, log=lambda *_: None)

    def test_a_sleep_during_entry_hours_is_logged_once(self):
        d, sch = self.sched("2026-11-20 09:30", "16:00")
        with mock.patch.object(S, "load", return_value=dict(S.load(), no_entries_before="09:45", no_entries_after="14:30")):
            sch.tick(wall=10000.0)
            d.src.now.return_value = "2026-11-20 10:17"
            sch.tick(wall=10000.0 + 47 * 60)
            d.src.now.return_value = "2026-11-20 10:18"
            sch.tick(wall=10000.0 + 48 * 60)                          # a normal pass: nothing more
        gaps = [c for c in d.j.add_event.call_args_list if c.args[0] == "health"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("from 09:45 to 10:17", gaps[0].args[1])

    def test_a_pause_before_the_entry_window_is_not_logged(self):
        d, sch = self.sched("2026-11-20 08:15", "16:00")
        sch.tick(wall=10000.0)
        d.src.now.return_value = "2026-11-20 09:30"
        sch.tick(wall=10000.0 + 75 * 60)
        self.assertFalse([c for c in d.j.add_event.call_args_list if c.args[0] == "health"])

    def test_nothing_hourly_on_a_market_holiday(self):
        d, sch = self.sched("2026-11-26 10:00", None)               # Thanksgiving
        sch.tick(wall=10000.0)
        sch.last_catalysts = 0.0
        sch.tick(wall=20000.0)
        self.assertEqual(sch.last_plan_try, 0.0)
        d.make_plan.assert_not_called()
        d.find_catalysts.assert_not_called()

    def test_game_plan_runs_on_an_early_close_morning_but_not_after_the_close(self):
        d, sch = self.sched("2026-11-27 10:00", "13:00")
        sch.tick(wall=10000.0)
        self.assertEqual(sch.last_plan_try, 10000.0)                  # a look was started
        d, sch = self.sched("2026-11-27 13:30", "13:00")
        sch.tick(wall=10000.0)
        sch.last_catalysts = 0.0
        sch.tick(wall=20000.0)
        self.assertEqual(sch.last_plan_try, 0.0)
        d.find_catalysts.assert_not_called()

    def test_session_close_reads_the_clock_once_a_day(self):
        d = Desk(Journal(), Demo())
        self.addCleanup(d.j.close)
        self.assertIsNone(d.session_close("2026-11-26"))
        self.assertEqual(d.session_close("2026-11-27"), "13:00")
        self.assertEqual(d.session_close("2026-11-30"), "16:00")
        self.assertIsNone(d.session_close("2026-11-28"))              # a Saturday


class OneShareFloor(DeskCase):
    """Paper mode, docs/IMPROVE-2026-11-20.md T3: when Claude's day cut to risk_per_trade_pct leaves 0 shares, the trade
    is sized again at your own percentage (one share), never above it."""

    def snow(self, mode="paper", plan=True):
        S.save({"starting_balance": 400, "risk_per_trade_pct": 1.0, "mode": mode})
        d = Desk(Journal(), Demo("2026-10-19 10:15"))
        if plan:
            d.j.put("plan_settings", {"date": "2026-10-19", "base": {"risk_per_trade_pct": 2.0},
                                      "set": {"risk_per_trade_pct": 1.0}})
        d.scan()
        return [x for x in d.j.signals() if x["symbol"] == "SNOW"][0]

    def test_the_cut_alone_never_blocks_a_trade_in_paper(self):
        s = self.snow()
        p = s["payload"]
        self.assertEqual(p["qty"], 1)
        self.assertLessEqual(p["max_loss"], 8.0)                  # your own 2 % of $400
        self.assertGreater(p["max_loss"], 4.0)                    # over the day's cut: that is why it needed the floor
        self.assertIn("One share", " ".join(p["warnings"]))
        self.assertNotEqual(s["status"], "blocked")

    def test_no_floor_without_a_cut_today(self):
        s = self.snow(plan=False)
        self.assertEqual((s["status"], s["payload"]["qty"]), ("blocked", 0))


class TestsLeaveNoData(DeskCase):
    """The suite must never write into the repo's own data/ folder (on 2026-11-20 a model thread a scheduler test
    started outlived the test and reset the real model accounts). Runs the scheduler tests and checks."""

    def test_the_scheduler_tests_write_nothing_under_the_repo_data_folder(self):
        import time
        import unittest
        from desk.paths import ROOT
        real = ROOT / "data"
        before = {p: p.stat().st_mtime for p in (real / "accounts").rglob("model.json")} if real.exists() else None
        existed = real.exists()
        loader = unittest.defaultTestLoader
        suite = unittest.TestSuite([loader.loadTestsFromTestCase(SchedulerCalendar)]
                                   + [loader.loadTestsFromName(n) for n in ("tests.test_combo", "tests.test_speed")])
        res = unittest.TestResult()
        suite.run(res)
        self.assertTrue(res.wasSuccessful(), res.errors + res.failures)
        time.sleep(0.5)                                   # a stray thread would have saved by now
        if not existed:
            self.assertFalse(real.exists(), "a test wrote into %s" % real)
        else:                                            # the main checkout: your model accounts must be untouched
            after = {p: p.stat().st_mtime for p in (real / "accounts").rglob("model.json")}
            self.assertEqual({p: t for p, t in after.items() if p in before}, before)
            self.assertEqual(set(after), set(before))

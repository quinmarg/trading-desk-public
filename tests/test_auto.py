from unittest import mock
"""Auto paper (desk/auto.py) and the review log it feeds (desk/outcome.py, scans, practice fills).

The hard rules: it trades only in paper mode, only the practice account, never a broker, with the same
limits as a person, and every step is in the paper journal. Prices come from a fake quote function."""
import json
import re

from desk import charts, outcome
from desk import settings as S
from desk.engine import DeskError
from desk.paths import ROOT
from desk.scheduler import Scheduler
from tests.test_desk import DemoCase
from tests.test_paper import PaperBase, q

SIG = {"symbol": "KO", "qty": 5, "limit": 60.20, "stop": 59.80, "target": 61.00, "valid_until": "10:25",
       "flat_by": "15:55", "trigger_close_time": "10:15", "workdir": "", "cost": 301.0}


class AutoBase(PaperBase):
    def setUp(self):
        super().setUp()
        S.update({"auto_paper": True})
        self.px["KO"] = q(60.50)
        self.sid = self.add()

    def add(self, sym="KO", **kw):
        return self.d.j.add_signal("2026-10-19", sym, "orb", "ready", dict(SIG, symbol=sym, **kw), self.d.src.now())

    def tick(self):
        return self.d.auto.tick()

    def entry(self, sid=None):
        return self.d.auto.book()[str(sid or self.sid)]

    def filled(self):
        self.tick()
        self.px["KO"] = q(60.10)
        self.tick()
        return self.d.j.open_trades()[0]


class Trading(AutoBase):
    def test_places_the_slips_bracket_in_the_practice_account_only(self):
        self.assertEqual(self.tick()["placed"], 1)
        e = self.entry()
        self.assertEqual(e["state"], "working")
        o = {r["id"]: r for r in self.rows()}[e["order_id"]]
        self.assertEqual((o["side"], o["type"], o["price"], o["qty"]), ("BUY", "LIMIT", 60.2, 5))

    def test_a_fill_is_a_journal_trade_marked_auto_and_the_target_closes_it(self):
        t = self.filled()
        self.assertEqual((t["symbol"], t["qty"], t["entry_price"], t["note"], t["signal_id"]), ("KO", 5, 60.1, "auto", self.sid))
        self.assertEqual(self.d.j.signal(self.sid)["status"], "taken")
        self.px["KO"] = q(61.10)
        self.assertEqual(self.tick()["closed"], 1)
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["status"], c["exit_reason"], c["pnl"]), ("closed", "target", 5.0))
        kinds = [e["kind"] for e in self.d.j.events(limit=100)]
        self.assertIn("auto", kinds)
        self.assertIn("paper", kinds)                   # the practice fills are logged too

    def test_the_stop_closes_it(self):
        t = self.filled()
        self.px["KO"] = q(59.70)
        self.tick()
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["exit_reason"], c["exit_price"]), ("stop", 59.69))

    def test_flat_by_the_close_sells_at_the_market(self):
        t = self.filled()
        self.d.src.set_now("2026-10-19 15:55")
        self.px["KO"] = q(60.40)
        self.tick()
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["status"], c["exit_reason"], c["exit_price"]), ("closed", "flat", 60.39))   # less the slippage guess
        self.assertEqual(self.d.paper.snapshot()["positions"], [])

    def test_a_buy_not_filled_in_time_is_cancelled(self):
        self.tick()
        self.d.src.set_now("2026-10-19 10:30")
        self.assertEqual(self.tick()["cancelled"], 1)
        self.assertEqual(self.entry()["state"], "unfilled")
        self.assertEqual(self.d.j.open_trades(), [])

    def test_no_rings_telling_you_to_check_thinkorswim_for_its_own_trades(self):
        self.filled()
        self.d.monitor()
        self.assertFalse([e for e in self.d.j.events(limit=100) if e["kind"] in ("stop", "target", "flat")])


class SameLimitsAsYou(AutoBase):
    @mock.patch.object(S, "trades_cap", lambda st: st["max_trades_per_day"])   # live-mode cap; paper has none
    def test_trades_per_day_counting_its_own_waiting_buys(self):
        S.update({"max_trades_per_day": 2})                                             # the default is no cap
        self.d.j.open_trade("T", 1, 12.0, 11.5, 13.0, self.d.src.now(), note="")      # one you took
        self.tick()                                                                     # KO: the second
        sid = self.add("F", qty=1, limit=12.0, stop=11.9, target=12.3, cost=12.0)
        self.tick()
        self.assertEqual(self.entry()["state"], "working")
        self.assertIn("2 of 2 trades", self.entry(sid)["why"])

    def test_loss_per_trade(self):
        sid = self.add("F", qty=40, limit=12.0, stop=11.5, target=13.0, cost=480.0)
        self.d.j.set_signal_status(self.sid, "skipped")
        self.tick()
        self.assertIn("risk $20.00 is over", self.entry(sid)["why"])

    def test_cash_after_its_own_waiting_buys(self):
        sid = self.add("F", qty=10, limit=12.0, stop=11.9, target=12.3, cost=120.0)
        self.px["F"] = q(12.5)
        self.tick()                                      # KO waits ($301), so F ($120) does not fit in $380
        self.assertEqual(self.entry()["state"], "working")
        self.assertIn("settled cash", self.entry(sid)["why"])

    def test_pause_and_the_entry_window(self):
        S.update({"paused": True})
        self.assertEqual(self.tick()["placed"], 0)
        S.update({"paused": False})
        self.d.src.set_now("2026-10-19 09:40")
        self.assertEqual(self.tick()["placed"], 0)

    def test_you_and_auto_paper_never_both_take_one_signal(self):
        self.tick()
        with self.assertRaises(DeskError):
            self.d.take(self.sid, 5, "60.10")
        self.d.skip(self.sid)                            # skipping cancels its waiting buy
        self.assertEqual(self.entry()["state"], "cancelled")
        self.assertEqual(self.d.j.signal(self.sid)["status"], "skipped")


class WeakSignals(AutoBase):
    def test_weak_signals_only_when_switched_on(self):
        self.tick()                                     # the ready KO slip is placed first
        sid = self.d.j.add_signal("2026-10-19", "PEP", "orb", "weak", dict(SIG, symbol="PEP"), self.d.src.now())
        self.px["PEP"] = q(60.50)
        self.tick()
        self.assertNotIn(str(sid), self.d.auto.book())
        S.update({"auto_paper_weak": True})
        self.tick()
        self.assertIn(str(sid), self.d.auto.book())     # looked at now (placed, or declined by the same limits as you)
        self.assertNotIn("weak", self.entry(sid).get("why", ""))


class NeverLiveNeverBroker(AutoBase):
    def test_live_mode_does_nothing_at_all(self):
        self.d.set_mode("live", "LIVE")
        self.d.j.deposit(400.0, self.d.src.now(), "test")
        self.d.j.add_signal("2026-10-19", "KO", "orb", "ready", dict(SIG), self.d.src.now())
        S.update({"auto_paper": True})
        before = self.d.paper.path().exists()
        self.assertIsNone(self.tick())
        self.assertEqual(self.d.paper.path().exists(), before)
        self.assertEqual(self.d.j.open_trades(), [])

    def test_switching_to_live_cancels_its_waiting_buy_first(self):
        self.tick()
        self.d.set_mode("live", "LIVE")
        self.d.set_mode("paper")
        self.assertEqual(self.entry()["state"], "cancelled")

    def test_an_open_auto_trade_blocks_the_switch_to_live(self):
        self.filled()
        with self.assertRaises(DeskError):
            self.d.set_mode("live", "LIVE")

    def test_the_code_has_no_way_to_a_broker(self):
        src = (ROOT / "desk" / "auto.py").read_text()
        for bad in ("urllib", "http", "socket", "requests"):
            self.assertNotIn(bad, src)
        calls = re.findall(r"place_order\(([^,]+),", src) + re.findall(r"cancel_order\(([^,]+),", src)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {"P.ACCOUNT"})

    def test_it_refuses_anything_but_the_practice_account(self):
        self.d._paper = object()
        with self.assertRaises(RuntimeError):
            self.tick()

    def test_switch_off_takes_nothing_new_but_finishes_what_it_has(self):
        t = self.filled()
        S.update({"auto_paper": False})
        self.add("F", limit=12.0, stop=11.9, target=12.3, qty=1, cost=12.0)
        self.px["F"] = q(11.95)
        self.px["KO"] = q(61.20)
        self.tick()
        self.assertEqual(self.d.j.trade(t["id"])["exit_reason"], "target")
        self.assertEqual(len(self.d.auto.book()), 1)

    def test_the_scheduler_runs_it_in_paper_mode(self):
        sch, wall = Scheduler(self.d, log=lambda *_: None), 1e9
        sch.premarket_day, sch.last_scan_slot, sch.last_monitor = "2026-10-19", int((wall - 25) // 300), wall   # no network
        sch.tick(wall=wall)
        self.assertEqual(self.entry()["state"], "working")

    def test_the_review_tells_auto_from_you(self):
        self.filled()
        self.px["KO"] = q(61.10)
        self.tick()
        text = self.d.review()["text"]
        self.assertIn("auto: 1 closed, +$5.00", text)
        self.assertIn("Practice-account fills logged: 2", text)
        self.assertTrue(self.d.state()["auto"]["on"])


def bars(rows):
    out = []
    for start, o, h, l, c in rows:
        hh, mm = start.split(":")
        out.append({"date": "2026-10-19", "start": start, "minute": int(hh) * 60 + int(mm), "o": o, "h": h, "l": l, "c": c, "v": 1})
    return out


class Replay(DemoCase):
    P = {"limit": 10.0, "stop": 9.5, "target": 11.0, "trigger_close_time": "10:00", "valid_until": "10:10", "flat_by": "15:55"}

    def test_fills_then_target(self):
        o = outcome.replay(self.P, bars([("09:55", 10, 10.2, 9.9, 10.1), ("10:00", 10.1, 10.2, 9.95, 10.1),
                                          ("10:05", 10.2, 11.1, 10.1, 11.0)]))
        self.assertEqual((o["result"], o["entry"], o["exit"], o["r"]), ("target", 10.0, 11.0, 2.0))

    def test_stop_first_when_one_candle_reaches_both(self):
        o = outcome.replay(self.P, bars([("10:00", 10.1, 10.1, 9.9, 10.0), ("10:05", 10.0, 11.2, 9.4, 10.0)]))
        self.assertEqual((o["result"], o["exit"], o["r"]), ("stop", 9.5, -1.0))

    def test_never_back_to_the_limit(self):
        o = outcome.replay(self.P, bars([("10:00", 10.3, 10.6, 10.2, 10.5), ("10:05", 10.5, 10.9, 10.4, 10.8),
                                          ("10:10", 10.0, 10.0, 9.0, 9.2)]))
        self.assertEqual(o["result"], "no fill")

    def test_flat_by_and_gaps(self):
        o = outcome.replay(dict(self.P, flat_by="10:10"), bars([("10:00", 9.9, 10.0, 9.8, 9.9), ("10:10", 10.2, 10.3, 10.1, 10.2)]))
        self.assertEqual((o["result"], o["entry"], o["exit"]), ("flat", 9.9, 10.2))
        o = outcome.replay(self.P, bars([("10:00", 10.0, 10.0, 9.9, 9.9), ("10:05", 9.2, 9.3, 9.1, 9.2)]))
        self.assertEqual((o["result"], o["exit"]), ("stop", 9.2))

    def test_no_plan(self):
        self.assertEqual(outcome.replay({"symbol": "X"}, [])["result"], "no plan")

    def test_after_the_close_every_signal_of_the_day_is_replayed_and_reported(self):
        d = self.desk()
        a = d.j.add_signal("2026-10-19", "KO", "orb", "skipped", dict(self.P, symbol="KO",
                           odds={"p_target": 0.4, "p_stop": 0.5}), "2026-10-19 10:00")
        d.j.add_signal("2026-10-19", "F", "orb", "blocked", {"symbol": "F", "problems": ["x"]}, "2026-10-19 10:00")
        real = charts.intraday
        charts.intraday = lambda src, sym: {"bars": bars([("10:00", 10.1, 10.1, 9.9, 10.0), ("10:05", 10.0, 11.2, 10.0, 11.1)])}
        self.addCleanup(setattr, charts, "intraday", real)
        self.assertEqual(d.record_outcomes("2026-10-19"), 2)
        got = {o["signal_id"]: o for o in d.j.outcomes()}
        self.assertEqual((got[a]["status"], got[a]["result"], got[a]["r"]), ("skipped", "target", 2.0))
        text = d.review()["text"]
        self.assertIn("skipped 1: target 1", text)
        self.assertIn("blocked 1: no plan 1", text)
        self.assertIn("Time Machine said target first 40.0%", text)


class ScanLog(DemoCase):
    def test_every_scan_is_kept_with_what_happened_to_each_breakout(self):
        d = self.desk()
        d.scan()
        rows = d.j.scans()
        self.assertEqual(len(rows), 1)
        s = rows[0]["summary"]
        self.assertEqual(len(s["detail"]), s["hits"])
        fates = {x["fate"] for x in s["detail"]}
        self.assertIn("too old", fates)
        self.assertIn("ready", fates)
        self.assertIn("SCANS", d.review()["text"])
        self.assertIn("1 scans over 1 days", d.review()["text"])

    def test_a_halt_is_logged_once(self):
        d = self.desk(paused=True)
        d.scan()
        d.scan()
        self.assertEqual(len(d.j.scans()), 1)

    def test_auto_paper_is_a_true_false_setting_and_off_by_default(self):
        self.assertFalse(S.load()["auto_paper"])
        with self.assertRaises(S.SettingsError):
            S.validate({"auto_paper": "yes"})
        self.assertEqual(json.loads(json.dumps(S.update({"auto_paper": True})))["auto_paper"], True)


class EarlyClose(AutoBase):
    """2026-11-27 closes at 1:00 PM: flat-by moves up to 12:55, or the trade would be held over the weekend."""

    def test_day_flat_by_moves_up_with_an_early_close(self):
        st = S.load()
        self.assertEqual(self.d.day_flat_by(st, "2026-10-19 10:15"), "15:55")
        self.assertEqual(self.d.day_flat_by(st, "2026-11-27 10:15"), "12:55")
        self.assertEqual(self.d.day_flat_by(dict(st, flat_by="12:00"), "2026-11-27 10:15"), "09:35")   # never before the open

    def test_auto_paper_sells_before_the_early_close_even_with_a_1555_slip(self):
        self.d.src.set_now("2026-11-27 10:15")
        sid = self.d.j.add_signal("2026-11-27", "KO", "orb", "ready", dict(SIG), self.d.src.now())
        self.tick()
        self.px["KO"] = q(60.10)
        self.tick()
        t = self.d.j.open_trades()[0]
        self.assertEqual(t["signal_id"], sid)
        self.d.src.set_now("2026-11-27 12:50")
        self.px["KO"] = q(60.40)
        self.tick()
        self.assertEqual(self.d.j.trade(t["id"])["status"], "open")
        self.d.src.set_now("2026-11-27 12:55")
        self.tick()
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["status"], c["exit_reason"]), ("closed", "flat"))


class PriceAlreadyAtTheStop(AutoBase):
    """A buy that fills at its stop is refused by the journal, so the round trip never reaches the record."""

    def test_a_signal_whose_price_is_already_at_the_stop_is_left_alone(self):
        self.px["KO"] = q(59.80)                                    # the slip's stop
        out = self.tick()
        self.assertEqual((out["placed"], out["declined"]), (0, 1))
        self.assertIn("already at or past the stop", self.entry()["why"])
        self.assertEqual(self.rows(), [])

    def test_a_price_above_the_stop_still_trades(self):
        self.px["KO"] = q(59.90)
        self.assertEqual(self.tick()["placed"], 1)

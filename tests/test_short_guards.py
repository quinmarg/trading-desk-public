"""Shorts stay practice-only: the desk has no way to place a real order, and no order shape for a short
outside the practice account. Also the practice account's short side, the per-stock decision log and
the review by side. Fake quotes only, no network (docs/SHORTING.md)."""
import inspect
import json

from desk import costs, decide, orders, paper, review, rulecard, shorts, stamp
from desk import settings as S
from desk.engine import DeskError
from desk.journal import Journal
from tests.base import DeskCase
from tests.test_auto import SIG
from tests.test_paper import PaperBase, q

SHORT_SIG = dict(SIG, side="short", limit=11.90, stop=12.10, target=11.50, qty=5, entry=11.92, paper_only=True)


class OrdersFileHasNoShort(DeskCase):
    def test_orders_py_cannot_build_a_short(self):
        src = inspect.getsource(orders)
        for word in ("SELL_SHORT", "BUY_TO_COVER", "SHORT"):
            self.assertNotIn(word, src.upper().replace("SHORTTITLE", ""), word)
        with self.assertRaises(ValueError):
            orders.check("F", 5, 11.90, 12.10, 11.50)      # a short slip's numbers: stop over the limit
        with self.assertRaises(ValueError):
            orders.single("F", "SELL_SHORT", 1, "MARKET")


class PracticeShorts(PaperBase):
    """The practice account's short side. Placed straight into the paper account, never at a broker."""

    def place_short(self, sym="F", qty=5, limit=11.90, stop=12.10, target=11.50):
        return self.d.paper.place_order(paper.ACCOUNT, paper.short_bracket(sym, qty, limit, stop, target))

    def look(self, price, low=None, high=None, sym="F"):
        self.px[sym] = q(price, low, high)
        self.d.paper.settle()
        return self.d.paper.snapshot()

    def test_short_fills_sets_value_aside_and_a_target_cover_makes_money(self):
        self.px["F"] = q(11.80)                       # under the sell limit: waits
        self.place_short()
        a = self.look(11.80)
        self.assertEqual((a["cash"], a["positions"]), (400.0, []))
        self.assertEqual(a["available"], round(400 - 5 * 11.90, 2))          # the working short ties up its value
        a = self.look(11.95)                          # at or over 11.90: sold short at the price
        self.assertEqual(a["positions"][0]["qty"], -5)
        self.assertEqual(a["positions"][0]["side"], "short")
        self.assertEqual(a["cash"], round(400 - 5 * 11.95, 2))
        self.assertEqual(a["value"], 400.0)           # equity unchanged at the price it sold at
        a = self.look(11.45, low=11.45)               # target 11.50 reached: covered
        self.assertEqual(a["positions"], [])
        self.assertEqual(a["cash"], round(400 + 5 * (11.95 - 11.45), 2))
        self.assertEqual(a["unsettled"], round(2 * 5 * 11.95 - 5 * 11.45, 2))

    def test_the_buy_stop_above_covers_at_a_loss(self):
        self.px["F"] = q(11.95)
        self.place_short()
        a = self.look(11.95)
        a = self.look(12.20, high=12.20)              # stop 12.10 reached
        self.assertEqual(a["positions"], [])
        self.assertEqual(a["cash"], round(400 - 5 * (12.21 - 11.95), 2))     # the cover pays the 1-cent slippage guess

    def test_never_long_and_short_at_once_and_no_cover_without_a_short(self):
        self.hold("F", qty=3, price=12.00)
        self.px["F"] = q(12.00)
        self.place_short(limit=11.90, stop=12.10, target=11.50)
        self.look(12.00)
        acct = self.d.paper.snapshot()
        self.assertEqual([p["qty"] for p in acct["positions"]], [3])          # the short was rejected
        cover = {"orderType": "MARKET", "session": "NORMAL", "duration": "DAY", "orderStrategyType": "SINGLE",
                 "orderLegCollection": [{"instruction": "BUY_TO_COVER", "quantity": 2,
                                         "instrument": {"symbol": "KO", "assetType": "EQUITY"}}]}
        self.px["KO"] = q(60.0)
        self.d.paper.place_order(paper.ACCOUNT, cover)
        self.assertNotIn("KO", [p["symbol"] for p in self.d.paper.snapshot()["positions"]])

    def test_short_bracket_refuses_wrong_numbers(self):
        for bad in (("F", 5, 12.10, 11.90, 11.50), ("F", 0, 11.90, 12.10, 11.50), ("f/../x", 1, 11.9, 12.1, 11.5)):
            with self.assertRaises(ValueError, msg=bad):
                paper.short_bracket(*bad)


class LiveRecordRefusesPracticeShorts(PaperBase):
    def test_a_practice_only_short_cannot_be_recorded_as_real_money(self):
        self.d.set_mode("live", "LIVE")
        self.d.j.deposit(400.0, self.d.src.now(), "test: real cash typed in")   # live starts at $0
        S.update({"directions": "both"})
        p = dict(SHORT_SIG, symbol="IONQ", date="2026-10-19", workdir=self.tmp, valid_until="23:59")
        sid = self.d.j.add_signal("2026-10-19", "IONQ", "orb_short", "ready", p, self.d.src.now())
        self.d.halt_reason = lambda st, now: None
        with self.assertRaises(DeskError) as e:
            self.d.take(sid, 5, "11.95")
        self.assertIn("cannot short for real", str(e.exception))
        self.assertEqual(self.d.j.open_trades(), [])


class SideAwareRecord(DeskCase):
    def test_turning_shorts_on_starts_a_new_rule_set(self):
        a = S.validate({})
        self.assertNotEqual(stamp.rules_hash(a), stamp.rules_hash(dict(a, directions="both")))
        self.assertNotEqual(stamp.rules_hash(a), stamp.rules_hash(dict(a, short_approved=True)))

    def test_after_cost_for_a_short(self):
        c = costs.after_cost(11.90, 12.10, 11.50, 5, 0.01, side="short")
        self.assertEqual((c["reward"], c["max_loss"], c["reward_risk"]), (1.95, 1.05, 1.86))
        self.assertEqual(costs.after_cost(12.10, 11.80, 12.70, 5, 0.01)["reward_risk"], 1.9)

    def test_the_rule_card_for_a_short_says_sell_short_and_buy_stop(self):
        st = S.validate({"directions": "both"})
        sig = dict(SHORT_SIG, opening_range={"high": 12.4, "low": 12.0}, risk_per_share=0.18, valid_until="10:25",
                   bound_by="risk per trade", max_loss=1.0, stop_label="the middle of the opening range")
        text = " ".join(c["text"] for c in rulecard.build(sig, st))
        for want in ("breakdown", "close below the low", "Sell short", "or higher", "Buy to cover", "Buy stop at 12.10",
                     "200-day", "not capped"):
            self.assertIn(want, text)
        self.assertEqual([c["part"] for c in rulecard.build(sig, st)],
                         ["Market", "Setup", "Filter", "Entry", "Exit", "Stop", "Size"])

    def test_review_reads_shorts_with_the_right_sign_and_by_side(self):
        sigs = [{"id": 1, "status": "taken", "payload": {"limit": 12.10, "qty": 5}},
                {"id": 2, "status": "taken", "payload": {"limit": 11.90, "qty": 5, "side": "short"}}]
        trades = [
            {"id": 1, "signal_id": 1, "side": "long", "status": "closed", "qty": 5, "entry_price": 12.12, "stop": 11.80,
             "target": 12.70, "exit_price": 11.78, "exit_reason": "stop", "pnl": -1.7, "r_multiple": -1.06, "exit_at": "a"},
            {"id": 2, "signal_id": 2, "side": "short", "status": "closed", "qty": 5, "entry_price": 11.88, "stop": 12.10,
             "target": 11.50, "exit_price": 12.13, "exit_reason": "stop", "pnl": -1.25, "r_multiple": -1.14, "exit_at": "b"},
        ]
        s = review.summary(trades, sigs)
        p = s["plan"]
        self.assertEqual(p["fills_over_limit"], 2)                 # both filled worse than the slip
        self.assertEqual(p["avg_fill_vs_limit"], 0.02)             # +0.02 on the buy, +0.02 short sold lower
        self.assertEqual(p["avg_stop_vs_plan"], -0.03)             # -0.02 sold lower, -0.03 covered higher: worse
        self.assertEqual((s["by_side"]["long"]["closed"], s["by_side"]["short"]["closed"]), (1, 1))
        self.assertEqual(s["by_side"]["short"]["total"], -1.25)
        self.assertIn("Short: 1 closed", review.report("paper", s, "now"))


class DecisionLog(DeskCase):
    def test_one_row_per_stock_says_long_short_both_or_nothing(self):
        rows = [decide.row("A", decide.note(signal=1, status="ready"), decide.note(reason="no close below the range low")),
                decide.row("B", decide.note(reason="breakout too old to chase"), decide.note(signal=2, status="weak")),
                decide.row("C", decide.note(signal=3, status="blocked"), decide.note(signal=4, status="ready")),
                decide.row("D", decide.note(reason="no close above the range high"), None)]
        self.assertEqual([r["decision"] for r in rows], ["long", "short", "both", "nothing"])
        self.assertEqual(rows[3]["short"], decide.OFF)
        c = decide.counts(rows)
        self.assertEqual(c["by_decision"], {"long": 1, "short": 1, "both": 1, "nothing": 1})
        self.assertEqual(c["top_reasons"]["short"], [("no close below the range low", 1)])

    def test_the_journal_keeps_the_rows(self):
        j = Journal()
        self.addCleanup(j.close)
        j.add_decisions([decide.row("A", decide.note(reason="x"), None)], "2026-10-19 10:15")
        (r,) = j.decisions("2026-10-19")
        self.assertEqual((r["symbol"], r["decision"], r["long"], r["short"]), ("A", "nothing", "x", decide.OFF))


class DecisionsInTheReview(DeskCase):
    def test_the_report_lists_scan_decisions(self):
        s = review.summary([], [])
        s["decisions"] = decide.counts([decide.row("A", decide.note(reason="no close above the range high"),
                                                   decide.note(signal=2, status="ready"))])
        text = review.report("paper", s, "now")
        self.assertIn("SCAN DECISIONS (1 stock-scans)", text)
        self.assertIn("short 1", text)
        self.assertIn("No long, commonest reasons: no close above the range high (1)", text)


# ---- auto paper and the after-close replay, with shorts ------------------------------------------
from desk import outcome                                                      # noqa: E402
from tests.test_auto import AutoBase, bars                                    # noqa: E402

SHORT = {"symbol": "F", "qty": 5, "limit": 11.90, "stop": 12.10, "target": 11.50, "valid_until": "10:25",
         "flat_by": "15:55", "trigger_close_time": "10:15", "workdir": "", "cost": 60.5, "side": "short",
         "paper_only": True}


class AutoPaperShorts(AutoBase):
    def setUp(self):
        super().setUp()
        self.d.j.set_signal_status(self.sid, "skipped")                   # the base's long KO signal steps aside
        S.update({"directions": "both"})
        self.px["F"] = q(11.80)
        self.short_sid = self.d.j.add_signal("2026-10-19", "F", "orb_short", "ready", dict(SHORT), self.d.src.now())

    def test_places_a_practice_short_never_at_a_broker(self):
        self.assertEqual(self.tick()["placed"], 1)
        e = self.entry(self.short_sid)
        self.assertEqual((e["state"], e["side"], e["cost"]), ("working", "short", 60.5))   # 5 x 12.10 set aside

    def test_fill_then_target_is_a_short_trade_with_the_right_pnl(self):
        self.tick()
        self.px["F"] = q(11.95)
        self.tick()
        (t,) = [t for t in self.d.j.open_trades() if t["symbol"] == "F"]
        self.assertEqual((t["side"], t["note"], t["entry_price"]), ("short", "auto", 11.95))
        self.px["F"] = q(11.45, low=11.45)
        self.tick()
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["status"], c["exit_reason"], c["pnl"]), ("closed", "target", 2.5))
        self.assertIn("bought to cover", " ".join(ev["message"] for ev in self.d.j.events(limit=50)))

    def test_the_buy_stop_and_flat_by_the_close(self):
        self.tick()
        self.px["F"] = q(11.95)
        self.tick()
        (t,) = [t for t in self.d.j.open_trades() if t["symbol"] == "F"]
        self.d.src.set_now("2026-10-19 15:55")
        self.px["F"] = q(11.85)
        self.tick()
        c = self.d.j.trade(t["id"])
        self.assertEqual((c["exit_reason"], c["exit_price"], c["pnl"]), ("flat", 11.86, 0.45))   # market cover + slippage guess
        self.assertEqual(self.d.paper.snapshot()["positions"], [])

    def test_shorts_switched_off_are_left_alone(self):
        S.update({"directions": "long"})
        self.tick()
        self.assertNotIn(str(self.short_sid), self.d.auto.book())

    def test_live_mode_does_nothing_with_a_short(self):
        self.d.set_mode("live", "LIVE")
        self.assertIsNone(self.tick())


class ReplayShorts(DeskCase):
    P = {"limit": 10.0, "stop": 10.5, "target": 9.0, "trigger_close_time": "10:00", "valid_until": "10:10",
         "flat_by": "15:55", "side": "short"}

    def test_fills_at_the_limit_or_higher_then_target(self):
        o = outcome.replay(self.P, bars([("10:00", 9.9, 10.05, 9.8, 9.9), ("10:05", 9.9, 9.95, 8.9, 9.0)]))
        self.assertEqual((o["result"], o["entry"], o["exit"], o["r"]), ("target", 10.0, 9.0, 2.0))

    def test_buy_stop_first_when_one_candle_reaches_both(self):
        o = outcome.replay(self.P, bars([("10:00", 9.9, 10.1, 9.9, 10.0), ("10:05", 10.0, 10.6, 8.8, 10.0)]))
        self.assertEqual((o["result"], o["exit"], o["r"]), ("stop", 10.5, -1.0))

    def test_never_back_up_to_the_limit_and_gaps(self):
        self.assertEqual(outcome.replay(self.P, bars([("10:00", 9.8, 9.9, 9.5, 9.6), ("10:05", 9.6, 9.7, 9.0, 9.1)]))["result"],
                         "no fill")
        o = outcome.replay(self.P, bars([("10:00", 10.0, 10.0, 9.9, 9.95), ("10:05", 10.8, 10.9, 10.7, 10.8)]))
        self.assertEqual((o["result"], o["exit"]), ("stop", 10.8))
        self.assertEqual(outcome.replay(dict(self.P, stop=9.9), [])["result"], "no plan")

    def test_the_review_groups_short_replays_and_auto_shorts_apart(self):
        sigs = [{"id": 1, "status": "skipped", "payload": {"side": "short"}}, {"id": 2, "status": "skipped", "payload": {}}]
        outs = [{"signal_id": 1, "status": "skipped", "result": "target", "r": 2.0},
                {"signal_id": 2, "status": "skipped", "result": "stop", "r": -1.0}]
        t = review.outcome_table(outs, {s["id"]: s for s in sigs})
        self.assertEqual((t["short skipped"]["results"], t["skipped"]["results"]), ({"target": 1}, {"stop": 1}))
        src = review.by_source([{"status": "closed", "pnl": 1.0, "note": "auto", "side": "short", "exit_at": "a"},
                                {"status": "closed", "pnl": -1.0, "note": "auto", "exit_at": "b"}])
        self.assertEqual(sorted(src), ["auto", "auto short"])


class LiveModeLooksForNoPracticeShorts(DeskCase):
    def test_live_mode_skips_practice_only_shorts_and_says_why(self):
        from desk.engine import Desk
        from desk.source import Demo
        S.save({"directions": "both", "mode": "live"})
        j = Journal()
        self.addCleanup(j.close)
        d = Desk(j, Demo("2026-10-19 10:15"))
        j.deposit(400.0, "2026-10-19 09:00", "test cash")
        s = d.scan()
        self.assertEqual(s["short_hits"], 0)
        self.assertIn("paper mode only", s["shorts_skipped"])
        self.assertFalse([g for g in j.signals() if g["setup"] == "orb_short"])
        rows = j.decisions("2026-10-19")
        self.assertTrue(rows and all(r["short"].startswith("practice only") for r in rows))

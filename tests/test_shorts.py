"""The short side: the maths, the journal, the settings gate and the desk on the demo data.
No network. Nothing here can test a real short order, a borrow or a real restriction day."""
import sqlite3
import unittest

from desk import charts, pipeline, shorts
from desk import settings as S
from desk.engine import Desk, DeskError
from desk.journal import Journal, JournalError
from desk.source import Demo
from tests.base import DeskCase

NOW = "2026-10-19 10:15"


def bar(start, o, h, l, c, v=1000):
    hh, mm = start.split(":")
    return {"date": "2026-10-19", "start": start, "minute": int(hh) * 60 + int(mm),
            "o": o, "h": h, "l": l, "c": c, "v": v}


def session(*after, low=99.0, high=101.0):
    """A 15-minute opening range of 99.00 to 101.00, then the bars given."""
    rng = [bar("09:30", 100, high, 99.5, 100.5), bar("09:35", 100.5, 100.8, low, 99.6), bar("09:40", 99.6, 100.2, 99.4, 100)]
    return rng + list(after)


LIMITS = {"max_loss_per_trade": 8.0, "max_position": 380.0, "cash_buffer": 20.0}


class Maths(unittest.TestCase):
    def test_range_needs_every_bar(self):
        self.assertIsNone(shorts.opening_range(session()[:2], 15))
        r = shorts.opening_range(session(), 15)
        self.assertEqual((r["high"], r["low"], r["bars"]), (101.0, 99.0, 3))

    def test_a_wick_below_the_low_is_not_a_trigger(self):
        _, trig, why = shorts.breakdown(session(bar("09:45", 100, 100.1, 98.5, 99.2)), 15)
        self.assertIsNone(trig)
        self.assertIn("waiting", why)

    def test_first_close_below_the_low_is_the_trigger(self):
        bars = session(bar("09:45", 100, 100.1, 99.1, 99.3), bar("09:50", 99.3, 99.4, 98.6, 98.7, 2000),
                       bar("09:55", 98.7, 98.8, 98.0, 98.1))
        rng, trig, why = shorts.breakdown(bars, 15)
        self.assertEqual((trig["price"], trig["bar_start"], trig["close_time"], trig["time"]), (98.7, "09:50", "09:55", "9:55 AM"))
        self.assertEqual(trig["volume_x"], 2.0)
        self.assertIn("closed below the range low", why)

    def test_a_close_exactly_on_the_low_is_not_below_it(self):
        self.assertIsNone(shorts.breakdown(session(bar("09:45", 100, 100, 99, 99.0)), 15)[1])

    def test_a_first_close_after_the_last_entry_time_is_no_trigger(self):
        _, trig, why = shorts.breakdown(session(bar("15:30", 100, 100, 98, 98.5)), 15, "15:30")
        self.assertIsNone(trig)
        self.assertIn("after the last entry time", why)

    def test_volume_floor(self):
        _, trig, why = shorts.breakdown(session(bar("09:45", 100, 100, 98, 98.5, 500)), 15, min_volume_x=1.5)
        self.assertIsNone(trig)
        self.assertIn("volume", why)

    def test_plan_puts_the_stop_above_and_the_target_below(self):
        rng = {"high": 101.0, "low": 99.0}
        p = shorts.plan(98.7, rng, "or-mid", 2.0, 0.2)
        self.assertEqual((p["stop"], p["risk_per_share"], p["target"], p["limit"]), (100.0, 1.3, 96.1, 98.44))
        self.assertTrue(p["target"] < p["limit"] <= p["entry"] < p["stop"])

    def test_stops_round_up_to_the_cent_away_from_the_entry(self):
        p = shorts.plan(98.7, {"high": 101.01, "low": 99.0}, "or-mid", 1.0, 0)
        self.assertEqual(p["stop"], 100.01)                    # midpoint 100.005 rounds up, never down
        self.assertEqual(shorts.plan(98.7, {"high": 101.0, "low": 99.0}, "or-low", 1, 0)["stop"], 101.0)
        self.assertEqual(shorts.plan(100.0, {"high": 101.0, "low": 99.0}, "pct:1.5", 1, 0)["stop"], 101.5)

    def test_plan_refuses_what_it_cannot_do(self):
        rng = {"high": 101.0, "low": 99.0}
        with self.assertRaises(shorts.ShortError):
            shorts.plan(98.7, rng, "atr:2", 2, 0.2)
        with self.assertRaises(shorts.ShortError):
            shorts.plan(100.5, rng, "or-mid", 2, 0.2)          # the stop would be under the entry
        with self.assertRaises(shorts.ShortError):
            shorts.plan(1.0, {"high": 3.0, "low": 1.5}, "or-mid", 2, 0)   # target under zero

    def test_size_uses_the_same_percentage_limits(self):
        p = shorts.plan(98.7, {"high": 101.0, "low": 99.0}, "or-mid", 2.0, 0.2)
        z = shorts.size(p, LIMITS, 400.0)
        # risk at the limit is 100.00 - 98.44 = 1.56 a share: 8 / 1.56 = 5 shares; cash 380 / 100 = 3 shares
        self.assertEqual((z["qty"], z["bound_by"], z["max_loss"], z["reward"], z["cost"]), (3, "position cap", 4.68, 7.02, 300.0))
        self.assertEqual(z["reward_risk"], 1.5)
        z = shorts.size(p, dict(LIMITS, max_position=5000), 5000.0)
        self.assertEqual((z["qty"], z["bound_by"], z["max_loss"]), (5, "risk per trade", 7.8))

    def test_size_refuses_instead_of_rounding_up(self):
        p = shorts.plan(98.7, {"high": 101.0, "low": 99.0}, "or-mid", 2.0, 0.2)
        z = shorts.size(p, dict(LIMITS, max_loss_per_trade=1.0), 400.0)
        self.assertEqual(z["qty"], 0)
        self.assertIn("No order", z["refusal"])
        z = shorts.size(p, LIMITS, 50.0)
        self.assertEqual((z["qty"], z["bound_by"]), (0, "settled cash"))

    def test_short_sale_restriction_at_ten_percent(self):
        self.assertTrue(shorts.restricted(90.0, 100.0))
        self.assertTrue(shorts.restricted(85.0, 100.0))
        self.assertFalse(shorts.restricted(90.01, 100.0))
        self.assertFalse(shorts.restricted(90.0, None))

    def test_trend_needs_200_days(self):
        self.assertEqual(shorts.trend([10.0] * 199, 9.0), (None, None))
        self.assertEqual(shorts.trend([10.0] * 200, 9.0), ("down", 10.0))
        self.assertEqual(shorts.trend([10.0] * 250, 11.0), ("up", 10.0))

    def test_the_order_the_risk_manager_sees_is_a_bracketed_sell(self):
        o = shorts.order({"symbol": "AAL", "qty": 3, "limit": 11.9, "stop": 12.1, "target": 11.5})
        self.assertEqual((o["side"], o["type"], o["limit_price"], o["stop_loss_stop_price"], o["take_profit_limit_price"]),
                         ("sell", "limit", "11.90", "12.10", "11.50"))

    def test_steps_are_a_sell_short_with_a_buy_stop_and_say_paper_only(self):
        sig = {"symbol": "AAL", "qty": 3, "limit": 11.9, "stop": 12.1, "target": 11.5, "max_loss": 0.6, "paper_only": True}
        text = " ".join(shorts.tos_steps(sig))
        for want in ("PRACTICE ONLY", "paper (practice) account", "SELL SHORT", "TO OPEN", "a BUY, above your entry", "12.10", "11.50",
                     "hard to borrow"):
            self.assertIn(want, text)
        self.assertNotIn("PRACTICE ONLY", " ".join(shorts.tos_steps(dict(sig, paper_only=False))))


class Gate(DeskCase):
    def test_shorts_are_off_by_default(self):
        st = S.load()
        self.assertEqual((st["directions"], st["short_approved"]), ("long", False))
        self.assertFalse(shorts.status(st, 400.0)["on"])

    def test_directions_and_approval_are_validated(self):
        for bad in ({"directions": "sideways"}, {"short_approved": "yes"}):
            with self.assertRaises(S.SettingsError):
                S.validate(bad)
        self.assertEqual(S.validate({"directions": "both"})["directions"], "both")

    def test_paper_only_until_every_condition_is_met(self):
        st = S.validate({"directions": "both"})
        g = shorts.status(st, 400.0)
        self.assertTrue(g["on"] and g["paper_only"])
        self.assertEqual(len(g["why"]), 3)                      # cash account, under $2,000, not approved
        self.assertEqual(len(g["facts"]), 5)
        st = S.validate({"directions": "both", "account_type": "margin", "short_approved": True})
        self.assertEqual(len(shorts.status(st, 1999.99)["why"]), 1)
        self.assertFalse(shorts.status(st, 2000.0)["paper_only"])
        st["short_approved"] = False
        self.assertTrue(shorts.status(st, 50000.0)["paper_only"])

    def test_the_skills_config_never_allows_shorts_globally(self):
        cfg = S.skills_config(S.validate({"directions": "both", "account_type": "margin", "short_approved": True}), 5000)
        self.assertFalse(cfg["allow_short"])
        self.assertFalse(cfg["allow_margin"])


class Charts(unittest.TestCase):
    DOC = {"chart": {"result": [{"meta": {"symbol": "ABC", "chartPreviousClose": 10.5},
                                 "timestamp": [1792416600, 1792416900, 1792417200],      # 9:30, 9:35, 9:40 New York
                                 "indicators": {"quote": [{"open": [10, None, 10.2], "high": [10.3, None, 10.4],
                                                           "low": [9.9, None, 10.1], "close": [10.2, None, 10.3],
                                                           "volume": [100, None, 300]}]}}]}}

    def test_parse_drops_empty_bars_and_reads_new_york_time(self):
        c = charts.parse(self.DOC, "ABC")
        self.assertEqual((c["symbol"], c["prev_close"], [b["start"] for b in c["bars"]]), ("ABC", 10.5, ["09:30", "09:40"]))

    def test_parse_refuses_the_wrong_symbol_and_junk(self):
        with self.assertRaises(charts.ChartError):
            charts.parse(self.DOC, "XYZ")
        with self.assertRaises(charts.ChartError):
            charts.parse({"chart": {"result": None}}, "ABC")

    def test_a_bar_still_forming_is_left_out(self):
        c = charts.parse(self.DOC, "ABC")
        self.assertEqual(len(charts.session_bars(c, "2026-10-19 09:44")), 1)     # the 9:40 bar closes at 9:45
        self.assertEqual(len(charts.session_bars(c, "2026-10-19 09:45")), 2)
        self.assertEqual(len(charts.session_bars(c, "2026-10-20 09:45")), 0)

    def test_fetch_refuses_anything_that_is_not_a_ticker(self):
        for bad in ("", "AAPL/../x", "TOOLONGNAME", "A B"):
            with self.assertRaises(charts.ChartError):
                charts.fetch(bad, "1d", "5m")

    def test_only_yahoo_chart_hosts_and_only_get(self):
        with open(charts.__file__) as f:
            src = f.read()
        self.assertEqual(charts.HOSTS, ("query2.finance.yahoo.com", "query1.finance.yahoo.com"))
        self.assertIn('method="GET"', src)
        self.assertNotIn("data=", src)


class Dashboard(unittest.TestCase):
    """The page is not run here; these check the words a short must never be shown without."""

    def setUp(self):
        from desk.paths import STATIC
        self.html = (STATIC / "index.html").read_text()

    def test_short_slips_are_labelled_in_words(self):
        for want in (">SHORT<", ">PRACTICE ONLY<", "Sell short", "or ${sh ? \"higher\" : \"lower\"}", "Buy stop (above)",
                     "I sold short and it filled", "Bought back at", "A short's loss is not capped"):
            self.assertIn(want, self.html, want)

    def test_the_rules_and_risks_are_shown_on_the_desk_the_slip_and_settings(self):
        self.assertEqual(self.html.count("${factsList()}"), 3)             # the Desk note, every short slip, Settings
        for want in ('id="shorts-note"', 'id="shorts-facts"', '"directions"', '"short_approved"'):
            self.assertIn(want, self.html, want)

    def test_no_slip_has_a_button_that_sends_an_order(self):
        # this copy of the desk sends nothing to a broker: every trade is placed by hand
        for bad in ("data-buy=", "can_order", "orderNote("):
            self.assertNotIn(bad, self.html)


class JournalShorts(DeskCase):
    def journal(self, cash=1000.0):
        j = Journal()
        self.addCleanup(j.close)
        j.seed(cash, NOW)
        return j

    def test_a_winning_short(self):
        j = self.journal()
        tid = j.open_trade("AAL", 10, 12.00, 12.30, 11.40, NOW, side="short")
        t = j.trade(tid)
        self.assertEqual((t["side"], t["status"]), ("short", "open"))
        self.assertEqual((j.cash(), j.equity()), (880.0, 1000.0))          # $120 set aside, equity unchanged
        self.assertEqual(j.day("2026-10-19")["open_risk"], 3.0)
        pnl = j.close_trade(tid, 11.40, "target", "2026-10-19 11:00", "2026-10-19")
        self.assertEqual(pnl, 6.0)                                          # (12.00 - 11.40) x 10
        self.assertEqual((j.cash(), j.equity(), j.trade(tid)["r_multiple"]), (1006.0, 1006.0, 2.0))
        self.assertEqual([r["kind"] for r in j.ledger()][:2], ["cover", "short"])

    def test_a_losing_short_costs_what_it_rose(self):
        j = self.journal()
        tid = j.open_trade("AAL", 10, 12.00, 12.30, 11.40, NOW, side="short")
        self.assertEqual(j.close_trade(tid, 12.30, "stop", "2026-10-19 11:00", "2026-10-19"), -3.0)
        self.assertEqual((j.cash(), j.trade(tid)["r_multiple"]), (997.0, -1.0))

    def test_a_gap_over_the_stop_loses_more_than_1r(self):
        j = self.journal()
        tid = j.open_trade("AAL", 10, 12.00, 12.30, 11.40, NOW, side="short")
        self.assertEqual(j.close_trade(tid, 14.00, "stop", "2026-10-19 11:00", "2026-10-19"), -20.0)
        self.assertEqual(j.trade(tid)["r_multiple"], -6.67)

    def test_short_stop_must_be_above_and_long_stop_below(self):
        j = self.journal()
        with self.assertRaises(JournalError):
            j.open_trade("AAL", 10, 12.00, 11.90, 11.40, NOW, side="short")
        with self.assertRaises(JournalError):
            j.open_trade("AAL", 10, 12.00, 12.30, 12.60, NOW)                # a long with its stop above
        with self.assertRaises(JournalError):
            j.open_trade("AAL", 10, 12.00, 12.30, 11.40, NOW, side="sideways")

    def test_a_short_needs_its_full_value_in_settled_cash(self):
        j = self.journal(100.0)
        with self.assertRaises(JournalError):
            j.open_trade("AAL", 10, 12.00, 12.30, 11.40, NOW, side="short")

    def test_no_long_and_short_in_the_same_stock_at_once(self):
        j = self.journal()
        j.open_trade("AAL", 5, 12.00, 11.70, 12.60, NOW)
        with self.assertRaises(JournalError):
            j.open_trade("AAL", 5, 12.00, 12.30, 11.40, NOW, side="short")
        j.open_trade("F", 5, 12.00, 12.30, 11.40, NOW, side="short")
        with self.assertRaises(JournalError):
            j.open_trade("F", 5, 12.00, 11.70, 12.60, NOW)

    def test_longs_still_record_as_before(self):
        j = self.journal()
        tid = j.open_trade("AAL", 10, 12.00, 11.70, 12.60, NOW)
        self.assertEqual(j.trade(tid)["side"], "long")
        self.assertEqual(j.close_trade(tid, 12.60, "target", "2026-10-19 11:00", "2026-10-20"), 6.0)
        self.assertEqual(j.cash(), 1006.0)

    def test_an_old_journal_gains_the_new_columns_and_keeps_its_trades(self):
        import os
        path = os.path.join(self.tmp, "old.db")
        db = sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE trades(id INTEGER PRIMARY KEY, signal_id INTEGER, date TEXT NOT NULL, symbol TEXT NOT NULL,
              qty INTEGER NOT NULL, entry_price REAL NOT NULL, entry_at TEXT NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
              flat_by TEXT, status TEXT NOT NULL, exit_price REAL, exit_at TEXT, exit_reason TEXT, pnl REAL, r_multiple REAL, note TEXT);
            INSERT INTO trades(date,symbol,qty,entry_price,entry_at,stop,target,status)
              VALUES('2026-10-16','F',3,12.0,'2026-10-16 10:00',11.7,12.6,'open');""")
        db.commit()
        db.close()
        for _ in range(2):                                     # running the migration twice changes nothing
            j = Journal(path)
            t = j.open_trades()[0]
            self.assertEqual((t["symbol"], t["side"], t["qty"]), ("F", "long", 3))
            j.close()

    def test_the_migration_does_not_mind_columns_another_branch_added(self):
        import os
        path = os.path.join(self.tmp, "other.db")
        j = Journal(path)
        j._db.execute("ALTER TABLE trades ADD COLUMN something_else TEXT DEFAULT 'x'")
        j.close()
        j = Journal(path)
        self.addCleanup(j.close)
        j.seed(1000, NOW)
        tid = j.open_trade("AAL", 1, 12.00, 12.30, 11.40, NOW, side="short")
        self.assertEqual(j.trade(tid)["something_else"], "x")


class DeskShorts(DeskCase):
    def desk(self, now=NOW, **settings):
        S.save(settings)
        j = Journal()
        self.addCleanup(j.close)
        return Desk(j, Demo(now))

    def test_the_default_desk_makes_no_short_signals(self):
        d = self.desk()
        s = d.scan()
        rows = d.j.decisions("2026-10-19")
        self.assertTrue(rows)
        self.assertTrue(all(r["short"] == "switched off in Settings" for r in rows))
        self.assertTrue(any(r["decision"] == "long" for r in rows))
        self.assertEqual((s["directions"], s["short_hits"], s["short_new"]), ("long", 0, 0))
        self.assertFalse([g for g in d.j.signals() if g["setup"] == shorts.SETUP])
        self.assertFalse(d.state()["shorts"]["on"])

    def test_short_only_scan_take_and_cover(self):
        d = self.desk(directions="short")
        s = d.scan()
        self.assertGreater(s["short_hits"], 0)
        self.assertGreater(s["short_new"], 0)
        self.assertEqual(s["hits"], 0)                          # the long scanner did not run
        ready = [g for g in d.j.signals(statuses=("ready",))]
        self.assertTrue(ready)
        for g in ready:
            p = g["payload"]
            self.assertEqual((g["setup"], p["side"], p["paper_only"]), ("orb_short", "short", True))
            self.assertTrue(p["target"] < p["limit"] <= p["entry"] < p["stop"])
            self.assertLessEqual(p["max_loss"], 8.0)            # 2 % of $400
            self.assertLessEqual(p["cost"], 380.0)
            self.assertEqual(p["risk"]["verdict"], "PASS")
            self.assertIn("PRACTICE ONLY", p["ticket"]["steps"][0])
            self.assertTrue(p["valid_until"] > p["trigger_close_time"])
        state = d.state()
        self.assertTrue(state["shorts"]["on"] and state["shorts"]["paper_only"])
        self.assertIn("SHORT (practice only)", " ".join(e["message"] for e in state["events"]))

        g = ready[0]
        p = g["payload"]
        with self.assertRaises(DeskError):
            d.take(g["id"], p["qty"], p["stop"])                # a fill at the stop is not a fill
        with self.assertRaises(DeskError):
            d.take(g["id"], p["qty"] + 1, p["limit"])
        tid = d.take(g["id"], p["qty"], "$%.2f" % p["limit"])
        t = d.j.trade(tid)
        self.assertEqual((t["side"], t["note"], t["stop"], t["target"]), ("short", "practice short", p["stop"], p["target"]))
        d.monitor()
        ot = d.state()["open_trades"][0]
        self.assertEqual(ot["max_loss"], round((p["stop"] - p["limit"]) * p["qty"], 2))
        self.assertGreater(ot["reward"], 0)
        rules = (pipeline.workdir(p["date"], p["symbol"], "short") / "trader" / "alerts.json").read_text()
        self.assertIn("-short-stop", rules)
        self.assertIn("-short-target", rules)
        pnl = d.exit(tid, p["target"], "target")
        self.assertEqual(pnl, round((p["limit"] - p["target"]) * p["qty"], 2))
        self.assertIn("bought to cover", d.state()["events"][0]["message"])
        self.assertEqual(d.j.equity(), round(400 + pnl, 2))
        rows = d.j.decisions("2026-10-19")
        self.assertTrue(rows)
        self.assertTrue(any(r["decision"] == "short" for r in rows))
        self.assertTrue(all(r["long"] == "switched off in Settings" for r in rows))    # directions = short
        text = d.review()["text"]
        self.assertIn("SCAN DECISIONS", text)
        self.assertIn("Short: 1 closed", text)

    def test_switching_shorts_off_turns_a_waiting_short_off(self):
        d = self.desk(directions="short")
        d.scan()
        g = d.j.signals(statuses=("ready",))[0]
        S.update({"directions": "long"})
        with self.assertRaises(DeskError):
            d.take(g["id"], 1, g["payload"]["limit"])
        off = [x for x in d.state()["signals"] if x["id"] == g["id"]][0]["off"]
        self.assertIn("switched off", off)

    def test_a_qualifying_account_is_not_paper_only(self):
        d = self.desk(directions="short", account_type="margin", short_approved=True, starting_balance=5000)
        d.scan()
        ready = d.j.signals(statuses=("ready",))
        self.assertTrue(ready)
        self.assertFalse(ready[0]["payload"]["paper_only"])
        self.assertNotIn("PRACTICE ONLY", " ".join(ready[0]["payload"]["ticket"]["steps"]))

    def tsla(self, *after):
        return {"symbol": "TSLA", "prev_close": 362.0, "bars": [
            bar("09:30", 364, 366.0, 363.0, 365.0), bar("09:35", 365, 365.5, 362.0, 363.0), bar("09:40", 363, 364.0, 362.5, 363.5),
            bar("09:45", 363.5, 364.0, 362.4, 362.9), bar("09:50", 362.9, 363.4, 362.2, 362.6),
            bar("09:55", 362.6, 363.0, 362.1, 362.4), bar("10:00", 362.4, 362.8, 362.05, 362.3),
            bar("10:05", 362.3, 362.6, 362.0, 362.2)] + list(after)}

    def test_odds_come_from_the_time_machine_run_as_a_sell(self):
        d = self.desk(min_edge_points=-100, starting_balance=2000)
        chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual(status, "ready", sig)
        self.assertEqual((sig["entry"], sig["stop"], sig["target"], sig["limit"]), (361.5, 364.0, 356.5, 361.0))
        o = sig["odds"]
        self.assertEqual((o["replays"], o["sessions"]), (10000, 59))
        self.assertAlmostEqual(o["p_target"] + o["p_stop"] + o["p_neither"], 1.0, places=3)
        self.assertGreater(o["history"]["triggered"], 0)

    def test_a_ten_percent_drop_shorts_above_the_bid_in_paper_and_blocks_in_live(self):
        # SEC Rule 201 lets a short fill above the national best bid (docs/IMPROVE-2026-11-20.md, T2)
        for mode in ("paper", "live"):
            d = self.desk(starting_balance=2000, mode=mode)
            chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
            chart["prev_close"] = 402.0                         # today's low 361.2 is more than 10 % under it
            status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
            self.assertEqual(sig["ssr"], "today")
            if mode == "paper":
                self.assertNotEqual(status, "blocked", sig["problems"])
                self.assertEqual(sig["limit"], 361.51)          # a cent over the trigger close, not 0.2R under it
                self.assertFalse([p for p in sig["problems"] if "restriction" in p])
                self.assertIn("bounces back up", " ".join(sig["warnings"]))
                self.assertEqual(sig["max_loss"], round(sig["qty"] * (sig["stop"] - 361.51), 2))
            else:
                self.assertEqual(status, "blocked")
                self.assertIn("Short-sale restriction", sig["problems"][0])

    def test_a_short_the_days_risk_cut_leaves_at_zero_shares_gets_one_share_in_paper(self):
        # T3: one share risks $3.00 at the limit; the cut allows $2.40 (0.12 % of $2,000), your own 0.2 % allows $4.00
        d = self.desk(starting_balance=2000, risk_per_trade_pct=0.12, min_edge_points=-100)
        chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual(sig["qty"], 0)                           # no plan settings today: the cut stands
        d.j.put("plan_settings", {"date": "2026-10-19", "base": {"risk_per_trade_pct": 0.2}})
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual((sig["qty"], sig["max_loss"]), (1, 3.0))
        self.assertIn("One share", " ".join(sig["warnings"]))
        S.update({"mode": "live"})                                # live mode keeps your own settings: no floor
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual(sig["qty"], 0)

    def test_no_breakdown_is_not_a_signal_and_an_old_one_is_missed(self):
        d = self.desk(starting_balance=2000)
        status, why = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=self.tsla())
        self.assertIsNone(status)
        self.assertIn("waiting", why)
        d = self.desk(now="2026-10-19 10:40", starting_balance=2000)
        chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
        self.assertEqual(pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)[0], "missed")

    def test_live_shorts_need_the_trend_check(self):
        d = self.desk(starting_balance=2000)
        d.src.demo = False                                      # live rules, but nothing below touches the network
        self.addCleanup(setattr, d.src, "demo", True)
        chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
        real = charts.daily_bars
        self.addCleanup(setattr, charts, "daily_bars", real)
        for closes, want in (([300.0] * 250, "uptrend"), ([300.0] * 50, "cannot check the trend")):
            charts.daily_bars = lambda source, symbol, closes=closes: days(closes)
            status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
            self.assertEqual(status, "blocked")
            self.assertIn(want, " ".join(sig["problems"]))
        charts.daily_bars = lambda source, symbol: days([400.0] * 250)
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual(sig["trend"], {"direction": "down", "average": 400.0, "days": 200})
        self.assertNotIn("trend", " ".join(sig["problems"]))
        self.assertNotIn("restriction", " ".join(sig["problems"]))

    def test_a_10pct_drop_yesterday_keeps_the_short_sale_restriction_on_today(self):
        # SEC Rule 201: the price test lasts the rest of the day it triggers AND the next day.
        d = self.desk(starting_balance=2000)
        d.src.demo = False
        self.addCleanup(setattr, d.src, "demo", True)
        chart = self.tsla(bar("10:10", 362.2, 362.3, 361.2, 361.5))
        real = charts.daily_bars
        self.addCleanup(setattr, charts, "daily_bars", real)
        hist = days([400.0] * 249)
        hist[-1]["l"] = 355.0                                    # yesterday: down 11% intraday from 400
        charts.daily_bars = lambda source, symbol: hist
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual((sig["ssr"], sig["limit"]), ("yesterday", 361.51))   # paper: the above-bid limit
        self.assertIn("runs through today", " ".join(sig["warnings"]))
        S.update({"mode": "live"})
        status, sig = pipeline.evaluate_short("TSLA", S.load(), d.j, d.src, chart=chart)
        self.assertEqual(status, "blocked")
        self.assertIn("runs through today", " ".join(sig["problems"]))


def days(closes):
    """Daily bars before 2026-10-19 (the demo day) with these closes."""
    import datetime
    start = datetime.date(2026, 10, 18) - datetime.timedelta(days=len(closes))
    return [{"date": (start + datetime.timedelta(days=i)).isoformat(), "o": c, "h": c, "l": c, "c": c}
            for i, c in enumerate(closes)]


if __name__ == "__main__":
    unittest.main()

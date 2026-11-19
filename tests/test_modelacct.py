"""The two model accounts (desk/modelacct.py): sweep interest, pay dates, T+1 and good-faith checks, the journal,
the migration from the old single-file books, the Graph tab and the reserved account names."""
import argparse
import json
from pathlib import Path

from desk import __main__ as main
from desk import combo, graph as G, modelacct, winter3x
from desk.engine import Desk
from desk.journal import Journal
from desk.source import Demo
from tests.base import DeskCase


def day(d, target, price=100.0):
    return {"date": d, "target": target, "fills": {"SPY": price}, "fill_at": d + " 09:36", "how": "live"}


class Ledger(DeskCase):
    def test_idle_cash_earns_the_sweep_rate_from_the_second_day(self):
        days = [day("2026-11-16", {}), day("2026-11-17", {}), day("2026-11-18", {})]
        a = modelacct.replay(days, {}, {}, 400.0, {"SPY": 3.0}, sweep_apy=2.52)
        one = 400 * 2.52 / 100 / 252
        self.assertAlmostEqual(a["interest"], 2 * one, 2)    # accrued in the month, paid into cash when it ends
        self.assertEqual(a["cash"], 400.0)
        self.assertEqual(a["interest_owed"], round(2 * one, 2))
        a = modelacct.replay(days + [day("2026-12-01", {})], {}, {}, 400.0, {}, sweep_apy=2.52)
        self.assertAlmostEqual(a["cash"], 400 + 2 * one, 2)          # November's two days, paid Dec 1
        self.assertEqual(a["ledger"][-1]["kind"], "interest")
        self.assertEqual(modelacct.SWEEP_APY, 0.01)       # a broker's bank sweep, not the T-bill rate

    def test_spy_pays_on_the_last_trading_day_of_the_next_month(self):
        self.assertEqual(modelacct.pay_date("SPY", "2026-03-20"), "2026-04-30")
        self.assertEqual(modelacct.pay_date("SPY", "2025-12-19"), "2026-01-30")
        self.assertEqual(modelacct.pay_date("SPY", "2026-09-18"), "2026-10-30")
        self.assertEqual(modelacct.pay_date("UPRO", "2026-12-23"), "2026-12-30")

    def test_selling_a_purchase_before_its_money_settles_is_a_good_faith_violation(self):
        # Fri May 1 sells and buys with the unsettled money (allowed); selling that buy on a day before Mon May 4
        # (a made-up Saturday here, which the rules never trade on) is the violation the account counts.
        days = [day("2026-04-30", {"SPY": 1.0}), day("2026-05-01", {"SPY": 0.5}),
                {"date": "2026-05-01", "target": {"SPY": 1.0}, "fills": {"SPY": 100.0}, "fill_at": "2026-05-01 10:00"},
                {"date": "2026-05-02", "target": {}, "fills": {"SPY": 100.0}, "fill_at": "2026-05-02 10:00"}]
        a = modelacct.replay(days, {}, {}, 400.0, {})
        self.assertEqual(a["good_faith_violations"], [{"date": "2026-05-02", "symbol": "SPY", "until": "2026-05-04"}])

    def test_orders_under_a_dollar_are_skipped(self):
        a = modelacct.replay([day("2026-11-16", {"SPY": 0.001})], {}, {}, 400.0, {})
        self.assertEqual(a["orders"], [])

    def test_buy_and_hold_spy_gets_its_dividend_on_the_pay_date(self):
        days = [day("2026-03-19", {}), day("2026-03-20", {}), day("2026-04-30", {})]
        a = modelacct.replay(days, {"SPY": {d["date"]: 100.0 for d in days}}, {"SPY": {"2026-03-20": 1.0}}, 400.0,
                             {"SPY": 0.0}, sweep_apy=0)
        self.assertAlmostEqual(a["spy"], 404.0, 2)          # 4 shares, $4 of dividends reinvested on Apr 30
        self.assertEqual(a["equity"], 400.0)                # the model sat in cash


class Account(DeskCase):
    def rows(self):
        from tests.test_combo import hand_rows
        return hand_rows()

    def test_a_run_writes_the_accounts_own_journal(self):
        rows = self.rows()
        combo.run("2026-04-29 09:40", data=(rows[:201], {}, (101.0, "2026-04-29 09:40")))
        combo.run("2026-05-05 09:40", data=(rows, {}, (95.0, "2026-05-05 09:40")))
        f = Path(self.tmp) / "accounts" / "combo" / "journal.db"
        self.assertTrue(f.exists())
        j = Journal(f)
        self.assertAlmostEqual(j.cash(), combo.load()["account"]["cash"], delta=0.05)   # rows are rounded to cents
        trades = modelacct.journal_trades("combo")
        self.assertTrue(trades and all(t["note"] == "model: combo" for t in trades))
        self.assertFalse((Path(self.tmp) / "journal.db").exists() and Journal().trades())   # main journal untouched

    def test_the_old_books_move_into_their_own_accounts_once(self):
        old = {"start_equity": 10000.0, "days": [{"date": "2026-11-19", "votes": {"dip": 1, "halloween": 1, "turn": 1},
                                                  "weight": 1.0, "fill": 719.447, "fill_at": "2026-11-19 13:51",
                                                  "how": "live"}],
               "totals": {"equity": 9997.0}, "checked": "2026-11-19 13:51"}
        (Path(self.tmp) / "combo.json").write_text(json.dumps(old))
        r = modelacct.migrate("combo")
        self.assertEqual(r, {"account": "combo", "days": 1, "start_equity": 400.0})
        self.assertIsNone(modelacct.migrate("combo"))       # twice is harmless
        self.assertTrue((Path(self.tmp) / "combo.json.migrated").exists())
        s = combo.load()
        self.assertEqual((s["days"], s["start_equity"]), (old["days"], 400.0))
        self.assertNotIn("totals", s)
        self.assertEqual(s["migrated_from"]["start_equity"], 10000.0)
        self.assertIsNone(modelacct.migrate("winter3x"))    # nothing to move

    def test_the_command_line_migration(self):
        (Path(self.tmp) / "winter3x.json").write_text(json.dumps({"days": [], "start_equity": 10000.0}))
        self.assertEqual(main.main(["migrate-models"]), 0)
        self.assertTrue(modelacct.path("winter3x").exists())

    def test_the_graph_shows_each_model_account_as_made_or_lost_each_day(self):
        rows = self.rows()
        winter3x.run("2026-04-29 09:40", data={"SPY": (rows[:201], {}, (101.0, "2026-04-29 09:40")),
                                               "UPRO": (rows[:201], {}, (101.0, "2026-04-29 09:40"))})
        got = {a["name"]: a for a in Desk(Journal(), Demo()).graph()["accounts"]}
        self.assertEqual(set(got), {"main", "winter3x"})
        w = got["winter3x"]
        self.assertTrue(w["model"])
        a = winter3x.load()["account"]
        self.assertEqual([p["total"] for p in w["points"]], [round(c["equity"] - 400.0, 2) for c in a["curve"]])

    def test_the_model_account_names_are_reserved(self):
        for name in ("combo", "winter3x"):
            self.assertIn("model accounts", main.open_account(argparse.Namespace(account=name, tickers=None, demo=False)))

    def test_neither_model_has_a_path_to_an_order(self):
        for mod in (modelacct, combo, winter3x):
            src = Path(mod.__file__).read_text()
            for word in ("orders", "paper", "trading", "auto"):
                self.assertNotIn("import " + word, src)
                self.assertNotIn("from ." + word, src)

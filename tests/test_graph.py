"""The Graph tab (desk/graph.py) and extra paper accounts (python3 -m desk --account NAME)."""
import argparse
import os
from pathlib import Path

from desk import __main__ as main
from desk import graph as G
from desk import paths
from desk import settings as S
from desk.engine import Desk, DeskError
from desk.journal import Journal
from desk.source import Demo
from tests.base import DeskCase


def close(j, symbol, pnl, at, note=None):
    with j._tx() as db:
        db.execute("INSERT INTO trades(date,symbol,qty,entry_price,entry_at,stop,target,status,exit_price,exit_at,pnl,note) "
                   "VALUES(?,?,1,10,?,9,12,'closed',11,?,?,?)", (at[:10], symbol, at, at, pnl, note))


class Graph(DeskCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, "DESK_ACCOUNT", None)

    def test_curve_splits_the_bot_from_you(self):
        c = G.curve([{"symbol": "A", "exit_at": "2026-11-17 10:00", "pnl": 5, "note": "auto"},
                     {"symbol": "B", "exit_at": "2026-11-17 11:00", "pnl": -2, "note": None},
                     {"symbol": "C", "exit_at": "2026-11-18 10:00", "pnl": 3, "note": "auto"}])
        self.assertEqual((c["total"], c["bot"], c["you"], c["wins"]), (6, 8, -2, 2))
        self.assertEqual([p["total"] for p in c["points"]], [5, 3, 6])
        self.assertEqual(c["days"], [{"date": "2026-11-17", "pnl": 3, "trades": 2}, {"date": "2026-11-18", "pnl": 3, "trades": 1}])

    def test_summary_reads_every_paper_account(self):
        j = Journal()
        close(j, "A", 4, "2026-11-18 10:00", "auto")
        other = Path(self.tmp) / "accounts" / "growth"
        other.mkdir(parents=True)
        close(Journal(other / "journal.db"), "B", -1, "2026-11-18 10:05")
        got = {a["name"]: a for a in Desk(j, Demo()).graph()["accounts"]}
        self.assertEqual(set(got), {"main", "growth"})
        self.assertTrue(got["main"]["current"])
        self.assertEqual((got["main"]["bot"], got["growth"]["you"]), (4, -1))

    def test_an_account_is_made_as_paper_with_its_own_tickers(self):
        S.save(dict(S.load(), starting_balance=1000))
        a = argparse.Namespace(account="growth", tickers="tsla, nvda", demo=False)
        self.assertIsNone(main.open_account(a))
        self.assertEqual(paths.account_name(), "growth")
        st = S.load()
        self.assertEqual((st["mode"], st["watchlist"], st["auto_list"], st["starting_balance"]),
                         ("paper", ["TSLA", "NVDA"], "off", 1000))
        self.assertEqual(paths.home_dir(), Path(self.tmp))
        # its own hourly Claude look would double the Claude use and the game-plan pushes to the same phone
        self.assertEqual((st["analyst"], st["catalyst_alerts"]), (False, False))
        with self.assertRaises(DeskError):
            Desk(Journal(), Demo()).set_mode("live", "LIVE")

    def test_an_existing_account_keeps_its_own_choice(self):
        a = argparse.Namespace(account="growth", tickers=None, demo=False)
        self.assertIsNone(main.open_account(a))
        S.update({"analyst": True})
        os.environ["DESK_DATA"] = self.tmp                       # a second run starts from the main desk again
        self.assertIsNone(main.open_account(argparse.Namespace(account="growth", tickers="amd", demo=False)))
        self.assertTrue(S.load()["analyst"])

    def test_bad_account_names_are_refused(self):
        for name in ("Main", "main", "../x", ""):
            self.assertTrue(main.open_account(argparse.Namespace(account=name, tickers=None, demo=False)))
        self.assertTrue(main.open_account(argparse.Namespace(account="x", tickers=None, demo=True)))

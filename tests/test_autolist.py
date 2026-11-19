from unittest import mock

from desk import autolist
from desk import review as R
from desk import settings as S
from desk.charts import ChartError
from desk.engine import Desk
from desk.journal import Journal
from desk import mode as M
from tests.base import DeskCase

REAL_PICK = autolist.pick      # tests/base.py stubs it for every other test


def daily(rng_pct, price=20.0, vol=20e6, days=20):
    """Daily bars with a fixed high-low range of rng_pct % and vol shares a day, ending 2026-10-20."""
    h = price * rng_pct / 200
    return {"bars": [{"date": "2026-10-%02d" % (d + 1), "h": price + h, "l": price - h, "c": price, "v": vol}
                     for d in range(days)]}


class Rate(DeskCase):
    def test_keeps_volatile_liquid_names_with_a_reason(self):
        row, why = autolist.rate("ABC", daily(8)["bars"], "2026-10-21", 5)
        self.assertIsNone(why)
        self.assertEqual((row["atr_pct"], row["price"], row["dollar_vol_m"]), (8.0, 20.0, 400))
        self.assertIn("moves 8.0% a day", row["why"])

    def test_leaves_out_calm_thin_cheap_and_new(self):
        self.assertEqual(autolist.rate("A", daily(1.5)["bars"], "2026-10-21", 5)[1], "moves under 3% a day")
        self.assertIn("traded a day", autolist.rate("A", daily(8, vol=1e5)["bars"], "2026-10-21", 5)[1])
        self.assertEqual(autolist.rate("A", daily(8, price=3)["bars"], "2026-10-21", 5)[1], "under your lowest share price")
        self.assertEqual(autolist.rate("A", daily(8, days=5)["bars"], "2026-10-21", 5)[1], "under 15 days of history")

    def test_today_is_never_used(self):
        bars = daily(8)["bars"] + [{"date": "2026-10-21", "h": 99, "l": 1, "c": 20, "v": 1}]
        self.assertEqual(autolist.rate("A", bars, "2026-10-21", 5)[0]["atr_pct"], 8.0)


def no_screen(name):
    return []


class Pick(DeskCase):
    def fetch(self, ranges):
        def f(sym, rng, iv):
            if sym not in ranges:
                raise ChartError("none")
            return daily(ranges[sym])
        return f

    def test_ranks_by_atr_caps_and_skips_blocked(self):
        ranges = {s: 4 + i * 0.1 for i, s in enumerate(autolist.POOL)}
        st = S.validate({"blocked": [autolist.POOL[-1]]})
        out = REAL_PICK(st, "2026-10-21 08:00", self.fetch(ranges), pause=0, screen=no_screen)
        syms = [r["symbol"] for r in out["symbols"]]
        self.assertEqual(len(syms), 40)                                    # auto_watchlist_movers
        self.assertNotIn(autolist.POOL[-1], syms)
        self.assertEqual(syms[0], autolist.POOL[-2])
        self.assertIsNone(out["error"])

    def test_too_few_falls_back_to_watchlist(self):
        st = S.validate({"mode": "paper", "watchlist": ["F", "T"]})
        out = REAL_PICK(st, "2026-10-21 08:00", self.fetch({"MARA": 9}), pause=0, screen=no_screen)
        self.assertIn("scans your watchlist", out["error"])
        self.assertEqual(autolist.symbols(st, out, "2026-10-21"), ["F", "T"])

    def test_always_scan_tickers_come_first_and_screeners_add_names(self):
        st = S.validate({"core_watchlist": ["KO", "ZZZZ"], "auto_watchlist_movers": 3})
        ranges = {"KO": 1.0, "MARA": 9, "RIOT": 8, "NEWCO": 12, "IREN": 7, "CALMCO": 1}

        def screen(name):
            if name == "day_losers":
                raise ChartError("down")
            return [{"symbol": "NEWCO", "quoteType": "EQUITY"}, {"symbol": "SPY", "quoteType": "ETF"},
                    {"symbol": "BAD.X", "quoteType": "EQUITY"}, {"symbol": "CALMCO", "quoteType": "EQUITY"}]
        out = REAL_PICK(st, "2026-10-21 08:00", self.fetch(ranges), pause=0, screen=screen)
        self.assertEqual([r["symbol"] for r in out["symbols"]], ["KO", "ZZZZ", "NEWCO", "MARA", "RIOT"])
        self.assertIn("always-scan", out["symbols"][0]["why"])          # calm, still on: yours
        self.assertIsNone(out["symbols"][1]["atr_pct"])                  # no data, still on
        self.assertIn("on Yahoo's most actives and day gainers today", out["symbols"][2]["why"])
        self.assertEqual(len(out["errors"]), 1)                          # one screener down, the others used
        self.assertEqual(out["by"], "formula")

    def test_agent_picks_or_the_formula_stands(self):
        ranges = {s: 4 + i * 0.1 for i, s in enumerate(autolist.POOL)}
        st = S.validate({"watchlist_agent": True, "auto_watchlist_movers": 6})
        top = sorted(ranges, key=lambda s: -ranges[s])
        ask = lambda text: {"summary": "Busy day.", "picks": [{"symbol": s, "why": "news"} for s in top[3:9]] + [{"symbol": "EVIL", "why": "x"}]}
        news = lambda syms, st, wd: {}
        run = lambda ask: REAL_PICK(st, "2026-10-21 08:00", self.fetch(ranges), pause=0, screen=no_screen, wd=self.tmp, ask=ask, news=news)
        out = run(ask)
        self.assertEqual((out["by"], out["summary"]), ("claude", "Busy day."))
        self.assertEqual([r["symbol"] for r in out["symbols"]], top[3:9])
        self.assertTrue(out["symbols"][0]["why"].startswith("Claude: news."))

        def broken(text):
            raise RuntimeError("not signed in")
        out = run(broken)
        self.assertEqual((out["by"], [r["symbol"] for r in out["symbols"]]), ("formula", top[:6]))
        self.assertIn("not signed in", out["errors"][-1])
        few = run(lambda text: {"summary": "", "picks": [{"symbol": top[0], "why": "x"}]})
        self.assertEqual(few["by"], "formula")                            # one pick is too few to scan

    def test_which_list_is_used(self):
        good = {"date": "2026-10-21", "error": None, "symbols": [{"symbol": "MARA"}]}
        paper, live = S.validate({"mode": "paper", "watchlist": ["F"]}), S.validate({"mode": "live", "watchlist": ["F"]})
        self.assertEqual(autolist.symbols(paper, good, "2026-10-21"), ["MARA"])
        self.assertEqual(autolist.symbols(live, good, "2026-10-21"), ["F"])              # default "paper": live keeps yours
        self.assertEqual(autolist.symbols(dict(live, auto_list="on"), good, "2026-10-21"), ["MARA"])
        self.assertEqual(autolist.symbols(dict(paper, auto_list="off"), good, "2026-10-21"), ["F"])
        self.assertEqual(autolist.symbols(paper, good, "2026-10-22"), ["F"])             # yesterday's list is not used
        with self.assertRaises(S.SettingsError):
            S.validate({"auto_list": "sometimes"})


class Src:
    demo = False

    def now(self):
        return "2026-10-21 08:01"

    def now_args(self):
        return []


class DeskWiring(DeskCase):
    def test_pick_list_logs_and_the_scans_use_it(self):
        d = Desk(Journal(M.journal_path("paper")), Src())
        out = {"date": "2026-10-21", "at": "2026-10-21 08:01", "error": None, "looked_at": 90, "left_out": {},
               "symbols": [{"symbol": "MARA", "atr_pct": 8.6, "price": 7.2, "dollar_vol_m": 277, "why": "moves"}] * 5}
        with mock.patch.object(autolist, "pick", return_value=out):
            d.pick_list(S.load(), "2026-10-21 08:01")
        self.assertEqual(d.scan_symbols(S.load(), "2026-10-21 10:00"), ["MARA"] * 5)
        self.assertEqual(d.j.get("scan_lists")["2026-10-21"]["symbols"], ["MARA"] * 5)
        self.assertIn("Today's scan list: 5 stocks", d.j.events(limit=5)[0]["message"])
        st = d.state()["scan_list"]
        self.assertEqual((st["on"], st["using"]), (True, "picked"))

    def test_review_section(self):
        lists = {"2026-10-21": {"symbols": ["MARA", "RIOT"], "error": None}}
        sigs = [{"id": 1, "date": "2026-10-21", "symbol": "MARA", "status": "ready"},
                {"id": 2, "date": "2026-10-21", "symbol": "KO", "status": "ready"}]
        rows = R.scan_lists(lists, sigs, [{"signal_id": 1, "result": "target", "r": 2.0}])
        self.assertEqual(rows[0], {"date": "2026-10-21", "stocks": 2, "error": None, "signals": 1, "ready": 1,
                                   "replayed": 1, "avg_r": 2.0, "top": ["MARA", "RIOT"], "catalyst": []})

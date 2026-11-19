import math
"""The winter 3x paper book (desk/winter3x.py): the rule, the book's arithmetic, the daily run, the card's view."""
import json
import threading
import urllib.request
from pathlib import Path

from desk import combo, winter3x
from desk.server import serve
from unittest import mock

from tests.base import DeskCase
from tests.test_combo import hand_rows
from tests.test_desk import DemoCase


def data(rows, live_day=None):
    """SPY rows as given; UPRO moves 3x SPY's close-to-close, from $50. Live price = the day's close."""
    up, prev = [], None
    for r in rows:
        u = 50.0 if prev is None else up[-1]["c"] * (1 + 3 * (r["c"] / prev - 1))
        up.append({"date": r["date"], "o": round(u * 0.99, 4), "c": round(u, 4), "adj": u})
        prev = r["c"]
    live = lambda rs: (rs[-1]["c"], rs[-1]["date"] + " 09:40") if live_day else None
    return {"SPY": (rows, {}, live(rows)), "UPRO": (up, {}, live(up))}


class Rule(DeskCase):
    def test_holds_upro_in_winter_spy_in_summer_cash_below_the_average(self):
        self.assertEqual(winter3x.hold_for({"bull": True}, "2026-11-20"), "UPRO")
        self.assertEqual(winter3x.hold_for({"bull": True}, "2026-04-30"), "UPRO")
        self.assertEqual(winter3x.hold_for({"bull": True}, "2026-05-01"), "SPY")
        self.assertEqual(winter3x.hold_for({"bull": True}, "2026-10-30"), "SPY")
        self.assertEqual(winter3x.hold_for({"bull": False}, "2026-01-05"), "cash")
        self.assertEqual(winter3x.hold_for({"bull": False}, "2026-07-01"), "cash")

    def test_it_has_no_path_to_an_order(self):
        src = Path(winter3x.__file__).read_text()
        for word in ("orders", "paper.", "trading"):
            self.assertNotIn("import " + word, src)
            self.assertNotIn("from ." + word, src)


class Book(DeskCase):
    def test_a_switch_sells_first_and_buys_with_the_unsettled_money(self):
        days = [{"date": "2026-04-29", "hold": "UPRO", "fills": {"SPY": 100.0, "UPRO": 50.0}, "fill_at": "2026-04-29 09:36"},
                {"date": "2026-04-30", "hold": "UPRO", "fills": {"SPY": 101.0, "UPRO": 51.5}, "fill_at": "2026-04-30 09:36"},
                {"date": "2026-05-01", "hold": "SPY", "fills": {"SPY": 102.0, "UPRO": 53.0}, "fill_at": "2026-05-01 09:36"},
                {"date": "2026-05-04", "hold": "cash", "fills": {"SPY": 102.0, "UPRO": 53.0}, "fill_at": "2026-05-04 09:36"}]
        prices = {"SPY": {"2026-04-29": 101.0, "2026-04-30": 102.0, "2026-05-01": 102.0, "2026-05-04": 103.0},
                  "UPRO": {"2026-04-29": 51.5, "2026-04-30": 53.0, "2026-05-01": 53.0, "2026-05-04": 54.5}}
        a = winter3x.book(days, prices, {"SPY": {}, "UPRO": {}}, 400.0)
        self.assertEqual([(o["date"], o["side"], o["symbol"]) for o in a["orders"]],
                         [("2026-04-29", "buy", "UPRO"), ("2026-05-01", "sell", "UPRO"), ("2026-05-01", "buy", "SPY"),
                          ("2026-05-04", "sell", "SPY")])
        self.assertEqual(a["good_faith_violations"], [])           # the SPY bought May 1 is sold May 4, after settling
        self.assertEqual(a["holding"], "cash")
        self.assertEqual(a["unsettled"], [{"amount": a["cash"], "until": "2026-05-05"}])   # T+1
        self.assertEqual(len(a["trades"]), 2)                       # two round trips in the journal
        self.assertGreater(a["trades"][0]["pnl"], 0)

    def test_dividends_are_owed_then_reinvested_on_their_pay_date(self):
        days = [{"date": d, "hold": "SPY", "fills": {"SPY": 100.0, "UPRO": 50.0}, "fill_at": d + " 09:36"}
                for d in ("2026-03-19", "2026-03-20", "2026-04-29", "2026-04-30")]
        prices = {"SPY": {d["date"]: 100.0 for d in days}, "UPRO": {}}
        a = winter3x.book(days[:2], prices, {"SPY": {"2026-03-20": 1.0}, "UPRO": {}}, 400.0)
        sh = a["positions"][0]["qty"]
        self.assertEqual(a["owed"], [{"symbol": "SPY", "amount": round(sh * 1.0, 2), "pay": "2026-04-30"}])
        a = winter3x.book(days, prices, {"SPY": {"2026-03-20": 1.0}, "UPRO": {}}, 400.0)
        self.assertEqual(a["owed"], [])
        self.assertAlmostEqual(a["positions"][0]["qty"], sh + math.floor(sh * 1.0 / 100 * 1e5) / 1e5, 5)
        self.assertAlmostEqual(a["dividends"], sh, 2)


class Run(DeskCase):
    def test_starts_today_then_backfills_missed_days(self):
        rows = hand_rows()                                  # flat to Apr 28, 101 on Apr 29, then below the average
        s = winter3x.run("2026-04-29 09:40", data=data(rows[:201], live_day=True))
        self.assertEqual([d["date"] for d in s["days"]], ["2026-04-29"])
        self.assertEqual(s["days"][0]["hold"], "cash")      # Apr 28 closed at its average: not above
        self.assertEqual(s["days"][0]["how"], "live")
        s = winter3x.run("2026-05-05 09:40", data=data(rows, live_day=True))
        self.assertEqual([(d["date"], d["hold"], d["how"]) for d in s["days"]],
                         [("2026-04-29", "cash", "live"), ("2026-04-30", "UPRO", "backfill"),
                          ("2026-05-01", "cash", "backfill"), ("2026-05-04", "cash", "backfill"),
                          ("2026-05-05", "cash", "live")])
        self.assertEqual(s["next"]["date"], "2026-05-05")      # from the May 4 close (today has not closed)
        self.assertEqual(s["next"]["hold"], "cash")
        self.assertLess(s["account"]["equity"], 400)       # bought UPRO before a 3x drop of 10.9 %

    def test_waits_for_a_price_from_today(self):
        rows = hand_rows()
        s = winter3x.run("2026-04-29 09:40", data=data(rows[:201]))
        self.assertFalse(s["days"])


class View(DemoCase):
    def test_card_compares_with_the_old_model_and_spy(self):
        v = winter3x.view()
        self.assertFalse(v["started"])
        self.assertTrue(v["paper_only"])
        self.assertEqual(v["test"]["spy"], 13.8)
        rows = hand_rows()
        combo.run("2026-04-29 09:40", data=(rows[:201], {}, (101.0, "2026-04-29 09:40")))
        winter3x.run("2026-04-29 09:40", data=data(rows[:201], live_day=True))
        v = winter3x.view()
        self.assertTrue(v["started"])
        self.assertEqual(v["combo"]["since"], "2026-04-29")
        text = "\n".join(winter3x.lines(v))
        self.assertIn("combined book", text)
        self.assertIn("buy-and-hold SPY", text)
        self.assertIn("p = 0.47", text)
        self.assertIn("never places an order", text)

    def test_api_and_review(self):
        srv = serve(mock.Mock(), None, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with urllib.request.urlopen("http://127.0.0.1:%d/api/winter3x" % srv.server_address[1], timeout=10) as r:
            body = json.loads(r.read())
        self.assertFalse(body["started"])
        self.assertIn("MODEL 3: WINTER 3X", self.desk().review()["text"])

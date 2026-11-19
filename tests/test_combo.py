"""The combined SPY paper book (desk/combo.py): the votes, the calendar, the book's arithmetic, the daily run."""
import datetime
import json
import threading
import urllib.request
from unittest import mock

from desk import combo
from desk.scheduler import Scheduler
from desk.server import serve
from tests.base import DeskCase


def trading_days(last, n):
    """The n NYSE trading days ending on `last`, oldest first."""
    out, d = [], last
    while len(out) < n:
        if combo.is_open(d):
            out.append(d)
        d = (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()
    return out[::-1]


def hand_rows():
    """200 closes at $100 up to 2026-04-28, then 101, 90, 85, 95, 95 (Apr 29 to May 5). Opens are close - 1."""
    dates = trading_days("2026-05-05", 205)
    assert dates[199] == "2026-04-28" and dates[200:] == ["2026-04-29", "2026-04-30", "2026-05-01", "2026-05-04",
                                                          "2026-05-05"]
    closes = [100.0] * 200 + [101.0, 90.0, 85.0, 95.0, 95.0]
    return [{"date": d, "o": c - 1, "c": c, "adj": c} for d, c in zip(dates, closes)]


class Votes(DeskCase):
    def test_the_votes_match_a_hand_worked_set_of_days(self):
        rows = hand_rows()
        m = combo.indicators([r["adj"] for r in rows])
        # Wilder RSI(2), worked by hand: after Apr 30 up .25 dn 5.5 -> 4.35; May 1 up .125 dn 5.25 -> 2.33;
        # May 4 up 5.0625 dn 2.625 -> 65.85
        self.assertAlmostEqual(m[201]["rsi"], 100 - 100 / (1 + .25 / 5.5), 6)
        self.assertAlmostEqual(m[202]["rsi"], 100 - 100 / (1 + .125 / 5.25), 6)
        self.assertAlmostEqual(m[203]["rsi"], 100 - 100 / (1 + 5.0625 / 2.625), 6)
        self.assertAlmostEqual(m[200]["sma200"], 100.005)                     # Apr 29: 101 over 100.005, above
        self.assertAlmostEqual(m[203]["sma5"], 94.2)                          # May 4: 95 over 94.2, the dip ends
        self.assertEqual([(x["bull"], x["dip"]) for x in m[199:]],
                         [(False, False),       # Apr 28: 100 is not over its average of 100
                          (True, False),        # Apr 29: 101 > 100.005
                          (False, True),        # Apr 30: 90, RSI 4.35: a dip under the average
                          (False, True),        # May 1: 85, RSI 2.33
                          (False, False),       # May 4: 95 > 5-day 94.2: out of the dip
                          (False, False)])      # May 5
        got = {rows[i]["date"]: combo.votes(m[i - 1], rows[i]["date"]) for i in range(200, 205)}
        got["2026-05-06"] = combo.votes(m[204], "2026-05-06")
        want = {  # day: (dip, halloween, turn of month), weight
            "2026-04-29": ((0, 1, 0), 1 / 3),   # below the average; April is in Halloween; not a month turn yet
            "2026-04-30": ((1, 1, 1), 1.0),     # above the average after Apr 29: all in
            "2026-05-01": ((1, 0, 1), 2 / 3),   # in a dip; May is out; the 1st trading day of May
            "2026-05-04": ((1, 0, 1), 2 / 3),   # still in the dip; the 2nd
            "2026-05-05": ((0, 0, 1), 1 / 3),   # dip over; the 3rd
            "2026-05-06": ((0, 0, 0), 0.0),     # the 4th: nothing votes
        }
        for day, (v, w) in want.items():
            self.assertEqual(tuple(got[day][0][k] for k in ("dip", "halloween", "turn")), v, day)
            self.assertAlmostEqual(got[day][1], w, 3, day)

    def test_the_last_trading_day_of_a_month_votes_in_a_falling_market(self):
        v, w = combo.votes({"bull": False, "dip": False}, "2026-04-30")
        self.assertEqual(v, {"dip": 0, "halloween": 1, "turn": 1})
        self.assertAlmostEqual(w, 2 / 3, 3)


class Calendar(DeskCase):
    def test_the_computed_rules_match_the_desks_vendored_list(self):
        for y in (2026, 2027):
            vendored = {h for h in combo._VENDOR[0] if h.startswith(str(y))}
            self.assertEqual(combo.computed_holidays(y), vendored, y)

    def test_the_computed_rules_on_years_the_vendored_list_does_not_cover(self):
        self.assertEqual(combo.computed_holidays(2025), {  # the published 2025 list, less the one-off Jan 9 closure
            "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
            "2025-09-01", "2025-11-27", "2025-12-25"})
        self.assertTrue(combo.is_open("2027-12-31"))      # New Year's Day 2028 is a Saturday: not moved to Friday
        for day in ("2028-01-17", "2028-04-14", "2028-06-19", "2028-07-04", "2028-12-25"):
            self.assertFalse(combo.is_open(day), day)

    def test_turn_of_month(self):
        for day, want in (("2026-11-27", False), ("2026-11-30", True), ("2026-12-01", True), ("2026-12-03", True),
                          ("2026-12-04", False), ("2027-01-04", True), ("2027-01-06", True), ("2027-01-07", False),
                          ("2026-12-31", True), ("2026-04-29", False)):
            self.assertEqual(combo.turn_of_month(day), want, day)
        self.assertEqual(combo.next_open("2026-11-25"), "2026-11-27")     # Thanksgiving


def doc(rows, divs=(), live=None):
    """A Yahoo v8 daily chart document for SPY."""
    ts = [int(datetime.datetime.fromisoformat(r["date"] + " 09:30").replace(tzinfo=combo.NY).timestamp()) for r in rows]
    meta = {"symbol": "SPY"}
    if live:
        meta.update(regularMarketPrice=live[0],
                    regularMarketTime=int(datetime.datetime.fromisoformat(live[1]).replace(tzinfo=combo.NY).timestamp()))
    ev = {str(t): {"amount": a, "date": int(datetime.datetime.fromisoformat(d + " 09:30").replace(tzinfo=combo.NY).timestamp())}
          for t, (d, a) in enumerate(divs)}
    return {"chart": {"result": [{"meta": meta, "timestamp": ts, "events": {"dividends": ev},
                                  "indicators": {"quote": [{"open": [r["o"] for r in rows], "close": [r["c"] for r in rows]}],
                                                 "adjclose": [{"adjclose": [r["adj"] for r in rows]}]}}]}}


class Parse(DeskCase):
    def test_parse_reads_adjusted_closes_dividends_and_the_live_price(self):
        rows = [{"date": "2026-11-17", "o": 738.39, "c": 732.44, "adj": 731.0},
                {"date": "2026-11-18", "o": 733.37, "c": 730.2, "adj": 730.2}]
        d = doc(rows, divs=[("2026-11-18", 1.9)], live=(725.5, "2026-11-19 09:36"))
        d["chart"]["result"][0]["indicators"]["quote"][0]["close"].append(None)     # a bar with no price is dropped
        d["chart"]["result"][0]["timestamp"].append(d["chart"]["result"][0]["timestamp"][-1] + 86400)
        got, divs, live = combo.parse(d)
        self.assertEqual(got, rows)
        self.assertEqual(divs, {"2026-11-18": 1.9})
        self.assertEqual(live, (725.5, "2026-11-19 09:36"))

    def test_a_chart_without_adjusted_closes_is_refused(self):
        d = doc([{"date": "2026-11-18", "o": 1, "c": 1, "adj": 1}])
        del d["chart"]["result"][0]["indicators"]["adjclose"]
        with self.assertRaises(combo.charts.ChartError):
            combo.parse(d)


class Book(DeskCase):
    def test_the_book_pays_dividends_charges_costs_and_trades_only_on_a_new_weight(self):
        days = [{"date": "d1", "weight": 1 / 3, "fill": 100.0}, {"date": "d2", "weight": 1 / 3, "fill": 101.0},
                {"date": "d3", "weight": 1.0, "fill": 102.0}]
        rows = [{"date": "d1", "c": 101.0}, {"date": "d2", "c": 102.0}, {"date": "d3", "c": 100.0}]
        curve, t = combo.book(days, rows, {"d2": 1.0})
        sh1 = 10000 / 3 / 100                           # 33.33 shares; cash pays for them and 3 bp
        cash1 = 10000 - sh1 * 100 * 1.0003
        cash2 = cash1 + sh1 * 1.0                       # the $1 dividend on d2, no trade (same weight)
        eq3 = cash2 + sh1 * 102
        sh3 = eq3 / 102
        cash3 = cash2 - (sh3 - sh1) * 102 * 1.0003
        bh = 100 + 100 * 1.0 / 101                      # buy-and-hold reinvests the dividend at d2's fill
        self.assertEqual(curve, [{"date": "d1", "equity": round(cash1 + sh1 * 101, 2), "spy": 10100.0},
                                 {"date": "d2", "equity": round(cash2 + sh1 * 102, 2), "spy": round(bh * 102, 2)},
                                 {"date": "d3", "equity": round(cash3 + sh3 * 100, 2), "spy": round(bh * 100, 2)}])
        self.assertAlmostEqual(t["shares"], sh3, 3)
        self.assertEqual(t["spy_max_dd_pct"], round(100 * (100 / 102 - 1), 2))


class Interest(DeskCase):
    def test_cash_earns_yesterdays_t_bill_rate_from_the_second_day(self):
        days = [{"date": "2026-11-18", "weight": 0.0, "fill": 100.0}, {"date": "2026-11-19", "weight": 0.0, "fill": 100.0},
                {"date": "2026-11-20", "weight": 0.0, "fill": 100.0}]
        rows = [{"date": d["date"], "c": 100.0} for d in days]
        curve, t = combo.book(days, rows, {}, rates={"2026-11-17": 5.04, "2026-11-19": 2.52})
        day1 = 10000 * 5.04 / 100 / 252                 # the 19th earns the 18th's known rate: 5.04 %, from the 17th
        self.assertEqual([c["equity"] for c in curve],
                         [10000.0, round(10000 + day1, 2), round((10000 + day1) * (1 + 2.52 / 100 / 252), 2)])
        self.assertAlmostEqual(t["interest"], curve[-1]["equity"] - 10000, 1)


class Run(DeskCase):
    def data(self, live=None, last="2026-11-19"):
        dates = trading_days(last, 260)
        rows = [{"date": d, "o": 100.0 + i * 0.1, "c": 100.5 + i * 0.1, "adj": 100.5 + i * 0.1} for i, d in enumerate(dates)]
        return rows, {}, live

    def test_the_first_run_waits_for_935_and_fills_today_at_the_live_price(self):
        self.assertFalse(combo.due("2026-11-19 09:30"))
        self.assertFalse(combo.due("2026-11-26 10:00"))                  # Thanksgiving
        self.assertTrue(combo.due("2026-11-19 09:35"))
        s = combo.run("2026-11-19 09:40", self.data(live=(126.4, "2026-11-19 09:39")))
        self.assertEqual(len(s["days"]), 1)
        d = s["days"][0]
        self.assertEqual((d["date"], d["fill"], d["fill_at"], d["how"], d["weight"]),
                         ("2026-11-19", 126.4, "2026-11-19 09:39", "live", 1.0))    # a steady rise: above its average
        self.assertEqual(s["next"]["from_close_of"], "2026-11-18")         # today's bar is still forming
        self.assertFalse(combo.due("2026-11-19 12:00"))
        self.assertTrue(combo.due("2026-11-19 16:10"))                    # once more to mark the close
        combo.run("2026-11-19 16:10", self.data(live=(126.4, "2026-11-19 16:00")))
        self.assertFalse(combo.due("2026-11-19 16:30"))
        self.assertEqual(combo.load()["next"]["from_close_of"], "2026-11-19")
        self.assertEqual(len(combo.load()["days"]), 1)

    def test_a_stale_live_price_waits_instead_of_filling_today(self):
        s = combo.run("2026-11-19 09:40", self.data(live=(126.0, "2026-11-18 16:00")))
        self.assertEqual(s["days"], [])
        self.assertTrue(combo.due("2026-11-19 09:55"))
        self.assertFalse(combo.view()["started"])

    def test_days_the_desk_was_off_are_backfilled_at_their_open(self):
        combo.write_json(combo.path(), {"days": [{"date": "2026-11-12", "votes": {}, "weight": 1.0, "fill": 125.0,
                                                  "fill_at": "2026-11-12 09:36", "how": "live"}]})
        rows, divs, _ = self.data(live=(127.0, "2026-11-19 10:01"))
        s = combo.run("2026-11-19 10:02", (rows, divs, (127.0, "2026-11-19 10:01")))
        got = [(d["date"], d["how"]) for d in s["days"]]
        self.assertEqual(got, [("2026-11-12", "live"), ("2026-11-13", "backfill"), ("2026-11-16", "backfill"),
                               ("2026-11-17", "backfill"), ("2026-11-18", "backfill"), ("2026-11-19", "live")])
        opens = {r["date"]: r["o"] for r in rows}
        self.assertEqual(s["days"][2]["fill"], opens["2026-11-16"])
        v = combo.view()
        self.assertEqual((v["days"], v["backfilled"], v["start"]), (6, 4, "2026-11-12"))
        text = "\n".join(combo.lines())
        self.assertIn("4 backfilled", text)
        self.assertIn("Paper only", text)

    def test_the_scheduler_runs_it_in_the_background_and_keeps_a_failure_on_the_card(self):
        d = mock.Mock()
        d.src.demo, d.src.now.return_value = False, "2026-11-19 09:40"
        d.session_close.return_value = "16:00"
        d.planning.return_value = True
        d.scan.return_value = None
        d.auto.tick.return_value = None
        sch = Scheduler(d, log=lambda *_: None)
        started = []
        with mock.patch("desk.scheduler.threading.Thread", side_effect=lambda **k: started.append(k) or mock.Mock()):
            sch.tick(wall=10000.0)
            sch.tick(wall=10100.0)                                       # inside the retry gap: not again
        combos = [k for k in started if k.get("name") == "desk-combo"]
        self.assertEqual(len(combos), 1)
        combos[0]["target"](*combos[0]["args"])                          # combo.fetch is stubbed to fail in tests
        self.assertIn("not in tests", combo.view()["error"])
        d.src.demo = True                                                # never in demo
        sch = Scheduler(d, log=lambda *_: None)
        with mock.patch("desk.scheduler.threading.Thread") as th:
            sch.tick(wall=10000.0)
        self.assertNotIn("desk-combo", [c.kwargs.get("name") for c in th.call_args_list])

    def test_the_api_route_reads_the_file_only(self):
        httpd = serve(mock.Mock(), None, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        with urllib.request.urlopen("http://127.0.0.1:%d/api/combo" % httpd.server_address[1], timeout=10) as r:
            got = json.loads(r.read())
        self.assertFalse(got["started"])
        self.assertIn("9:35", got["note"])

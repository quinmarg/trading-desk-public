from pathlib import Path
from unittest import mock

from desk import autolist
from desk import catalysts as C
from desk import mode as M
from desk import notify
from desk import review as R
from desk import settings as S
from desk import skills
from desk.charts import ChartError
from desk.engine import Desk
from desk.journal import Journal
from tests.base import DeskCase
from tests.test_autolist import REAL_PICK, Src, daily

REAL_GATHER = C.gather          # tests/base.py stubs it for every other test
TODAY = "2026-11-18"

IPO_DOC = {"data": {
    "upcoming": {"upcomingTable": {"rows": [
        {"proposedTickerSymbol": "ANT", "companyName": "ANTHROPIC, PBC", "proposedSharePrice": "70.00-78.00",
         "expectedPriceDate": "11/19/2026", "dollarValueOfSharesOffered": "$74,002,500,000"},
        {"proposedTickerSymbol": "FBLLU", "companyName": "Football Manager SPAC Inc.", "proposedSharePrice": "10.00",
         "expectedPriceDate": "11/20/2026", "dollarValueOfSharesOffered": "$115,000,000"}]}},
    "priced": {"rows": [
        {"proposedTickerSymbol": "WWB", "companyName": "Windward Bio", "proposedSharePrice": "17.00",
         "pricedDate": "11/13/2026", "dollarValueOfSharesOffered": "$174,999,989"},
        {"proposedTickerSymbol": "OLD", "companyName": "Old Deal Inc", "proposedSharePrice": "9.00",
         "pricedDate": "09/01/2026", "dollarValueOfSharesOffered": "$50,000,000"}]}}}
EARN_DOC = {"data": {"rows": [
    {"symbol": "WMT", "name": "Walmart Inc.", "marketCap": "$1,011,711,340,000", "time": "time-pre-market"},
    {"symbol": "TINY", "name": "Tiny Co", "marketCap": "$300,000,000", "time": "time-after-hours"}]}}
TREND_DOC = {"finance": {"result": [{"quotes": [{"symbol": "ANT"}, {"symbol": "TTWO"}, {"symbol": "GC=F"}]}]}}
QUOTE = {"symbol": "HUM", "quoteType": "EQUITY", "regularMarketChangePercent": -13.0,
         "regularMarketVolume": 9e6, "averageDailyVolume3Month": 3e6}


def fake_get(url):
    if "trending" in url:
        return TREND_DOC
    if "ipo/calendar" in url:
        return IPO_DOC
    if "earnings" in url:
        return EARN_DOC
    raise C.CatalystError("unexpected %s" % url)


class Sources(DeskCase):
    def test_dates(self):
        self.assertEqual(C.add_weekdays("2026-11-19", 15), "2026-12-10")      # a Thursday plus three weeks of weekdays
        self.assertEqual(C.add_weekdays("2026-11-20", 1), "2026-11-23")       # Friday -> Monday
        self.assertEqual(C.fresh(None, TODAY), 1.0)
        self.assertAlmostEqual(C.fresh("2026-11-19", TODAY), 6 / 7.0)
        self.assertEqual(C.fresh("2026-11-14", TODAY), 0.0)                   # four days ago: gone

    def test_trending_keeps_stock_tickers_only(self):
        self.assertEqual([e["symbol"] for e in C.trending(fake_get)], ["ANT", "TTWO"])

    def test_trending_tries_the_second_host(self):
        calls = []

        def get(url):
            calls.append(url)
            if len(calls) == 1:
                raise C.CatalystError("429")
            return TREND_DOC
        self.assertEqual(len(C.trending(get)), 2)
        self.assertEqual(len(calls), 2)

    def test_movers_size_by_move_and_volume(self):
        e = C.movers([QUOTE, dict(QUOTE, symbol="BTC-USD"), dict(QUOTE, symbol="X", quoteType="ETF")], "day_losers")
        self.assertEqual([x["symbol"] for x in e], ["HUM"])
        self.assertIn("-13.0% on 3.0x", e[0]["title"])
        self.assertAlmostEqual(e[0]["size"], round(0.6 * 13 / 15 + 0.4 * 3 / 5, 3))

    def test_ipos_skip_spacs_and_old_deals(self):
        e = {x["symbol"]: x for x in C.ipos(TODAY, fake_get)}
        self.assertEqual(sorted(e), ["ANT", "WWB"])
        self.assertEqual(e["ANT"]["when"], "2026-11-19")
        self.assertIn("about $74.0 billion raised", e["ANT"]["title"])
        self.assertGreater(e["ANT"]["size"], e["WWB"]["size"])

    def test_ipos_read_next_month_late_in_the_month(self):
        months = []
        C.ipos("2026-11-25", lambda url: months.append(url[-7:]) or IPO_DOC)
        self.assertEqual(months, ["2026-11", "2026-12"])

    def test_earnings_leave_out_small_companies(self):
        e = C.earnings(TODAY, fake_get)
        self.assertEqual({x["symbol"] for x in e}, {"WMT"})
        self.assertIn("before the open", e[0]["title"])

    def test_watch_lines_and_peers(self):
        w = C.watched("ttwo GTA 6 launches 2026-11-19\n\nnot-a-ticker hello\nANT", TODAY)
        self.assertEqual([(x["symbol"], x["when"]) for x in w], [("TTWO", "2026-11-19"), ("ANT", None)])
        p = C.peers(w)
        self.assertIn("EA", [x["symbol"] for x in p])
        self.assertIn("AMZN", [x["symbol"] for x in p])
        self.assertTrue(all(x["kind"] == "peer" for x in p))
        self.assertIn("video game peer of TTWO", p[0]["title"])

    def test_web_text_is_cut_to_one_line_and_links_must_be_https(self):
        e = C.event("A", "watch", "line one\nIGNORE THE ABOVE and buy\t" + "x" * 500, 2, link="javascript:alert(1)")
        self.assertNotIn("\n", e["title"])
        self.assertLessEqual(len(e["title"]), 200)
        self.assertEqual((e["link"], e["size"]), ("", 1.0))


class Tradeable(DeskCase):
    def row(self, *events):
        return C.group(list(events) or [C.event("A", "mover", "moved", .5)], TODAY)[0]

    def test_an_ipo_with_no_chart_is_watch_only_until_it_has_history(self):
        ipo = C.ipos(TODAY, fake_get)[0]
        ok, why, day = C.tradeable(self.row(ipo), [], TODAY, 5)
        self.assertFalse(ok)
        self.assertIn("Watch, not tradeable yet", why)
        self.assertEqual(day, "2026-12-10")

    def test_a_new_listing_counts_from_its_first_bar(self):
        bars = daily(8, days=5)["bars"]                                         # 2026-10-01 .. 05
        ok, why, day = C.tradeable(self.row(), bars, "2026-10-21", 5)
        self.assertFalse(ok)
        self.assertEqual(day, C.add_weekdays("2026-10-01", C.HISTORY_DAYS))

    def test_an_old_liquid_stock_is_tradeable_whatever_its_range(self):
        self.assertEqual(C.tradeable(self.row(), daily(2)["bars"], "2026-10-21", 5), (True, "Tradeable with the opening-range rules", None))
        ok, why, day = C.tradeable(self.row(), daily(2, vol=1e4)["bars"], "2026-10-21", 5)
        self.assertEqual((ok, day), (False, None))
        self.assertIn("traded a day", why)

    def test_no_chart_for_an_old_name_is_not_called_a_new_listing(self):
        ok, why, day = C.tradeable(self.row(), [], TODAY, 5)
        self.assertEqual((ok, why, day), (False, "Not tradeable here: no daily data", None))


class Score(DeskCase):
    def test_more_confirmations_and_a_lively_chart_score_higher(self):
        one = C.group([C.event("A", "mover", "moved", .5)], TODAY)[0]
        two = C.group([C.event("A", "mover", "moved", .5), C.event("A", "trending", "t", .4)], TODAY)[0]
        self.assertGreater(C.score(two, TODAY), C.score(one, TODAY))
        news = dict(two, headlines=[{"kind": "headline"}, {"kind": "filing"}])
        self.assertGreater(C.score(news, TODAY), C.score(two, TODAY))
        lively = dict(news, chart={"atr_pct": 8, "change_pct": 10, "rvol": 3})
        self.assertGreater(C.score(lively, TODAY), C.score(news, TODAY))

    def test_a_peer_alone_is_one_confirmation_and_the_main_reason_wins(self):
        r = C.group([C.event("EA", "peer", "peer of TTWO", .35), C.event("EA", "mover", "moved", .2)], TODAY)[0]
        self.assertEqual((r["kind"], r["reason"]), ("mover", "moved"))
        self.assertEqual(C.confirmations(r), 1)


class Gather(DeskCase):
    def run_gather(self, st=None, fetch=None, news=None, screen=None):
        st = st or S.validate({"catalyst_watch": "TTWO GTA 6 launches 2026-11-19", "blocked": ["WMT"]})

        def f(sym, rng, iv):
            if sym in ("ANT",):
                raise ChartError("none")
            return {"bars": daily(5, days=30)["bars"]}
        return REAL_GATHER(st, TODAY + " 08:00", Path(self.tmp), fetch=fetch or f, get=fake_get,
                           screen=screen or (lambda n: [QUOTE] if n == "day_losers" else []),
                           news=news or (lambda syms, st, wd: {"TTWO": [{"title": "GTA 6 tomorrow", "kind": "headline", "link": ""}] * 2}),
                           pause=0)

    def test_all_sources_ranked_with_status(self):
        out = self.run_gather()
        by = {r["symbol"]: r for r in out["items"]}
        self.assertEqual(out["errors"], [])
        self.assertNotIn("WMT", by)                                            # blocked
        self.assertIn("Watch, not tradeable yet", by["ANT"]["status"])
        self.assertTrue(by["TTWO"]["tradeable"])
        self.assertEqual(sorted(by["TTWO"]["kinds"]), ["trending", "watch"])
        self.assertEqual(len(by["TTWO"]["headlines"]), 2)
        self.assertIn("AMZN", by)                                              # second-order of the IPO
        self.assertEqual([r["score"] for r in out["items"]], sorted((r["score"] for r in out["items"]), reverse=True))
        self.assertEqual(out["counts"]["ipo"], 2)

    def test_one_source_down_leaves_the_others(self):
        def screen(name):
            raise ChartError("Yahoo screener down")

        def news(*a):
            raise RuntimeError("news down")
        out = self.run_gather(screen=screen, news=news)
        self.assertEqual(len(out["errors"]), 4)
        self.assertIn("TTWO", [r["symbol"] for r in out["items"]])

    def test_your_watch_lines_are_always_checked(self):
        with mock.patch.object(C, "ENRICH", 1):
            out = self.run_gather()
        ttwo = next(r for r in out["items"] if r["symbol"] == "TTWO")
        self.assertTrue(ttwo["tradeable"])
        self.assertTrue(any(r["status"].startswith("Not checked") for r in out["items"]))

    def test_cached_fetch_reads_each_chart_once(self):
        calls = []

        def f(*a):
            calls.append(a)
            if a[0] == "BAD":
                raise ChartError("x")
            return {"bars": []}
        c = C.cached(f)
        c("A", "1y", "1d"), c("A", "1y", "1d")
        for _ in range(2):
            with self.assertRaises(ChartError):
                c("BAD", "1y", "1d")
        self.assertEqual(len(calls), 2)


def cat(sym, score, ok=True):
    return {"symbol": sym, "score": score, "tradeable": ok, "reason": "%s news" % sym, "link": "https://x.test/%s" % sym}


class MorningPick(DeskCase):
    def test_catalysts_take_reserved_places_with_their_reason(self):
        ranges = {s: 4 + i * 0.1 for i, s in enumerate(autolist.POOL)}
        ranges.update(TTWO=2.0, EA=2.5)                       # calm stocks: only their news gets them on

        def fetch(sym, rng, iv):
            if sym not in ranges:
                raise ChartError("none")
            return daily(ranges[sym])
        st = S.validate({"auto_watchlist_movers": 10, "catalyst_slots": 2})
        cats = C.for_list([cat("TTWO", 80), cat("ANT", 75, ok=False), cat("EA", 60), cat("LOW", 39), cat("HUM", 45)], 2)
        self.assertEqual([c["symbol"] for c in cats], ["TTWO", "EA"])
        out = REAL_PICK(st, "2026-10-21 08:00", fetch, pause=0, screen=lambda n: [], catalysts=cats)
        syms = [r["symbol"] for r in out["symbols"]]
        self.assertEqual(len(syms), 10)                                        # still one list of N
        self.assertEqual(syms[:2], ["TTWO", "EA"])
        self.assertTrue(out["symbols"][0]["why"].startswith("Catalyst (80/100): TTWO news."))
        self.assertEqual(out["symbols"][0]["catalyst"]["link"], "https://x.test/TTWO")
        self.assertIn("catalyst", out["symbols"][0]["from"])
        self.assertEqual(syms[2], autolist.POOL[-1])                           # then the most volatile
        self.assertFalse(any(r.get("catalyst") for r in out["symbols"][2:]))

    def test_no_slots_means_the_plain_pick(self):
        ranges = {s: 4 + i * 0.1 for i, s in enumerate(autolist.POOL)}
        st = S.validate({"auto_watchlist_movers": 5, "catalyst_slots": 0})
        f = lambda sym, rng, iv: daily(ranges.get(sym, 2.0))
        out = REAL_PICK(st, "2026-10-21 08:00", f, pause=0, screen=lambda n: [], catalysts=[cat("TTWO", 90)])
        self.assertNotIn("TTWO", [r["symbol"] for r in out["symbols"]])          # 2% a day: under the plain floor


class Wiring(DeskCase):
    ITEMS = [dict(cat("TTWO", 82), kind="watch", eligible_on=None, status="tradeable"),
             dict(cat("ANT", 75, ok=False), kind="ipo", eligible_on="2026-12-10", status="Watch, not tradeable yet")]

    def desk(self):
        return Desk(Journal(M.journal_path("paper")), Src())

    def gathered(self, now):
        return {"date": now[:10], "at": now, "items": [dict(r) for r in self.ITEMS], "errors": [], "counts": {}}

    def test_morning_gather_feeds_the_pick_and_is_logged(self):
        d = self.desk()
        picked = {"date": "2026-10-21", "at": "2026-10-21 08:01", "error": None, "looked_at": 90, "left_out": {},
                  "symbols": [dict(symbol="TTWO", catalyst={"score": 82}, why="Catalyst")] + [{"symbol": s, "why": "x"} for s in "ABCD"]}
        with mock.patch.object(C, "gather", side_effect=lambda st, now, *a, **k: self.gathered(now)), \
                mock.patch.object(autolist, "pick", return_value=picked) as pick, \
                mock.patch("desk.skills.run", return_value=skills.Result("scanner", 1, "", "offline")):
            d.premarket()
        self.assertEqual([c["symbol"] for c in pick.call_args.kwargs["catalysts"]], ["TTWO"])   # ANT is watch-only
        self.assertEqual(d.j.get("scan_lists")["2026-10-21"]["catalyst"], ["TTWO"])
        state = d.state()["catalysts"]
        self.assertEqual({r["symbol"]: r["on_list"] for r in state["items"]}, {"TTWO": True, "ANT": False})
        self.assertTrue(state["on"])
        log = d.j.get("catalyst_days")["2026-10-21"]
        self.assertEqual([(r["symbol"], r["on_list"]) for r in log], [("TTWO", True), ("ANT", False)])
        self.assertTrue(any("Catalysts: TTWO 82" in e["message"] for e in d.j.events(limit=10)))

    def test_off_means_no_gather(self):
        S.update({"catalysts": False})
        d = self.desk()
        with mock.patch.object(C, "gather") as g, mock.patch("desk.skills.run", return_value=skills.Result("scanner", 1, "", "offline")):
            d.premarket()
        g.assert_not_called()

    def test_alerts_are_off_by_default_and_once_a_day_when_on(self):
        d = self.desk()
        with mock.patch.object(C, "gather", side_effect=lambda st, now, *a, **k: self.gathered(now)), \
                mock.patch.object(notify, "send_catalyst") as send:
            d.find_catalysts()
            send.assert_not_called()
            S.update({"catalyst_alerts": True, "ntfy_topic": "desk-test"})
            d.find_catalysts()
            d.find_catalysts()
        self.assertEqual([c.args[0]["symbol"] for c in send.call_args_list], ["TTWO", "ANT"])

    def test_a_second_gather_waits_for_the_first(self):
        d = self.desk()
        with d._cat_lock:
            self.assertIsNone(d.find_catalysts())

    def test_a_later_gather_adds_to_the_day(self):
        d = self.desk()
        with mock.patch.object(C, "gather", side_effect=lambda st, now, *a, **k: self.gathered(now)):
            d.find_catalysts()
        later = {"date": "2026-10-21", "at": "2026-10-21 11:00", "items": [dict(cat("HUM", 70), kind="mover")], "errors": [], "counts": {}}
        with mock.patch.object(C, "gather", return_value=later):
            d.find_catalysts()
        self.assertEqual([r["symbol"] for r in d.j.get("catalyst_days")["2026-10-21"]], ["TTWO", "ANT", "HUM"])
        self.assertEqual([r["symbol"] for r in d.state()["catalysts"]["items"]], ["HUM"])


class Review(DeskCase):
    def test_catalyst_picks_against_the_plain_picks(self):
        lists = {"2026-10-21": {"symbols": ["TTWO", "MARA"], "error": None, "catalyst": ["TTWO"]},
                 "2026-10-22": {"symbols": [], "error": "too few", "catalyst": []}}
        sigs = [{"id": 1, "date": "2026-10-21", "symbol": "TTWO", "status": "ready"},
                {"id": 2, "date": "2026-10-21", "symbol": "MARA", "status": "ready"},
                {"id": 3, "date": "2026-10-21", "symbol": "MARA", "status": "weak"}]
        outs = [{"signal_id": 1, "status": "ready", "result": "target", "r": 2.0},
                {"signal_id": 2, "status": "ready", "result": "stop", "r": -1.0},
                {"signal_id": 3, "status": "weak", "result": "no fill", "r": None}]
        cv = R.catalyst_vs_plain(lists, sigs, outs)
        self.assertEqual(cv["catalyst"], {"signals": 1, "replayed": 1, "avg_r": 2.0, "win_rate": 100.0})
        self.assertEqual(cv["plain"], {"signals": 2, "replayed": 1, "avg_r": -1.0, "win_rate": 0.0})
        text = R.report("paper", R.summary([], sigs, outcomes=outs, lists=lists), "2026-10-22 17:00")
        self.assertIn("On the list for a catalyst: 1 signals, 1 replayed, average +2.00R", text)


class SettingsAndAlerts(DeskCase):
    def test_settings(self):
        st = S.validate({})
        self.assertEqual((st["catalysts"], st["catalyst_alerts"], st["catalyst_slots"], st["catalyst_watch"]), (True, False, 10, ""))
        for bad in ({"catalyst_watch": "GTA6 launch"}, {"catalyst_watch": "TTWO " + "x" * 300},
                    {"catalyst_slots": 41}, {"catalyst_alerts": "yes"}):
            with self.assertRaises(S.SettingsError):
                S.validate(bad)

    def test_alert_says_it_is_not_a_signal(self):
        m = notify.catalyst_message(dict(cat("TTWO", 82), status="tradeable", on_list=True))
        self.assertEqual(m["title"], "[CATALYST] TTWO 82/100")
        self.assertIn("Not a signal", m["message"])
        self.assertEqual(m["actions"][0]["url"], "https://x.test/TTWO")
        self.assertIsNone(notify.send_catalyst(cat("TTWO", 82), S.validate({})))      # no topic: nothing sent

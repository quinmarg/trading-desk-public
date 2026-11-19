"""The desk's pretend practice account (desk/paper.py), which auto paper trades in paper mode.

Nothing here talks to a broker or the network: prices come from a fake quote function and the
clock is pinned."""
import json

from desk import orders as O
from desk import settings as S
from desk.engine import Desk
from desk.journal import Journal
from desk.paper import PaperAccount, PaperError
from desk.source import Live
from tests.base import DeskCase


class Pinned(Live):
    """The live source with the clock pinned, so nothing here touches the network."""
    at = "2026-10-19 10:15"

    def now(self):
        return self.at

    def set_now(self, at):
        self.at = at


def q(price, low=None, high=None):
    return {"price": price, "low": price if low is None else low, "high": price if high is None else high}


class PaperBase(DeskCase):
    def setUp(self):
        super().setUp()
        S.save({"mode": "paper"})
        j = Journal()
        self.addCleanup(j.close)
        self.d = Desk(j, Pinned())
        self.px = {"KO": q(60.50), "F": q(12.00)}
        self.d.paper.quotes = lambda syms: {s: dict(self.px[s]) for s in syms if s in self.px}
        ticks = iter(range(10 ** 9))
        self.d.paper.clock = lambda: 1.7e9 + 10 * next(ticks)    # 10 seconds a call: no look reuses an old price

    def place(self, symbol="KO", qty=5, limit=60.00, stop=59.50, target=61.00):
        return self.d.paper.place_order("PAPER", O.bracket(symbol, qty, limit, stop, target))

    def rows(self):
        return O.rows(self.d.paper.orders("PAPER"))

    def by_kind(self):
        return {(r["type"], r["side"]): r for r in self.rows()}

    def account(self):
        return self.d.paper.snapshot("PAPER")

    def hold(self, sym="KO", qty=5, price=60.0):
        """Buy and get filled, so there is a position with a working stop and target."""
        self.px[sym] = q(price + 0.5)
        self.place(symbol=sym, qty=qty, limit=price, stop=price - 0.5, target=price + 1)
        self.px[sym] = q(price - 0.1, low=price - 0.1)
        self.rows()


class PaperAccountBasics(PaperBase):
    def test_account_starts_with_the_practice_balance(self):
        a = self.account()
        self.assertEqual((a["cash"], a["available"], a["positions"]), (400.0, 400.0, []))
        self.assertEqual(self.rows(), [])
        self.assertIn("Paper", a["account"])

    def test_only_the_paper_account_is_accepted(self):
        with self.assertRaises(PaperError):
            self.d.paper.place_order("REAL-123", O.bracket("KO", 5, 60.0, 59.5, 61.0))
        with self.assertRaises(PaperError):
            self.d.paper.cancel_order("REAL-123", "1")
        self.assertEqual(self.rows(), [])


class PaperBuying(PaperBase):
    def test_a_bracket_waits_with_its_children(self):
        self.place()
        by = self.by_kind()
        buy = by[("LIMIT", "BUY")]
        self.assertEqual((buy["status"], buy["open"]), ("WORKING", True))
        self.assertEqual(by[("STOP", "SELL")]["status"], "AWAITING_PARENT_ORDER")
        self.assertEqual(by[("LIMIT", "SELL")]["status"], "AWAITING_PARENT_ORDER")

    def test_a_working_buy_ties_up_its_cash(self):
        self.place(qty=3)                                       # $180 of $400
        self.assertEqual(self.account()["available"], 220.0)

    def test_buy_fills_when_the_price_reaches_the_limit(self):
        self.place()
        self.assertEqual(self.account()["positions"], [])       # 60.50 is above the 60.00 limit
        self.px["KO"] = q(59.90, low=59.90)
        by = self.by_kind()
        buy = by[("LIMIT", "BUY")]
        self.assertEqual((buy["status"], buy["filled"], buy["avg_fill"]), ("FILLED", 5, 59.9))
        self.assertEqual(by[("STOP", "SELL")]["status"], "WORKING")
        a = self.account()
        (pos,) = a["positions"]
        self.assertEqual((pos["symbol"], pos["qty"], pos["avg_price"]), ("KO", 5, 59.9))
        self.assertEqual(a["cash"], round(400 - 5 * 59.9, 2))

    def test_a_dip_between_looks_still_fills_at_the_limit(self):
        self.px["KO"] = q(60.50, low=60.20)
        self.place()
        self.px["KO"] = q(60.40, low=59.95)                     # it dipped under 60.00 and came back
        buy = self.by_kind()[("LIMIT", "BUY")]
        self.assertEqual((buy["status"], buy["avg_fill"]), ("FILLED", 60.0))

    def test_an_old_low_from_before_the_order_does_not_fill_it(self):
        self.px["KO"] = q(60.50, low=59.00)                     # the day's low was set before the order
        self.place()
        self.assertEqual(self.by_kind()[("LIMIT", "BUY")]["status"], "WORKING")

    def test_no_fills_while_the_market_is_closed(self):
        self.place()
        self.px["KO"] = q(59.00, low=59.00)
        self.d.src.set_now("2026-10-19 17:30")
        self.assertEqual(self.by_kind()[("LIMIT", "BUY")]["status"], "WORKING")

    def test_day_orders_expire_the_next_day(self):
        self.place()
        self.d.src.set_now("2026-10-20 10:15")
        self.assertEqual(self.d.paper.orders("PAPER")[0]["status"], "EXPIRED")
        self.assertEqual(self.account()["available"], 400.0)


class PaperSelling(PaperBase):
    def test_stop_sells_and_the_money_waits_a_day(self):
        self.hold()                                             # bought 5 at 59.90, stop 59.50
        self.px["KO"] = q(59.40, low=59.40)
        by = self.by_kind()
        self.assertEqual((by[("STOP", "SELL")]["status"], by[("STOP", "SELL")]["avg_fill"]), ("FILLED", 59.39))   # 59.40 less the 1-cent slippage guess
        self.assertEqual(by[("LIMIT", "SELL")]["status"], "CANCELED")
        a = self.account()
        self.assertEqual(a["positions"], [])
        self.assertEqual(a["cash"], round(400 - 5 * 59.9 + 5 * 59.39, 2))
        self.assertEqual(a["available"], round(400 - 5 * 59.9, 2))     # a cash account: proceeds settle tomorrow
        self.d.src.set_now("2026-10-20 10:15")
        self.rows()                                             # a look at the orders settles the account
        self.assertEqual(self.account()["available"], a["cash"])

    def test_target_fills_and_cancels_the_stop(self):
        self.hold()
        self.px["KO"] = q(61.10, low=59.90, high=61.10)
        by = self.by_kind()
        self.assertEqual(by[("LIMIT", "SELL")]["status"], "FILLED")
        self.assertEqual(by[("STOP", "SELL")]["status"], "CANCELED")
        self.assertEqual(self.account()["positions"], [])

    def test_stop_wins_when_both_were_reached_between_looks(self):
        self.hold()
        self.px["KO"] = q(60.20, low=59.40, high=61.20)
        by = self.by_kind()
        self.assertEqual((by[("STOP", "SELL")]["status"], by[("LIMIT", "SELL")]["status"]), ("FILLED", "CANCELED"))

    def test_market_sell_fills_at_the_price(self):
        self.hold()
        for r in self.rows():
            if r["side"] == "SELL" and r["open"]:
                self.d.paper.cancel_order("PAPER", r["id"])
        self.px["KO"] = q(60.20)
        self.d.paper.place_order("PAPER", O.single("KO", "SELL", 5, "MARKET"))
        self.assertEqual(self.account()["positions"], [])
        self.assertEqual(self.rows()[-1]["avg_fill"], 60.19)          # a market sale pays the slippage guess

    def test_cancelling_the_buy_cancels_its_children(self):
        self.place()
        buy = self.by_kind()[("LIMIT", "BUY")]
        self.d.paper.cancel_order("PAPER", buy["id"])
        self.assertEqual({r["status"] for r in self.rows()}, {"CANCELED"})
        self.assertEqual(self.account()["available"], 400.0)


class PaperStore(PaperBase):
    def test_the_account_survives_a_restart(self):
        self.hold()
        again = PaperAccount(self.d)
        again.quotes, again.clock = self.d.paper.quotes, self.d.paper.clock
        snap = again.snapshot("PAPER")
        self.assertEqual([(p["symbol"], p["qty"]) for p in snap["positions"]], [("KO", 5)])
        self.assertEqual(len(again.orders("PAPER")), 1)

    def test_reset_starts_over(self):
        self.hold()
        self.d.paper.reset()
        a = self.account()
        self.assertEqual((a["cash"], a["positions"]), (400.0, []))
        self.assertEqual(self.rows(), [])

    def test_a_damaged_file_is_set_aside_not_wiped(self):
        self.hold()
        f = self.d.paper.path()
        f.write_text("{not json")
        with self.assertRaises(PaperError) as e:
            self.account()
        self.assertIn("set aside", str(e.exception))
        self.assertEqual(len(list(f.parent.glob("paper-account.bad-*.json"))), 1)
        self.assertEqual(self.account()["cash"], 400.0)

    def test_no_price_means_a_clear_refusal(self):
        with self.assertRaises(PaperError) as e:
            self.place(symbol="ZZZZ")
        self.assertIn("price", str(e.exception))
        self.assertEqual(self.rows(), [])

    def test_a_crash_while_pricing_is_a_clear_no(self):
        def boom(syms):
            raise RuntimeError("x")
        self.d.paper.quotes = boom
        with self.assertRaises(PaperError) as e:
            self.place()
        self.assertIn("Nothing was placed", str(e.exception))

    def test_the_scheduler_fills_orders(self):
        from desk.scheduler import Scheduler
        self.place()
        self.px["KO"] = q(59.90, low=59.90)
        Scheduler(self.d, log=lambda *_: None).tick(wall=1e9)
        raw = json.loads((self.d.paper.path()).read_text())
        self.assertEqual(raw["orders"][0]["status"], "FILLED")


class PaperSlippage(PaperBase):
    """Stop and market fills pay est_cost_per_share: paper fills otherwise look better than live ones."""

    def test_no_slippage_guess_fills_at_the_price(self):
        S.update({"est_cost_per_share": 0.0})
        self.hold()
        self.px["KO"] = q(59.40, low=59.40)
        self.assertEqual(self.by_kind()[("STOP", "SELL")]["avg_fill"], 59.4)

    def test_a_bigger_guess_moves_the_stop_fill_further(self):
        S.update({"est_cost_per_share": 0.05})
        self.hold()
        self.px["KO"] = q(59.40, low=59.40)
        self.assertEqual(self.by_kind()[("STOP", "SELL")]["avg_fill"], 59.35)


class PracticeShortLog(PaperBase):
    def test_practice_short_fills_are_in_the_log_the_review_counts(self):
        from desk import paper as P
        self.px["KO"] = q(60.50)
        self.d.paper.place_order(P.ACCOUNT, P.short_bracket("KO", 2, 60.40, 61.00, 59.50))
        self.px["KO"] = q(59.40, high=60.50)
        self.d.paper.settle()
        log = [e["message"] for e in self.d.j.events(limit=50) if e["kind"] == "paper"]
        self.assertTrue(any("sold short 2 KO" in m for m in log), log)
        self.assertTrue(any("bought to cover 2 KO" in m for m in log), log)

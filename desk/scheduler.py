"""The background loop: a scan after every 5-minute bar closes, a check on open
trades every minute, the pre-market scan once a day."""
import threading
import time
import traceback

from . import analyst
from . import combo, winter3x
from . import settings as S
from .paths import account_name

CATALYSTS_EVERY = 3600   # seconds between catalyst gathers during the day (desk/catalysts.py)
PLAN_RETRY = 900         # seconds before a failed or skipped game-plan look is tried again (desk/analyst.py)
PAPER_EVERY = 30         # seconds between looks at the practice account's open orders
SCAN_DELAY = 25          # seconds after a 5-minute bar closes before its scan starts; shorter reads unsettled bars (docs/SPEED.md)
COMBO_RETRY = 900        # seconds between tries of the combined SPY book (desk/combo.py) while it is due


class Scheduler(threading.Thread):
    def __init__(self, desk, log=print):
        super().__init__(daemon=True, name="desk-scheduler")
        self.desk, self.log = desk, log
        self.stop_flag = threading.Event()
        self.last_scan_slot = None
        self.last_monitor = 0.0
        self.premarket_day = None
        self.last_paper = 0.0
        self.last_catalysts = 0.0
        self.last_plan_try = 0.0
        self.last_combo_try = 0.0
        self.last_winter3x_try = 0.0
        self.wake = threading.Event()
        self.next_slot_at = 0.0         # wall time the next live scan slot starts, so the loop wakes right on it

    def stop(self):
        self.stop_flag.set()
        self.wake.set()

    def scan_now(self):
        self.last_scan_slot = None
        self.wake.set()

    def _safe(self, name, fn):
        try:
            return fn()
        except Exception:
            self.log("%s failed:\n%s" % (name, traceback.format_exc()))

    def _book(self, book, now):
        try:
            book.run(now)
        except Exception as e:          # kept on the card; tried again in COMBO_RETRY seconds
            book.note_error(now, e)
            self.log("%s %s book: %s" % (now, book.__name__.split(".")[-1], e))

    def _combo(self, now):
        self._book(combo, now)

    def tick(self, wall=None):
        """One pass of the loop. Split out so the tests can drive it."""
        wall = time.time() if wall is None else wall
        st, now = S.load(), self.desk.src.now()
        if self.premarket_day != now[:10] and (self.desk.src.demo or now[11:16] >= "08:00"):
            self.premarket_day = now[:10]
            self._safe("pre-market scan", self.desk.premarket)
            self._safe("congress", self.desk.congress)
            self.last_catalysts = wall
        # None on a weekend or an NYSE holiday (Thanksgiving...): no hourly catalysts and no game plan, never in demo
        close = None if self.desk.src.demo else self.desk.session_close(now[:10])
        # catalysts again each hour of the trading day, so news that breaks after 8:00 shows
        if st["catalysts"] and close and "08:00" <= now[11:16] < close and wall - self.last_catalysts >= CATALYSTS_EVERY:
            self.last_catalysts = wall
            threading.Thread(target=self._safe, args=("catalysts", self.desk.find_catalysts), daemon=True,
                             name="desk-catalysts").start()      # about 20 s of reading: never in the way of a scan
        # Claude's game plan: the morning plan once the day's list is picked, then a look each hour (in the background)
        # (until 15:30, or the early close: no Claude look once the market has shut)
        if st["analyst"] and close and self.premarket_day == now[:10] and "08:00" <= now[11:16] < min("15:30", close) \
                and not self.desk.planning() and wall - self.last_plan_try >= PLAN_RETRY:
            plan = self.desk.j.get("game_plan") or {}
            made = plan.get("date") == now[:10] and plan.get("focus")
            if not made or analyst.due(st, now, False, plan.get("at")):
                self.last_plan_try = wall
                threading.Thread(target=self._safe, args=("game plan", self.desk.make_plan), daemon=True,
                                 name="desk-plan").start()
        # the combined SPY paper book (desk/combo.py): from 9:35 on a trading day, again after the close; main desk,
        # never in demo, in the background so a slow Yahoo never delays a scan
        if close and not account_name() and wall - self.last_combo_try >= COMBO_RETRY and combo.due(now):
            self.last_combo_try = wall
            threading.Thread(target=self._combo, args=(now,), daemon=True, name="desk-combo").start()
        # the winter 3x paper book (desk/winter3x.py), the same way
        if close and not account_name() and wall - self.last_winter3x_try >= COMBO_RETRY and winter3x.due(now):
            self.last_winter3x_try = wall
            threading.Thread(target=self._book, args=(winter3x, now), daemon=True, name="desk-winter3x").start()
        # scan once per slot; in live a slot starts SCAN_DELAY seconds after each bar closes
        every = st["scan_every_seconds"]
        slot = "demo-" + now if self.desk.src.demo else int((wall - SCAN_DELAY) // every)
        self.next_slot_at = wall + 5 if self.desk.src.demo else (slot + 1) * every + SCAN_DELAY
        if slot != self.last_scan_slot:
            self.last_scan_slot = slot
            s = self._safe("scan", self.desk.scan)
            if s and s.get("new_signals"):
                self.last_paper = 0.0                   # a new ready signal: auto paper looks at once
            if s:
                self.log("%s scan: %s" % (now, s.get("halt") or s.get("error") or
                                            "%d charts, %d breakouts, %d fresh, %d new signals"
                                            % (s["scanned"], s["hits"], s["fresh"], s["new_signals"])))
        # the practice account: fill paper orders the price has reached (desk/paper.py), then auto paper
        # (desk/auto.py) follows its trades and takes new ready signals. Paper mode only. Right after the scan,
        # before the monitor, so a new ready signal is taken at once.
        if st["mode"] == "paper" and wall - self.last_paper >= PAPER_EVERY:
            self.last_paper = wall
            if not self.desk.src.demo:
                self._safe("paper account", self.desk.paper.settle)
            got = self._safe("auto paper", self.desk.auto.tick)
            if got and any(got.values()):
                self.log("%s auto paper: %s" % (now, ", ".join("%d %s" % (v, k) for k, v in got.items() if v)))
        if wall - self.last_monitor >= st["monitor_every_seconds"]:
            self.last_monitor = wall
            self._safe("monitor", self.desk.monitor)

    def run(self):
        while not self.stop_flag.is_set():
            self.tick()
            self.wake.wait(max(0.05, min(5, self.next_slot_at - time.time())))   # on the slot, not up to 5 s after it
            self.wake.clear()

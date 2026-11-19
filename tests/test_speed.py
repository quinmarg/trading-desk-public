"""The speed work (docs/SPEED.md): faster, and deciding exactly as before."""
import json
import os
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from desk import engine
from desk import scheduler as SCH
from desk import settings as S
from desk.engine import Desk
from desk.journal import Journal
from desk.scheduler import Scheduler
from desk.source import Demo, Live
from tests.base import DeskCase

GOLDEN = Path(__file__).parent / "fixtures" / "demo-day-signals.json"
TIMES = ("09:50", "10:00", "10:15")
KEYS = ("qty", "entry", "limit", "stop", "target", "max_loss", "reward", "valid_until", "side")


def demo_day(compact=True):
    """Three scans of the demo day, longs and shorts. Every signal in id order: the numbers, or the whole slip."""
    S.save({"directions": "both"})
    j = Journal()
    d = Desk(j, Demo("2026-10-19 %s" % TIMES[0]))
    for t in TIMES:
        d.src.set_now("2026-10-19 %s" % t)
        d.scan()
    sigs = sorted(j.signals(limit=10000), key=lambda s: s["id"])
    j.close()
    if compact:
        return [[s["id"], s["symbol"], s["setup"], s["status"]] + [s["payload"].get(k) for k in KEYS] for s in sigs]
    return [dict(s, payload={k: v for k, v in s["payload"].items() if k != "workdir"}) for s in sigs]


class OneAtATime:
    """Stands in for ThreadPoolExecutor: runs each job at once, one after another, the way the desk did before."""
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *a, **k):
        f = Future()
        try:
            f.set_result(fn(*a, **k))
        except BaseException as e:
            f.set_exception(e)
        return f

    def map(self, fn, items):
        return [fn(x) for x in items]


class SameSignals(DeskCase):
    def test_the_demo_day_gives_the_same_signals_as_before_the_speed_work(self):
        rows = demo_day()
        if os.environ.get("DESK_WRITE_GOLDEN"):        # made once, on the code from before the speed work (c8278b9)
            GOLDEN.write_text(json.dumps(rows, indent=1) + "\n")
        self.assertGreater(len(rows), 20)
        self.assertEqual(rows, json.loads(GOLDEN.read_text()))

    def test_graded_side_by_side_is_the_same_as_one_at_a_time(self):
        fast = demo_day(compact=False)
        os.environ["DESK_DATA"] = self.tmp + "/serial"      # a second, empty data folder
        with mock.patch.object(engine, "ThreadPoolExecutor", OneAtATime):
            slow = demo_day(compact=False)
        self.assertEqual(fast, slow)

    def test_the_scan_says_how_long_each_part_took(self):
        S.save({"directions": "both"})
        j = Journal()
        self.addCleanup(j.close)
        s = Desk(j, Demo("2026-10-19 09:50")).scan()
        tm = s["timings"]
        for k in ("scanner", "longs", "short_charts", "shorts", "total"):
            self.assertGreaterEqual(tm[k], 0, k)
        self.assertIsNone(tm["after_close"])                     # the demo has no real bar close
        self.assertTrue(tm["ready"] and all(r["scan_s"] <= tm["total"] for r in tm["ready"]))
        steps = next(iter(tm["evals"].values()))
        self.assertIn("entry", steps)
        self.assertGreaterEqual(steps["total"], steps["entry"])


class JournalThreads(DeskCase):
    def test_many_threads_write_and_read_one_journal_at_once(self):
        j = Journal()
        self.addCleanup(j.close)
        errors = []

        def work(n):
            try:
                for i in range(25):
                    sym = "T%d%d" % (n, i)
                    j.add_signal("2026-10-19", sym, "orb", "ready", {"symbol": sym, "qty": i}, "2026-10-19 10:00")
                    j.put("k%d" % n, i)
                    j.add_event("signal", sym, "2026-10-19 10:00", sym, key="e-%s" % sym)
                    j.has_signal("2026-10-19", sym, "orb")
                    j.signals(date="2026-10-19")
            except Exception as e:                                 # noqa: BLE001 - the test reports any failure
                errors.append(e)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(j.signals(limit=10000)), 200)
        self.assertEqual([j.get("k%d" % n) for n in range(8)], [24] * 8)
        self.assertEqual(len(j.events(limit=1000)), 200)


class At(Live):
    def now(self):
        return "2026-10-19 10:00"


class SchedulerSpeed(DeskCase):
    def setUp(self):
        super().setUp()
        S.save({"catalysts": False, "analyst": False})
        self.j = Journal()
        self.addCleanup(self.j.close)
        self.d = Desk(self.j, At())
        self.calls = []
        self.d.scan = lambda: self.calls.append("scan") or {"new_signals": 1, "scanned": 1, "hits": 1, "fresh": 1}
        self.d.monitor = lambda: self.calls.append("monitor")
        self.d._paper = SimpleNamespace(settle=lambda: self.calls.append("settle"))
        self.d._auto = SimpleNamespace(tick=lambda: self.calls.append("auto") or {})
        self.sch = Scheduler(self.d, log=lambda *_: None)
        self.sch.premarket_day = "2026-10-19"

    def test_a_slot_starts_scan_delay_seconds_after_the_bar_closes(self):
        self.sch.tick(wall=30000 + 60)                     # the 30000 bar closed a minute ago: its slot runs now
        self.assertEqual(self.sch.next_slot_at, 30300 + SCH.SCAN_DELAY)
        self.sch.tick(wall=30300 + SCH.SCAN_DELAY - 0.5)
        self.assertEqual(self.calls.count("scan"), 1)
        self.sch.tick(wall=30300 + SCH.SCAN_DELAY)
        self.assertEqual(self.calls.count("scan"), 2)

    def test_auto_paper_takes_a_new_signal_before_the_monitor_runs(self):
        self.sch.tick(wall=30000 + 60)
        self.assertEqual(self.calls, ["scan", "settle", "auto", "monitor"])

    def test_the_hourly_catalysts_never_hold_up_a_scan(self):
        S.update({"catalysts": True})
        started, release = threading.Event(), threading.Event()
        self.d.find_catalysts = lambda: (started.set(), release.wait(10))
        self.sch.tick(wall=30000 + 60)                     # returns while the gather is still running
        self.assertTrue(started.wait(5))
        self.assertIn("scan", self.calls)
        release.set()

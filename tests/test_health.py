from desk import health, skills
from desk import settings as S
from tests.test_desk import DemoCase

CLOCK = {"open": True, "reason": "regular hours", "date": "2026-10-19", "next_open": "2026-10-20 09:30", "phase": "open"}


class Check(DemoCase):
    def run_check(self, last_scan, streak=0, halt=None, now="2026-10-19 10:15", clock=CLOCK, demo=False, **st):
        d = self.desk(**st)
        return health.check(now, clock, S.load(), last_scan, streak, halt, demo, d.j.path, skills.TOOLS)

    def item(self, h, name):
        return next(i for i in h["items"] if i["name"] == name)

    def test_all_well(self):
        h = self.run_check({"at": "2026-10-19 10:15", "scanned": 290, "failed": 0, "error": None, "halt": None})
        self.assertEqual((h["level"], h["trust"], h["headline"]), ("ok", None, "Everything is working."))
        self.assertIn("290 charts read", self.item(h, "Scanner")["detail"])
        self.assertIn("pinned at 3d0f4ef", self.item(h, "Skills")["detail"])
        self.assertIn("PAPER record, journal.db", self.item(h, "Record")["detail"])

    def test_one_failed_scan_warns_three_in_a_row_say_do_not_trust(self):
        bad = {"at": "2026-10-19 10:15", "scanned": 0, "error": "Scanner: no reply", "halt": None}
        self.assertEqual(self.run_check(bad, streak=1)["level"], "warn")
        h = self.run_check(bad, streak=3)
        self.assertEqual(h["level"], "bad")
        self.assertTrue(h["trust"].startswith("Do not trust the list right now."))

    def test_a_stuck_scanner_and_missing_charts_warn(self):
        old = self.run_check({"at": "2026-10-19 09:50", "scanned": 290, "failed": 0, "error": None, "halt": None})
        self.assertIn("25 minutes ago", self.item(old, "Scanner")["detail"])
        self.assertEqual(old["level"], "warn")
        holes = self.run_check({"at": "2026-10-19 10:14", "scanned": 20, "failed": 10, "error": None, "halt": None})
        self.assertIn("10 of 30 charts did not load", self.item(holes, "Scanner")["detail"])
        empty = self.run_check({"at": "2026-10-19 10:14", "scanned": 0, "failed": 0, "error": None, "halt": None})
        self.assertIn("read 0 charts", self.item(empty, "Scanner")["detail"])

    def test_charts_left_out_for_gaps_in_the_data_warn(self):
        # Seen live on 2026-11-11: the scanner drops a chart with any missing 5-minute candle, and says so
        # only in its counts. 15 of 29 were dropped while the health card said everything was working.
        h = self.run_check({"at": "2026-10-19 10:14", "scanned": 14, "failed": 0, "unusable": 15, "error": None, "halt": None})
        self.assertEqual(self.item(h, "Scanner")["level"], "warn")
        self.assertIn("15 of 29 charts", self.item(h, "Scanner")["detail"])
        self.assertIn("gaps", self.item(h, "Scanner")["detail"])
        few = self.run_check({"at": "2026-10-19 10:14", "scanned": 28, "failed": 0, "unusable": 1, "error": None, "halt": None})
        self.assertEqual(self.item(few, "Scanner")["level"], "ok")
        self.assertIn("1 left out for gaps", self.item(few, "Scanner")["detail"])

    def test_the_scan_summary_carries_the_left_out_count(self):
        s = self.desk().scan()
        self.assertIsInstance(s.get("unusable"), int)

    def test_a_halt_is_not_a_fault(self):
        h = self.run_check(None, halt="The market is closed (weekend).")
        self.assertEqual(self.item(h, "Scanner")["level"], "ok")
        self.assertEqual(h["level"], "ok")

    def test_a_dead_clock_and_demo_data_are_flagged(self):
        h = self.run_check(None, halt="x", clock={"open": False, "reason": "alerts took longer than 30 seconds", "date": "2026-10-19"})
        self.assertEqual(self.item(h, "Market clock")["level"], "bad")
        self.assertEqual(self.item(self.run_check(None, halt="x", demo=True), "Market data")["level"], "warn")

    def test_missing_tools_are_named(self):
        tools = dict(skills.TOOLS, ghost="trader-ghost/ghost.py")
        self.assertEqual(health.missing_skills(tools), ["ghost"])
        self.assertEqual(health.missing_skills(skills.TOOLS), [])


class Streak(DemoCase):
    def test_counts_failures_in_a_row_and_ignores_halts(self):
        d = self.desk()
        fail = {"error": "Scanner: no reply", "scanned": 0, "halt": None}
        self.assertEqual([health.note_scan(d.j, fail) for _ in range(3)], [1, 2, 3])
        self.assertEqual(health.note_scan(d.j, {"halt": "The market is closed.", "scanned": 0}), 3)     # not a scan
        self.assertEqual(health.note_scan(d.j, {"error": None, "scanned": 12, "halt": None}), 0)

    def test_a_real_scan_resets_it_and_state_carries_health(self):
        d = self.desk()
        d.j.put("scan_fail_streak", 5)
        d.scan()
        self.assertEqual(d.j.get("scan_fail_streak"), 0)
        h = d.state()["health"]
        self.assertEqual(h["level"], "warn")                         # demo data is the one note
        self.assertIsNone(h["trust"])
        self.assertEqual([i["name"] for i in h["items"]], ["Market clock", "Scanner", "Market data", "Skills", "Record"])


class Calendar(Check):
    def test_a_year_past_the_holiday_calendar_warns(self):
        h = self.run_check({"at": "2028-01-03 10:15", "scanned": 290, "failed": 0, "error": None, "halt": None},
                           now="2028-01-03 10:15", clock=dict(CLOCK, date="2028-01-03", calendar_known=False))
        self.assertEqual(self.item(h, "Market clock")["level"], "warn")
        self.assertIn("does not cover 2028", self.item(h, "Market clock")["detail"])

    def test_the_vendored_clock_matches_the_nyse_calendar(self):
        # NYSE's 2026-2028 holiday and early-close release (2025-12-23), checked against NYSE's published calendar.
        want = {"2026-11-26 12:00": (False, None), "2026-11-27 12:00": (True, "13:00"), "2026-12-24 12:00": (True, "13:00"),
                "2026-12-25 12:00": (False, None), "2027-11-26 12:00": (True, "13:00"), "2027-12-24 12:00": (False, None),
                "2026-11-30 12:00": (True, "16:00")}
        for now, (opens, closes) in want.items():
            c = skills.run("alerts", ["clock", "--json", "--now", now], self.tmp).json
            self.assertEqual((c["open"], c.get("closes")), (opens, closes), now)
            self.assertTrue(c["calendar_known"], now)

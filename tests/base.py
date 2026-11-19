import os
import shutil
import tempfile
import unittest
from unittest import mock

from desk import autolist
from desk import settings as S


class DeskCase(unittest.TestCase):
    """Every test gets its own empty data folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="desk-test-")
        os.environ["DESK_DATA"] = self.tmp
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(os.environ.pop, "DESK_DATA", None)
        # the tests check your own limits; paper mode's bold profile has its own test (test_settings.PaperBold)
        patcher = mock.patch.dict(S.PAPER_BOLD, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        scr = mock.patch.dict(S.PAPER_SCREEN, {"min_rvol": 0.0, "min_atr_pct": 0.0})   # test_volscreen covers it
        scr.start()
        self.addCleanup(scr.stop)
        # no test reads a year of daily bars for 90 stocks; test_autolist drives the pick with fake data
        pick = mock.patch.object(autolist, "pick", side_effect=lambda st, now, *a, **k: {
            "date": now[:10], "at": now, "symbols": [], "looked_at": 0, "left_out": {}, "error": "not in tests"})
        pick.start()
        self.addCleanup(pick.stop)
        # and no test reads the live news; test_catalysts drives the gather with fake sources
        from desk import catalysts
        cat = mock.patch.object(catalysts, "gather", side_effect=lambda st, now, *a, **k: {
            "date": now[:10], "at": now, "items": [], "errors": ["not in tests"], "counts": {}})
        cat.start()
        self.addCleanup(cat.stop)
        # and no test asks Claude for a game plan; test_analyst drives it with a fake Claude
        from desk import analyst
        for name in ("morning", "update"):
            p = mock.patch.object(analyst, name, side_effect=RuntimeError("not in tests"))
            p.start()
            self.addCleanup(p.stop)
        # and no test reads SPY's daily chart for the combined book; test_combo drives it with fake bars
        from desk import combo
        cb = mock.patch.object(combo, "fetch", side_effect=RuntimeError("not in tests"))
        cb.start()
        self.addCleanup(cb.stop)
        from desk import winter3x
        w3 = mock.patch.object(winter3x, "fetch", side_effect=RuntimeError("not in tests"))
        w3.start()
        self.addCleanup(w3.stop)
        lev = mock.patch.object(S, "PAPER_LEVERAGE", 1.0)        # and plain cash; test_settings.PaperBold covers 4x
        lev.start()
        self.addCleanup(lev.stop)

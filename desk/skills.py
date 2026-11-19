"""Adapter for the day-trader-skill tools (vendor/day-trader-skill, pinned).

Each tool is a stand-alone script that reads and writes a trader/ folder in
its working directory. The desk gives every symbol its own working directory
so two candidates never share entry.json / plan.json / orders.json, and runs
the scripts as subprocesses with the same Python that runs the desk.
"""
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import guards
from .paths import VENDOR

TOOLS = {
    "scanner": "trader-scanner/scan.py", "news": "trader-news/news.py",
    "entry": "trader-entry/entry.py", "exit": "trader-exit/exit.py",
    "timemachine": "trader-timemachine/timemachine.py", "risk": "trader-risk/check.py",
    "budget": "trader-budget/size.py", "broker": "trader-broker/ticket.py",
    "alerts": "trader-alerts/alerts.py", "analyst": "trader-analyst/facts.py",
    "pelosi": "trader-pelosi/ptr.py",
}


class Result:
    def __init__(self, tool, rc, out, err):
        self.tool, self.rc, self.out, self.err = tool, rc, out, err
        self.json = None
        s = out.strip()
        if s[:1] in "{[":
            try:
                self.json = json.loads(s)
            except ValueError:
                pass

    @property
    def message(self):
        """The tool's own words when it refuses: last non-empty line of stderr, else stdout."""
        for text in (self.err, self.out):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                return lines[-1][:400]
        return "%s exited with code %d" % (self.tool, self.rc)


_timing = threading.local()


@contextmanager
def timed():
    """{tool: seconds} for every tool this thread runs inside the block: the scan's timings (docs/SPEED.md)."""
    prev = getattr(_timing, "steps", None)
    _timing.steps = steps = {}
    try:
        yield steps
    finally:
        _timing.steps = prev


def run(tool, args, cwd, timeout=180):
    guards.check_command(tool, args)          # broker: 'show' only
    script = VENDOR / TOOLS[tool]
    Path(cwd).mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(script)] + [str(a) for a in args]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return Result(tool, p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return Result(tool, 124, "", "%s took longer than %d seconds" % (tool, timeout))
    finally:
        steps = getattr(_timing, "steps", None)
        if steps is not None:
            steps[tool] = round(steps.get(tool, 0) + time.perf_counter() - t0, 3)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    tmp.replace(path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default

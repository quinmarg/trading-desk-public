"""Is the desk itself working? A beginner cannot tell a quiet market from a
broken program, so this says which it is. The video's checklist before each
cycle: data fresh, the account known, limits not reached, and stop trusting
the output after repeated failures.

check() is a plain function over facts the engine already has. It reads; it
never fixes, retries or changes anything.
"""
import os

from .paths import ROOT, VENDOR

FAILS_BEFORE_DISTRUST = 3
OK, WARN, BAD = "ok", "warn", "bad"
_RANK = {OK: 0, WARN: 1, BAD: 2}


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def scan_failed(summary):
    """A scan that ran and got nothing usable. A halt (market closed, paused) is not a failure."""
    if not summary or summary.get("halt"):
        return None
    return bool(summary.get("error")) or not summary.get("scanned")


def note_scan(journal, summary):
    """Keeps the count of failed scans in a row."""
    failed = scan_failed(summary)
    if failed is None:
        return journal.get("scan_fail_streak", 0)
    streak = journal.get("scan_fail_streak", 0) + 1 if failed else 0
    journal.put("scan_fail_streak", streak)
    return streak


def missing_skills(tools):
    return sorted(name for name, rel in tools.items() if not (VENDOR / rel).is_file())


def pinned_commit():
    try:
        return (ROOT / "vendor" / "PINNED_COMMIT").read_text().strip()
    except OSError:
        return ""


def check(now, clock, st, last_scan, streak, halt, demo, journal_path, tools):
    items = []
    add = lambda name, level, detail: items.append({"name": name, "level": level, "detail": detail})

    # 1. the market clock (the Price Alerts skill)
    if len(clock or {}) <= 3:
        add("Market clock", BAD, "The clock tool did not answer: %s" % ((clock or {}).get("reason") or "no reply"))
    elif clock.get("calendar_known") is False:
        add("Market clock", WARN, "The holiday calendar in vendor/day-trader-skill does not cover %s, so NYSE holidays and "
                                  "early closes this year are unknown: the desk may treat a holiday as a trading day. "
                                  "Update the skills copy." % now[:4])
    else:
        add("Market clock", OK, "Market open." if clock.get("open") else "Market closed (%s)." % (clock.get("reason") or "closed"))

    # 2. the scanner
    every_min = st["scan_every_seconds"] / 60.0
    today = bool(last_scan) and str(last_scan.get("at", ""))[:10] == now[:10]
    if halt:
        add("Scanner", OK, "Not scanning: %s" % halt)
    elif not today:
        add("Scanner", WARN, "No scan yet today. The first one runs within %d minutes of the desk starting." % max(1, round(every_min)))
    else:
        age = _minutes(now[11:16]) - _minutes(last_scan["at"][11:16])
        gaps = last_scan.get("unusable") or 0       # left out by the scanner: a candle is missing from the free data
        total = (last_scan.get("scanned") or 0) + (last_scan.get("failed") or 0) + gaps
        if last_scan.get("error"):
            add("Scanner", BAD if streak >= FAILS_BEFORE_DISTRUST else WARN, "Last scan failed: %s" % last_scan["error"])
        elif not last_scan.get("scanned") and not last_scan.get("halt"):
            add("Scanner", BAD if streak >= FAILS_BEFORE_DISTRUST else WARN, "Last scan read 0 charts. The data source may be down.")
        elif age > 2 * every_min + 2:
            add("Scanner", WARN, "Last scan was %d minutes ago; it should run every %d. The desk may be stuck: restart it." % (age, round(every_min)))
        elif total and (last_scan.get("failed") or 0) > 0.2 * total:
            add("Scanner", WARN, "%d of %d charts did not load in the last scan. Breakouts on those are being missed." % (last_scan["failed"], total))
        elif total and gaps > 0.2 * total:
            add("Scanner", WARN, "%d of %d charts were left out of the last scan for gaps in the free price data. "
                                 "Breakouts on those are being missed." % (gaps, total))
        else:
            add("Scanner", OK, "Last scan %d minute%s ago: %d charts read%s%s." % (age, "" if age == 1 else "s", last_scan.get("scanned") or 0,
                                                                                ", %d did not load" % last_scan["failed"] if last_scan.get("failed") else "",
                                                                                ", %d left out for gaps in the data" % gaps if gaps else ""))
    if streak >= FAILS_BEFORE_DISTRUST:
        add("Failed scans in a row", BAD, "%d. The desk is blind until one works." % streak)

    # 3. data
    add("Market data", WARN if demo else OK,
        "Demo: saved data from 2026-10-19, not today's market." if demo else
        "Free public data, delayed. A signal needs a breakout candle from the last %d minutes, so stale data cannot make one. "
        "Still check the price at your broker." % st["signal_valid_minutes"])

    # 4. the skills copy
    gone, pin = missing_skills(tools), pinned_commit()
    if gone:
        add("Skills", BAD, "Missing tool scripts: %s. Restore vendor/day-trader-skill." % ", ".join(gone))
    else:
        add("Skills", OK if pin else WARN, "All %d tools present, pinned at %s." % (len(tools), pin[:7]) if pin else
            "All tools present, but vendor/PINNED_COMMIT is missing.")

    # 5. the record
    p = str(journal_path)
    writable = os.path.exists(p) and os.access(p, os.W_OK) and os.access(os.path.dirname(p) or ".", os.W_OK)
    add("Record", OK if writable else BAD,
        "%s record, %s." % (st["mode"].upper(), os.path.basename(p)) if writable else "The journal file cannot be written: %s" % p)

    level = max((i["level"] for i in items), key=_RANK.get)
    bad = [i for i in items if i["level"] == BAD]
    trust = None
    if bad:
        trust = "Do not trust the list right now. %s: %s" % (bad[0]["name"], bad[0]["detail"])
    headline = {OK: "Everything is working.", WARN: "Working, with something to know.", BAD: "Something is broken."}[level]
    return {"level": level, "headline": headline, "trust": trust, "items": items, "checked_at": now}

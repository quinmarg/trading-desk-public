# Speed: from a candle close to a ready slip

Measured on 2026-11-19 on a Mac with 10 cores (4 of them fast), on that day's live Yahoo data, with one desk's settings:
40 stocks on the list, longs and shorts, 10,000 Time Machine replays. Nothing here changes what the rules decide;
the same inputs give the same signals, sizes, stops and targets (proved below).

## The short version

| | Before | After |
|---|---|---|
| Scan starts after the 5-minute candle closes | 25 s, plus up to 5 s for the loop to wake | 25 s, on the second (shorter is not safe, see below) |
| Busiest scan of the day (9:50, 12 fresh breakouts, 8 graded, 1 short) | **56.1 s** | **9.4 s** |
| A quieter scan (10:10, 4 breakouts graded, 7 shorts graded) | 58.2 s | 13.5 s |
| First ready slip saved and phone alert sent, seconds into the 9:50 scan | 17.4 s | 9.2 s |
| ... seconds after the candle closed (start + scan time) | about 45 s (25 + up to 5 + 17.4) | about 34 s (25 + 9.2) |
| Last of 8 longs graded at 9:50, after the candle closed | about 55 s | about 34 s |
| Auto paper places the practice order, after the candle closed | 81 to 86 s or more (after the whole scan, then the monitor's own tool runs) | about 35 s (straight after the scan) |
| Hourly catalyst gather blocking the scan loop | 18.6 s, once an hour | 0 s (own thread) |
| `/api/state` on a real journal (every 10 s poll) | 3.4 ms | unchanged (already fast) |
| `/api/chart` (one Yahoo read) | 0.2 to 0.3 s | unchanged |

## How it was measured

Every scan now carries a `timings` dict (saved with the scan in the journal, so the review can read it):

```
"timings": {"after_close": 15.2,        # seconds after the candle closed that the scan started (live only)
            "scanner": 4.51,            # the Chart Scanner finished, seconds into the scan
            "short_charts": 1.87,       # every short-side chart read
            "longs": 9.35, "shorts": 9.35, "total": 9.35,
            "evals": {"PDD": {"entry": 0.33, "exit": 0.11, "timemachine": 2.76, "budget": 0.09,
                              "risk": 0.11, "broker": 0.14, "news": 0.42, "total": 4.72}, ...},
            "ready": [{"symbol": "PDD", "side": "long", "scan_s": 9.23, "after_close": 24.4}]}
```

`skills.timed()` collects each tool's seconds in the thread that ran it.

The live numbers come from replaying today's 9:50 and 10:10 scans on live Yahoo data with the clock pinned
(a throwaway replay script, a throwaway data folder, alerts off). The demo numbers come from `python3 -m desk`'s
demo day (no network, no Time Machine, so it shows the threading but not the network).

## Where the time went (before)

The 9:50 scan, live:

| Part | Seconds | Why |
|---|---|---|
| Chart Scanner | 10.9 (7 to 26 over the day) | Yahoo spark for 40 stocks, then one chart per candidate with a 0.3 s pause between them |
| 8 fresh breakouts graded one after another | 26.4 | about 3.3 s each: Time Machine 1.7 to 2.0 (1.4 maths, 0.4 reading 60 days), news 0.35, entry 0.25, the rest 0.05 to 0.1 each |
| Short side: 40 charts read one by one, 0.2 s apart | 15.7 (16 to 78 over the day) | one Yahoo read at a time; the 78 s run had two reads that hung until their timeout |
| 1 short graded | 3.0 | Time Machine again |
| **Total** | **56.1** | the first ready slip (PDD) was saved 17.4 s in |

Then auto paper: it ran only after the whole scan, and after the monitor in the same loop pass.

## What changed

1. **Graded side by side.** Each fresh breakout (and breakdown) goes through the pipeline in its own thread; the
   tools are separate processes, so they really run at once. Eight Time Machines at once take 2.6 s wall time
   instead of 11.6 s one after another. Signals are still saved, graded by Claude's plan and alerted one by one in
   the old order, longs first, so signal ids, and so auto paper's order, are exactly as before.
2. **Short-side charts read 4 at a time, while the Chart Scanner runs.** 40 charts in about 2.5 s instead of 16 s
   or more, and done before the scanner is. The shorts are graded during the scanner too.
3. **No pause between the scanner's chart reads** (`--pause 0`). Same charts, same answer; 21 candidates took
   6.8 s instead of 16.3 s in back-to-back runs. No Yahoo refusals (429) seen in any run today.
4. **The loop wakes on the second the scan slot starts** instead of checking every 5 s (it lost up to 5 s).
   The slot itself still starts 25 s after the close (`SCAN_DELAY`); see "Is the candle final?" below.
5. **Auto paper right after the scan**, before the monitor, so a new ready signal becomes a
   practice order straight away.
6. **The hourly catalyst gather runs in its own thread**, like Claude's game plan, so its 18.6 s never lands on
   a scan slot. (The 8:00 one still runs inside the pre-market job, before the first scan at 9:45.)

## Is the candle final? (the delay)

No: 25 s stays. Two probes read the just-closed bar again and again after each close and counted how many
bars still changed afterwards (final = the read at +75 s).

First probe, 6 stocks, 12:30 to 12:40: final at +1 to +5 s. That looked like room to start at 15 s. The second
probe, all 40 list stocks read 4 at a time, five closes from 12:55 to 13:25, says otherwise:

| Read at, after the close | 12:55 | 13:00 | 13:05 | 13:20 | 13:25 |
|---|---|---|---|---|---|
| +4 s: bars whose price still changed later | 13 | 3 | 5 | 9 | 12 |
| +13 s | 5 | 0 | 0 | 1 | 2 |
| +16 s | 3 | 0 | 0 | 1 | 2 |
| +25 s (the delay in use) | 2 | 0 | 0 | 1 | 2 |
| +40 s | 1 | 0 | 0 | 0 | 2 |

(At 13:20 and 13:25 the reads ran late, so "+16 s" was really read 31 and 24 s in.) Yahoo keeps adjusting a few
bars for up to a minute. Spark, the scanner's first pass, was worse: 18 to 20 of 40 stocks missing from some reads.
A changed high or close can change whether a breakout counts, so starting at 15 s would trade speed for wrong
signals. 25 s is not fully final either, but it is what the desk has always used and shortening it makes it
worse. The time saved now comes from doing the scan faster, not from starting it sooner.

## What was left alone, and why

- **Time Machine replays stay at 10,000.** The odds are seeded and identical run to run, and with grading side by
  side the replays are no longer the long pole.
- **No cache of the 60-day history.** It includes today's bars, so a cache would change the Time Machine's inputs.
  Reading it costs 0.4 s and now overlaps with the other gradings.
- **News stays where it is in the pipeline.** The phone alert carries the headlines and the earnings warning;
  moving news after the alert would change what the alert says, and running it early would fetch news for
  setups that end up blocked. It costs about 0.4 s a grading.
- **The pre-market job (8:00) still runs in the loop.** The day's list comes from it, and a scan before it is done
  would use the watchlist instead, which would change what is scanned.
- **`/api/state` and the dashboard.** State is built in 3.4 ms from a real journal (199 KB of JSON); the page,
  chart library and fonts are local files; the chart reloads at most once every 55 s. Nothing worth changing.

## Left for you to decide

- **Let the scanner read the charts the desk already has.** The desk now reads every list stock's 5-minute chart
  at the start of each scan for the short side. Handing those same charts to the Chart Scanner (`--offline`) makes
  its part 0.1 s instead of 5 to 26 s. But it is not the same input: the scanner's first pass uses Yahoo's "spark"
  data, which often drops a candle, and then it skips the stock for that scan ("unusable" in the scan log, 1 to 12
  stocks in most scans this week). With the full charts it sees them. In today's 12:29 test that found one more
  breakout (RUN, 9:50) than the live scanner. So it is faster and sees more, but it changes which breakouts the
  desk finds. Say if you want it.
- **The delay after the close (25 s).** Measured only at midday. If you want the open checked (9:45 to 10:15,
  the busiest bars), the probe can run tomorrow morning; it might argue for a longer delay, not a shorter one.

## Proof it decides the same

- `tests/test_speed.py` runs three demo scans (9:50, 10:00, 10:15, longs and shorts) and checks every signal's id,
  symbol, setup, status, size, entry, limit, stop, target, max loss, reward and good-until against
  `tests/fixtures/demo-day-signals.json`, which was made by the code from before this work (1.2.1).
- The same test runs the day again with the thread pool swapped for one-at-a-time and checks every slip, field by
  field, is identical.
- The full demo day (10 scans, 95 signals) gave the same fingerprint before and after (`c31441df27e8de3e`), and
  today's live 9:50 and 10:10 replays gave the same 19 signals with the same statuses.
- The journal (one SQLite connection behind one lock) is hammered by 8 threads at once in a test.

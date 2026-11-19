# Models: the combined SPY book, the opening-range check, and the entry-style A/B

Written 2026-11-19 after a friend's research handoff (his fork, branch `desk-upgrades`, commit `e403783`, on
his computer). His GitHub fork has an older push of that branch (`667c6cd`, round 3 of his model lab): it
has `research/model/lab.py` and his first ORB backtest, but not `desk/combo.py` or `entry_timing.py`. So the
combined model here is rebuilt from his handoff's description, and his round-5 numbers are quoted from the
handoff, not rerun. Nothing in this file is advice. Paper first, free data only, and no rule changes
without you deciding.

## 1. The combined SPY model (a second paper book)

**What it is.** Three votes on SPY, each 0 or 1; the book holds their average:

| vote | in when |
| --- | --- |
| dip-buyer | SPY closed above its 200-day average, or it is in a dip: RSI(2) under 10, held until a close back over the 5-day average |
| Halloween | November to April, or above the 200-day average |
| turn of month | the last trading day of a month or the first 3 of the next, or above the 200-day average |

So above the 200-day average it is all in. Below it, each vote counts on its own: 0, 1/3, 2/3 or all in.

**What the friend's lab found** (quoted from his handoff, not rerun here):

| 2000–2026 | combined | SPY |
| --- | --- | --- |
| a year (CAGR) | 7.07 % | 8.00 % |
| Sharpe | 0.61 | 0.50 |
| worst drop | −31 % | −55 % |
| 7 fresh markets | better Sharpe in 6 of 7, smaller drop in 7 of 7 | |

It gives up about 1 point a year for about half the worst crash. **Most of this is in-sample.** He says so
himself: every choice after round 1 was made with 2021–2026 in view, and no result passed his multiple-testing
check (best deflated-Sharpe p 0.82 against 0.95 needed). His cash earned 0 % and his index tests used price
indices, which bias against a timing model by roughly 1 % a year each way. The only clean test left is
forward, which is why it runs here as a paper book.

**How this desk runs it** (`desk/combo.py`; fixes from his handoff, section 5):

- **Adjusted closes.** Signals use Yahoo's `adjclose` (`events=div,split`), as his research did. His desk
  copy used raw closes. The book is kept in real SPY prices and pays dividends in cash on the ex-date;
  buy-and-hold SPY reinvests them, so the comparison is total return against total return.
- **The desk's own NYSE calendar.** The vendored holiday list (2026–27) where it exists; past 2027 the
  standing NYSE rules are computed (a test checks they give the vendored list exactly for 2026 and 2027, and
  the published 2025 list). One-off closures cannot be computed; for past days Yahoo's own daily bars are
  the record.
- **Backfill.** Days the desk was off are filled at that day's open and marked "backfill".
- **Real fill time.** Today fills at the first price Yahoo gives after the book runs (from 9:35 New York),
  not at an open that is already past. A run at noon fills at noon's price.
- 3 basis points a side, fractional shares, $10,000 to start, trades only when the weight changes. A look
  after 4:05 marks the day at its close. Paper only: it has no path to an order.

**It already disagrees with his book, on day one.** On 2026-11-18 SPY closed at $730.20. Its 200-day average
was $730.02 on adjusted closes (above: all in) and $732.55 on raw closes (below). So this book's first day,
2026-11-19, is 100 % in SPY, and his book opened at 1/3. That is his section 5 problem #2. One more
difference: his 1/3 means his dip vote was out that day, but RSI(2) was 4.4 (a dip) under the raw average,
which by the rule as written gives 2/3. So his dip vote probably counts only above the 200-day average (in
his lab the round-3 dip rule lived inside the bull branch). This desk follows the rule as written. **Worth
asking him which one his sealed tests used.** If his is the bull-only version, his results do not cover
this rule exactly.

**How to judge it.** Against buy-and-hold SPY, after 6 to 12 months, on both return and worst drop. A few
weeks of a daily model say nothing: the lab's edge is in rare crashes, and there may not be one in a year.

## 2. "The opening-range model loses": his test against this desk's

**The short answer: both are right, about different rules.** The plain opening-range breakout loses on free
data in both desks. This desk's in-play screen turns it slightly positive, but no test here, his or ours, is
sure of that yet.

**What was run** (read-only, rules unchanged): `tools/vol_backtest.py fetch` and `rows --name base` on
2026-11-19, into a scratch folder, not the desk's `data/`. Yahoo's free 5-minute bars, 88 stocks (the desk's pool),
45 sessions, 2026-09-17 to 2026-11-18, 3,392 signals. The desk's slip and replay; costs $0.01 a share, and
5 basis points a side where marked. The split is the one `docs/VOLATILITY.md` fixed (ticker half A before
2026-10-27 = training). The 95 % ranges resample whole days (signals on one day move together).

| slice | trades | average R | profit factor | 95 % range, average R |
| --- | --- | --- | --- | --- |
| held-out, every signal, no screen | 2,214 | −0.059 | 0.89 | −0.18 to +0.06 |
| held-out, no screen, longs | 1,294 | −0.083 | 0.84 | −0.23 to +0.08 |
| held-out, in play (rvol ≥ 1.5x, ATR ≥ 3 %) | 320 | **+0.113** | **1.28** | −0.05 to +0.26 |
| same, 5 bp a side | 320 | +0.063 | 1.15 | −0.10 to +0.21 |
| held-out, in play, longs / shorts | 194 / 126 | +0.165 / +0.032 | 1.43 / 1.07 | |
| strict (other stocks, later days), in play | 93 | +0.072 | 1.15 | −0.26 to +0.33 |
| fresh: 2026-11-18, the one session after the doc's data | 2 in play (83 all) | −0.38 (−0.46 all) | | one day |

It reproduces `docs/VOLATILITY.md` within a few hundredths (+0.110R, PF 1.27 on 321 trades there); the window
moved by a few days. Unscreened longs lost on 32 of 45 sessions. In-play trades lost on 23 and won on 22.

**Where the two agree**

- **The plain rule loses.** His base model lost over his 39 sessions (expectancy −0.23R in tuning, −0.63R on his
  8 locked days). Here every unscreened slice is negative too (−0.04R to −0.08R before slippage).
- **Buys land at the top of the day.** He found the median buy at the 95th percentile of the day's range so far.
  Here it is the 96th for every long and the 95th for in-play longs. A breakout entry is, by construction, a buy at
  the high.
- **Nothing is settled.** His bootstrap range ran from −0.93 % to +0.39 % a day (p 0.47). Here every 95 % range
  crosses zero, the in-play one included.

**Where they disagree, and why**

| | his backtest | this desk's |
| --- | --- | --- |
| universe | 212 stocks: daily movers (top volume, gainers, losers) plus a core list | 88 liquid stocks, calm and wild mixed |
| screen | none in the base; his "volume" variant is the breakout candle's volume (`min_volume_x` 1.5) | opening-range relative volume ≥ 1.5x **and** ATR ≥ 3 % (the stocks-in-play paper's filter) |
| account | $400 and $2,000 cash, whole shares, T+1, risk stops, one trade at a time | every signal scored alone, in R |
| costs | `est_cost_per_share` + $0.01 a side, cash-deducted | $0.01 a share (+5 bp a side shown) |
| odds floor | the Time Machine at 10,000 paths | not used for these rows (every signal) |
| period | 2026-09-25 to 11-18 (39 sessions) | 2026-09-17 to 11-18 (45) |

The big one is the screen. His "1.5x volume" test is a different filter: the breakout candle's volume, not the
opening range's volume against its own 14-day normal, and it had 3 locked trades. The in-play screen is what the
Zarattini paper says carries the edge, and it is what the desk's paper mode uses since 2026-11-18. His account
simulation is also harsher and more real (whole shares on $400, cash tied up, one position), which costs good
trades the R-per-signal view counts. So: **his result is the right verdict on the unscreened, live-default rule;
it says little about the in-play rule paper mode runs now**, which he did not test.

**How sure anyone can be**

- About 40 to 45 sessions of one autumn, from one free source, on today's tickers (survivorship). The 95 % ranges
  say a true edge of zero is still quite possible for the in-play rule.
- The in-play screen was chosen on part of this data (training half, 2026-11-18). The held-out half was looked at
  once then. Only 2026-11-18 is new, with 2 in-play trades. Forward paper is the real test; at +0.1R a trade it
  takes roughly 150 to 300 trades to tell it from zero.
- Outside evidence: a cost-realistic replication of the ORB rule on five index markets found the gross result
  but nothing significant net of spread and slippage
  ([mql5 blog](https://www.mql5.com/en/blogs/post/776235)); the stocks-in-play paper charges commission but not
  slippage ([paper](https://alexandria.unisg.ch/handle/20.500.14171/122125),
  [QuantConnect recreation](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)),
  and one trader's IBKR paper fills came in a median 0.47R worse than the level
  ([QuantConnect forum](https://www.quantconnect.com/forum/discussion/21585/breakout-entries-on-us-stocks-eat-most-of-the-edge-how-do-you-cut-entry-cost/)).
  At +0.06R after 5 bp, real entry slippage alone can erase this desk's edge. The review's "plan against what
  happened" fill line is the number to watch.

## 3. The entry-style A/B (shadow, logging only)

His entry-timing study replayed his 56 base trades with other entries, the same stop and target:
breakout −13.8R, 0.25R pullback −11.3R, 0.5R pullback −10.6R, opening-range retest −9.2R, VWAP −6.0R. His
day-block bootstrap showed none reliably better. This desk now collects the same comparison forward:

- **What is logged** (`desk/outcome.shadow`, journal table `shadow`): after the close, for each long slip that
  was good to buy (ready, taken, skipped or expired), two more replays on the day's candles. One puts the buy
  limit at the session VWAP when the trigger candle closed, the other at the opening-range high (a retest).
  Same stop and target as the slip, never a higher limit than the slip's, resting 60 minutes from the trigger.
- **Declared before any data:** these two arms, the 60-minute window, and the units: R in the real slip's
  own risk (limit − stop), so every arm counts the same shares. Changing any of these later restarts the count.
- **What it does not do:** it changes no signal, size or fill, and auto paper never sees it. Shorts are not
  logged (the desk's short side is paper-only and rare).
- **Reading it.** The review's "ENTRY STYLE A/B" section lists each arm: signals, fills, never-filled, total and
  average R. It waits for 20 trading days. Even then, look at the spread: a pullback arm that fills half as
  often can look better on average because it skips the trades that ran away. Those were often winners.

## 4. Combining the evidence: the friend's labs, this desk's docs and outside sources

| question | friend's research | this desk (`docs/STRATEGIES.md`, `docs/VOLATILITY.md`) | outside | stronger evidence |
| --- | --- | --- | --- | --- |
| Does the ORB rule make money? | No, 39 sessions, unscreened | Unscreened no; in play +0.11R, not significant | Paper: yes for stocks in play, no slippage; index replication: no net | Neither proves it. The unscreened "no" is solid; the in-play "yes" is a hint |
| Pullback entries (VWAP, retest)? | Lose less on a losing base | On in-play longs, VWAP limits fill 36 of 195 slips, ~0R; retest fills 154, 26R against the slip's 32R | Entry slippage is where live ORB edges go | His "loses less" is mostly "trades less". Do not switch; the forward A/B measures fills honestly |
| Market filter | Trend filter was his best fallback (0 trades on the locked days) | SPY over its VWAP: best of 9 candidates, +0.12R held-out, not significant (section 5) | Playbook rule 9 (weak) | This desk's test, weakly. Logged forward, not switched on |
| Calendar timing on SPY | Combined model: half the crash for 1 point a year, mostly in-sample | Not studied before | Halloween held out-of-sample in 37 markets ([Jacobsen and Zhang](https://www.bnains.org/backtest/periode/The_Halloween_Indicator_everywhere_and_all_the_time_-_Ben_Jacobsen_%26_Cherry_Y._Zhang.pdf)); turn of month disputed: gone after 1990 in S&P futures ([Atlanta Fed](https://www.atlantafed.org/research/publications/wp/2000/11.aspx)) vs. still there in practitioner tests ([Alpha Architect](https://alphaarchitect.com/tactical-asset-allocation-day-month-matter/)) | Halloween is the best-supported vote. Turn of month is the weakest; the 200-day "or" does most of the work |
| Too few trades to judge | 56 trades | 20 replays is the desk's floor before reading results | | Agreed: collect, don't tune |

Where they disagree, the larger and cleaner sample wins, and none of these is large. The one place this desk's
evidence is clearly stronger than his is the filter: he tested the plain rule, and this desk's paper mode does not
trade the plain rule.

## 5. Playbook rules tested on the desk's own backtest (declared before testing)

Declared 2026-11-19 and committed before any of these numbers were computed. Data: the fresh 60-day 5-minute
cache (section 2), the desk's 88-stock pool, rows from `tools/vol_backtest.py rows` with the new fields in
`desk/backtest.py` (first bar, NR7, 50-day trend, SPY at the signal, shadow entry arms).

- **Baseline B0**: the desk's paper rule today: 15-minute range, range-middle stop, 2R, in play
  (relative volume ≥ 1.5x and ATR ≥ 3 %), both sides, every signal (no odds floor).
- **Candidates**, each one filter added alone on top of B0:

  | | candidate | kept when |
  | --- | --- | --- |
  | C1 | first-bar direction | the first 5-minute bar closed the way of the breakout |
  | C2 | NR7 | the day before was the narrowest of 7 |
  | C3 | gap agrees | the open gapped the way of the breakout |
  | C4 | SPY regime | SPY is over its session VWAP for a long, under it for a short, at the signal |
  | C5 | relative strength | the stock is up more than SPY since the open for a long, down more for a short |
  | C6 | trend | the prior close is over the 50-day average for a long, under it for a short |
  | C7 | early cutoff | the signal comes by 10:30 (bar 11 or earlier) |
  | C8 | longs only | |
  | C9 | more volume | relative volume ≥ 3x instead of 1.5x |

- **Entry arms**, in-play long slips, every slip including ones the real limit missed: E0 the slip, E1 a buy limit
  at VWAP, E2 a buy limit at the range high (both rest 60 minutes, same stop and target), total R in the slip's risk.
- **Costs**: $0.01 a share plus 5 basis points a side, for every number used to choose.
- **Selection, fixed**: on the training half only (ticker half A, before 2026-10-27), a candidate qualifies if its
  average R beats B0's by 0.05R or more with at least 30 trades. Each qualifier is then scored **once** on the
  held-out set (everything else). Paper mode adopts at most one: the qualifier with the best held-out average,
  and only if it beats B0 held-out by 0.05R or more, its profit factor is at least B0's, it has 50 or more
  trades, and the lower end of its 95 % day-block bootstrap range for average R is above 0. Anything else is
  left for you to decide or logged as a shadow arm. An entry arm is never adopted from this test: it changes fills,
  which the forward A/B (section 3) measures better.
- **Honest limits, stated now**: the held-out set was already used once, for B0 (docs/VOLATILITY.md), so it is not
  untouched; only the sessions after 2026-11-17 are new to anyone. About 40 sessions of one autumn.

**Results** (run once, 2026-11-19; $0.01 a share + 5 bp a side)

| | training (choose here) | | held-out (qualifiers only) | | |
| --- | --- | --- | --- | --- | --- |
| | trades | average R | trades | average R, PF | 95 % range |
| **B0**, the desk's paper rule | 131 | +0.056 | 320 | +0.063, 1.15 | −0.10 to +0.21 |
| C1 first-bar direction | 76 | +0.014 | | | |
| C2 NR7 | 16 | −0.312 | | | |
| C3 gap agrees | 68 | −0.139 | | | |
| **C4 SPY on its side of VWAP** | 93 | **+0.188** | 234 | **+0.123, 1.32** | −0.05 to +0.30 |
| C5 relative strength | 126 | +0.080 | | | |
| C6 50-day trend | 76 | −0.033 | | | |
| **C7 by 10:30** | 89 | **+0.112** | 221 | +0.084, 1.18 | −0.15 to +0.31 |
| C8 longs only | 79 | +0.058 | | | |
| C9 relative volume ≥ 3x | 22 | −0.092 | | | |

**Nothing is adopted.** C4 beat B0 on the held-out set by 0.06R with a better profit factor and 234 trades, but its
95 % range still reaches below zero, so it fails the declared rule. C7 failed on the margin. A note on the run: the
first held-out pass had a bug in the analysis script (both qualifiers were scored with the last candidate's
filter); it was fixed and the held-out set scored once more with the declared filters. No choice changed between
the two passes; neither run adopted anything.

**What the desk does with it.** C4 is logged forward: after the close, each long slip's real replay is also tagged
"SPY over its VWAP" or "under" at the trigger (`outcome.shadow`), and the review's entry A/B lists both groups. The
analyst's PLAYBOOK now carries these results as evidence notes: rule 9 (SPY and VWAP) is the one rule with some
support from this desk's data; first-bar direction (rule 3), 3x volume (rule 4) and NR7 (rule 18) found no help
here. Small samples; the notes say so.

**Entry arms** (in-play longs, every slip, R in the slip's risk, before costs):

| | training: filled of 79, total | held-out: filled of 195, total |
| --- | --- | --- |
| E0 the slip (breakout + 0.2R chase) | 79, +11.0R | 194, +31.6R |
| E1 buy limit at VWAP | 24, +1.2R | 36, +0.6R |
| E2 buy limit at the range high | 61, +0.3R | 154, +26.1R |

On in-play stocks the pullback limits miss the trades that run, and those are the winners. The friend's
"VWAP loses less" is true on the plain rule because it trades less of a losing rule. Not adopted; the forward
A/B keeps measuring it with real fills.

**Cash interest in the combined book.** Done: uninvested cash in the combined SPY book earns the prior day's
13-week T-bill rate (Yahoo `^IRX`, 4.15 % on 2026-11-19), shown on its own line. Below the 200-day average the book
can sit up to 100 % in cash, so this was a real bias against it.

## 6. What is left for you to decide (nothing here is switched on)

1. **Raise `chase_r` limits or allow negative `chase_r` (pullback entries)?** Not now. Section 5 says pullback
   limits lose the best in-play trades. `desk/settings.py` keeps 0 to 1. Revisit after 20+ days of the shadow A/B.
2. **Add SPY-over-VWAP (C4) as a paper rule?** The best candidate, but not significant. Recommended: wait for the
   forward split in the review (about 50 replays a side), then decide. It would be a new rule-set code.
3. **Live mode's screen.** Live still trades the plain rule unless `min_rvol` and `min_atr_pct` are set. Both
   backtests say the plain rule loses. If you go live, setting them (1.5 and 3) matches paper mode. Your call.
4. **The combined SPY book: give it real money one day?** Not before 6 to 12 months of paper next to SPY, and only
   if at all; that is your decision, not the desk's. It trades often around month turns, so taxes and real fills
   would matter. The desk will never place its orders itself.

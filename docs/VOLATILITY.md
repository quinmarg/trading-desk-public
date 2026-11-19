# High-volatility stocks: research, tests and what the desk does with them

Started 2026-11-18 with one goal: learn to trade high-fluctuation stocks, stay mostly on them, and get
"accuracy within 25 %" from testing. Not financial advice. This describes what
the sources and the desk's own tests show, nothing more.

## The target (2026-11-18)

"Accuracy within 25 %" was pinned down before anything was built. A 25 % win rate alone loses money
with the desk's 2R targets (break-even is about 33 %), so the target became this:

On days and stocks the rule was **not** tuned on, over **at least 100 replayed trades**:

1. **It makes money after costs**: average R above 0 and profit factor 1.2 or more, after $0.01 a share.
2. **The Time Machine's odds are honest**: in every odds band with 20 or more trades, the share that
   really hit the target first is within **10 points** of what the Time Machine predicted.

## What the research says

Sources are listed at the end. **[study]** means data-backed; **[opinion]** means a practitioner's view or
a secondary write-up. The two Zarattini papers' full texts were blocked (SSRN answered 403), so their
numbers come from the abstracts and from three write-ups that quote the tables (Danfin, Tradoki, CXO
Advisory). They were not checked against the papers themselves.

### Opening-range breakouts on "stocks in play"

- **Zarattini, Barbon and Aziz (2024)**, more than 7,000 US stocks, 2016 to 2023, delisted names
  included [study, via write-ups]. Screen: price over $5, 14-day average volume of 1 million shares or
  more, 14-day ATR over $0.50, and the first 5-minute bar's volume at least 100 % of its 14-day average
  for that same bar ("relative volume"); then the 20 highest each day. Entry on a break of the first
  5-minute bar in the direction it closed; stop 10 % of the 14-day ATR away; no target, out at the close;
  1 % risk a trade, 4x leverage cap; commission modelled, slippage not.
- Results for the top 20: Sharpe 2.81, 41.6 % a year. **The same rule without the relative-volume
  filter: Sharpe 0.48, 3.2 % a year.** Average result by relative volume: about −0.02R under 100 %,
  +0.08R over 100 %, +0.38R over 3,000 %. The filter is where the edge was.
- **Opening-range length**, same paper, with the filter: 5 minutes Sharpe 2.81, 15 minutes 1.43,
  30 minutes 0.21, 60 minutes 0.40. The authors say they do not know why 5 minutes is best.
- **Zarattini and Aziz (2023)**, QQQ: win rate 24 %, about +0.13R a trade, 10R target with an exit at
  the close [study, via write-ups]. Low win rates with big winners are normal for this kind of rule.
- **Replications and critiques.** QuantConnect's 2016-only replication of the stocks-in-play rule beat
  SPY (Sharpe 2.4 against 0.84) [study]. An MQL5 replication of the QQQ rule on index CFDs, 2015 to 2026,
  matched the +0.13R gross edge but found it about 0R after spread and slippage [study, self-published].
  Marshall, Cahan and Cahan (2008) tested 7,846 intraday rules on SPY and found none profitable after
  correcting for data snooping [study]. Neither Zarattini paper has a separate out-of-sample period.

### Which measures pick "high-fluctuation" stocks

- **Relative volume at the open** is the only measure with paper evidence for this setup (above).
- **ATR**: the paper uses ATR over $0.50 in dollars; QuantConnect found ATR floors from $0 to $2 and an
  ATR of at least 1 % of price all worked in 2016 [study]. Scanners commonly use **ATR % (ATR / price)**
  of about 1 % to 5 %, or over 3 % [opinion]. No study ties an ATR % level to breakout profit.
- **Gap %**, **float** and **news catalysts** are momentum-trader criteria (gap over 4 % to 10 %, float
  under 10 to 20 million shares) [opinion]. Low float is the riskiest of them (see frictions).
- **Beta**: no ORB source uses it. Not used here.

### Stops and size

- Fixed dollar risk with a stop scaled to the stock's volatility keeps the loss per trade constant;
  both papers do this. No source compares ATR stops with fixed stops head to head. The paper's 10 % of
  ATR stop is very tight and relies on fills a free-data desk will not get [opinion].
- The desk already sizes by dollar risk (`risk_per_trade_pct`), so a wider stop on a wilder stock
  already means fewer shares. Results below are in R (multiples of the planned risk), which is the same
  whatever the size.

### Gaps and news

Evidence conflicts. Berkman et al. (2012) find overnight gains in high-attention stocks tend to reverse
during the day [study]; the stocks-in-play paper finds open-to-close continuation on high relative
volume. Gao et al. (2018) find the market's first half hour predicts its last half hour, more so on
volatile days [study]. Nothing here says a gap's direction alone helps.

### Frictions on volatile names

- **Halts (LULD)**: price bands of 5 % (Tier 1) or 10 % (Tier 2) for stocks over $3, 20 % from $0.75 to
  $3, doubled in the last 25 minutes; a limit state that does not clear in 15 seconds becomes a
  5-minute pause. A stop does not fill during a pause.
- **Short-sale restriction (SEC Rule 201)**: after a 10 % drop from the prior close, shorts may not
  execute at or below the best bid for the rest of that day and the next. The desk already blocks a
  short once the stock is down 10 %.
- **Spreads and slippage** are widest near the open and on small, thin names. The papers model none;
  the replication shows a few basis points a side can erase the whole edge. The tests below repeat each
  result at 2 and 5 basis points a side.
- **Low float**: FINRA's 2026 oversight report flags pump-and-dump schemes in small, low-priced listed
  stocks, where you may not be able to sell at all.
- **Pattern day trader rule**: the SEC approved FINRA's removal of the $25,000 rule on 2026-04-14,
  effective 2026-06-04, with brokers allowed to phase it in until 2027-10-20 (FINRA Notice 26-10). A
  cash account was never under it; settlement still applies to real cash trades.

### What tends to fail

Overfitting (trying many settings and keeping the best), ignoring costs, unfiltered breakouts,
low-float runners, and testing only on today's survivors. Most day traders lose money: Barber, Lee,
Liu and Odean's Taiwan data show more than 8 in 10 lose in a typical six months [study].

## How it was tested

`desk/backtest.py` and `tools/vol_backtest.py` (run `python3 tools/vol_backtest.py --help`):

- **Data**: 88 stocks, calm and wild mixed on purpose so the screen, not a hand-picked list, decides what
  "volatile" is. For each one: Yahoo's free 60 days of 5-minute bars (about 41 trading sessions,
  2026-09-17 to 2026-11-17) and a year of daily bars, cached in `data/backtest/`.
- **The rule**: the desk's own slip for every session and side. First 5-minute close beyond the opening
  range, stop at the range middle, 2R target, buy limit entry + 0.2R, good for 10 minutes, no entry after
  15:30, out by 15:55, the 0.3 % closest-stop check, and the short side's 10 %-drop and 200-day checks.
  Each slip is replayed with `desk/outcome.py`, the same replay the review uses (a candle that touches
  both stop and target counts as the stop).
- **The odds**: the Time Machine skill's own simulator, run on only the sessions before that day,
  2,000 replays (the desk uses 10,000). It needs 20 earlier sessions, so only the last ~21 days of
  each stock get odds. "Ready" means odds known and edge at or over the desk's −5 point floor.
- **Costs**: $0.01 a share (the desk's `est_cost_per_share`), and again with 5 basis points a side.
- **Held out**: stocks are split into halves A and B by a hash of the ticker (fixed before any test).
  Settings were chosen only on half A before 2026-10-27 ("train"). Everything else is held out:
  half B on every day, and half A from 2026-10-27 on. "Strict" is half B from 2026-10-27 on: other
  stocks and later days. The held-out numbers were looked at once, after the choice was made.

### What was tried, training half only (every signal, $0.01 a share)

| rule | no screen | relative volume ≥ 1.5x | + ATR ≥ 3 % |
| --- | --- | --- | --- |
| desk today: 15-min range, range-middle stop, 2R | −0.028R, PF 0.94 (1,227) | +0.103R, PF 1.23 (161) | **+0.113R, PF 1.26 (132)** |
| 5-min range, 2R | −0.055R, PF 0.91 (1,412) | −0.050R, PF 0.91 (204) | −0.008R (169) |
| 5-min range, hold to 15:55 | −0.029R (1,412) | +0.123R, PF 1.21 (204) | +0.190R, PF 1.33 (169) |
| 15-min range, hold to 15:55 | −0.026R (1,227) | +0.105R (161) | +0.127R (132) |
| 5-min, stop 0.1 x ATR, hold (the paper's rule) | −0.083R (1,210) | +0.142R (170) | +0.174R, **−0.038R at 5 bp** (166) |
| 5-min, stop 0.25 x ATR, 2R | −0.002R (1,423) | −0.035R (205) | +0.018R (170) |
| 5-min, stop 0.25 x ATR, hold | −0.012R (1,423) | +0.015R (205) | +0.074R (170) |
| 5-min, stop at the far side of the range, 2R | −0.008R (1,425) | +0.049R (205) | +0.071R (170) |

The one thing that held in every row: **relative volume turns a losing rule into a winning one**, as in
the paper. ATR-scaled stops did not help, and the paper's very tight stop lost money once 5 basis points
of slippage were counted. The 5-minute range only helped when held to the close.

**Chosen on training alone**: the desk's current rule plus the screen (relative volume ≥ 1.5x and ATR ≥
3 %). It is the smallest change and it keeps the Time Machine's target odds meaningful (with a hold-to-close
plan nearly every signal fails the odds floor, because the edge measure only counts target against stop).
The 5-minute hold-to-close rule was kept as a second candidate.

### Before and after, held out ($0.01 a share)

| | before (no screen) | after (the screen) |
| --- | --- | --- |
| every signal | n 2,167, win 40.9 %, avg −0.049R, PF 0.90 | **n 321, win 49.2 %, avg +0.110R, PF 1.27** |
| every signal at 5 bp a side | avg −0.126R, PF 0.77 | avg +0.059R, PF 1.14 |
| graded ready (odds floor) | n 539, avg −0.044R, PF 0.93 | n 39, avg +0.115R, PF 1.21 |
| strict (other stocks, later days) | n 545, avg −0.009R, PF 0.98 | n 91, avg +0.082R, PF 1.17 |
| after, longs / shorts | | +0.166R (194) / +0.024R (127) |
| second candidate, 5-min hold to 15:55 | n 2,511, avg −0.064R, PF 0.90 | n 391, avg +0.187R, PF 1.36 (+0.129R at 5 bp) |

"Win" is any trade above 0R after costs; most winners end at 15:55 above the entry rather than at the target.

### Are the Time Machine's odds honest? (held out, predicted vs real share that hit the target first)

| band | all stocks, ready | in-play stocks (after the screen) |
| --- | --- | --- |
| 0–20 % | 16.0 vs 12.2 (−3.8, n 82) | 4.6 vs 12.8 (+8.2, n 265) |
| 20–30 % | 25.6 vs 24.5 (−1.2, n 278) | 25.4 vs 39.1 (**+13.8**, n 23) |
| 30–40 % | 33.6 vs 26.2 (−7.4, n 168) | 5 trades, too few |

Across ordinary stocks the odds are within 10 points in every band with 20+ trades. On in-play stocks they
are too pessimistic: the Time Machine builds its replays from the stock's last 60 days, mostly ordinary
days, so it underrates how far a busy day runs.

### Did it meet the target?

- **Money (a): yes, with a caveat.** Over every in-play signal held out, 321 trades, +0.11R and profit factor
  1.27 after $0.01 a share. The strict slice (91 trades) came in at PF 1.17, just short, and with 5 basis
  points of slippage the full set drops to PF 1.14. With the desk's odds floor only 39 would have been
  ready, too few to count. That is why paper mode now lets in-play signals past the floor (below).
- **Odds within 10 points (b): only for ordinary stocks.** On in-play stocks one band missed by 13.8 points.
  The Time Machine cannot be changed (the skills are vendored as they are), so the desk notes it instead.
- **Sample**: about 41 sessions from one autumn. Results here could be one market mood. Longs did best in
  the held-out days, shorts in the training days. Nothing here is proof; paper trading is the next test.
- **Survivorship**: the pool is today's tickers, chosen in November 2026, so stocks that collapsed or were
  delisted earlier are missing. That flatters every number a little.

## What the desk now does (paper mode; live is unchanged)

- **Volatility screen** (`desk/volscreen.py`): when a breakout or breakdown fires, the desk reads the
  stock's ATR % and its opening-range relative volume (two read-only Yahoo GETs per stock per day, cached).
  In paper mode a signal under **1.5x relative volume or 3 % ATR** is graded **weak** with the reason
  "Not in play", so auto paper skips it and the review still replays it. Settings `min_rvol` and
  `min_atr_pct` turn the same screen on in live mode; both are 0 (off) by default. In paper mode your own
  value is used when it is higher than the paper one (`settings.PAPER_SCREEN`).
- **In-play signals skip the odds floor in paper mode** (`volscreen.skips_floor`): they are graded ready with
  a warning that shows the Time Machine edge. Live mode keeps the floor.
- Both are part of the rule-set code, so the review can read results from before and after apart.

### The desk picks its own scan list (added 2026-11-18)

The desk can choose its own stocks instead of a list you paste. Setting **`auto_list`**
("Pick stocks to scan for me"): `paper` (the default: paper mode only), `on` (both modes) or `off`.

- **When**: once a day in the desk's pre-market run (`Desk.premarket`, from 8:00 New York, or when the desk
  starts later). A restart later the same day keeps the morning's list.
- **How** (`desk/autolist.py`): it reads a year of daily bars for about 90 liquid stocks (`autolist.POOL`, the
  same pool as the backtest) plus your watchlist, one read-only GET each, about 45 seconds. It keeps stocks at or
  over your lowest share price that trade $100 million or more a day, and moves of at least 3 % a day (ATR %).
  Then it ranks them by ATR % and keeps the top 40. Forty because each listed stock's chart is read on every scan.
- **No refresh during the day.** Whether a stock is in play today depends on its opening volume. That is
  checked on every signal by the volatility screen, so re-picking the list after the open would add data
  requests without changing which signals count.
- **Fallback**: with picking off, before the first pick, or when fewer than 5 stocks pass, the desk scans
  your own watchlist, and the dashboard says why.
- **Shown** on the Desk tab, "Stocks to scan today": each stock with why it is there (its average daily range,
  money traded a day and price). **Logged** each day (journal key `scan_lists`, plus an event) and judged in
  `python3 -m desk review` under "SCAN LISTS THE DESK PICKED": the list's size, its signals and their replay R.

For comparison, the stocks in the backtest pool with a median ATR of 4 % or more, $5 or more and $100 million
a day over the test period (53): CIFR HUT NBIS CLSK ASTS RIOT MARA WULF IREN SMR ALAB MRNA SMCI CRWV TEM IONQ
MSTR ARM OKLO DELL QBTS HIMS COIN RGTI RKLB INTC HOOD VST SNAP ENPH NET ORCL AFRM MU JOBY RBLX SNOW U CRWD CVNA
APP AMD DKNG RDDT SHOP FSLR CEG TTD RIVN PLTR CELH GME PATH.

The first live pick (2026-11-18) chose 40, led by IREN, NBIS, CIFR, ASTS and HUT (12 % to 17.5 % a day).

## What to try next

1. The 5-minute range held to 15:55 did best held out (+0.187R, PF 1.36, 391 trades, still +0.129R at
   5 basis points). Trying it in paper needs a different odds measure, because the target-vs-stop edge
   rejects every hold-to-close plan.
2. Keep the paper log for 100+ in-play trades and run `python3 -m desk review`. That is the only test with
   real (practice) fills.
3. Store the desk's own 5-minute bars each day, so later tests can go past Yahoo's 60 days.

## Sources

1. Zarattini, Barbon, Aziz, "A Profitable Day Trading Strategy For The U.S. Equity Market", abstract: https://www.alexandria.unisg.ch/entities/publication/ab50f49b-4d5c-4aa8-aaa1-af7a4c131008
2. Zarattini, Aziz, "Can Day Trading Really Be Profitable?": https://papers.ssrn.com/abstract=4416622
3. Danfin write-up of both papers: https://danfin.net/opening-range-breakout-research
4. Tradoki write-up and critique: https://blog.tradoki.com/posts/opening-range-breakout-stocks-in-play-research
5. CXO Advisory on the screen: https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/
6. QuantConnect replication: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/
7. MQL5 net-of-cost replication: https://www.mql5.com/en/blogs/post/776235
8. Literature roundup (Marshall et al. 2008, Lundström): https://passthechallenge.com/blog/opening-range-breakout-research/
9. Retail Traders Repository on paper B: https://retailtradersrepository.substack.com/p/trading-research-paper-can-day-trading-really-be-profitable
10. Berkman et al. 2012, JFQA: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/paying-attention-overnight-returns-and-the-hidden-cost-of-buying-at-the-open/F9AAD159B512C651F09D5D52011D88E0
11. Gao, Han, Li, Zhou 2018, JFE: https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
12. Scanner thresholds: https://tradethatswing.com/how-to-scan-for-day-trading-stocks-that-are-making-big-moves-today/ ; https://www.warriortrading.com/day-trading-watch-list-top-stocks-to-watch/ ; https://chartswatcher.com/pages/blog/how-to-choose-stocks-for-day-trading-a-professional-guide
13. LULD plan: https://www.luldplan.com/
14. SEC Rule 201 FAQ: https://www.sec.gov/divisions/marketreg/rule201faq.htm
15. FINRA Notice 26-10 (day-trading rule replaced): https://www.finra.org/rules-guidance/notices/26-10
16. FINRA 2026 oversight report, manipulative trading: https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/manipulative-trading
17. Barber, Lee, Liu, Odean on day traders: https://faculty.haas.berkeley.edu/odean/papers/day%20traders/day%20trading%20and%20learning%20110217.pdf

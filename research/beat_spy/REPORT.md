# Can a SPY rule beat the S&P 500? An honest test (2026-11-19)

**Short answer: no rule clearly beat buy-and-hold on years it never saw.** I tried 222 rules on 1961–2009, sealed three
finalists, and tested them once on 2010–2026. The best one gained 0.4 points a year on SPY before tax, with a much
deeper crash. That lead is the size luck alone produces about half the time (p = 0.47). After tax it lost. Nothing was
added to the desk.

Chart: [`out/beat_spy.html`](out/beat_spy.html). Raw numbers: `out/sealed.json`, `out/test_result.json`,
`out/dev_table.json`. Literature notes with sources: section 6.

Nothing here is advice. It is a replay of the past on free data.

## 1. What was tested

Six families of rules on the US market, each at 1x, 1.5x, 2x and 3x where it made sense (the grid is in `dev.py`):

| family | idea | configs |
| --- | --- | --- |
| hold | buy and hold at 1.25x to 3x | 4 |
| sma | in above an n-day average (50 to 250), out below, with a 0–2 % band; out to cash or Treasuries | 120 |
| dual | absolute momentum: in when the 3–12-month return beats T-bills (checked monthly) | 32 |
| vt | volatility targeting: exposure = target ÷ recent volatility, capped; optional 200-day filter | 48 |
| combo | your combined model (dip, Halloween, turn-of-month votes), scaled 1x to 3x | 4 |
| season / tom | Halloween (more in Nov–Apr) and turn-of-month tilts, with leverage | 14 |

Leverage was simulated the way SSO and UPRO actually work:
- they reset every day;
- each day returns 2x or 3x SPY's total return;
- minus the fund fee (0.88 % a year, ProShares' current gross figure);
- minus borrowing at the T-bill rate plus a spread.

The spread was set so the synthetic 2x matched real SSO over 2006–2009 (development data only). It came out at
T-bills + 1.22 %. Exposures between 1x and 2x mix SPY and a 2x fund; between 2x and 3x they mix 2x and 3x.

## 2. How it was kept honest

- **Declared in code first.** The families, grids, costs, selection rule and pass rule are in `dev.py` and `test.py`
  docstrings, written before any result existed.
- **Development data only for choosing.** `dev.py` loads nothing after 2009-12-31. It uses two windows:
  - **B:** 1961–1992, ^GSPC with Shiller's monthly dividends added, filled at the next close because the old index
    feed has no real opens;
  - **A:** 1993–2009, SPY with dividends, filled at the next open.
- **Fixed selection rule.** A rule was eligible only if its worst drop was no deeper than buy-and-hold's in both windows.
  Among those:
  - **F1:** highest return over SPY;
  - **F2:** highest Sharpe;
  - **F3:** best rule that never goes above 1x.

  99 of 222 were eligible.
- **Sealed, then tested once.** `out/sealed.json` holds the finalists and a fingerprint of the code. `test.py` refuses
  to run if that code changed, and refuses to run a second time (`out/test.lock` records the single run,
  2026-11-19 14:21–14:24).
- **Costs and realism.**
  - Next-open fills, 3 bp a side on SPY, 5 bp on the 2x and 3x funds, 2 bp on Treasuries.
  - Cash earns the 13-week T-bill rate (^IRX) known the day before. Dividends are reinvested.
  - Trades happen only when exposure is 10 points off target.
  - Taxes are shown both ways (section 3).
- **Three held-out checks:**
  1. SPY 2010-01-04 to 2026-11-18.
  2. A walk-forward that re-applies the selection rule every January from 2000 to 2026, using only data before
     that year.
  3. Nine stock indices the friend's lab never touched: India (Sensex), Shanghai, Italy, Turkey, Ireland, Portugal,
     Copenhagen, Helsinki and South Africa. These are price indices, so cash earns 0, fills are at the next close and
     costs are doubled. Russell 2000 and Nasdaq are reported apart, because they move with SPY.
- **Multiple testing.**
  - On development data: White's Reality Check over all 222 rules, and Bailey and López de Prado's deflated Sharpe ratio
    for each finalist.
  - On the test: a one-sided stationary block bootstrap (mean block 21 days) of the daily log-return gap to SPY,
    multiplied by 3 because three finalists were tested.
- **Seen data, said plainly.**
  - Every family comes from published research. Gayed–Bilello, Faber, Antonacci, Bouman–Jacobsen and others studied
    data that overlaps 2010–2026, and I knew roughly how those years went.
  - So the SPY held-out test is "never used for choosing", not "never seen by anyone".
  - The walk-forward and the foreign indices are the stronger checks.
  - Your combined model's 2000–2026 numbers are all seen data.

**Mistakes caught before the test, and fixed:**
- The first development run had a bug: the swap spread was captured as a default argument, so the calibration never
  moved and recorded 5 %. I fixed it and re-ran development with the rule and grid unchanged. The bad seal is kept in
  `out/discarded/`.
- A later re-seal only added a trade counter. The finalists were identical.
- A dry run of `test.py --dry` exercised every step on 2005–2009 data, with the foreign indices cut at 2009, before the
  real run.

## 3. Results

**Development (1961–2009).**
- The biggest raw winners were 2x and 3x above a 200- or 250-day average, the Gayed–Bilello idea. They made 5–7 points
  a year over buy-and-hold.
- All of them fell 55–80 % at some point, mostly in October 1987. A 200-day filter cannot dodge a one-day 20 % crash:
  3x of −20.5 % is −61 % before you can act.
- The drawdown cap ruled them out.
- Best eligible rule per family, in yearly log return over SPY:

  | family | season | sma | dual | tom | vt | combo |
  | --- | --- | --- | --- | --- | --- | --- |
  | over SPY | +5.3 % | +4.0 % | +2.0 % | +1.7 % | +1.5 % | +1.2 % |

- Even on development data, the multiple-testing checks said this could be luck:
  - Reality Check p = 0.16;
  - deflated-Sharpe p = 0.58 (F1), 0.68 (F2) and 0.73 (F3), against 0.05 needed.

**Held out, SPY 2010-01-04 to 2026-11-18** (the one run):

| book | a year | worst drop | Sharpe | vs SPY, pts a year | p (×3) | after tax |
| --- | --- | --- | --- | --- | --- | --- |
| SPY buy and hold | 13.8 % | −33.7 % | 0.75 | – | – | 13.4 % |
| your combined model (1x) | 11.1 % | −26.2 % | 0.75 | −2.4 | 0.95 (one test) | 9.4 % |
| **F1** 3x Nov–Apr, 1x May–Oct, cash below the 200-day | 14.2 % | −48.4 % | 0.57 | +0.4 | 1.00 (0.47 alone) | 11.1 % |
| **F2** SPY above the 250-day (2 % band), else Treasuries | 8.3 % | −25.3 % | 0.56 | −4.9 | 1.00 | 7.1 % |
| **F3** same, 1 % band | 8.5 % | −23.9 % | 0.58 | −4.7 | 1.00 | 7.3 % |

**Walk-forward** (the rule re-picked every January, past data only):

| | from 2000 | from 2010 |
| --- | --- | --- |
| F1 rule | 10.1 % vs SPY 8.0 %, worst drop −48 %, p = 0.32 | 14.2 %, p = 0.47 |
| F3 rule | 8.3 % vs SPY 8.0 % | 8.9 % vs 13.8 % |

From 2009 on, the F1 rule picked the same 3x-winter rule every year.

**Foreign indices** (a win means the rule beat the index after costs):
- F1 won 5 of 9: Shanghai, Italy, Turkey, Ireland and Portugal. It lost India, Copenhagen, Helsinki and South Africa.
- F2 and F3 won 3 of 9. Your combined model won 4 of 9.
- F1's worst drops there ran to −85 % (Shanghai) and −92 % (Turkey).
- On the unused US indices, F1 beat the Russell 2000 by 4.6 points and the Nasdaq by 7.9, with drops of −72 % and −88 %.
- South Africa's feed has a bad print on 2025-07-23 (99,325 → 180 → 99,971). Buy-and-hold rides through it, but every
  rule gets knocked out by the fake crash, so the South Africa results for rules are invalid. Without it F1 wins 5 of 8,
  still short of the two thirds the pass rule asked for.

**Verdict, by the rule declared before the test:** a finalist needed a held-out lead with p under 0.05 after ×3, plus
a walk-forward lead, plus wins on two thirds of the foreign indices. None passed:
- F1 had the walk-forward lead but not the p-value or the foreign wins.
- F2 and F3 lost outright.

**Taxes.** In a taxable account (22 % on short-term gains and interest, 15 % on long-term gains and dividends, paid
yearly, nothing at the end), F1 fell from 14.2 % to 11.1 % against SPY's 13.4 %. Switching in and out of 3x twice a year
turns gains short-term. A Roth IRA would avoid this.

**Synthetic funds against the real ones.**
- Over their whole lives the real funds beat the synthetic ones: SSO 15.0 % vs 14.4 % a year, UPRO 31.2 % vs 29.6 %.
  Swap financing got cheaper after 2009.
- So F1 with the real funds would likely have done about half a point to a point a year better than shown. Still
  nowhere near significant.

**Your combined model.**
- In the held-out years it gave up 2.4 points a year (11.1 % against 13.8 %) for a smaller worst drop (−26 % vs −34 %).
  It was in SPY 89 % of the time on average.
- From 2000 it is 8.6 % against 8.0 %. That window includes 2000–2002 and 2008, which it was built around.
- `compare_models.py` showed 8.21 %. The 0.4-point gap is most likely the desk book's dividend handling: `combo.book`
  pays dividends into cash and only reinvests them when the weight changes, while this engine reinvests them.
  Rebalance tolerance (0.07 points) and the calendar (3 days differ) are not the cause.

## 4. What it means for you

- **Nothing beat SPY by enough to trust.** The most return came from leverage, and leverage paid for it with a −48 %
  drop in the test years (−50 % in development).
- **If someone shows you a leveraged-trend backtest:** with a 200-day filter, 2x or 3x made the most money in history
  and also fell 55–80 %. The filter can't help on a one-day crash like 1987.
- **Leveraged funds, for a beginner with a small account:**
  - UPRO fell about 77 % in five weeks in 2020.
  - Daily reset means a choppy market eats them even when SPY ends flat. For example, +10 % then −10 % leaves SPY at
    −1 % and a 3x fund at −9 %.
  - FINRA's notice 09-31 calls them typically unsuitable for retail investors who hold longer than a day.
- **Your combined model is a risk-reducer, not a return-booster.** In the test years it gave up about 2.4 points a year
  for a smaller drop. That is what the friend's lab found too. Keep it running forward as the clean test.
- **The plain answer for a small account:** buy-and-hold SPY (or a total-market fund) beat every honest rule here.
  In a Roth IRA, its dividends and gains go untaxed.

## 5. The desk: added later as a paper book, on request

By the pass rule declared before the test, no finalist earned a place on the desk. Afterwards the best one was asked for
anyway, so F1 now runs as a third paper-only book, `desk/winter3x.py`:
- it holds UPRO from November to April and SPY from May to October while SPY is above its 200-day average, and cash
  below it;
- it fills like the combined book, reinvests dividends and never places an order;
- its Desk-tab card compares it with the combined book and buy-and-hold SPY over the same days, and shows the
  sealed-test numbers.

Treat it as a forward paper record, not a model that passed. Real money in it would carry every risk in section 4.

Four-way chart from 2000: [`out/compare4.html`](out/compare4.html) (`compare4.py`). It shows the S&P 500, the friend's
model, the combined book as it ran before this work, and the winter 3x book. $10,000 became:

| book | end value | a year | worst drop |
| --- | --- | --- | --- |
| S&P 500 | $78.7k | 8.1 % | −55 % |
| friend's model | $57.8k | 6.8 % | −27 % |
| combined book | $82.7k | 8.3 % | −28 % |
| winter 3x | $101.3k | 9.0 % | −50 % |

The winter 3x book's lead came in 2010–2014. It has lost ground to the S&P since 2015.

## 6. What the research says (sources)

Full notes, with every claim tagged Evidence or Opinion, opened or snippet-only: the shared notes file
`beat-spy-research.md` (side-session notes folder, 2026-11-19). The parts that shaped this test:

- **Leverage with a trend filter.** Gayed and Bilello, "Leverage for the Long Run" (SSRN, 2016), 1928–2015, 200-day
  rule on 1.25–3x, 1 % leverage cost, no switching cost.
  - Sharpe 0.51 for 2x timing against 0.30 for buy-and-hold; worst drop −78 % against −86 %. **Evidence, via the
    [CXO summary](https://www.cxoadvisory.com/volatility-effects/leveraging-the-u-s-stock-market-based-on-sma-rules/).**
  - CXO notes the costs flatter it. **Opinion.**
  - No independent replication or live record since 2016 found.
  - This test agrees: highest raw return in development, crashes too deep.
- **Volatility targeting.** Moreira and Muir (J. Finance 2017) claim large gains. **Evidence.**
  - [Cederburg, O'Doherty, Wang and Yan](https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:1:p:95-117)
    (JFE 2020, 103 strategies) find real-time versions usually do not beat unmanaged ones. **Evidence.**
  - Harvey et al. (JPM 2018) find it trims tails in equities. **Evidence.**
  - Here: +1.5 points in development at best, not a finalist.
- **Trend following.** Moskowitz, Ooi and Pedersen (JFE 2012) and Hurst, Ooi and Pedersen (a century of data) find
  trend works across many markets, mostly as crash protection. **Evidence.**
  - On a single index, the gain is smaller drops, not more return.
  - Here: F2 and F3 cut the worst drop in the test (about −25 % against −34 %) but lost 4.7–4.9 points a year in a
    bull market.
- **Dual momentum.** Antonacci (2014). In-sample, partly helped by a 40-year bond rally. No independent post-2014 record
  found. **Evidence (author) / Opinion.**
- **Seasonality.** Bouman and Jacobsen (AER 2002): Nov–Apr beat May–Oct in 36 of 37 markets. Jacobsen and Zhang report
  it held 1998–2011 out of sample. **Evidence, snippet-level.**
  - F1 leaned on this, and it was the one family that held up a little out of sample: 5 of 9 foreign wins, and a lead
    in the walk-forward.
- **Turn of the month.** Ariel (1987), Lakonishok and Smidt (1988),
  [McConnell and Xu](https://econpapers.repec.org/RePEc:taf:ufajxx:v:64:y:2008:i:2:p:49-64) (FAJ 2008): about 0.15 %
  over four days, in 30 markets. **Evidence.** Small enough that costs and taxes eat it.
- **Overnight returns.** Cliff, Cooper and Gulen (2008) and Lou, Polk and Skouras (JFE 2019): the overnight premium is
  real gross. **Evidence.**
  - No study found that it survives a daily round trip. Not tested here; the friend's lab found it did not pay.
- **Risk parity and stock/bond rotation.** Asness, Frazzini and Pedersen (FAJ 2012) say yes. **Evidence, by a firm that
  sells it.**
  - Critics say it depends on the period, and 2022 broke the stock/bond hedge.
  - Here the Treasury exit did not save F2 or F3 in the test.
- **Why edges fade.**
  [McLean and Pontiff](https://www.cxoadvisory.com/big-ideas/effects-of-market-adaptation) (J. Finance 2016), 97
  predictors: returns 26 % lower out of sample and 58 % lower after publication. **Evidence.**
  - Harvey, Liu and Zhu (RFS 2016) ask for a t-statistic above 3. **Evidence.**
  - This test fits the pattern: F1's development edge of 5.3 points shrank to 0.4.
- **Fund facts.** [SSO](https://www.proshares.com/our-etfs/leveraged-and-inverse/sso): 0.88 % gross, 0.84 % net until
  2027-09-30, launched 2006-06-19. [UPRO](https://www.proshares.com/our-etfs/leveraged-and-inverse/upro): 0.88 %,
  launched 2009-06-23. Both pages opened 2026-11-19.

## 7. How to run it

```sh
python3 research/beat_spy/data.py                     # fetch and cache the free Yahoo data (git-ignored cache/)
python3 -m unittest research.beat_spy.test_engine     # engine tests: no look-ahead, fund math, fills, statistics
python3 -m research.beat_spy.dev                      # development; refuses while out/sealed.json exists
python3 -m research.beat_spy.test --dry               # every step on 2005-2009 only, to check the code
python3 -m research.beat_spy.test                     # the one-time test; refuses to run again
python3 -m research.beat_spy.report                   # redraw out/beat_spy.html from the saved results
```

Standard library only. Shortcuts:
- Treasuries switch at the decision close (close enough for a bond fund).
- Foreign indices have no dividends and no local cash rate, on both sides.
- Taxes use FIFO lots with no final sale.
- The 1961–1992 window uses Shiller's monthly dividend yield spread evenly over trading days.

## 8. Added after the test: the ceiling (descriptive, seen data, picks nothing)

The ask was a rule that beats the S&P by at least 2.5 points a year, or failing that, the highest possible. I didn't
keep searching new rules against 2010–2026. Those years are already spent on the sealed test, and enough tries against
them will always "find" a winner by luck. Instead, `frontier.py` shows how far simple leverage got, on both halves of
history:

| rule | 1961–2009 a year (vs SPY) | worst drop | 2010–2026 a year (vs SPY) | worst drop | 2026 to Nov 18 (vs SPY) |
| --- | --- | --- | --- | --- | --- |
| SPY buy and hold | 9.6 % | −55 % | 13.8 % | −34 % | 7.9 % |
| 1.5x hold | 9.4 % (−0.2) | −75 % | 17.8 % (+4.0) | −49 % | 8.4 % (+0.4) |
| 2x hold (SSO) | 8.4 % (−1.1) | −89 % | 21.3 % (+7.5) | −59 % | 8.7 % (+0.8) |
| 3x hold (UPRO) | 5.2 % (−4.4) | −98 % | 26.5 % (+12.7) | −76 % | 8.4 % (+0.5) |
| 2x above 200-day, else cash | 11.7 % (+2.1) | −60 % | 13.1 % (−0.7) | −43 % | 4.0 % (−3.9) |
| 3x above 200-day, else cash | 12.4 % (+2.8) | −80 % | 16.5 % (+2.8) | −58 % | 1.8 % (−6.1) |
| F1 (sealed) | 15.5 % (+5.9) | −50 % | 14.2 % (+0.4) | −48 % | −1.8 % (−9.7) |

**What this says:**
- Yes, +2.5 points a year over 2010–2026 was easy to get, but only by holding 1.5x to 3x through one of the best bull
  markets on record.
- The same holdings lost to SPY over 1961–2009. At its worst, 3x buy-and-hold fell 98 % from a peak, so $10,000
  at the top was worth about $200 at the bottom.
- 3x above the 200-day average beat SPY by +2.8 points in both halves. Its worst drops were −80 % and −58 %, and it lost
  6 points to SPY in 2026 so far. That is a bet on leverage plus luck in timing the crashes, not an edge that held up.
- In 2026 so far, nothing here beat SPY by 2.5 points. The best was +0.8.

So the honest ceiling is this: more return than SPY comes from more risk, not from a smarter rule. No rule tested gave
more return for the same risk on data it hadn't seen.

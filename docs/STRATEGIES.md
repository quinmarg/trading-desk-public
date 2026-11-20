# What successful traders and bots do, and what the desk should take from it

Written 2026-11-19 for the desk's analyst. Not financial advice. Most day traders lose money.

How to read this. Every claim has a link. Each claim is tagged:

- **[evidence]**: a paper, a backtest with stated rules, or audited records.
- **[popular]**: a trader's published rule, a teaching course, or a blog. Popular does not mean tested.
- **[secondary]**: I only saw a summary of a paper or video, not the original. Check before relying on it.

Several primary sources blocked me (SSRN, Warrior Trading's site, Bear Bull Traders PDFs). Where that
happened the tag is **[secondary]**. `docs/VOLATILITY.md` already covers the ORB papers and the desk's own
tests; this file does not repeat its tables. It adds what that file lacks.

## 1. Academic and quant evidence

### 1.1 Opening range breakout on "stocks in play" (the desk's base rule)

- Paper: Zarattini, Barbon, Aziz, "A Profitable Day Trading Strategy For The U.S. Equity Market"
  ([abstract](https://www.alexandria.unisg.ch/entities/publication/ab50f49b-4d5c-4aa8-aaa1-af7a4c131008),
  earlier version [SSRN 4416622](https://papers.ssrn.com/abstract=4416622)). [evidence, secondary: full text blocked]
- Rules as quoted by write-ups: 7,000+ US stocks, 2016 to 2023. Pick the 20 with the highest relative
  volume in the first 5-minute bar. Buy a break of that bar if it closed up, short if down. Stop at 10 % of
  the 14-day ATR. No target; out at the close. Risk 1 % a trade. Reported: Sharpe 2.81, 41.6 % a year
  ([QuantConnect replication](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/),
  [CXO Advisory](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/)).
- Caveats: no separate out-of-sample period; slippage not modelled; the stop is very tight, so real fills
  would be worse. The desk's own test found the same 10 % ATR stop turned negative at 5 basis points of
  slippage (`docs/VOLATILITY.md`). The one robust finding, in the paper and in the desk's test: the
  relative-volume filter is what makes it work.
- Index version: QQQ, first 5-minute bar sets direction, stop at that bar's far end, target 10R, out at the
  close, 1 % risk, up to 4x leverage. 33.2 % a year vs 14.9 % buy-and-hold, January 2016 to February 2023,
  1,795 trades, **no spread and no slippage modelled**
  ([CXO Advisory](https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy)).
  [evidence, secondary]. An independent re-test on index CFDs found the edge about zero after costs
  ([MQL5](https://www.mql5.com/en/blogs/post/776235), self-published).

### 1.2 Intraday momentum on SPY

- Gao, Han, Li, Zhou (2018), Journal of Financial Economics: the return from the previous close to the end of
  the first half hour predicts the last half hour's return on the S&P 500 ETF, 1993 to 2013. Stronger on
  volatile days, high-volume days and big-news days. Also seen in ten other liquid ETFs
  ([abstract](https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414)). [evidence]
  It is a statistical link, not a published trading system with costs.
- Zarattini, Aziz, Barbon, "Beat the Market" (SPY): every minute, draw noise bands around the day's open,
  sized from the average daily move of the past 14 days. Long above the upper band, short below the lower,
  checked on the hour and half hour. Trailing stop at the opposite band or at VWAP. Flat at the close. Volatility
  targeting of 2 % a day, up to 4x leverage. 19.6 % a year, Sharpe 1.33, worst drawdown 25 %, May 2007 to April 2024,
  with $0.0035 commission and $0.001 slippage a share
  ([CXO summary](https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/),
  [SFI paper page](https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy)).
  [evidence, secondary]. In-sample; no out-of-sample test seen. Index, not single stocks.
- VWAP trend rule: long when price is above VWAP, short below, on QQQ and TQQQ, 2018 to 2023. The authors
  report $25,000 growing to $192,656 on QQQ
  ([Concretum](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/)).
  A QuantConnect algorithm page reports a paper Sharpe near 2.1 and says several public replications came in far lower
  ([QuantConnect](https://www.quantconnect.com/terminal/cache/embedded_backtest_0cab7e083e99d5a372e02fe882bbf078.html); I saw this only in a search summary).
  [evidence, disputed]. Treat the headline as an upper bound.

### 1.3 Crabel and narrow ranges

- Toby Crabel, *Day Trading with Short Term Price Patterns and Opening Range Breakout* (1990). Ideas: the
  opening range's high and low are the day's trigger levels; an NR4 or NR7 day (narrowest range of the last
  4 or 7 days) is followed by expansion more often, so an ORB after a narrow day is better
  ([Oxford Strat](https://oxfordstrat.com/trading-strategies/narrow-range/),
  [NexusFi](https://nexusfi.com/a/strategies/opening-range-breakout)). [popular]
  I found no reliable published success rate for NR4/NR7. The desk can test it (section 4).

### 1.4 Gaps, news and attention

- Evidence on gaps is mixed. Overnight gains in high-attention stocks tend to reverse during the day
  (Berkman et al. 2012, [JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/paying-attention-overnight-returns-and-the-hidden-cost-of-buying-at-the-open/F9AAD159B512C651F09D5D52011D88E0)). [evidence]
  The stocks-in-play paper finds continuation when relative volume is high. Both can be true: direction of the gap
  alone does not help; volume plus news may.
- Post-earnings drift: price keeps moving in the surprise's direction for days; high attention reduces the delayed
  move but adds continuation from overreaction
  ([Peng and Xiong, via Princeton](https://www.princeton.edu/~wxiong/papers/momentum.pdf)). [evidence, daily horizon, not intraday]
- No reliable published win rate for "gap and go" vs "gap fade" in small caps. Vendor pages quote 68 to 72 %
  fade rates with no data ([sample](https://elitetrader.com/et/threads/fading-the-gap.365093/post-6004280)). [popular, unproven]
  One vendor guide says no reliable win rate exists ([Gap and Go guide](https://daytradingtoolkit.com/strategies/gap-and-go-day-trading-strategy)).

### 1.5 Regime and time of day

- VIX and regime filters for ORB: no peer-reviewed ORB-specific test found. Kozyra and Lento found VIX-based index rules
  worked less well in low-volatility periods ([CXO](https://www.cxoadvisory.com/volatility-effects/use-vix-technical-signals-to-trade-stock-indexes)). [evidence, not ORB]
  A practitioner note says ORB suits moderate-VIX days and struggles on inside days with repeated false breaks
  ([Trade-Ideas](https://www.trade-ideas.com/learning-center/trading-strategies/opening-range-breakout-strategy/)). [popular]
  An Option Alpha piece argues the opening range's own size is a better filter than VIX
  ([Option Alpha](https://optionalpha.com/blog/opening-range-breakout)). [popular]
- Volume is U-shaped across the day (high at open and close). Spreads are often widest at the open and close on
  US stocks, but studies vary by market
  ([Wood and McInish 1992 as cited here](https://journals.agh.edu.pl/manage/article/download/2662/1799)). [evidence, mixed]
- Day traders as a group lose money: Barber, Lee, Liu, Odean
  ([paper](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/day%20trading%20and%20learning%20110217.pdf)). [evidence]

## 2. Well-known discretionary traders and their published rules

All are [popular]. None is audited by a third party that I could find. Most numbers come from secondary summaries.

| Trader | Stock filter | Entry | Stop and size | Source |
| --- | --- | --- | --- | --- |
| Ross Cameron (Warrior Trading) | "Five pillars": up 10 %+ on the day, relative volume 5x+, breaking news, price $2 to $20, float under 10 million (thresholds vary by source) | Gap-and-go and first pullback, small caps | Small size, cut quickly; no verified figures | [TradingView 5-pillars script](https://www.tradingview.com/script/mbqMf3pF-Ross-Cameron-5-Pillars-Filter), [Warrior watch list summary](https://recapio.com/digest/day-trading-watch-list-for-tuesday-by-ross-cameron-warrior-trading) [secondary] |
| Andrew Aziz (Bear Bull Traders) | "Stocks in play": news, high relative volume, ATR big enough, float and price ranges | ORB on 1 or 5 minutes, VWAP, 9/20 EMA pullbacks; marks premarket high/low, prior-day high/low, VWAP | Stop at a technical level, 1 % risk idea; 9 EMA as first target on the 9/20 trade | [Bear Bull Traders 9/20 trade](https://members.bearbulltraders.com/wp-content/uploads/2023/02/Strategy-9-20-Trade.pdf) (PDF unreadable to me), [Aziz routine summary](https://www.forex.in.rs/aziz-daytrader-routine) [secondary, low-quality site] |
| Kristjan Kullamagi (Qullamaggie) | Breakout: top 1 to 2 % by 1, 3, 6-month gain, then a tight orderly pullback. Episodic pivot: gap of 10 %+ on unexpected news, heavy volume, not already run up. | Opening-range high break (1, 5 or 60 minute bar) | Stop at the day's low, not wider than 1 ADR/ATR. Sell 1/3 to 1/2 after 3 to 5 days, trail the rest on the 10 or 20-day average. | [his own page](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/) (first 100,000 characters read) |
| Mark Minervini | Trend Template (swing, not day): price above rising 150 and 200-day averages, 50-day above both, price 25 %+ above its 52-week low and within 25 % of its high, relative strength rank 70+ | Buy a tight base breaking out on volume | Risk 1.25 % to 2.5 % of equity a trade; stop 7 to 8 % | [Chartmill](https://www.chartmill.com/documentation/trading-and-investing/methodologies/523-SEPA-Explained-Mark-Minervinis-Specific-Entry-Point-Analysis-System), [MQL5 write-up](https://www.mql5.com/en/articles/22790), [daytrading.com](https://www.daytrading.com/mark-minervini-momentum-strategies) [secondary] |
| Linda Raschke | "Holy Grail": 14-day ADX above 30 and rising, price pulls back to the 20-period average; buy above the high of the bar that touches it | Daily bars in the 1995 book; no intraday first-hour rule found | Exit if price closes through the average | [Trading Setups Review](https://tradingsetupsreview.com/the-holy-grail-trading-setup) [secondary] |
| Lance Breitstein | Stocks in play; trades the strongest ideas bigger | Day-trading, prop-firm background | Sizes up on best setups; reduces in bad regimes (one low-quality summary; not confirmed) | [Retail Traders Repository interview](https://retailtradersrepository.substack.com/p/lance-breitstein-trillium-interview), [TraderLion](https://traderlion.com/investing-champions/lance-breitsteins-simple-setup-that-made-millions/) [secondary] |

What they share: a catalyst or unusual volume first, then a chart level, then a hard stop. What they do not share:
Cameron wants sub-$20 low-float stocks; Qullamaggie and Minervini want larger leaders already in trends; Aziz sits between.
The desk's list (liquid names, ATR 3 %+) is closer to Aziz and Qullamaggie than to Cameron. Cameron's
low-float rules do not fit: low-float names can halt, and FINRA flags pump-and-dump risk there
([FINRA 2026](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/manipulative-trading)).

## 3. Bots and systematic approaches

No profitable retail bot I found publishes audited live results. What is published is advice from vendors, which is
[popular] and often promotional. The points repeated across independent write-ups:

- **Overfitting is the top cause of failure.** Many tuned inputs fit the past. Remedies: walk-forward tests, a held-out period never touched,
  few rules ([MQL5](https://www.mql5.com/en/blogs/post/771573), [MQL5](https://www.mql5.com/en/blogs/post/773547)). The desk's test already used a hashed
  stock split and a later-days split.
- **Costs and slippage.** Backtest defaults of zero cost overstate results; take cost numbers from your own fills
  ([TradersPost](https://blog.traderspost.io/article/why-automated-trading-strategies-fail), [DEV](https://dev.to/aurora_systems/your-trading-bots-backtest-is-lying-to-you-here-are-the-4-ways-5044)).
  The one cost-aware replication (section 1.1) shows a few basis points can erase an edge.
- **Live failures:** data errors, partial fills, outages, no risk rules. Start small and paper trade first.
- **Common design choices** (published rules, not proof): flat at the close (all three Zarattini systems); one entry a day per stock;
  volatility-scaled size with a leverage cap; trailing stop to VWAP or a band; no trades in the first minutes
  on the index system (it checks on the hour and half hour); a first-bar direction rule for stocks.
- **Scaling out and trailing** is standard among discretionary traders (Qullamaggie sells a third to a half, trails the rest).
  The ORB papers use no target; the desk's test showed holding to the close beat a 2R target
  (`docs/VOLATILITY.md`: +0.19R vs about 0R).

## 4. How the pros combine news, chart and market

All [popular] unless noted.

1. **Catalyst first.** Earnings, guidance, FDA, contracts and upgrades are ranked above vague "momentum" or sympathy. Qullamaggie wants
   unexpected news and a stock that had not already run ([page](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/)).
   Evidence: abnormal volume around news goes with a continued move ([Gerard, as cited](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2011-Braga/papers/0361.pdf), [evidence, European, daily]).
2. **Sympathy plays.** Peers of a stock with news often move too. I found no measured data; treat as unproven.
3. **Regime.** Market up: take longs in strong stocks. Market down: shorts in weak stocks. Relative strength is the stock's
   % change minus SPY's, checked on a 5-minute basis, with volume
   ([r/RealDayTrading thread](https://redlib.hackliberty.org/r/RealDayTrading/comments/otpd7a/understanding_and_figuring_out_relative_strength/ht9hq8d/?context=3)).
   No performance data in these threads.
4. **Key levels.** Premarket high and low, prior-day high and low, prior close, VWAP, whole and half dollars
   ([Bear Bull Traders materials, as summarised](https://www.forex.in.rs/aziz-daytrader-routine)). Breaking a level and holding on a retest is the common
   confirmation. No source here tests it.
5. **VWAP.** Stocks in play tend to hold or lose VWAP after the open; above VWAP is read as buying
   (Bear Bull Traders text, as summarised in my search; not read in full). The VWAP paper (1.2) is the only quantitative test.

## PLAYBOOK FOR THE DESK'S ANALYST

Paste into the analyst's system prompt. Each line: rule, then (strength). "Strong" means a test with stated rules and costs;
"some" means a paper or desk test with a gap; "weak" means popular belief only. No rule here is proven for this desk.

1. Only call a stock "in play" if the opening 5-minute volume is at least 1.5x its 14-day average for that bar; avoid otherwise. (strong: paper and the desk's own test)
2. Require a daily ATR of at least 3 % of price; skip calm stocks. (some: desk test; paper uses a dollar ATR)
3. Favor the direction the first 5-minute bar closed (long if up, short if down); a break against it is lower grade. (some: paper)
4. Rank stocks by opening relative volume; the higher the multiple, the better the thesis. (strong: paper, edge rose with the multiple)
5. Require a named catalyst (earnings, guidance, regulatory, contract, upgrade). No catalyst means "move may fade": lower the bias one notch. (some: attention studies; no intraday test)
6. Rank catalysts: company-specific numbers news above analyst notes above sector or macro talk above no news. (weak)
7. Prefer a stock that had not already run 50 %+ in recent weeks for a long thesis on news. (weak: Qullamaggie)
8. Compare the stock with SPY: long bias needs the stock stronger than SPY since the open; short bias needs it weaker. (weak)
9. If SPY and QQQ are both below VWAP and falling at 9:45, downgrade long theses one notch; the reverse for shorts. (weak)
10. A gap alone is not a thesis. A gap with 1.5x+ opening volume and news may continue; a gap on thin volume probably fades. (some: Berkman et al. vs the stocks-in-play paper)
11. Key levels to list: premarket high and low, prior-day high, low and close, VWAP, the opening range high and low. (weak as predictors; strong as price targets for stops and entries)
12. Confirms a long: a 5-minute close above the opening range high with volume above the opening candles and price above VWAP. Confirms a short: the mirror. (some: ORB paper; VWAP paper is disputed)
13. Invalidates: price closes back inside the opening range, or crosses VWAP the wrong way after entry. (weak)
14. Do not plan entries in the first 5 minutes or after 15:30; plan to be flat by 15:55. (some: papers exit at the close; the desk's rule)
15. Prefer "hold to the close" over a fixed 2R target in the plan text for strong catalyst days; say a quick target is likely to be hit rarely. (some: desk test, +0.19R vs about 0R on 41 sessions)
16. Flag low-float, under-$5 names, and halt-prone moves as "avoid": a stop does not fill during a trading pause. (some: LULD rules; FINRA warnings)
17. A stock down 10 %+ from the prior close (or yesterday) is under SEC Rule 201: a short may only fill above the bid. In paper mode the desk shorts it with a limit a cent over the trigger, which fills only on a bounce; do not call 'avoid' for that alone. In live mode the desk does not short it. (strong: rule; desk backtest 2026-11-20: +0.07R on 108 modelled fills, in-play ones −0.16R on 46, wide ranges)
18. After a narrow-range prior day (the narrowest of the last 4 or 7 days), raise the chance of expansion; note it. (weak: Crabel, untested here)
19. On a day when SPY has no direction and the stock's opening range is very wide relative to ATR, call "avoid": stop distance and slippage eat the edge. (weak)
20. Always state costs: breakeven requires the move to beat about $0.01 a share plus slippage; say if the stop is under 0.3 % of price. (strong: costs erase thin edges, both replications)

Output format for each stock: bias (long, short, avoid), one-line thesis, key levels, what confirms, what invalidates, and
the evidence strength of the two or three rules it leaned on.

## Changes worth testing in the desk's rules

The tool is `tools/vol_backtest.py`. Its `screen()` filters rows on `atr_pct`, `rvol`, `side` and the entry bar index. It
replays 60 days of 5-minute bars from Yahoo, about 41 sessions, so any new filter needs enough trades to be read (aim 100+).
Anything needing news, float or premarket data is not in the rows today and must be added to the data first.

| Candidate | How to test | Needs |
| --- | --- | --- |
| Relative volume at 2x, 3x, 5x (the paper: edge rose with rvol) | `screen(rows, rvol=...)`; compare avg R and profit factor at each step with the 5 basis point cost run | Nothing new |
| Early entry cutoff (`by=`) e.g. 10:30 vs 15:30 | `screen(rows, by=11)` | Nothing new |
| Longs only vs both sides | `side="long"`; the desk's held-out run had longs +0.166R, shorts +0.024R | Nothing new |
| First-bar direction agrees with breakout | Add a field to each row in `desk/backtest.py:signals` from the first bar's colour; filter | Small code add |
| SPY regime: SPY above/below its own VWAP or its first bar at the signal time | Fetch SPY 5-minute bars into the same cache, add `spy_vs_vwap` to rows; compare longs when SPY is up vs down | New field |
| Relative strength vs SPY at signal time | Add stock % change since open minus SPY's to rows; split into terciles | New field |
| Prior-day narrow range (NR4 or NR7) | Daily bars are already cached; compute the flag in `signals` | Small code add |
| Gap size and gap direction vs breakout direction | Gap = open vs prior close, from the daily cache; bucket by size and agreement | Small code add |
| Hold to 15:55 vs 2R target | Already in `--target-r` and the hold option; rerun on newer data | Nothing new |
| Catalyst present (news yes/no) | Cannot be backtested on Yahoo's 60 days; log the desk's catalyst score each morning and score it in the paper review | Daily logging |

Rules for the test: choose the setting on the train half only; judge on the held-out half; report 5 basis point costs; keep a filter
only if it helps on both halves and the trade count stays above 100. One session of data from one autumn can be one market mood.

## Sources not listed inline above

- Retail Traders Repository on the 2023 paper: https://retailtradersrepository.substack.com/p/trading-research-paper-can-day-trading-really-be-profitable
- QuantConnect VWAP/ORB replications: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/
- Existing desk research and full source list: `docs/VOLATILITY.md`

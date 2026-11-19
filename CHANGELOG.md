# Changelog

## 1.2.2 (2026-11-19)

- **Each model has its own practice account.** Model 1 (opening-range breakout
  and Claude's game plan) keeps the main one. Model 2 (combined SPY) and model 3
  (winter 3x) trade in `data/accounts/combo/` and `data/accounts/winter3x/`
  (`desk/modelacct.py`), each with a `model.json` record and its own
  `journal.db`. Same starting cash as your practice account, fractional
  shares, market orders at the first price after 9:35 plus 3/5 bp, idle cash
  at a typical 0.01 % bank sweep, dividends paid on their pay date, T+1
  settlement and a good-faith-violation counter. The cash can no longer go
  below zero. `python3 -m desk migrate-models` moves older books across;
  `--account combo` and `--account winter3x` are reserved.
- **Winter 3x paper book** (`desk/winter3x.py`, `GET /api/winter3x`,
  `python3 -m desk winter3x`): UPRO November to April, SPY May to October,
  cash below the 200-day average. It did not pass its sealed test; it is a
  forward practice record only, and leveraged funds can fall far and fast.
- **Graph tab and review** show models 2 and 3; Desk cards show each account.
- **Sealed beat-the-S&P research** (`research/beat_spy/`): 222 rules, developed
  on 1961-2009, tested once on 2010-2026, with a walk-forward and nine foreign
  indices. No finalist passed. Plus `research/compare_models.py`.
- **Faster from candle close to ready slip** (`docs/SPEED.md`): fresh setups
  graded side by side, short-side charts read 4 at a time during the scanner,
  no pause between scanner reads, the loop wakes on the second a scan is due,
  auto paper right after the scan, and the hourly catalyst gather in its own
  thread. The busiest scan measured went from 56 s to 9.4 s. Same signals,
  sizes, stops and targets (`tests/test_speed.py`). Every scan records a
  `timings` dict.

## 1.2.1 (2026-11-19)

- **Combined SPY model, a second paper book** (`desk/combo.py`): three
  daily votes on SPY (dip-buyer, Halloween, turn of month, each "or above the
  200-day average"), held as their average. Dividends and T-bill interest on
  uninvested cash count. Desk-tab card, review section, `GET /api/combo` and
  `python3 -m desk combo`. Paper only.
- **Entry style A/B, shadow only**: after the close each long slip that was
  good to buy is also replayed with a buy limit at the session VWAP and at the
  opening-range high. Logged for comparison; it changes no signal or fill.
- **SPY-vs-VWAP tag** on each long slip's replay, for the review.
- **Backtest rows** gain the playbook's fields and the shadow entry arms;
  Claude's playbook carries the test results as evidence notes.
- **docs/MODELS.md**: the combined model, the opening-range check against the
  desk's own backtest, and nine playbook filters declared before testing (none
  passed, so nothing is switched on).

## 1.2.0 (2026-11-19)

- **Desk tab redesign**: a TradingView-style workspace. Today's list on the
  left with Claude's bias per stock, a candle chart in the middle (1-minute,
  5-minute or daily, with VWAP, the 9 and 20 EMA, premarket, prior-day and
  opening-range lines, and the slip's entry, stop and target), the plan,
  account and signals on the right. The chart (Lightweight Charts) and the
  fonts (Geist, Schibsted Grotesk) are stored in `desk/static/vendor` with
  their licences; nothing loads from the internet. New read-only route
  `/api/chart`. See docs/CHART-SETTINGS.md.
- **Claude's game plan** (optional, needs the `claude` command): each morning
  and hour Claude reads the day's list and writes a plan from the playbook in
  docs/STRATEGIES.md. In paper mode it can tighten the day's settings and grade
  signals it argues against as weak (`plan_filter`); the review compares
  signals with and against the plan. `/api/plan` asks it to look again now.
- **Volatility screen** (paper mode): signals on stocks that are not in play
  (opening volume under 1.5x normal, or daily range under 3 % of the price)
  are graded weak. Backtest and research in docs/VOLATILITY.md
  (`tools/vol_backtest.py`).
- **The desk picks its own scan list** each morning (paper mode by default):
  the most volatile liquid stocks, plus your always-scan tickers and Yahoo's
  movers screeners. Optional watchlist agent (`python3 -m desk agent`).
- **Catalyst tracker**: public news and events, scored 0 to 100, with places
  on the morning list. New Catalysts tab.
- **Phone alerts** through ntfy, a **Graph** tab, and **extra paper accounts**
  (`python3 -m desk --account NAME`). Ported from a community fork.
- **Paper mode**: risk per trade and the daily loss limit now come from your
  Settings in both modes.
- **Fixes**: early closes move flat-by up to 12:55; no hourly plan or catalyst
  look on NYSE holidays; the short-sale restriction (Rule 201) carries into the
  next day; auto paper leaves a signal alone when the price is already at its
  stop; practice stop and market fills pay the slippage guess; practice short
  fills are logged; Health warns when the holiday calendar does not cover the
  year; a missing import that would have stopped a live short scan.
- Optional 7:50 weekday start for Mac, documented in the README.
- Still broker-neutral: the desk never places a real order.

## 1.1.0 (2026-11-18)

- **Short side, off by default.** Opening-range breakdowns, the long rule
  mirrored: long, short or nothing per stock. Shorts are practice only unless
  your account can really short (margin, $2,000 or more, and the approval
  switch on). Auto paper can practise shorts in paper mode. Every scan logs
  the decision per stock and why. Both chart studies can draw the short
  levels. See docs/SHORTING.md.
- **Risk stops over more than a day**: weekly loss limit, drop from the best
  point, losers in a row, with a Reset stops button. They stop new entries
  only. Ideas from CloddsBot, see docs/CLODDSBOT.md.
- **Richer review**: odds by edge band, why signals were held back, stop trips
  and resets, profit factor, best and worst trade, worst day, scan decisions,
  results by side.
- **Auto paper "Take weak signals too" switch**, off by default.
- **Paper mode learning profile** (paper only, live unchanged): no
  trades-a-day cap, sales settle at once, bolder risk limits and 4x buying
  power, so the practice record shows more. Rule stamps record the paper
  rules in force.
- **Replay retry**: after-close replays that got no candles are retried with a
  longer history.
- Still broker-neutral: the desk never places a real order.

## 1.0.0 (2026-11-11)

First public release: the opening-range-breakout signal desk on the 11
day-trader-skill tools, paper and live journals, auto paper trading in a
pretend practice account, the review report and after-the-close replays, the
dashboard, the thinkorswim and TradingView studies, watchlist export and the
Mac screenshot reader. Broker-neutral: it never places a real order.

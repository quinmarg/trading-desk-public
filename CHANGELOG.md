# Changelog

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

# Changelog

## Unreleased

- Phone alerts through ntfy: each new Ready slip, with its headlines, is
  pushed to an ntfy topic set in Settings (off by default, never in the demo),
  plus a **Send test alert** button.

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

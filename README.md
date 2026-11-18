# Trading Desk

A local day-trading **signal desk** for learning, built on the 11 skills in
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) by
Jake Schincariol. It finds opening-range breakouts in US stocks (and, if you
switch it on, breakdowns for practice shorts), works out the
exact order (shares, buy limit, stop, target, how long the signal is good
for), checks it against your own limits, and shows you how to enter it at your
broker. It keeps a journal of what you did, can practise by itself on a
pretend account, and writes a review of how the rules are doing.

It runs on your own computer, uses only free delayed public data, and needs
nothing but Python.

> [!WARNING]
> **Not financial advice. For education only.** Most day traders lose money.
> The data is free and delayed, the odds are estimates from past prices, and
> nothing here is a recommendation to buy or sell anything. Check every
> number against your broker before you place an order, and only trade money
> you can afford to lose. The authors accept no responsibility for any loss.

**It never places a real order.** The desk has no connection to any broker.
You place every trade yourself, at your broker, and tell the desk what
filled. The only orders it ever "places" are in its own pretend practice
account (see Auto paper below), which lives in a file on your computer.

## Install

Needs Python 3.9 or newer. There is nothing to `pip install`: it uses the
Python standard library only. Works on macOS, Linux and Windows (the
screenshot reader and the Dock app are Mac-only extras).

```bash
git clone https://github.com/<you>/trading-desk.git
cd trading-desk
```

## Run it

```bash
python3 -m desk --demo     # saved data from Monday 2026-10-19, no network: look around first
python3 -m desk            # today's market, during US market hours
python3 -m desk review     # print your record (paper and live) as text and exit
```

The dashboard opens at http://127.0.0.1:8787 and only your computer can reach
it. Use `--port 8790` (or any free port) if 8787 is taken, and
`--no-browser` to stop it opening a browser tab. Stop it with Ctrl+C.

On a Mac you can also double-click `start.command`, or build a Dock app with
`tools/make_app.sh` (it creates **Trading Desk.app** in `~/Applications`;
click to start the desk, right-click > Quit to stop it).

The demo keeps its data in `data-demo/`, apart from your real record in
`data/`. Never trade from the demo: it is one old day with the clock stuck at
10:15 AM.

## What a day looks like

1. Before the open the desk lists daily-chart setups to watch.
2. From 9:45 AM to 3:30 PM New York time it scans after every 5-minute candle
   closes.
3. A breakout that fits your account becomes a slip:
   *Buy 3 W at 110.77 or lower. Stop 108.91. Target 113.56. Good until 10:25.*
4. If you want it, enter it at your broker as a bracket order (a buy with a
   stop and a target attached, one cancelling the other). The slip lists the
   steps. If the price is already above the limit, skip it.
5. Press **I placed it and it filled** and type your fill price.
6. The desk rings when the stop, the target or 3:55 PM arrives. Your bracket
   order at the broker is what actually sells; then record the exit here.

## Paper or live

The badge at the top of every tab says **PAPER · practice** or
**LIVE · real money**. They are two separate records, each with its own cash,
signals, trades and results, so practice never mixes with real money.

- The desk starts in paper. Use it alongside your broker's practice (paper)
  account if it has one, and set the desk's cash to the amount you would
  really trade, not a big practice default.
- To switch: Settings > **Paper or live**, type LIVE. Live starts at $0 until
  you enter your real cash in the Account tab. You cannot switch while a
  trade is open.
- When to move from paper to live is your decision. The desk has no opinion.

## Auto paper (practice, no real money)

The Desk tab's **Auto paper** switch lets the desk trade by itself, in paper
mode only, in a pretend practice account kept in `data/paper-account.json`.
Each ready signal's bracket order goes into that account, which fills it from
free delayed prices. A buy not filled by the slip's good-until time is
cancelled; an open trade is sold at the market at the flat-by time. It obeys
your limits (trades per day, loss per trade, daily loss, settled cash, Pause),
and every entry and exit lands in the paper journal marked **Auto**, so the
review can compare its trades with yours.

- It never trades in live mode and never talks to a broker (`desk/auto.py`,
  tests in `tests/test_auto.py`).
- **Take weak signals too** (switch under Auto paper, off by default): auto
  paper also practises signals whose Time Machine odds are under your floor,
  so the review can show how they would have done.
- **Paper mode trades boldly so the record has more to learn from.** In paper
  mode only: 5 % risk a trade, 20 % daily loss, no weekly stop, a 50 % drop
  stop, no cash buffer, no trades-a-day cap, sales settle at once, and 4x the
  account as buying power (like a margin account's day-trading power). Live
  mode always uses your own settings and plain settled cash. The profile is
  `PAPER_BOLD` and `PAPER_LEVERAGE` in `desk/settings.py`; each signal's rule
  stamp records the paper rules in force.
- Practice fills from delayed quotes are not real fills. Use it to see what
  the rules do, not to predict live results.
- Settings > **Practice account** starts it over.

## Phone alerts (ntfy)

The desk can push each new **Ready** slip to your phone through
[ntfy](https://ntfy.sh): the order, the reward to risk, the odds and up to
three of the headlines it pulled, with buttons for the articles and the chart.

1. Install the ntfy app and subscribe to a long, hard-to-guess topic name.
2. Settings > **Phone alerts (ntfy topic)**: paste the same name, Save.
3. Press **Send test alert** to check your phone.

Empty topic = off. The demo never pushes. A failed push is logged and
dropped; it never stops a scan. Weak and blocked signals are not pushed.

> [!NOTE]
> On ntfy.sh, topics are public: **anyone who knows the topic name can read
> your alerts.** Pick a name nobody would guess, or run your own ntfy server
> and put its `https://` address in Settings > **ntfy server**.

## The Account tab

Because the desk never connects to a broker, you tell it your cash and how
each trade ended. Type the numbers, or on a Mac drop in a screenshot of your
broker's balance or filled-orders screen and the desk reads it on your own
computer (Apple Vision; nothing is uploaded). It only suggests; nothing is
saved until you press Save. The reader knows thinkorswim's labels; other
brokers may need more label words in `desk/screenshot.py`. Details:
[docs/ACCOUNT-TAB.md](docs/ACCOUNT-TAB.md).

## Reading your record

- **Journal > How it is going**: average win and loss, worst drawdown,
  longest losing run, your fills against the slip's limit, signals by
  outcome. Under 20 closed trades it says "Too few to judge".
- **`python3 -m desk review`** prints the record as plain text for both modes,
  including every scan, every practice fill, and an after-the-close replay of
  every signal of the day (taken or not) on that day's candles
  (`desk/outcome.py`; a replay that got no candles, say because the computer
  was offline, is retried later). It also shows whether the Time Machine's
  odds held up, those odds by edge band, why signals were held back, every
  risk-stop trip and reset, profit factor and the worst day. It changes
  nothing.
- Every signal carries a **rule set** code, so results can be read per set of
  rules. Every settings change is logged; write rule changes up in
  [docs/CHANGES.md](docs/CHANGES.md).

## Things that keep you out of trouble

- **Pause** (Desk tab): no new signals and no new fills until you resume.
- **Health** (Settings): the clock, the last scan, the data, the skills copy
  and which record is in use. After three failed scans in a row the Desk tab
  says "Do not trust the list right now".
- **Risk stops over more than a day** (Settings, under the daily loss limit;
  `desk/breaker.py`): a **weekly loss limit** (default 8 % of the account,
  clears on Monday), a **drop from your best point** (default 15 %) and
  **losers in a row** (off until you set a number). The last two stay on until
  you read the review and press **Reset stops** under Today's limits. Like the
  daily limit they stop new entries only, for you and auto paper; open trades
  keep their stop, target and flat-by time. Ideas from the CloddsBot project,
  rebuilt in Python: [docs/CLODDSBOT.md](docs/CLODDSBOT.md).
- **Closest stop** (`min_stop_pct`, default 0.3 %): a stop nearer the entry
  than that blocks the signal.
- **Slippage guess** (`est_cost_per_share`, default $0.01): each slip also
  shows reward to risk after it.
- The desk can only ever run the Order Executor skill's `show` command (the
  ticket text). Every other command is refused in `desk/guards.py`.

## The short side (off by default)

Settings, **Signals to look for**, can add short signals: opening-range
breakdowns, the long rule mirrored. Per stock the desk decides long, short or
nothing. A short slip reads
*Sell short 5 IONQ at 30.11 or higher. Buy stop 31.59. Target 27.87.*
and is marked **SHORT** in red.

- Shorts are **practice only** (labelled PRACTICE ONLY) unless the account
  type is margin, the account has $2,000 or more, and "My broker approved this
  account for short selling" is on. In live mode a practice-only short is
  shown but cannot be recorded.
- In paper mode, auto paper can practise short signals in the practice
  account. The desk still never sends any order anywhere.
- Every scan logs one row per stock: long, short, both or nothing, and why.
  The review shows those counts and results for longs and shorts apart.
- The loss on a short is not capped, shares may not be available to borrow,
  and a short-sale restriction applies after a 10 % drop. The dashboard says
  so on the Desk tab, on every short slip and in Settings.
- The desk blocks a short when the stock is already down 10 % on the day, or
  is above its 200-day average, and wants the short's full value in settled
  cash. Shorts are closed by the flat-by time, never held overnight.
- Four of the skills are long-only, so the short maths is the desk's own code
  in `desk/shorts.py`. No real short order has been placed from a slip: treat
  your first practice short as the test.

Sources, rules and limits: [docs/SHORTING.md](docs/SHORTING.md).

## How the money rules scale

Every limit is a percentage of the account:

| setting | default | at $400 | at $40,000 |
| --- | --- | --- | --- |
| risk per trade | 2 % | $8 | $800 |
| daily loss limit | 4 % | $16 | $1,600 |
| cash kept aside | 5 % | $20 | $2,000 |
| trades per day | 2 | 2 | 2 |

These are your settings, used in live mode. Paper mode uses the bolder
practice profile described under Auto paper.

In a cash account, money from a sale cannot buy again until the next business
day. The desk tracks settled cash and sizes only against that.

## Where each skill is used

| skill | in the desk |
| --- | --- |
| Chart Scanner | the scan every 5 minutes, and the pre-market watch list |
| Entry Timer | confirms the breakout candle closed above the range |
| Exit Planner | the stop and the target |
| Time Machine | the odds bar on every slip (10,000 replays + the last 60 days) |
| Budget Manager | how many shares |
| Risk Manager | pass or block, with reasons |
| Order Executor | the order ticket text only (its broker connection is never used) |
| Price Alerts | market clock, stop / target / flat-by-close rings |
| News Monitor | headlines on each slip, earnings warnings |
| Earnings Analyst | Research tab (put your name and email in Settings > SEC contact) |
| Pelosi Tracker | Research tab: public congressional trade filings |

## Chart studies

- **thinkorswim**: `thinkorswim/TradingDesk_ORB.ts` draws the same levels on a
  5-minute chart. In thinkorswim: Studies > Edit studies > Create, paste the
  file, OK. Keep its inputs equal to the dashboard's settings.
- **TradingView**: `tradingview/TradingDesk_ORB.pine` is the same study in
  Pine Script v6, with an alert named **Trading Desk breakout** (indicator
  alerts need a paid TradingView plan). Steps: `tradingview/INSTALL.md`.

Both are indicators: they cannot place orders. `tests/test_chart_studies.py`
checks that their defaults equal `desk/settings.py`. Both have a "show shorts"
input, off by default, that also draws the breakdown, the sell limit, the buy
stop and the short target.

## Export watchlist

The Desk tab's **Export watchlist** card turns today's signals, open trades
and your watchlist into a list you import yourself: **Copy for thinkorswim**
(one ticker a line, which most platforms accept) and **Download for
TradingView** (`NASDAQ:AAPL,NYSE:F,...`). Each ticker also gets a **Chart in
TradingView** link. The desk sends nothing anywhere.

## Tests

Everything runs offline on saved data.

```bash
python3 -m unittest discover -s tests -t .                               # the desk
(cd vendor/day-trader-skill && python3 -m unittest discover -s tests)    # the vendored skills
```

Two screenshot-reader tests run only on a Mac after the reader is built
(`swiftc -O tools/ocr/ocr.swift -o build/ocr`, needs the Xcode command line
tools); elsewhere they are skipped.

## Layout

```
desk/settings.py    settings, validated, scaled to the account
desk/journal.py     SQLite: cash ledger with settlement, signals, trades
desk/skills.py      runs the vendored skill scripts
desk/source.py      live clock and data, or the demo's saved data
desk/pipeline.py    one stock through every skill -> one signal (long, and short)
desk/shorts.py      the short side's maths: breakdown, stop, target, size, gate
desk/charts.py      5-minute and daily candles for the short side (read-only)
desk/decide.py      one row per stock per scan: long, short, both or nothing, and why
desk/breaker.py     risk stops over more than a day: weekly loss, drop from the best point, losers in a row
desk/engine.py      scan, watch, record fills and exits
desk/paper.py       the pretend practice account
desk/auto.py        auto paper: the desk trades the practice account itself
desk/orders.py      order shapes for the practice account
desk/outcome.py     after-the-close replay of every signal
desk/review.py      results, the review report, day summary
desk/scheduler.py   the background loop
desk/server.py      local web server (127.0.0.1 only)
desk/screenshot.py  reads numbers off broker screenshots (Mac)
desk/exports.py     watchlist export and chart links
desk/notify.py      phone alerts for ready signals (ntfy)
desk/static/        the dashboard
thinkorswim/        chart study for thinkorswim
tradingview/        chart study for TradingView, install steps
tools/              Mac Dock app and the screenshot reader source
vendor/             day-trader-skill, pinned (vendor/PINNED_COMMIT)
data/               your journal and settings (created on first run, not in git)
```

## Licence and credits

Trading Desk is released under the MIT licence: see [LICENSE](LICENSE).

It includes an unmodified copy of
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) by
**Jake Schincariol** in `vendor/day-trader-skill`, used under its MIT licence
(Copyright (c) 2026 Jake Schincariol). The full licence text is in
[vendor/day-trader-skill/LICENSE](vendor/day-trader-skill/LICENSE) and
repeated in [LICENSE](LICENSE). Market data comes from free public sources
(Yahoo Finance charts, SEC EDGAR, the House Clerk); follow their terms of use.

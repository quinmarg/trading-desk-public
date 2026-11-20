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
python3 -m desk combo      # model 2, the combined SPY account: bring it up to date and print it
python3 -m desk winter3x   # model 3, the winter 3x account, the same way
python3 -m desk migrate-models   # once, after updating: moves older combo/winter3x books into their own accounts
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

1. At 8:00 the desk picks today's stocks to scan (paper mode), lists daily-chart setups to watch, and Claude
   writes the game plan (if the `claude` command is set up).
2. From 9:45 AM to 3:30 PM New York time it scans 25 seconds after every 5-minute candle
   closes. **The Mac has to be awake**: if it sleeps (a closed lid on battery, for example) the desk sees none of
   those breakouts, and the event log says when that happened. A ready slip and its phone alert usually follow 5 to 15
   seconds later (`docs/SPEED.md`).
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

Two more things are logged for comparison only; neither changes a signal, a size or a fill:

- **Entry style A/B (shadow).** For each long slip that was good to buy, the after-close replay also asks
  what a buy limit at the session VWAP, or at the opening-range high (a retest), would have done with
  the same stop and target, resting 60 minutes. The review lists the three side by side, in the real
  slip's risk units, and says to wait for 20 trading days before reading anything into it.
  It also tags each long slip's real replay by SPY's side of its VWAP at the trigger, the best of nine
  playbook filters in the backtest but not yet significant (`docs/MODELS.md` section 5).
- **Models 2 and 3**, the combined SPY account (`desk/combo.py`) and the winter 3x account (`desk/winter3x.py`): see below.

## Three models, three practice accounts

Each model trades only by its own rules, in its own practice account. Nothing mixes.

| Model | Account | Starting cash | Trades |
|---|---|---|---|
| 1. Opening-range breakout + Claude's game plan | the main practice account (`data/journal.db`, `data/paper-account.json`) | your starting balance | auto paper, all day |
| 2. Combined SPY | `data/accounts/combo/` | the same as yours | once a day, SPY |
| 3. Winter 3x | `data/accounts/winter3x/` | the same as yours | once a day, SPY or UPRO or cash |

Models 2 and 3 (`desk/modelacct.py`) work like a small cash account at a large U.S. broker. They buy
**fractional shares** (from $1, no commission at large brokers), so a few hundred dollars can follow a
1/3 or 2/3 weight. Each trading day from 9:35 New York they decide from the close before and trade at
the first price after that, plus 3 basis points a side on SPY and 5 on UPRO. Idle cash earns a typical
bank sweep rate (0.01 % a year, `SWEEP_APY`; set it to your broker's), not T-bills. A dividend is owed
from the ex-date and paid in cash on its pay date. Money from a sale settles the next trading day, and
a good-faith violation would be counted on the card (the rules trade at most once a day, so it should
stay at zero). Each account has its own `journal.db` (cash ledger and trades), rebuilt from the model's
record on every run. They show on the Graph tab as made or lost each day, in the review under
**MODEL 2** and **MODEL 3**, and on their Desk tab cards. They never place a real order. The research
behind each choice: [docs/MODELS.md](docs/MODELS.md) section 8.

### Model 2: the combined SPY account

A daily model on SPY from a friend's model lab. Three votes, each in or out, and the account holds their
average (0, 1/3, 2/3 or all of it): **dip-buyer** (above the 200-day average, or RSI(2) under 10 until the
close is back over the 5-day average), **Halloween** (November to April, or above the 200-day) and
**turn of month** (last trading day and first 3, or above the 200-day). It decides from the close
before, on dividend-adjusted closes, trades only when the weight changes, and backfills days the desk
was off at their open. The Desk tab's **Model 2** card shows today's weight, the votes, the account
(balance, holding, cash and settled cash) and buy-and-hold SPY from the same start. `GET /api/combo`
and `python3 -m desk combo` give the same. What the lab found and what is in-sample:
[docs/MODELS.md](docs/MODELS.md).

### Model 3: the winter 3x account

The best finalist of a sealed beat-the-S&P test ([research/beat_spy/REPORT.md](research/beat_spy/REPORT.md)), added on
request. It holds UPRO (3x S&P 500, daily reset) from November to April and SPY from May to October while SPY is above
its 200-day average, and cash below it. A switch sells first and buys with the unsettled money, as a cash account may.
Dividends are reinvested on their pay date. **It did not pass its test**: in 2010-2026 it made 14.2 % a year against
SPY's 13.8 %, with a worst drop of -48 % against -34 %, and p = 0.47. It is a forward practice record only.
Leveraged funds carry real risks: UPRO fell about 77 % in five weeks in 2020, and daily reset lets a choppy market
eat a 3x fund even when SPY ends flat (the report's section 4). The Desk tab's **Model 3** card compares it with
model 2 and buy-and-hold SPY over the same days. `GET /api/winter3x` and `python3 -m desk winter3x` give the same.

## Volatile stocks (paper mode)

In paper mode the desk keeps to stocks **in play**: a signal counts only when the stock's opening
volume is at least 1.5x its normal and its daily range (ATR) is at least 3 % of its price; otherwise it
is graded weak, "Not in play". Each morning it also picks its own scan list, the 40 most volatile
liquid stocks, and shows why each one is there under "Stocks to scan today" (Settings, "Pick stocks to
scan for me": paper, on or off; your watchlist is the fallback). The research, the backtest
(`python3 tools/vol_backtest.py`), the before-and-after numbers and a volatile watchlist to paste into
Settings are in [docs/VOLATILITY.md](docs/VOLATILITY.md). Live mode is unchanged unless you set
`min_rvol` or `min_atr_pct`.

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

## Claude's game plan (optional, needs the `claude` command)

If the [Claude Code](https://claude.com/claude-code) `claude` command is installed and signed in, Claude
studies the day's list each morning after the 8:00 pick (`desk/analyst.py`, the **Desk** tab's right side).
Without it the desk trades on without a plan; turn it off in Settings (`analyst`).

- **What it reads**, all free and read-only: SPY, QQQ and IWM's daily trend; for each stock on the list its daily
  chart in numbers (20/50/200-day averages, RSI, 20-day high and low, prior day's levels, narrow-range days, strength
  against SPY), the Chart Scanner's daily setups, its catalyst and its headlines.
- **How it decides**: the playbook in [docs/STRATEGIES.md](docs/STRATEGIES.md), 20 rules distilled from studies of
  opening-range breakouts on stocks in play, intraday momentum, gaps and news, and the published rules of successful
  traders and systematic bots, each marked strong, some or weak evidence.
- **What it writes**: the market's mood, what to watch for today, and per stock a bias (long, short or avoid), a
  conviction from 1 to 5, a thesis, the levels, what confirms it and what kills it. With ntfy set up, it goes to your
  phone too.
- **All day**: each hour from 10:00 to 3:00 it looks again at how each stock trades (change on the day, VWAP,
  volume), the signals so far, today's movers and new catalysts. It updates the plan and may add up to 5 in-play
  stocks to the list (`analyst_adds`). **Look again now** runs it at once.
- **Settings for the day (paper mode)**: the plan writes today's stocks into Settings' watchlist and may set the
  directions, lower risk per trade to between half of yours and yours, and move the last entry earlier, with a reason
  in the log. Each morning starts from your own settings again; a setting you changed yourself stays yours.
  If the lower risk leaves a trade at 0 shares, the desk sizes it at your own risk instead, which is always one share
  and never more than your own setting.
- **Signals**: each slip shows what the plan said. In paper mode a ready signal the plan argues against (avoid, or the
  other side at conviction 3+) is graded weak (`plan_filter`: paper, on or off). The review's "CLAUDE'S GAME PLAN"
  section compares signals with and against the plan, so the research has to earn its place.

It runs `claude -p` with Sonnet on your own Claude plan, with no tools and no MCP; headlines are treated as data.
Live mode only gets the notes on each slip: no filter, no settings changes.

### Optional: start the desk at 7:50 on weekdays (Mac)

A launch agent can start the desk before the 8:00 pick. `tools/app/desk-control.sh start` does nothing when the
desk is already running. Save this as `~/Library/LaunchAgents/com.example.tradingdesk.morning.plist`, with
`/path/to/trading-desk` replaced by your own folder:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.tradingdesk.morning</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>/path/to/trading-desk/tools/app/desk-control.sh</string><string>start</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>50</integer></dict>
  </array>
</dict>
</plist>
```

The times are your Mac's local time: set 7:50 in New York time for your time zone. Load it with
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.tradingdesk.morning.plist` and turn it off with
`launchctl bootout gui/$(id -u)/com.example.tradingdesk.morning`. A sleeping Mac runs it when it wakes; to wake the
Mac for it, `sudo pmset repeat wakeorpoweron MTWRF 07:45:00`.

## The Desk tab

A TradingView-style workspace: today's list on the left with Claude's bias for each stock, the chart in the middle
(1-minute, 5-minute or daily candles with VWAP, the 9 and 20 EMA, the premarket, prior-day and opening-range lines and
the slip's entry, stop and target), and the plan, account and signals on the right. At the top of the right side a
money strip leads with **All models**: made or lost today and since the start, summed over every model running. Then a box
per model (Breakout + Claude, Combined SPY, Winter 3x) with its made
today and since start in large green or red type and its balance under them, then two small boxes with what the
breakout model can spend and risk on a trade. In live mode the breakout row is your real account and the total
says it mixes real and practice money; models 2 and 3 are always practice. Type any ticker in the list's box
and press Enter to chart it. Chart settings and how to set up TradingView the same way: [docs/CHART-SETTINGS.md](docs/CHART-SETTINGS.md).
The chart is TradingView's open-source Lightweight Charts and the fonts are Geist and Schibsted Grotesk, all stored in
`desk/static/vendor` (licences there); nothing loads from the internet.

## The daily list, the watchlist agent, the graph and extra paper accounts

- **One list a day.** Before the open the desk reads a year of daily bars for its own pool of liquid
  stocks, your watchlist, your **Always scan these** tickers and the names on Yahoo's free most-active,
  gainers and losers screeners. Your always-scan tickers go on the list whatever their range; the
  **Stocks picked each day** most volatile of the rest join them (40 by default). It all shows under
  "Stocks to scan today", each with why.
- **Watchlist agent** (Settings, off by default): Claude reads those candidates' headlines and picks
  from them, with a reason each, avoiding halts, fixed-price buyouts and reverse splits. It uses the
  signed-in `claude` command on your Claude plan, with Haiku, no tools and no MCP, and can only pick
  stocks the formula already found. If Claude fails or keeps too few, the formula's picks stand.
  `python3 -m desk agent` is a dry run; add `--apply` to make the picks today's list.
- **Graph tab**: made or lost over time for the bot, you and the total; every paper account on one
  chart; results by day. Closed trades only, except the two model accounts, which hold for weeks: their
  line is the account's value each day less its starting cash.
- **Extra paper accounts**, practice only, each with its own cash, journal and tickers in
  `data/accounts/NAME`, on the first free port from 8791:

  ```bash
  python3 -m desk --account growth --tickers "TSLA NVDA AMD"
  ```

  Run it again without `--tickers` to reopen it. Its alerts say its name. It cannot switch to live.
  A new account starts with Claude's game plan and catalyst alerts off, so the main desk is the only one
  using your Claude plan each hour and pushing those to your phone; turn them on in its Settings if you want.
- **Trades per day**: 0 means no cap, and 0 is the default, in live mode too. Paper mode never had one.

## Catalysts: news and events that move stocks

The **Catalysts** tab follows public news and events and ranks them, so the morning list can lean
toward stocks with a reason to move today (`desk/catalysts.py`). Free, read-only, no key, no account:

- **Where it looks**: Yahoo's trending tickers and its most-active, gainers and losers screeners;
  Nasdaq's IPO calendar and earnings calendar (companies worth $2 billion or more, today and the next
  weekday); the News skill's headlines (and SEC filings when you set an SEC contact); a year of daily
  bars; and your own lines under **Events to watch** in Settings, one per line, like
  `TTWO GTA 6 launches 2026-11-19`.
- **Second-order names**: clear peers, suppliers and investors (EA and RBLX next to Take-Two; Amazon
  and Google next to the Anthropic IPO), each with its reason. The list is short and hand-kept.
- **The score** (0 to 100): fresh 30, big 25, confirmed by more than one source 25, a lively chart 20.
- **One list.** The best tradeable catalysts scored 40 or more take up to **Places for catalysts**
  (10) of the stocks picked each morning, with the catalyst as the reason. The rest of the places
  go to the most volatile, as before. The tab marks each catalyst "On today's list", "Not on the list"
  or "Watch".
- **New listings**: an IPO has no history, and the opening-range rules need 15 days of daily bars.
  It shows as "Watch, not tradeable yet" with the date it should become eligible (holidays can push
  that a day later).
- **When**: at 8:00 AM New York with the morning pick, then each hour until 4 PM on weekdays, or when
  you press **Look again now**. Later looks add to the tab; they never change the day's list.
- **Phone alerts** (Settings, Catalyst phone alerts, off): new catalysts scored 70 or more go to your
  ntfy topic, at most 3 a look, each once a day. They say they are not signals.
- **The review** logs each day's catalysts and compares signals on the list for a catalyst against
  signals on it for their daily range ("CATALYST PICKS AGAINST THE VOLATILITY PICKS").

Web text is treated as data: it is cut to one line and shown, never followed. A catalyst is a reason
to look, not a signal; a trade still needs its breakout. The desk still never places a real order.

## Things that keep you out of trouble

- **Pause** (Desk tab): no new signals and no new fills until you resume.
- **Health** (Settings): the clock, the last scan, the data, the skills copy
  and which record is in use. After three failed scans in a row the Desk tab
  says "Do not trust the list right now". It warns when the holiday calendar
  in the skills copy does not cover the current year (it covers 2026-2027).
- **Holidays and early closes**: on an NYSE holiday there is no game plan and
  no hourly catalyst look. On a 1:00 PM early close (2026-11-27, 2026-12-24,
  2027-11-26) new entries stop 3 hours early and flat-by moves up with the
  close, 15:55 to 12:55, for every new signal and for auto paper.
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
  shows reward to risk after it. It never blocks a signal. In the practice
  account a stop or market fill (a stop-out, a flat-by sale, a cover) fills
  that much worse than the price, as a real one would; set 0 for exact fills.
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
- Under SEC Rule 201 (down 10 % today, or yesterday) a short may only fill
  above the best bid. In paper mode the slip then rests its sell-short limit a
  cent over the trigger close, so it fills only if the price bounces back up
  to it (docs/IMPROVE-2026-11-20.md); in live mode the desk blocks it. The desk
  also blocks a short when the stock is above its 200-day average, and wants the short's full value in settled
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
desk/outcome.py     after-the-close replay of every signal, plus the shadow entry arms
desk/review.py      results, the review report, day summary
desk/scheduler.py   the background loop
desk/server.py      local web server (127.0.0.1 only)
desk/screenshot.py  reads numbers off broker screenshots (Mac)
desk/exports.py     watchlist export and chart links
desk/volscreen.py   is the stock in play: ATR % and opening relative volume
desk/autolist.py    the desk's own scan list each morning, most volatile first
desk/backtest.py    the rule over 60 days of 5-minute bars (tools/vol_backtest.py)
desk/analyst.py     Claude's game plan: morning and hourly looks, day settings (optional)
desk/agent.py       the watchlist agent: Claude picks from the morning's candidates (optional)
desk/notify.py      phone alerts for ready signals and big catalysts (ntfy)
desk/catalysts.py   public news and events, scored, with places on the morning list
desk/combo.py       model 2, the combined SPY model, in its own practice account (docs/MODELS.md)
desk/winter3x.py    model 3, the winter 3x model, in its own practice account (research/beat_spy/REPORT.md)
desk/modelacct.py   the practice account models 2 and 3 trade in: fractional shares, T+1, sweep, dividends
desk/graph.py       the Graph tab: made or lost over time, every paper account
desk/static/        the dashboard (vendor/: Lightweight Charts and two fonts, with licences)
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

The Desk tab's chart uses [Lightweight Charts](https://github.com/tradingview/lightweight-charts) by
TradingView, under the Apache License 2.0, and the fonts Geist and Schibsted Grotesk, under the SIL Open
Font License 1.1. Their licence files are in `desk/static/vendor`.

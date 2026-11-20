# Short side: rules, sources and how it works

The desk can look for **short** signals as well as long ones: long, short or
nothing per stock. It is **off by default** (`directions` = `long`).

**The desk never sends an order anywhere, long or short.** You place every
trade yourself at your broker. Shorts are practice only unless your account
can really short (section 3). Not financial advice.

## 1. Short-selling rules, checked 2026-11-10

| fact | source | what the desk does |
| --- | --- | --- |
| Shorting needs a margin account. A cash account cannot short. | Broker margin and short-selling pages | A short is "practice only" unless `account_type` is margin. |
| At least $2,000 of equity to borrow at all. | FINRA Rule 4210 | "Practice only" while the account is under $2,000. |
| A custodial account (under the age of majority) cannot be a margin account, so it cannot short. | Exam guides and broker FAQs | Stated on the dashboard. A separate "my broker has approved this account for short selling" switch (`short_approved`) must be on before a short stops being practice only. |
| The loss on a short has no cap: the price can rise without limit, and a stop can be jumped by a gap. | Broker short-selling pages | Stated on every short slip. Shorts are intraday only, stop above entry, flat by the close. |
| Shares must be located to borrow before a short sale. They may not be available, may cost a fee, and the broker can close the position (buy-in). | SEC, "Key Points About Regulation SHO" (Rule 203 locate) | The desk cannot see borrow availability. The slip's steps tell you to check for your broker's hard-to-borrow or not-available message. |
| Short-sale restriction (Rule 201): after a stock falls 10 % or more in a day, short sales are only allowed above the best bid, for the rest of that day and the next day. | SEC, same page. Law-firm summaries say the 10 % is measured from the previous close. | Live mode blocks the short when today's low is 10 % or more under the previous close, or yesterday's low was 10 % or more under the close before. Paper mode (2026-11-20) instead rests the sell-short limit a cent over the trigger close, which fills only on a bounce, as the rule allows; the after-close replay uses the same fill (`outcome.replay_ssr`, docs/IMPROVE-2026-11-20.md). |
| The $25,000 day-trading rule ended 2026-06-04, with a broker phase-in to 2027-10-20. The $2,000 minimum is unchanged. | FINRA Regulatory Notice 26-10 | No change; `pdt_guard` stays a setting. |

Read your broker's margin agreement before any real short. With a small cash
account a real short is not possible at all.

## 2. What the vendored skills support

Checked in `vendor/day-trader-skill` at the pinned commit. Nothing there is
edited.

| skill | short side? | so the desk |
| --- | --- | --- |
| Chart Scanner (`scan.py orb`) | No. Finds closes above the range high only. | Finds breakdowns itself from the 5-minute candles. |
| Entry Timer | No. Refuses `--side sell`. | Confirms the breakdown candle itself. |
| Exit Planner | No. Refuses a short. | Works out stop and target itself. |
| Budget Manager | No. Sizes long day trades only. | Sizes the short itself, from the same percentage limits. |
| Time Machine | **Yes.** `--side sell` with target < entry < stop. | Runs it as it is for the odds bar. |
| Risk Manager | **Yes**, a sell entry with a stop above it, when `allow_short` is set. | Runs it as it is for pass or block, with `allow_short` only in the short slip's own working folder. |
| Order Executor | Sell tickets are for closing a long. | Writes its own sell-short steps. |
| Price Alerts | Yes: "above" and "below" alerts. | Adds a stop alert above and a target alert below. |

## 3. The short setup: opening-range breakdown

The long rule mirrored. Seven parts:

1. Market: the same watchlist, price above `min_price`.
2. Setup: the first completed 5-minute candle after the opening range that
   **closes below the range low**. A wick below is not a trigger.
3. Filter: inside the entry window; the stock is below its 200-day average;
   not under a short-sale restriction; Risk Manager passes.
4. Entry: sell short with a limit at `entry - chase_r x risk` **or higher**
   (rounded up to the cent). Good for `signal_valid_minutes`.
5. Exit: target at `entry - target_r x risk`; flat by `flat_by`. Never held
   overnight.
6. Stop: a buy stop above the entry: the range midpoint (`or-mid`, rounded up)
   or the range high (`or-low` mirrored), or `pct:X`. `atr:K` is not built
   for shorts; a short is blocked with that reason.
7. Size: whole shares, the smallest of: risk per trade / risk a share at the
   limit; the position cap; settled cash after the buffer divided by the price
   (the desk wants the full value of the short in cash, which is stricter than
   the 50 % the rules ask for).

**Practice only** (`paper_only` in the code) is decided by `shorts.status()`
each time: margin account, $2,000 or more of equity, and `short_approved` on.
It is about the account's facts, not the desk's Paper / Live mode, so the
dashboard says "PRACTICE ONLY". In live mode a practice-only short is shown
but cannot be recorded as a real trade, and the desk skips the short scan on
an account that cannot short.

## 4. How it works

- **Settings.** `directions` = `long` (default) | `short` | `both`;
  `short_approved` (default off). Both are in the rule-set code, so turning
  shorts on starts a new rule set.
- **Candles.** With `short` or `both` the desk reads each watchlist stock's
  5-minute candles every scan (about 30 small read-only requests to Yahoo's
  chart address) and its daily candles for the 200-day trend check. The demo
  files have no daily history, so the demo skips the trend check and says so.
- **Cash.** When a short is recorded the journal sets aside its full value,
  so equity does not change at the open. When it is covered the journal
  returns that amount plus or minus the result. Brokers often show cash
  differently while a short is open (they add the sale proceeds), so match
  your cash to the broker only when no short is open.
- **One direction a stock.** The journal refuses a short while a long in the
  same stock is open, and the other way round.
- **Odds.** The Time Machine skill is run with `--side sell`. The demo has
  60-day history for TSLA only, so demo short slips show no odds.
- **Practice account** (`desk/paper.py`): `SELL_SHORT` LIMIT, `BUY_TO_COVER`
  STOP above and LIMIT below (one cancels the other), `BUY_TO_COVER` MARKET.
  `paper.short_bracket()` builds the order; `desk/orders.py` has no short
  order at all. A stock is never long and short there at once, and a cover
  never buys more than is short.
- **Auto paper practises shorts** (`desk/auto.py`), in paper mode only and
  only while `directions` is `short` or `both`: it places the short bracket,
  records the fill as a short trade (note `auto`), and covers at the market at
  the flat-by time. Live mode does nothing at all.
- **One decision per stock, logged** (`desk/decide.py`). Each scan writes one
  row per stock: long, short, both or nothing, with the reason for each side
  ("no close below the range low", "breakdown too old to chase", "switched off
  in Settings", or the signal's status). The review report has a SCAN
  DECISIONS section, results by side, and fill / stop / target comparisons
  with the right sign for a short.
- **After-close replay** (`desk/outcome.py`) has a short branch: fills at the
  limit or higher, buy stop above, target below; when one candle reaches both,
  the stop is counted.
- **Chart studies.** Both the thinkorswim and TradingView studies have a
  `showShorts` input (default no) that draws the breakdown levels.

## 5. Tested and not tested

Tested: `tests/test_shorts.py` (maths, candles, the settings gate, journal
entries and the migration, the desk on the demo data, the dashboard's
wording), `tests/test_short_guards.py` (no short order outside the practice
account, practice shorts, the decision log, the review by side) and
`tests/test_chart_studies.py`.

Not tested: no real short order has been placed, and nothing checks borrow
availability, borrow fees or a buy-in. Neither chart study has been run
inside its platform. A real short-sale-restriction day has not been seen.

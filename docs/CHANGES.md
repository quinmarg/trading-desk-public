# Rule changes

Every change to how the desk makes or sizes a signal, with the date, what
changed and why. Newest first.

Two logs work together:

- **This file** is for changes made in the code or agreed in a review of your
  record (`python3 -m desk review`). Add a line here whenever a rule changes.
- **The journal's event log** records every settings change made on the
  dashboard by itself, old value and new (`python3 -m desk review` lists them).

Each signal carries a stamp (`rule set a1b2c3d4`), a short code for the rule
settings that made it, so results can be read per rule set. One bad week is
not a reason to change a rule; a change needs enough trades to mean something.

| Date | What changed | Why |
|---|---|---|
| 2026-11-20 | Paper mode only: a short under SEC Rule 201 (down 10 % today or yesterday) is no longer blocked. Its sell-short limit rests a cent over the trigger close, above the bid as the rule requires, so it fills only on a bounce; it is graded like any short. Live mode still blocks it. After-close replays of restricted shorts use the same above-bid fill. New rule-set code (`rule201_limit`). | Declared test T2 (`docs/IMPROVE-2026-11-20.md`): +0.071R after costs on 108 modelled fills, 88 stocks, 45 sessions. The in-play ones averaged −0.16R on 46 (wide range), so watch them in the review. |
| 2026-11-20 | Paper mode only: one-share floor. When Claude's day settings cut `risk_per_trade_pct` and that leaves a trade at 0 shares, the desk sizes it at your own percentage, which is always 1 share and never more than your own risk. New rule-set code (`one_share_floor`). | Declared test T3: a test proves it never risks more than your own setting. The day cut itself is untested; your own percentage is your setting. |
| 2026-11-20 | Not changed, tested: the in-play screen (not-in-play longs −0.20R on 1,696, the whole range under 0; shorts −0.04R), auto paper on not-in-play signals (both sides under 0), a 20-minute signal window (4 extra fills). | Declared tests T1, T5 and T4 failed their pass rules. |
| 2026-11-19 | Early close days: flat-by moves up to 12:55 for new signals and auto paper. Holidays: no hourly game plan or catalyst looks. Shorts: the Rule 201 restriction carries into the day after the drop. Auto paper leaves a signal alone when the price is already at its stop. Paper stop and market fills pay `est_cost_per_share`. | Fixes from a research pass over the paper record and the rules (SEC Rule 201, NYSE calendar). |
| 2026-11-19 | Claude's game plan (`analyst`, on): each morning and hour Claude reads the day's list and writes a plan. `plan_filter` (paper) grades a ready signal weak when the plan argues against it. `analyst_adds` (5) lets each hourly look add in-play stocks to the scan list. | Untested against the backtest, so it is paper only by default and the review splits its results out. |
| 2026-11-18 | Catalysts get places on the morning list: the best tradeable catalysts scored 40 or more (`desk/catalysts.py`) take up to `catalyst_slots` (10) of the `auto_watchlist_movers` places first. | A news and events tracker that helps pick trades. Untested against the backtest, so the review compares catalyst picks with volatility picks; set `catalyst_slots` to 0 to go back. |
| 2026-11-18 | The morning scan list also takes names from Yahoo's most-active, gainers and losers screeners, keeps your `core_watchlist` tickers, and its size is `auto_watchlist_movers` (40). Optional `watchlist_agent` (off): Claude picks from the same candidates after reading their headlines. Phone alerts (ntfy) send nothing until a topic is set. | Ported from a community fork. The screen and the in-play rules are unchanged; the agent is untested against the backtest, so it is off. |
| 2026-11-18 | Paper mode only: the desk picks its own scan list each morning (`auto_list` = paper): the 40 most volatile stocks (ATR % 3 or more, $5 or more, $100 million a day or more) of about 90 liquid ones plus your watchlist. | Same measures as the volatility screen (`docs/VOLATILITY.md`). The review's "SCAN LISTS" section judges it day by day. |
| 2026-11-18 | Risk per trade and the daily loss limit come from Settings in paper and live (removed from `PAPER_BOLD`). | Paper had forced 5 % and 20 %; now you choose. |
| 2026-11-18 | Paper mode only: volatility screen. A signal whose opening-range volume is under 1.5x its 14-day normal, or whose stock's daily range (ATR) is under 3 % of its price, is graded weak ("Not in play"). An in-play signal is not held back by the Time Machine odds floor. Live unchanged; `min_rvol` and `min_atr_pct` (0 = off) turn it on there. | Backtest of the desk's own rule on 88 stocks, 60 days (`docs/VOLATILITY.md`). Held out: before, 2,167 signals at −0.049R, profit factor 0.90; after, 321 at +0.110R, PF 1.27. One autumn of data, today's tickers only. |
| 2026-11-18 | Paper mode only: 4x buying power, no weekly stop, 50 % drop stop, no cash buffer, no trade cap, sales settle at once. Live unchanged. Rule stamps now record these. | Bolder, bigger practice trades show more in the review log. Paper is pretend money. |
| 2026-11-18 | New risk stops: weekly loss (`max_weekly_loss_pct`), drop from the best point (`max_drawdown_pct`), losers in a row (`max_losing_streak`, off by default). | Ideas from CloddsBot (docs/CLODDSBOT.md). |
| 2026-11-18 | Short side added, off by default (`directions` = long). Shorts are practice only unless `short_approved` is on. | docs/SHORTING.md. |
| 2026-11-11 | First public release. Default rules as shipped in `desk/settings.py`. | Starting point. |

# Chart settings for this desk, on the desk and on TradingView

Written 2026-11-19. Not financial advice. A chart setup is a matter of habit, not an edge: none of these settings has a backtest behind it.

## What I could and could not check

I could not read YouTube, TikTok or X directly, and Reddit only through mirrors. The "consensus" below comes from
TradingView's public scripts and docs, trading-school PDFs and summaries of videos and threads. Each item says which. Anything tagged
**[one source]** is a single post or summary. Menu names in TradingView change between versions; the paths below
come from third-party guides and I did not click through them. Check each one on screen.

## 1. What traders recommend

| Item | Consensus | Who and where |
| --- | --- | --- |
| Timeframes | 5-minute for the plan and the opening range; 1-minute to time the entry; daily for the bigger picture (levels, 200 average) | Ross Cameron's 9/20/200 averages "on the daily, 5-minute and 1-minute" ([video summary](https://youtubesummary.com/summary/qRirYfM4XiY), [transcript excerpt](https://lilys.ai/hi/notes/day-trading-20260304/best-day-trading-indicators-beginners)) [secondary]; 9 and 20 EMA on the 5-minute as the "workhorses" ([guide](https://chartinglens.com/blog/best-indicators-for-day-trading)); Aziz's 9/20 trade enters on a 2-minute chart, first target the 9 EMA ([Bear Bull Traders PDF](https://members.bearbulltraders.com/wp-content/uploads/2023/02/Strategy-9-20-Trade.pdf), I could not read the PDF; taken from a search summary). The ORB paper's best opening range was 5 minutes (`docs/VOLATILITY.md`). |
| VWAP | Near-universal. Above VWAP is read as buyers in control, below as sellers | Aziz / Bear Bull Traders ([summary](https://www.forex.in.rs/vwap-momentum-discipline), low-quality site); Cameron-style scripts ([TradingView](https://www.tradingview.com/script/DClHUUym-Momentum-Day-Trading-Setup)); the only quantitative test is the disputed VWAP trend paper ([Concretum](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/)) |
| 9 and 20 EMA | Very common on 1 and 5-minute charts. Used for pullback entries and a first target. Aziz says the exact periods are only examples. | [Bear Bull Traders 9/20](https://members.bearbulltraders.com/wp-content/uploads/2023/02/Strategy-9-20-Trade.pdf); a [Reddit post](https://lr.eu.psf.lt/r/Daytrading/comments/1imt9rk/i_trade_this_same_move_every_day) lists 9, 20, 200 EMA with VWAP and MACD [one source, anecdotal] |
| 200 average | Mostly a daily-chart level. Some show it on intraday too. One guide treats the 200 SMA as daily support and resistance, not an intraday signal. | [Risen guide](https://risen-website.pages.dev/learn/best-day-trading-indicators); Cameron summary above. EMA vs SMA: sources split. The desk's own short rule uses the 200-day (SMA), so use SMA for the daily 200. |
| Volume | A volume histogram under price; relative volume (today vs same time on past days) is the key number. | TradingView community scripts ([Relative Volume](https://www.tradingview.com/script/3SLEmBKa-Relative-Volume/), [Intraday RVOL overlay](https://id.tradingview.com/script/3Zv6IuBl-Intraday-RVOL-Overlay-Time-Of-Day-Relative-Volume/)). The ORB paper's edge came from this filter. |
| ATR | A daily ATR(14) used to judge stops and how far a stock can run; shown in the status line or the watchlist, not as a chart overlay | Zarattini/Aziz papers use a 14-day ATR ([abstract](https://www.alexandria.unisg.ch/entities/publication/ab50f49b-4d5c-4aa8-aaa1-af7a4c131008)) |
| MACD | Optional. One Reddit post uses it; no source ties it to a named trader. Skip it: it repeats the averages. | [Reddit mirror](https://lr.eu.psf.lt/r/Daytrading/comments/1imt9rk/i_trade_this_same_move_every_day) [one source] |
| Extended hours | Show premarket. You need it to see premarket high and low. | [TradingView blog](https://www.tradingview.com/blog/en/charting-pre-and-post-trade-periods-19986) (you can colour the extended session), community level scripts ([Premarket Hi/Lo](https://my.tradingview.com/script/xUfM1N9p-Premarket-Hi-Lo-Prior-Day-O-C-Levels), [Prior day and premarket high/low](https://in.tradingview.com/script/Iev9qjV6-Prior-day-and-pre-market-high-low/?amp)) say Extended Hours must be on for premarket levels |
| Key level lines | Premarket high and low, prior-day high, low and close, VWAP, whole and half dollars. Mark them before the open. | Bear Bull Traders materials, as summarised on [forex.in.rs](https://www.forex.in.rs/aziz-daytrader-routine) [secondary]; [education post](https://atraderseducation.substack.com/p/premarket-prep-for-quick-profits) |
| Chop warning | Do not trade when VWAP and the EMAs keep crossing | [VWAP + EMA playbook](https://thestockjoe.blogspot.com/2026/04/vwap-ema-liquidity-sweep-simple.html) [one source] |
| Candle colours | No standard. Green up, red down is the default; a guide suggests turning off borders and "color bars based on previous close"; bright candles on dark are said to reduce strain | [Arsturn guide](https://arsturn.com/blog/tradingview-like-a-pro-a-deep-dive-into-mastering-your-chart-settings), [TRND guide](https://trnd-bot.gitbook.io/trnd/setup-guide/customize-the-appearance-of-your-tradingview-chart) [low quality] |
| Opening range lines | A 5-minute (or 1 and 15-minute) opening range high and low drawn after the first bar closes | Aziz 1-minute ORB ([PDF](https://members.bearbulltraders.com/wp-content/uploads/2023/02/1Min-ORB.pdf)); Qullamaggie's 1, 5 or 60-minute high ([page](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/)) |

**What is popular but unproven:** every one of these indicator stacks. No source I found tested the 9/20 EMA with VWAP and 200 average on 1 and
5-minute charts. The VWAP paper and the ORB paper are the only chart elements with published tests.
**Not found:** any consensus on status line contents, scale settings, or session break lines. The setup below is my choice, marked as such.

## 2. Recommended setup on TradingView

Keep it simple: fewer than 8 lines on screen. Colours are chosen to read on a black or near-black background.

### Layout (3 charts, same symbol, synced)

| Chart | Timeframe | Why | Shows |
| --- | --- | --- | --- |
| Main | 5-minute | The desk trades the 5-minute opening range; the plan lives here | All indicators below |
| Entry | 1-minute | Timing the entry and spotting a failed break | VWAP, 9 EMA, 20 EMA, levels |
| Context | Daily, about 6 months | Is the stock at a prior high, and is it above the 200-day | 200 SMA, 50 SMA, ATR in status line |

Sync the symbol across the layout (the layout's link/sync options).

### Chart settings (gear icon). Menu names may differ.

- **Symbol**: Candles. Body up `#2EBD85`, down `#F6465D`. Wick same colours. Border off. Turn "Color bars based on previous close" **off**.
  If red and green are hard to tell apart for you, use up `#4DA3FF` (blue) and down `#FF9F0A` (orange).
- **Symbol, Session**: Extended trading hours **on**. Colour the pre-market and post-market backgrounds a faint grey (for example 90 % transparent `#FFFFFF`) so
  you can see where regular trading begins.
- **Status line**: show OHLC and the change, **volume**, and indicator values; hide the full indicator arguments and the symbol description. (My choice.)
- **Scales and lines**: price scale on the right; auto-scale on; **log scale off** for intraday; labels for the symbol's last price and previous close on;
  indicator name labels off; countdown to bar close **on** (the desk acts after a 5-minute candle closes).
- **Canvas**: background solid `#000000` (matches the desk); grid lines **off** (or `#1C1C1E`); crosshair on; watermark off.
  Session breaks: **on**, a faint vertical line `#3A3A3C`, dashed, so each day is clear on multi-day views.
- **Trading** (panel): leave off unless you trade through TradingView; the desk has its own order screens.
- **Events**: off.

### Indicators and exact inputs

| Indicator | Inputs | Colour, width | Notes |
| --- | --- | --- | --- |
| Volume | Default. Colour by candle direction | Up `#2EBD85` at 50 % opacity, down `#F6465D` at 50 % | On the main and entry charts |
| VWAP (built in) | Anchor: Session. Source: hlc3. Bands off. Offset 0 | `#FFD60A` yellow, 2 px | I could not confirm whether TradingView's session VWAP starts at 4:00 premarket when Extended Hours is on. Compare it to your broker's VWAP once. The desk's VWAP is regular hours from 9:30. |
| EMA 1 | Length 9, source close | `#64D2FF` cyan, 1 px | 1 and 5-minute charts |
| EMA 2 | Length 20, source close | `#FF9F0A` orange, 1 px | 1 and 5-minute charts |
| SMA | Length 200, source close | `#BF5AF2` purple, 2 px | On the daily chart; on 5-minute it is about 2.5 days of trading, so show it there only as a rough guide |
| SMA | Length 50 | `#8E8E93` grey, 1 px | Daily chart only (optional) |
| ATR | Length 14, smoothing RMA | Not plotted: show only in the status line on the daily chart (or read it in the desk) | The desk screen is ATR % of price at 3 or more |
| Relative volume (community script, same time of day) | 5-minute chart; lookback 14 sessions; median baseline | Histogram, show the value in the status line | Pick any script that compares each bar with the same time on prior days, and check its code. Alert level 1.5x to match the desk. |
| Prior day high / low, premarket high / low, prior close | Use a public script such as [Premarket Hi/Lo + Prior Day O/C](https://my.tradingview.com/script/xUfM1N9p-Premarket-Hi-Lo-Prior-Day-O-C-Levels) or [Previous and Premarket High Low](https://id.tradingview.com/script/LPsb7SBh-Previous-and-Premarket-High-Low-Indicator); premarket window 04:00 to 09:30 New York | See colours below | Read the script's code or settings before trusting it. If you prefer not to rely on a script, draw horizontal lines by hand each morning. |
| Opening range | Draw by hand after the 9:35 candle closes: horizontal rays at the first 5-minute bar's high and low | See below | Or use a script that has an opening-range option |

### Level line colours (dark theme)

| Line | Colour | Style |
| --- | --- | --- |
| Premarket high (PMH) | `#0A84FF` blue | dashed, 1 px, label "PMH" |
| Premarket low (PML) | `#0A84FF` blue | dotted, 1 px, label "PML" |
| Prior day high (PDH) | `#F2F2F7` near-white | dashed, 1 px |
| Prior day low (PDL) | `#F2F2F7` near-white | dotted, 1 px |
| Prior close | `#8E8E93` grey | solid, 1 px, label "PC" |
| Opening range high (ORH) | `#FF6BD6` pink | solid, 1 px |
| Opening range low (ORL) | `#FF6BD6` pink | dotted, 1 px |
| Planned entry, stop, target (from the desk's slip) | entry `#F2F2F7`, stop `#F6465D`, target `#2EBD85` | solid, 1 px |

### Morning routine (checklist)

1. Extended hours on. Open the 5-minute chart. Confirm the PMH, PML, PDH, PDL and PC lines are on the right levels.
2. Check relative volume is above 1.5x once the first bar closes, and the daily ATR % is 3 or more.
3. After the 9:35 candle closes, draw the opening range. Compare it with the desk's slip.
4. Compare the desk's entry, stop and target with the lines. Then follow the desk's rules; the chart is only to read.

## 3. Short spec for the desk's own small charts

The dashboard uses a black background (`--bg:#000000`) and cards at `#1C1C1E`. A small chart should show, in this order of importance:

1. 5-minute candles for today's regular session, up `#2EBD85`, down `#F6465D`, wicks the same, no borders.
2. VWAP, yellow `#FFD60A`, 2 px.
3. The opening range: high and low as pink `#FF6BD6` lines from 9:35 to the right edge (high solid, low dotted).
4. The slip's planned **entry** (near-white `#F2F2F7`), **stop** (`#F6465D`) and **target** (`#2EBD85`), solid, with short labels.
5. Prior close, grey `#8E8E93`, solid; prior day high and low, near-white dashed and dotted; premarket high and low, blue `#0A84FF` dashed and dotted.
   (The desk's chart data holds `prev_close` today; prior-day high/low come from the cached daily bars; premarket bars would need `prepost=true` on the Yahoo request, which the desk does not currently ask for.)
6. 9 EMA cyan `#64D2FF` and 20 EMA orange `#FF9F0A`, 1 px, only on the larger chart; leave them off the small card to avoid clutter.
7. Volume bars at the bottom, up and down colours at 50 % opacity, with a small marker where volume was 1.5x its usual for that time.
8. Text labels `#F2F2F7` at 11 px or larger; line labels sit at the right edge. Contrast: all colours above are bright enough for 4.5:1 on black. The grey `#8E8E93` has not been measured against `#1C1C1E`; check it if the chart sits on a card.
9. Mark the 09:30 open with a faint vertical line `#3A3A3C`.

## Sources not listed inline above

- TradingView premarket and prior-day indicators: https://www.tradingview.com/scripts/premarket/ and https://www.tradingview.com/scripts/priorday/
- Existing desk research: `docs/VOLATILITY.md`, `docs/STRATEGIES.md`

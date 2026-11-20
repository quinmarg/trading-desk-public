"""One candidate, start to finish, through the day-trader-skill tools:

    entry timer -> exit planner -> time machine -> budget -> risk -> ticket -> news

The result is a signal: the numbers, the time it is good until, and the
reasons if anything refused it. Nothing here places an order.
"""
import datetime
import math

from . import charts
from . import guards
from . import mode as M
from . import outcome
from . import settings as S
from . import shorts
from . import skills
from . import slipinfo
from . import volscreen


def workdir(date, symbol, side="long"):
    """Each signal's own folder: paper and live never share one, and a short never shares a long's."""
    return M.work_root(S.load()["mode"]) / date / (symbol if side == "long" else "%s.short" % symbol)


def _hhmm_add(hhmm, minutes):
    t = datetime.datetime.strptime(hhmm, "%H:%M") + datetime.timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def _floor_cent(x):
    return math.floor(x * 100 + 1e-6) / 100


def write_account(wd, st, journal, now):
    """The account as the tools read it: config, portfolio and what was placed today."""
    today = now[:10]
    equity = journal.equity()
    cfg = S.skills_config(st, equity)
    skills.write_json(wd / "trader" / "config.json", cfg)
    positions = [{"ticker": t["symbol"], "shares": t["qty"],
                  "lots": [{"id": "%s-%d" % (t["symbol"], t["id"]), "date": t["date"], "shares": t["qty"],
                            "cost": round(t["qty"] * t["entry_price"], 2)}]}
                 for t in journal.open_trades() if t.get("side", "long") == "long"]   # a short is not shares held
    skills.write_json(wd / "trader" / "portfolio.json",
                      {"cash": journal.buying_power(today), "positions": positions})
    orders = []
    for t in journal.trades(today):
        opened, closed = ("sell", "buy") if t.get("side") == "short" else ("buy", "sell")
        orders.append({"at": t["entry_at"], "date": t["date"], "status": "placed", "kind": "entry",
                       "symbol": t["symbol"], "side": opened, "qty": str(t["qty"]), "stop": t["stop"],
                       "max_loss": round(abs(t["entry_price"] - t["stop"]) * t["qty"], 2)})
        if t["status"] == "closed":
            orders.append({"at": t["exit_at"], "date": t["exit_at"][:10], "status": "filled", "kind": "exit",
                           "symbol": t["symbol"], "side": closed, "qty": str(t["qty"]), "price": t["exit_price"]})
    skills.write_json(wd / "trader" / "state" / "broker.json", {"orders": orders})
    return cfg


def own_risk(st, journal, today):
    """Paper mode (docs/IMPROVE-2026-11-20.md, T3): your settings with your own risk_per_trade_pct, when Claude's game
    plan cut it for today (analyst.day_settings scales it by 0.5 to 1.0), else None. A trade the cut sizes to 0 shares
    is sized again at your own percentage, which always gives exactly 1 share: the cut is at most half, so one share
    risks under twice the cut limit."""
    rec = journal.get("plan_settings") or {}
    base = (rec.get("base") or {}).get("risk_per_trade_pct")
    if st.get("mode") != "paper" or rec.get("date") != today or not base or float(base) <= float(st["risk_per_trade_pct"]):
        return None
    return dict(st, risk_per_trade_pct=float(base))


ONE_SHARE = ("One share: Claude's plan cut today's risk to %.1f %% of the account, which left no shares, so the desk "
             "sized it at your own %.1f %% (paper mode).")


def edge_points(p_target, p_stop, target_r):
    """Time Machine edge: the target's share of decided replays minus the break-even share, in points."""
    decided = p_target + p_stop
    if decided <= 0:
        return None
    return round(100 * (p_target / decided - 1 / (1 + target_r)), 1)


def order_steps(sig):
    """How to enter this exact order at your broker, by hand. Most brokers call it a bracket or OCO order."""
    return [
        "At your broker, open an order ticket for %s." % sig["symbol"],
        "Choose a bracket order (a buy with a stop and a target attached, one cancels the other).",
        "The buy: quantity %d, order type LIMIT, price %.2f, good for the DAY." % (sig["qty"], sig["limit"]),
        "The stop: order type STOP, price %.2f. The target: LIMIT, price %.2f. Both good for the DAY."
        % (sig["stop"], sig["target"]),
        "Read the review screen: max loss about $%.2f. Then send it yourself." % sig["max_loss"],
        "Back here, press 'I placed it' and type your fill price.",
    ]


def evaluate(symbol, st, journal, source, hit=None):
    """Runs one symbol through the tools. Returns (status, payload) or (None, reason) when
    there is nothing to signal yet (the setup has not triggered)."""
    status, sig = _evaluate(symbol, st, journal, source, hit)
    if status is not None:
        slipinfo.finish(sig, st, journal, source.now())      # stamp, costs, rule card: display and record only
    return status, sig


def _evaluate(symbol, st, journal, source, hit=None):
    now = source.now()
    today = now[:10]
    wd = workdir(today, symbol)
    write_account(wd, st, journal, now)
    na = source.now_args()

    # 1. entry timer
    args = ["check", symbol, "--setup", "orb", "--or-minutes", st["or_minutes"], "--write", "--json"]
    if st["min_volume_x"] > 0:
        args += ["--min-volume-x", st["min_volume_x"]]
    r = skills.run("entry", args + na + source.chart_offline(symbol), wd)
    e = r.json
    if not isinstance(e, dict):
        return None, "entry timer: %s" % r.message
    if e.get("status") != "triggered":
        return None, "%s: %s" % (e.get("status"), e.get("reason") or "")
    trig = e["trigger"]
    age = e.get("minutes_since")
    sig = {
        "symbol": symbol, "setup": "orb", "date": today, "created": now,
        "trigger_time": trig["time"], "trigger_close_time": trig["close_time"],
        "trigger_price": trig["price"], "volume_x": trig.get("volume_x"),
        "opening_range": {"high": e["opening_range"]["high"], "low": e["opening_range"]["low"]},
        "prev_close": e.get("prev_close"), "reason": e.get("reason"),
        "valid_until": _hhmm_add(trig["close_time"], st["signal_valid_minutes"]),
        "problems": [], "warnings": [], "workdir": str(wd),
    }
    if age is not None and age > st["signal_valid_minutes"]:
        sig["problems"].append("It triggered at %s, %d minutes ago. Too late to chase." % (trig["time"], age))
        return "missed", sig

    # 2. exit planner
    r = skills.run("exit", ["plan", "--stop", st["stop_rule"], "--target", "%gR" % st["target_r"],
                            "--flat-by", st["flat_by"], "--write", "--json"] + na + source.chart_offline(symbol), wd)
    plan = r.json
    if r.rc != 0 or not isinstance(plan, dict) or "stop" not in plan:
        sig["problems"].append("Exit planner refused: %s" % r.message)
        return "blocked", sig
    risk_ps = plan["risk_per_share"]
    sig.update({"entry": plan["entry"], "stop": plan["stop"], "target": plan["target"],
                "stop_label": plan.get("stop_label"), "target_label": plan.get("target_label"),
                "risk_per_share": risk_ps, "flat_by": plan["flat_by"],
                "limit": _floor_cent(plan["entry"] + st["chase_r"] * risk_ps)})
    sig["warnings"] += plan.get("warnings") or []
    close = guards.stop_too_close(plan["entry"], risk_ps, st.get("min_stop_pct"))
    if close:
        sig["problems"].append(close)
        sig.update({"qty": 0, "cost": 0.0, "max_loss": 0.0, "reward": 0.0})
        return "blocked", sig

    # 3. time machine
    sig["odds"] = None
    if source.has_history(symbol):
        r = skills.run("timemachine", ["run", "--replays", st["replays"], "--until", plan["flat_by"],
                                       "--json", "--write"] + na + source.history_offline(symbol), wd, timeout=300)
        tm = r.json
        if isinstance(tm, dict) and "mc" in tm:
            mc, hist = tm["mc"], tm.get("history") or {}
            sig["odds"] = {
                "p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"],
                "p_green": mc["p_green"], "avg_r": mc["avg_R"], "replays": mc["replays"],
                "sessions": mc["pool_sessions"], "median_close": mc["median_close"],
                "p5_close": mc["p5_close"], "p95_close": mc["p95_close"], "until": mc["until"],
                "edge_points": edge_points(mc["p_target"], mc["p_stop"], plan["target_r"]),
                "verdict": tm.get("verdict"), "notes": tm.get("verdict_notes") or [],
                "history": {k: hist.get(k) for k in ("sessions", "triggered", "target", "stop", "close", "avg_R")},
            }
            sig["warnings"] += tm.get("warnings") or []
        else:
            sig["warnings"].append("Time Machine could not run: %s" % r.message)
    else:
        sig["warnings"].append("No 60-day history in the demo files for %s, so no odds." % symbol)

    # 4. budget: size at the limit ceiling, the worst price you would pay
    r = skills.run("budget", ["--limit", "%.2f" % sig["limit"], "--write", "--json"] + na, wd)
    b = r.json
    sizing = (b or {}).get("sizing") if isinstance(b, dict) else None
    mine = own_risk(st, journal, today) if (sizing or {}).get("refusal") and sizing.get("bound_by") == "max loss" else None
    if mine:                                        # T3: the day's cut left 0 shares; size at your own risk instead
        write_account(wd, mine, journal, now)
        r2 = skills.run("budget", ["--limit", "%.2f" % sig["limit"], "--write", "--json"] + na, wd)
        s2 = (r2.json or {}).get("sizing") if isinstance(r2.json, dict) else None
        if s2 and not s2.get("refusal") and r2.json.get("orders"):
            sig["warnings"].append(ONE_SHARE % (st["risk_per_trade_pct"], mine["risk_per_trade_pct"]))
            st, r, b, sizing = mine, r2, r2.json, s2
        else:
            write_account(wd, st, journal, now)
    if not sizing or sizing.get("refusal") or not (b.get("orders")):
        why = (sizing or {}).get("refusal") or r.message
        sig["problems"].append("Budget: %s" % why)
        sig.update({"qty": 0, "cost": 0.0, "max_loss": 0.0, "reward": 0.0})
        return "blocked", sig
    qty = int(sizing["qty"])
    sig.update({"qty": qty, "cost": round(qty * sig["limit"], 2), "max_loss": sizing["max_loss"],
                "reward": round(qty * (sig["target"] - sig["limit"]), 2),
                "reward_risk": sizing["reward_risk"], "bound_by": sizing.get("bound_by"),
                "sizing_limits": [{"name": l["name"], "shares": l["shares"], "how": l["how"], "binds": l.get("binds")}
                                  for l in sizing.get("limits", [])]})

    # 5. risk manager
    r = skills.run("risk", ["--json"] + na, wd)
    res = ((r.json or {}).get("results") or [None])[0] if isinstance(r.json, dict) else None
    if not res:
        sig["problems"].append("Risk check could not run: %s" % r.message)
        return "blocked", sig
    sig["risk"] = {"verdict": res["verdict"], "reasons": res.get("reasons") or [], "info": res.get("info") or []}
    sig["warnings"] += res.get("warnings") or []

    # 6. order ticket
    r = skills.run("broker", ["show", "--json"] + na, wd)
    t = r.json[0] if isinstance(r.json, list) and r.json else {}
    sig["ticket"] = {"plain": t.get("plain"), "ready": bool(t.get("ready")), "steps": order_steps(sig)}

    # 7. news
    sig["news"] = news(symbol, st, source, wd)
    if any("earnings" in (n.get("tags") or []) for n in sig["news"]):
        sig["warnings"].append("Earnings are in the headlines for %s. A day trade is flat before the close, "
                               "but the stock can move hard on any leak or guidance." % symbol)

    if res["verdict"] != "PASS":
        sig["problems"] += ["Risk: %s" % x for x in sig["risk"]["reasons"]]
        return "blocked", sig
    off = volscreen.check(sig, st, source)
    if off:
        sig["problems"].append(off)
        return "weak", sig
    ep = (sig["odds"] or {}).get("edge_points")
    if sig["odds"] is None and not source.demo:
        sig["problems"].append("No Time Machine odds for this one, so the desk cannot grade it.")
        return "weak", sig
    if ep is not None and ep < st["min_edge_points"]:
        if volscreen.skips_floor(sig, st):
            sig["warnings"].append("Time Machine edge is %+.1f points, under your floor of %+.1f, but this stock is in play "
                                   "and on in-play days the Time Machine has rated the target too unlikely, so paper "
                                   "mode does not hold it back." % (ep, st["min_edge_points"]))
            return "ready", sig
        sig["problems"].append("Time Machine edge is %+.1f points, under your floor of %+.1f." % (ep, st["min_edge_points"]))
        return "weak", sig
    return "ready", sig


def news(symbol, st, source, wd, limit=5):
    args = ["--tickers", symbol, "--all", "--hours", st["news_hours"], "--no-moves", "--json"]
    if not st["sec_user_agent"]:
        args.append("--no-sec")
    r = skills.run("news", args + source.news_args(), wd, timeout=60)
    items = (r.json or {}).get("items") if isinstance(r.json, dict) else None
    out = []
    for it in (items or [])[:limit]:
        link = str(it.get("link") or "")
        out.append({"title": it.get("title"), "time": it.get("time"), "source": it.get("source"),
                    "kind": it.get("kind"), "tags": it.get("tags") or [],
                    "link": link if link.startswith("https://") else ""})
    return out


# ---------------------------------------------------------------- the short side (docs/SHORTING.md)

_TM_STOP_RULE = {"or-mid": "or_mid", "or-low": "or_high"}


def evaluate_short(symbol, st, journal, source, chart=None):
    """The short side's evaluate(): the same stamp, cost line and rule card as a long slip."""
    status, sig = _evaluate_short(symbol, st, journal, source, chart)
    if status is not None:
        slipinfo.finish(sig, st, journal, source.now())
    return status, sig


def _evaluate_short(symbol, st, journal, source, chart=None):
    """One symbol through the short side: an opening-range breakdown. Same return as evaluate().

    The Entry Timer, Exit Planner and Budget Manager skills are long-only, so the trigger, the stop,
    the target and the size come from desk/shorts.py. The Time Machine, the Risk Manager and the
    News Monitor take a sell as they are and are run unchanged. Nothing here places an order."""
    now = source.now()
    today = now[:10]
    wd = workdir(today, symbol, "short")
    na = source.now_args()
    try:
        chart = chart or charts.intraday(source, symbol)
    except charts.ChartError as e:
        return None, "chart: %s" % e
    bars = charts.session_bars(chart, now)
    rng, trig, reason = shorts.breakdown(bars, st["or_minutes"], st["no_entries_after"], st["min_volume_x"])
    if not trig:
        return None, reason
    equity = journal.equity()
    acct = shorts.status(st, equity)
    now_min = int(now[11:13]) * 60 + int(now[14:16])
    age = now_min - (int(trig["close_time"][:2]) * 60 + int(trig["close_time"][3:]))
    sig = {
        "symbol": symbol, "setup": shorts.SETUP, "side": "short", "date": today, "created": now,
        "paper_only": acct["paper_only"], "paper_why": acct["why"],
        "trigger_time": trig["time"], "trigger_close_time": trig["close_time"],
        "trigger_price": trig["price"], "volume_x": trig.get("volume_x"),
        "opening_range": {"high": round(rng["high"], 2), "low": round(rng["low"], 2)},
        "prev_close": chart.get("prev_close"), "reason": reason,
        "valid_until": _hhmm_add(trig["close_time"], st["signal_valid_minutes"]),
        "problems": [], "warnings": [], "workdir": str(wd), "flat_by": st["flat_by"],
    }
    if age > st["signal_valid_minutes"]:
        sig["problems"].append("It triggered at %s, %d minutes ago. Too late to chase." % (trig["time"], age))
        return "missed", sig

    # stop, target and the lowest price worth selling at
    try:
        pl = shorts.plan(trig["price"], rng, st["stop_rule"], st["target_r"], st["chase_r"])
    except shorts.ShortError as e:
        sig["problems"].append("No plan: %s" % e)
        return "blocked", sig
    sig.update({k: pl[k] for k in ("entry", "stop", "target", "limit", "risk_per_share", "stop_label", "target_label")})
    if st.get("min_stop_pct") and 100.0 * pl["risk_per_share"] / pl["entry"] + 1e-9 < st["min_stop_pct"]:
        sig["problems"].append("The stop is only %.2f%% above the entry (%.2f a share). Your floor is %.2f%%: "
                               "a stop that close is hit by normal wiggle."
                               % (100.0 * pl["risk_per_share"] / pl["entry"], pl["risk_per_share"], st["min_stop_pct"]))

    # the short-sale restriction (SEC Rule 201: it lasts the rest of the day it starts and all of the next), and the trend
    day_low = min(b["l"] for b in bars)
    try:
        days = charts.daily_bars(source, symbol)
    except charts.ChartError as e:
        days = None
        sig["warnings"].append("Daily history could not be read (%s)." % e)
    past = [b for b in days or [] if b["date"] < today]
    ssr = None
    if shorts.restricted(day_low, chart.get("prev_close")):
        ssr = "today"
        why = ("Short-sale restriction: %s is down %.0f%% or more from yesterday's close (%.2f). "
               "Shorts can only fill above the best bid for the rest of today and tomorrow."
               % (symbol, shorts.SSR_DROP_PCT, chart["prev_close"]))
    elif len(past) >= 2 and shorts.restricted(past[-1]["l"], past[-2]["c"]):
        ssr = "yesterday"
        why = ("Short-sale restriction: yesterday %s fell %.0f%% or more under the close before it (%.2f), "
               "so the restriction runs through today. Shorts can only fill above the best bid."
               % (symbol, shorts.SSR_DROP_PCT, past[-2]["c"]))
    if ssr:
        sig["ssr"] = ssr                            # the after-close replay uses outcome.replay_ssr either way
        if st["mode"] == "paper":                   # T2: a sell-short limit above the bid instead of no short
            pl["limit"] = sig["limit"] = outcome.ssr_limit(pl["entry"])
            sig["warnings"].append(why + " So the sell-short limit is %.2f, a cent over the trigger close: it waits "
                                   "above the bid and fills only if the price bounces back up to it." % pl["limit"])
        else:
            sig["problems"].append(why)
    direction, avg = shorts.trend([b["c"] for b in days] if days else None, pl["entry"])
    sig["trend"] = {"direction": direction, "average": avg, "days": shorts.TREND_DAYS}
    if direction == "up":
        sig["problems"].append("%s is above its %d-day average (%.2f): an uptrend. The desk only shorts below it."
                               % (symbol, shorts.TREND_DAYS, avg))
    elif direction is None and source.demo:
        sig["warnings"].append("The demo files have no daily history, so the %d-day trend check did not run." % shorts.TREND_DAYS)
    elif direction is None:
        sig["problems"].append("No %d days of history for %s, so the desk cannot check the trend. No short."
                               % (shorts.TREND_DAYS, symbol))

    # time machine: it replays a sell as it is
    sig["odds"] = None
    if source.has_history(symbol):
        args = ["run", "--symbol", symbol, "--side", "sell", "--date", today, "--entry", "%.2f" % pl["entry"],
                "--stop", "%.2f" % pl["stop"], "--target", "%.2f" % pl["target"], "--entry-time", trig["time"],
                "--setup", "orb", "--or-minutes", st["or_minutes"],
                "--stop-rule", _TM_STOP_RULE.get(st["stop_rule"], "pct"),
                "--replays", st["replays"], "--until", st["flat_by"], "--json"]
        r = skills.run("timemachine", args + na + source.history_offline(symbol), wd, timeout=300)
        tm = r.json
        if isinstance(tm, dict) and "mc" in tm:
            mc, hist = tm["mc"], tm.get("history") or {}
            sig["odds"] = {
                "p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"],
                "p_green": mc["p_green"], "avg_r": mc["avg_R"], "replays": mc["replays"],
                "sessions": mc["pool_sessions"], "median_close": mc["median_close"],
                "p5_close": mc["p5_close"], "p95_close": mc["p95_close"], "until": mc["until"],
                "edge_points": edge_points(mc["p_target"], mc["p_stop"], pl["target_r"]),
                "verdict": tm.get("verdict"), "notes": tm.get("verdict_notes") or [],
                "history": {k: hist.get(k) for k in ("sessions", "triggered", "target", "stop", "close", "avg_R")},
            }
            sig["warnings"] += tm.get("warnings") or []
        else:
            sig["warnings"].append("Time Machine could not run: %s" % r.message)
    else:
        sig["warnings"].append("No 60-day history in the demo files for %s, so no odds." % symbol)

    # size: the same percentage limits as a long
    lim = S.limits(st, equity)
    sz = shorts.size(pl, lim, journal.buying_power(today))
    mine = own_risk(st, journal, today) if sz["refusal"] and sz["bound_by"] == "risk per trade" else None
    if mine:                                        # T3: the day's cut left 0 shares; size at your own risk instead
        sz2 = shorts.size(pl, S.limits(mine, equity), journal.buying_power(today))
        if not sz2["refusal"]:
            sig["warnings"].append(ONE_SHARE % (st["risk_per_trade_pct"], mine["risk_per_trade_pct"]))
            st, sz = mine, sz2
    sig.update({"qty": sz["qty"], "cost": sz["cost"], "max_loss": sz["max_loss"], "reward": sz["reward"],
                "reward_risk": sz["reward_risk"], "bound_by": sz["bound_by"], "sizing_limits": sz["limits"]})
    if sz["refusal"]:
        sig["problems"].append("Size: %s" % sz["refusal"])
        return "blocked", sig

    # risk manager: a sell with a stop above it, allowed only in this short's own folder
    cfg = write_account(wd, st, journal, now)
    cfg.update({"allow_short": True, "allow_margin": True})
    skills.write_json(wd / "trader" / "config.json", cfg)
    skills.write_json(wd / "trader" / "orders.json", {"orders": [shorts.order(sig)]})
    r = skills.run("risk", ["--json", "--no-write"] + na, wd)
    res = ((r.json or {}).get("results") or [None])[0] if isinstance(r.json, dict) else None
    if not res:
        sig["problems"].append("Risk check could not run: %s" % r.message)
        return "blocked", sig
    sig["risk"] = {"verdict": res["verdict"], "reasons": res.get("reasons") or [], "info": res.get("info") or []}
    sig["warnings"] += res.get("warnings") or []

    sig["ticket"] = {"plain": "SELL SHORT %d %s, limit %.2f or higher, good for today / buy stop %.2f / buy limit (target) "
                              "%.2f / loss about $%.2f at the stop" % (sig["qty"], symbol, sig["limit"], sig["stop"],
                                                                         sig["target"], sig["max_loss"]),
                     "ready": res["verdict"] == "PASS" and not sig["problems"], "steps": shorts.tos_steps(sig)}

    sig["news"] = news(symbol, st, source, wd)
    if any("earnings" in (n.get("tags") or []) for n in sig["news"]):
        sig["warnings"].append("Earnings are in the headlines for %s. Good news can send a short up fast." % symbol)

    if res["verdict"] != "PASS":
        sig["problems"] += ["Risk: %s" % x for x in sig["risk"]["reasons"]]
    if sig["problems"]:
        return "blocked", sig
    off = volscreen.check(sig, st, source)
    if off:
        sig["problems"].append(off)
        return "weak", sig
    ep = (sig["odds"] or {}).get("edge_points")
    if sig["odds"] is None and not source.demo:
        sig["problems"].append("No Time Machine odds for this one, so the desk cannot grade it.")
        return "weak", sig
    if ep is not None and ep < st["min_edge_points"]:
        if volscreen.skips_floor(sig, st):
            sig["warnings"].append("Time Machine edge is %+.1f points, under your floor of %+.1f, but this stock is in play "
                                   "and on in-play days the Time Machine has rated the target too unlikely, so paper "
                                   "mode does not hold it back." % (ep, st["min_edge_points"]))
            return "ready", sig
        sig["problems"].append("Time Machine edge is %+.1f points, under your floor of %+.1f." % (ep, st["min_edge_points"]))
        return "weak", sig
    return "ready", sig

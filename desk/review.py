"""Reading the record: results, plan against what happened, and the day summary.

Plain functions over rows from the journal. Nothing here changes a rule, and
nothing here says what to do next: it lays the record out so you (or anyone helping you)
can read it before deciding whether to change a rule.

The video's list of what to look at besides profit is the list here: number
of trades, share of winners, average win and loss, worst drawdown, and how far
real fills were from the plan.
"""
from . import __version__
from . import stamp

MIN_TRADES = 20      # under this, every number below can flip with one trade
SIGNAL_ORDER = ("taken", "skipped", "expired", "ready", "weak", "blocked", "missed")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _r2(x):
    return None if x is None else round(x, 2)


def closed(trades):
    rows = [t for t in trades if t.get("status") == "closed" and t.get("pnl") is not None]
    return sorted(rows, key=lambda t: (t.get("exit_at") or "", t.get("id") or 0))


def results(trades):
    """The numbers for a list of trades. Every figure is from closed trades only."""
    rows = closed(trades)
    wins = [t["pnl"] for t in rows if t["pnl"] > 0]
    losses = [t["pnl"] for t in rows if t["pnl"] < 0]
    total = round(sum(t["pnl"] for t in rows), 2)
    peak = run = drawdown = 0.0
    streak = worst_streak = 0
    for t in rows:
        run += t["pnl"]
        peak = max(peak, run)
        drawdown = min(drawdown, run - peak)
        streak = streak + 1 if t["pnl"] < 0 else 0
        worst_streak = max(worst_streak, streak)
    avg_win, avg_loss = _mean(wins), _mean(losses)
    days = {}
    for t in rows:
        d = (t.get("exit_at") or t.get("date") or "")[:10]
        days[d] = round(days.get(d, 0.0) + t["pnl"], 2)
    worst_day = min(days.items(), key=lambda kv: (kv[1], kv[0])) if days else None
    return {
        "closed": len(rows), "wins": len(wins), "losses": len(losses), "even": len(rows) - len(wins) - len(losses),
        "win_rate": round(100.0 * len(wins) / len(rows), 1) if rows else None,
        "total": total, "per_trade": _r2(total / len(rows)) if rows else None,
        "avg_r": _r2(_mean([t.get("r_multiple") for t in rows])),
        "avg_win": _r2(avg_win), "avg_loss": _r2(avg_loss),
        "payoff": _r2(avg_win / -avg_loss) if avg_win is not None and avg_loss else None,
        "max_drawdown": round(drawdown, 2), "losing_run": worst_streak,
        # from CloddsBot's backtest report: money won for each dollar lost (None until there is a loser)
        "profit_factor": _r2(sum(wins) / -sum(losses)) if losses else None,
        "best": max((t["pnl"] for t in rows), default=None), "worst": min((t["pnl"] for t in rows), default=None),
        "worst_day": {"date": worst_day[0], "pnl": worst_day[1]} if worst_day else None,
    }


def standing(res, min_trades=MIN_TRADES):
    """Where the record stands against break-even, in words. A description, not advice."""
    n = res["closed"]
    if n < min_trades:
        if n == 0:
            return {"enough": False, "label": "No closed trades yet", "note": "Nothing to read until trades are recorded."}
        return {"enough": False, "label": "Too few to judge",
                "note": "Only %d closed trade%s. Under %d, one trade can flip every number here."
                        % (n, "" if n == 1 else "s", min_trades)}
    r = res["avg_r"] or 0.0
    label = "Ahead of break-even" if r > 0.1 else "Behind break-even" if r < -0.1 else "About break-even"
    return {"enough": True, "label": label,
            "note": "%d closed trades, average %+.2fR. One bad week is not a reason to change a rule." % (n, r)}


def by_exit(trades):
    out = {}
    for t in closed(trades):
        k = t.get("exit_reason") or "manual"
        o = out.setdefault(k, {"n": 0, "total": 0.0})
        o["n"] += 1
        o["total"] = round(o["total"] + t["pnl"], 2)
    return out


def by_rules(trades, sig_by_id, rulesets=None):
    groups = {}
    for t in closed(trades):
        p = (sig_by_id.get(t.get("signal_id")) or {}).get("payload") or {}
        groups.setdefault((p.get("stamp") or {}).get("rules") or "unstamped", []).append(t)
    out = []
    for h, rows in groups.items():
        r = results(rows)
        out.append({"rules": h, "first_seen": ((rulesets or {}).get(h) or {}).get("first_seen"),
                    "closed": r["closed"], "total": r["total"], "avg_r": r["avg_r"], "win_rate": r["win_rate"]})
    return sorted(out, key=lambda g: g["first_seen"] or "")


def _side(t):
    return "short" if t.get("side") == "short" else "long"


def by_side(trades):
    """Longs and shorts read apart, so a review can compare them."""
    out = {}
    for side in ("long", "short"):
        rows = [t for t in trades if _side(t) == side]
        r = results(rows)
        out[side] = {"closed": r["closed"], "total": r["total"], "avg_r": r["avg_r"], "win_rate": r["win_rate"],
                     "open": sum(1 for t in rows if t.get("status") == "open")}
    return out


def plan_vs_actual(trades, sig_by_id):
    """What the slip said against what was recorded, in the trader's favour or against it.
    Positive fill slip = a worse fill than planned (paid more on a buy, got less on a short sale).
    Stop and target gaps: minus = worse than planned, for longs and shorts alike."""
    fill_slip, over, fewer, stop_gap, target_gap = [], 0, 0, [], []
    planned = 0
    for t in trades:
        p = (sig_by_id.get(t.get("signal_id")) or {}).get("payload") or {}
        if p.get("limit") is not None:
            planned += 1
            sign = -1 if _side(t) == "short" else 1
            fill_slip.append(sign * (t["entry_price"] - p["limit"]))
            over += 1 if sign * (t["entry_price"] - p["limit"]) > 0.005 else 0
            fewer += 1 if p.get("qty") and t["qty"] < p["qty"] else 0
        if t.get("status") == "closed" and t.get("exit_price") is not None:
            sign = -1 if _side(t) == "short" else 1
            if t.get("exit_reason") == "stop":
                stop_gap.append(sign * (t["exit_price"] - t["stop"]))
            elif t.get("exit_reason") == "target":
                target_gap.append(sign * (t["exit_price"] - t["target"]))
    done = closed(trades)
    return {
        "from_signals": planned, "avg_fill_vs_limit": _r2(_mean(fill_slip)), "fills_over_limit": over, "took_fewer_shares": fewer,
        "stop_exits": len(stop_gap), "avg_stop_vs_plan": _r2(_mean(stop_gap)),
        "target_exits": len(target_gap), "avg_target_vs_plan": _r2(_mean(target_gap)),
        "closed_early": sum(1 for t in done if t.get("exit_reason") == "manual"),
        "closed_end_of_day": sum(1 for t in done if t.get("exit_reason") == "flat"),
    }


def by_source(trades):
    """The desk's own paper trades (auto paper, note "auto") against the ones you recorded, longs and
    shorts apart ("auto short", "you short")."""
    groups = {}
    for t in closed(trades):
        who = "auto" if t.get("note") == "auto" else "you"
        groups.setdefault(who + (" short" if t.get("side") == "short" else ""), []).append(t)
    return {k: {"closed": r["closed"], "total": r["total"], "avg_r": r["avg_r"], "win_rate": r["win_rate"]}
            for k, r in ((k, results(v)) for k, v in sorted(groups.items()))}


def outcome_table(outcomes, sig_by_id=None):
    """Per signal status (taken, skipped, expired, weak, blocked...): how the replays came out.
    Short signals are grouped apart ("short skipped", ...) so longs and shorts can be compared."""
    out = {}
    for o in outcomes:
        p = ((sig_by_id or {}).get(o.get("signal_id")) or {}).get("payload") or {}
        key = ("short " + o["status"]) if p.get("side") == "short" else o["status"]
        g = out.setdefault(key, {"n": 0, "results": {}, "rs": []})
        g["n"] += 1
        g["results"][o["result"]] = g["results"].get(o["result"], 0) + 1
        if o.get("r") is not None:
            g["rs"].append(o["r"])
    return {k: {"n": g["n"], "results": g["results"], "avg_r": _r2(_mean(g["rs"])), "with_r": len(g["rs"])}
            for k, g in out.items()}


def odds_check(signals, outcomes):
    """Did the Time Machine's odds hold up? Its share of target-first against the replays' share."""
    by = {o["signal_id"]: o for o in outcomes}
    rows = [(s["payload"]["odds"]["p_target"], s["payload"]["odds"]["p_stop"], by[s["id"]]["result"])
            for s in signals if (s.get("payload") or {}).get("odds") and s["id"] in by
            and by[s["id"]]["result"] in ("target", "stop", "flat", "open")]
    if not rows:
        return None
    return {"n": len(rows), "predicted_target": _r2(100 * _mean([r[0] for r in rows])),
            "predicted_stop": _r2(100 * _mean([r[1] for r in rows])),
            "actual_target": _r2(100.0 * sum(1 for r in rows if r[2] == "target") / len(rows)),
            "actual_stop": _r2(100.0 * sum(1 for r in rows if r[2] == "stop") / len(rows))}


JUDGED = ("target", "stop", "flat", "open")      # replay results that say how a trade would have gone
EDGE_BUCKETS = (("under -10", None, -10), ("-10 to -5", -10, -5), ("-5 to 0", -5, 0), ("0 to +5", 0, 5), ("+5 and up", 5, None))


def odds_by_edge(signals, outcomes):
    """CloddsBot's ledger checks its confidence bucket by bucket. Here: the Time Machine's edge points, in
    bands, against what the day's replay did. If a higher edge does no better, the floor
    (min_edge_points) is not sorting good from bad."""
    by = {o["signal_id"]: o for o in outcomes}
    groups = {}
    for s in signals:
        odds = (s.get("payload") or {}).get("odds") or {}
        o = by.get(s["id"])
        if o is None or odds.get("edge_points") is None:
            continue
        e = float(odds["edge_points"])
        name = next(b for b, lo, hi in EDGE_BUCKETS if (lo is None or e >= lo) and (hi is None or e < hi))
        g = groups.setdefault(name, {"judged": [], "no_fill": 0})
        if o["result"] in JUDGED:
            g["judged"].append((odds.get("p_target"), o["result"], o.get("r")))
        elif o["result"] == "no_fill":
            g["no_fill"] += 1
    out = []
    for name, _, _ in EDGE_BUCKETS:
        if name not in groups:
            continue
        rows, n = groups[name]["judged"], len(groups[name]["judged"])
        out.append({"bucket": name, "n": n, "no_fill": groups[name]["no_fill"],
                    "predicted_target": _r2(100 * _mean([r[0] for r in rows])) if n else None,
                    "actual_target": _r2(100.0 * sum(1 for r in rows if r[1] == "target") / n) if n else None,
                    "avg_r": _r2(_mean([r[2] for r in rows]))})
    return out


HELD = ("weak", "blocked", "missed")
REASONS = (("Time Machine edge is", "edge under your floor"), ("No Time Machine odds", "no odds"),
           ("The stop is only", "stop too close"), ("Budget", "budget or cash"),
           ("Risk check could not run", "risk check did not run"), ("Risk:", "risk manager"),
           ("Exit planner refused", "exit planner refused"))


def _reason(problems):
    first = str((problems or [""])[0])
    if "Too late to chase" in first:
        return "too late to chase"
    return next((name for head, name in REASONS if first.startswith(head)), "other")


def held_back(signals, outcomes=()):
    """CloddsBot's ledger counts why it said no. Here: why a signal was weak, blocked or missed, and how the
    held-back ones would have done on the day's replay. Most common first."""
    by = {o["signal_id"]: o for o in outcomes}
    groups = {}
    for s in signals:
        if s.get("status") not in HELD:
            continue
        g = groups.setdefault(_reason((s.get("payload") or {}).get("problems")), {"n": 0, "rs": [], "replayed": 0})
        g["n"] += 1
        o = by.get(s["id"])
        if o and o["result"] in JUDGED:
            g["replayed"] += 1
            if o.get("r") is not None:
                g["rs"].append(o["r"])
    rows = [{"reason": k, "n": g["n"], "replayed": g["replayed"], "avg_r": _r2(_mean(g["rs"]))} for k, g in groups.items()]
    return sorted(rows, key=lambda h: (-h["n"], h["reason"]))


def scan_stats(scans):
    ran = [s["summary"] for s in scans if not s["summary"].get("halt")]
    if not ran:
        return None
    failed = sum(1 for s in ran if s.get("error"))
    return {"scans": len(ran), "days": len({s["at"][:10] for s in ran}), "failed": failed,
            "avg_charts": _r2(_mean([s.get("scanned") for s in ran])),
            "avg_gaps": _r2(_mean([s.get("unusable") for s in ran if "unusable" in s])),
            "breakouts": sum(s.get("hits") or 0 for s in ran), "new_signals": sum(s.get("new_signals") or 0 for s in ran)}


def scan_lists(lists, signals, outcomes=()):
    """Each day the desk picked its own scan list (desk/autolist.py): how big it was and how that day's signals
    on it did on the replay, newest first. The way to judge whether the picking helps."""
    by = {o["signal_id"]: o for o in outcomes}
    rows = []
    for date, d in sorted((lists or {}).items(), reverse=True):
        listed = set(d.get("symbols") or [])
        sig = [x for x in signals if x.get("date") == date and x.get("symbol") in listed]
        rs = [by[x["id"]]["r"] for x in sig if x["id"] in by and by[x["id"]]["result"] in JUDGED and by[x["id"]].get("r") is not None]
        rows.append({"date": date, "stocks": len(listed), "error": d.get("error"), "signals": len(sig),
                     "ready": sum(1 for x in sig if x.get("status") == "ready"), "replayed": len(rs), "avg_r": _r2(_mean(rs)),
                     "top": (d.get("symbols") or [])[:8], "catalyst": list(d.get("catalyst") or [])})
    return rows


def catalyst_vs_plain(lists, signals, outcomes=()):
    """Signals on the picked lists, split by why the stock was there: a catalyst (desk/catalysts.py) or the plain
    volatility pick. Same replay R as above, so the two can be compared."""
    by = {o["signal_id"]: o for o in outcomes}
    out = {k: {"signals": 0, "rs": []} for k in ("catalyst", "plain")}
    for date, d in (lists or {}).items():
        if d.get("error"):
            continue
        cat, listed = set(d.get("catalyst") or []), set(d.get("symbols") or [])
        for x in signals:
            if x.get("date") == date and x.get("symbol") in listed:
                g = out["catalyst" if x["symbol"] in cat else "plain"]
                g["signals"] += 1
                o = by.get(x["id"])
                if o and o["result"] in JUDGED and o.get("r") is not None:
                    g["rs"].append(o["r"])
    return {k: {"signals": g["signals"], "replayed": len(g["rs"]), "avg_r": _r2(_mean(g["rs"])),
                "win_rate": _r2(100.0 * sum(1 for r in g["rs"] if r > 0) / len(g["rs"])) if g["rs"] else None}
            for k, g in out.items()}


def plan_agreement(signals, outcomes=()):
    """Signals by what Claude's game plan said (desk/analyst.py): with the plan, against it, or not in it.
    Same replay R as above, so you can see whether the research earns its place."""
    by = {o["signal_id"]: o for o in outcomes}
    out = {k: {"signals": 0, "rs": []} for k in ("with", "against", "none")}
    for x in signals:
        p = (x.get("payload") or {}).get("plan")
        g = out["none" if not p else "with" if p.get("agrees") else "against"]
        g["signals"] += 1
        o = by.get(x["id"])
        if o and o["result"] in JUDGED and o.get("r") is not None:
            g["rs"].append(o["r"])
    return {k: {"signals": g["signals"], "replayed": len(g["rs"]), "avg_r": _r2(_mean(g["rs"])),
                "win_rate": _r2(100.0 * sum(1 for r in g["rs"] if r > 0) / len(g["rs"])) if g["rs"] else None}
            for k, g in out.items()}


ARM_STATUSES = ("ready", "taken", "skipped", "expired")   # long slips that were good to buy at some point
ARM_DAYS = 20


def entry_arms(outcomes, shadows, sig_by_id):
    """The entry-style A/B (docs/MODELS.md): the real slip's replay against the shadow VWAP and retest limits, over
    the same long signals, in the real slip's risk units. Logging only: nothing here changed a signal or a fill."""
    real = {o["signal_id"]: o for o in outcomes}
    arms = {"slip": [], "vwap": [], "retest": [], "spy_with": [], "spy_against": []}
    days = set()
    for sh in shadows:
        s = sig_by_id.get(sh["signal_id"]) or {}
        if sh["status"] not in ARM_STATUSES or sh["arm"] not in arms:
            continue
        arms[sh["arm"]].append((sh["result"], sh["r_orig"]))
        days.add(sh["date"])
        if sh["arm"] == "vwap" and sh["signal_id"] in real:      # once per signal: the real slip, same units
            o, p = real[sh["signal_id"]], s.get("payload") or {}
            try:
                risk = float(p["limit"]) - float(p["stop"])
                r = round((o["exit"] - o["entry"]) / risk, 2) if o["exit"] is not None and risk > 0 else None
            except (KeyError, TypeError, ValueError):
                r = None
            arms["slip"].append((o["result"], r))
    out = {}
    for k, xs in arms.items():
        rs = [r for _, r in xs if r is not None]
        out[k] = {"signals": len(xs), "filled": len(rs), "total_r": _r2(sum(rs)) if rs else None,
                  "avg_r": _r2(_mean(rs)) if rs else None, "no_fill": sum(1 for res, _ in xs if res == "no fill")}
    return {"days": len(days), "enough": len(days) >= ARM_DAYS, "arms": out}


def signal_counts(signals):
    out = {}
    for s in signals:
        out[s["status"]] = out.get(s["status"], 0) + 1
    return out


def summary(trades, signals, events=(), rulesets=None, min_trades=MIN_TRADES, outcomes=(), scans=(), lists=None):
    sig_by_id = {s["id"]: s for s in signals}
    res = results(trades)
    return {
        "results": res, "standing": standing(res, min_trades), "min_trades": min_trades,
        "by_exit": by_exit(trades), "by_rules": by_rules(trades, sig_by_id, rulesets), "by_side": by_side(trades),
        "plan": plan_vs_actual(trades, sig_by_id),
        "signals": signal_counts(signals), "signals_total": len(signals),
        "open": sum(1 for t in trades if t.get("status") == "open"),
        "settings_changes": [{"ts": e["ts"], "message": e["message"]} for e in events if e.get("kind") == "settings"][:50],
        "by_source": by_source(trades), "outcomes": outcome_table(outcomes, sig_by_id), "odds_check": odds_check(signals, outcomes),
        "scans": scan_stats(scans), "rulesets": rulesets or {},
        "practice_fills": sum(1 for e in events if e.get("kind") == "paper"),
        "odds_by_edge": odds_by_edge(signals, outcomes), "held_back": held_back(signals, outcomes),
        "stops_log": [{"ts": e["ts"], "message": e["message"]} for e in events if e.get("kind") == "stops"][:30],
        "scan_lists": scan_lists(lists, signals, outcomes),
        "catalyst_vs_plain": catalyst_vs_plain(lists, signals, outcomes),
        "plan_agreement": plan_agreement(signals, outcomes),
    }


# ---- the day ---------------------------------------------------------
def _usd(x, sign=True):
    return "%s$%.2f" % (("+" if x > 0 else "-" if x < 0 else "") if sign else ("-" if x < 0 else ""), abs(x))


def day_summary(date, trades, signals):
    """One paragraph on a day, or None when nothing happened."""
    sigs = [s for s in signals if s.get("date") == date]
    rows = [t for t in trades if t.get("date") == date]
    if not sigs and not rows:
        return None
    c = signal_counts(sigs)
    parts = ", ".join("%d %s" % (c[k], k) for k in SIGNAL_ORDER if c.get(k))
    text = "Day summary %s: %d signal%s%s." % (date, len(sigs), "" if len(sigs) == 1 else "s", " (%s)" % parts if parts else "")
    done = closed(rows)
    if rows:
        text += " You took %d trade%s." % (len(rows), "" if len(rows) == 1 else "s")
    if done:
        r = _mean([t.get("r_multiple") for t in done])
        text += " Closed %d: %s%s." % (len(done), _usd(sum(t["pnl"] for t in done)), " (%+.2fR a trade)" % r if r is not None else "")
    still = [t["symbol"] for t in rows if t.get("status") == "open"]
    if still:
        text += " Still marked open: %s. Day trades are flat by the close: record the exit." % ", ".join(still)
    if not rows:
        text += " No trades taken. That is a fine day."
    return text


def _decision_lines(d):
    """What every scan decided per stock: long, short, both or nothing, and the commonest reasons for nothing."""
    if not d or not d.get("rows"):
        return []
    by = d["by_decision"]
    L = ["SCAN DECISIONS (%d stock-scans)" % d["rows"],
         "  " + ", ".join("%s %d" % (k, by[k]) for k in ("long", "short", "both", "nothing") if by.get(k))]
    for side in ("long", "short"):
        top = d["top_reasons"].get(side) or []
        if top:
            L.append("  No %s, commonest reasons: %s" % (side, "; ".join("%s (%d)" % kv for kv in top)))
    return L + [""]


# ---- the plain-text review report ------------------------------------
def report(mode, s, now, rules_hash=None):
    r, st, p = s["results"], s["standing"], s["plan"]
    f = lambda x, fmt="%+.2f": "n/a" if x is None else fmt % x
    L = ["Trading Desk review: %s record, as of %s" % (mode.upper(), now),
         "Desk %s, skills %s%s" % (__version__, stamp.skills_commit(), ", current rule set %s" % rules_hash if rules_hash else ""),
         "",
         "RESULTS (%d closed, %d open)" % (r["closed"], s["open"]),
         "  %s. %s" % (st["label"], st["note"])]
    if r["closed"]:
        L += ["  Winners %d, losers %d, even %d. Win rate %s%%." % (r["wins"], r["losses"], r["even"], f(r["win_rate"], "%.1f")),
              "  Total %s. Per trade %s. Average R %s." % (_usd(r["total"]), _usd(r["per_trade"]), f(r["avg_r"])),
              "  Average win %s, average loss %s, payoff %s." % ("n/a" if r["avg_win"] is None else _usd(r["avg_win"]),
                                                               "n/a" if r["avg_loss"] is None else _usd(r["avg_loss"]), f(r["payoff"], "%.2f")),
              "  Worst drawdown %s. Longest losing run %d." % (_usd(r["max_drawdown"]), r["losing_run"]),
              "  Profit factor %s (won for each $1 lost). Best trade %s, worst %s. Worst day %s%s."
              % (f(r.get("profit_factor"), "%.2f"), "n/a" if r.get("best") is None else _usd(r["best"]),
                 "n/a" if r.get("worst") is None else _usd(r["worst"]),
                 "n/a" if not r.get("worst_day") else _usd(r["worst_day"]["pnl"]),
                 " (%s)" % r["worst_day"]["date"] if r.get("worst_day") else ""),
              "  By exit: " + (", ".join("%s %d (%s)" % (k, v["n"], _usd(v["total"])) for k, v in sorted(s["by_exit"].items())) or "none")]
        L += ["  %s: %d closed, %s, average R %s, win rate %s%%." % (side.capitalize(), v["closed"], _usd(v["total"]), f(v["avg_r"]),
                                                                   f(v["win_rate"], "%.1f"))
              for side, v in s["by_side"].items() if v["closed"] or v["open"]]
    L += ["", "PLAN AGAINST WHAT HAPPENED",
          "  Fills from a signal: %d. Average fill against the slip's limit: %s a share (plus = worse: paid more, or shorted lower)."
          % (p["from_signals"], f(p["avg_fill_vs_limit"])),
          "  Fills worse than the limit (the slip says skip those): %d. Took fewer shares than sized: %d." % (p["fills_over_limit"], p["took_fewer_shares"]),
          "  Stop exits: %d, average %s a share against the planned stop (minus = worse)." % (p["stop_exits"], f(p["avg_stop_vs_plan"])),
          "  Target exits: %d, average %s a share against the planned target." % (p["target_exits"], f(p["avg_target_vs_plan"])),
          "  Closed early by hand: %d. Closed at the end of the day: %d." % (p["closed_early"], p["closed_end_of_day"]),
          "", "SIGNALS (%d)" % s["signals_total"],
          "  " + (", ".join("%s %d" % (k, s["signals"][k]) for k in SIGNAL_ORDER if s["signals"].get(k)) or "none"),
          "", "WHO TOOK THEM (auto = auto paper, you = recorded by you)"]
    L += ["  %s: %d closed, %s, win rate %s%%, average R %s" % (k, v["closed"], _usd(v["total"]), f(v["win_rate"], "%.1f"),
                                                               f(v["avg_r"])) for k, v in s.get("by_source", {}).items()] or ["  none"]
    L += ["  Practice-account fills logged: %d." % s.get("practice_fills", 0),
          "", "HOW EVERY SIGNAL WOULD HAVE DONE (replayed on the day's candles with the slip's own numbers)"]
    L += ["  %s %d: %s; average %sR over %d that filled" % (k, v["n"], ", ".join("%s %d" % kv for kv in sorted(v["results"].items())),
                                                          f(v["avg_r"]), v["with_r"])
          for k, v in sorted(s.get("outcomes", {}).items())] or ["  none yet (replays run after 4:05 PM New York)"]
    oc = s.get("odds_check")
    L += ["", "DID THE ODDS HOLD UP",
          "  %d replays with odds: Time Machine said target first %s%%, stop first %s%%; the day gave %s%% and %s%%."
          % (oc["n"], f(oc["predicted_target"], "%.1f"), f(oc["predicted_stop"], "%.1f"), f(oc["actual_target"], "%.1f"),
             f(oc["actual_stop"], "%.1f")) if oc else "  none yet"]
    fr = lambda x: "n/a" if x is None else "%+.2fR" % x
    L += ["", "ODDS BY EDGE (Time Machine edge points against the replays; if higher bands do no better, the floor does not sort)"]
    L += ["  %s: %d judged, said target first %s%%, the day gave %s%%, average %s (%d never filled)"
          % (b["bucket"], b["n"], f(b["predicted_target"], "%.1f"), f(b["actual_target"], "%.1f"), fr(b["avg_r"]), b["no_fill"])
          for b in s.get("odds_by_edge") or []] or ["  none yet"]
    L += ["", "WHY SIGNALS WERE HELD BACK (weak, blocked or missed; how they would have done on the replay)"]
    L += ["  %s %d (replayed %d, average %s)" % (h["reason"], h["n"], h["replayed"], fr(h["avg_r"]))
          for h in s.get("held_back") or []] or ["  none"]
    L += ["", "RISK STOPS (weekly loss, drop from the best point, losers in a row; newest first)"]
    L += ["  %s  %s" % (e["ts"], e["message"]) for e in s.get("stops_log") or []] or ["  none tripped"]
    sc = s.get("scans")
    L += ["", "SCANS",
          "  %d scans over %d days, %d failed. Average %s charts read, %s left out for gaps. %d breakouts, %d new signals."
          % (sc["scans"], sc["days"], sc["failed"], f(sc["avg_charts"], "%.1f"), f(sc["avg_gaps"], "%.1f"), sc["breakouts"],
             sc["new_signals"]) if sc else "  none logged yet"]
    L += ["", "SCAN LISTS THE DESK PICKED (newest first; signals on the list, and their average replay R)"]
    L += ["  %s  %s" % (d["date"], d["error"]) if d["error"] else
          "  %s  %d stocks (%s...), %d signals, %d ready, %d replayed, average %s"
          % (d["date"], d["stocks"], " ".join(d["top"]), d["signals"], d["ready"], d["replayed"], fr(d["avg_r"]))
          for d in (s.get("scan_lists") or [])[:15]] or ["  none: the desk has not picked a list yet (Settings, Pick stocks to scan for me)"]
    cv = s.get("catalyst_vs_plain") or {}
    L += ["", "CATALYST PICKS AGAINST THE VOLATILITY PICKS (signals on the picked list, by why the stock was on it)"]
    L += ["  %s: %d signals, %d replayed, average %s, win rate %s%%" % (
        "On the list for a catalyst" if k == "catalyst" else "On the list for its daily range", v["signals"], v["replayed"],
        fr(v["avg_r"]), f(v["win_rate"], "%.1f")) for k, v in sorted(cv.items()) if v["signals"]] \
        or ["  none yet: no signal has come from a picked list with catalysts on it"]
    pa = s.get("plan_agreement") or {}
    L += ["", "CLAUDE'S GAME PLAN (signals by whether the plan agreed; against = held back in paper mode)"]
    L += ["  %s: %d signals, %d replayed, average %s, win rate %s%%" % (
        {"with": "With the plan", "against": "Against the plan", "none": "Not in a plan"}[k], v["signals"], v["replayed"],
        fr(v["avg_r"]), f(v["win_rate"], "%.1f")) for k, v in pa.items() if v["signals"]] \
        or ["  none yet"]
    ea = s.get("entry_arms") or {}
    L += ["", "ENTRY STYLE A/B (shadow, logging only: same long signals, same stop and target, R in the slip's own risk)"]
    if ea.get("arms", {}).get("vwap", {}).get("signals"):
        names = {"slip": "Real slip (breakout + chase)", "vwap": "Buy limit at VWAP", "retest": "Buy limit at the range high",
                 "spy_with": "Real slip, SPY over its VWAP (C4)", "spy_against": "Real slip, SPY under its VWAP (C4)"}
        L += ["  %s: %d signals, %d filled, %d never filled, total %s, average %s"
              % (names[k], v["signals"], v["filled"], v["no_fill"], fr(v["total_r"]), fr(v["avg_r"]))
              for k, v in ea["arms"].items() if v["signals"] or k in ("slip", "vwap", "retest")]
        L.append("  %d trading days so far. %s" % (ea["days"], "Enough days to start comparing; still check the spread."
                                                  if ea["enough"] else "Wait for %d or more before reading anything into it."
                                                  % ARM_DAYS))
    else:
        L.append("  none yet (logged after 4:05 PM New York for each long signal that was ready)")
    try:
        from . import combo
        cl = combo.lines(s["combo"]) if s.get("combo") else ["  not loaded"]
    except Exception as e:          # a damaged combo.json must not break the review
        cl = ["  unreadable: %s" % e]
    L += ["", "COMBINED SPY MODEL (a second paper book: dip-buyer, Halloween and turn-of-month votes; docs/MODELS.md)"] + cl
    L += [""] + _decision_lines(s.get("decisions")) + ["BY RULE SET"]
    L += ["  %s%s: %d closed, %s, average R %s" % (g["rules"], " (since %s)" % g["first_seen"] if g["first_seen"] else "",
                                                  g["closed"], _usd(g["total"]), f(g["avg_r"])) for g in s["by_rules"]] or ["  none"]
    for h, v in sorted((s.get("rulesets") or {}).items(), key=lambda kv: kv[1].get("first_seen") or ""):
        L.append("    %s = %s" % (h, ", ".join("%s %s" % kv for kv in sorted((v.get("rules") or {}).items()))))
    L += ["", "SETTINGS CHANGES (newest first)"]
    L += ["  %s  %s" % (e["ts"], e["message"]) for e in s["settings_changes"]] or ["  none logged"]
    L += ["", "Reading this: a number from fewer than %d trades is noise. " % s["min_trades"] +
          ("Paper fills are simulated, so good paper results show the routine works, not that live results will match."
           if mode == "paper" else "Real fills include slippage the slip cannot see; compare the fill and stop lines above."),
          "Rule changes are logged in docs/CHANGES.md. The desk shows numbers; it is not advice."]
    return "\n".join(L)

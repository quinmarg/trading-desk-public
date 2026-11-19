"""How a signal would have done, taken or not.

After the close the desk replays every signal of the day against that day's 5-minute candles, with the
slip's own numbers: buy at the limit or lower while the signal was good, then the stop, the target or
the flat-by time, whichever comes first. A short slip is the mirror: sell short at the limit or higher,
then the buy stop above, the target below or the flat-by time. The answer is stored beside the signal so a later review can
ask "what did I skip, and was skipping right?". It is an estimate from candles, not a fill: inside one
candle the order of the high and the low is unknown, so when a candle reaches both the stop and the
target the stop is counted (the careful answer). Nothing here changes a signal or a trade.
"""

NO_PLAN, NO_FILL, TARGET, STOP, FLAT, OPEN = "no plan", "no fill", "target", "stop", "flat", "open"


def _minute(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def replay(p, bars):
    """p: a signal's payload. bars: that day's regular-session 5-minute bars (desk/charts.py), oldest first.
    Returns {result, entry, exit, exit_time, r, note}."""
    try:
        limit, stop, target = float(p["limit"]), float(p["stop"]), float(p["target"])
        start = _minute(p.get("trigger_close_time") or p["valid_until"])
        until = _minute(p["valid_until"])
        flat = _minute(p.get("flat_by") or "15:55")
    except (KeyError, TypeError, ValueError):
        return {"result": NO_PLAN, "entry": None, "exit": None, "exit_time": None, "r": None,
                "note": "The signal stopped before a plan was made."}
    if p.get("side") == "short":
        return _replay_short(limit, stop, target, start, until, flat, bars)
    if not stop < limit < target:
        return {"result": NO_PLAN, "entry": None, "exit": None, "exit_time": None, "r": None,
                "note": "The plan's numbers are not usable."}
    after = [b for b in bars if b["minute"] >= start]
    entry, i = None, None
    for k, b in enumerate(after):
        if b["minute"] >= until:
            break
        if b["l"] <= limit + 1e-9:
            entry, i = round(min(limit, b["o"]), 2), k     # a gap down fills at the open, under the limit
            break
    if entry is None:
        return {"result": NO_FILL, "entry": None, "exit": None, "exit_time": None, "r": None,
                "note": "The price never came back to the limit while the signal was good."}
    risk = entry - stop

    def done(result, price, b, note):
        price = round(price, 2)
        return {"result": result, "entry": entry, "exit": price, "exit_time": b["start"],
                "r": round((price - entry) / risk, 2) if risk > 0 else None, "note": note}

    for k, b in enumerate(after[i:]):
        if b["minute"] >= flat:
            return done(FLAT, b["o"], b, "Still open at the flat-by time.")
        if b["l"] <= stop + 1e-9:
            gap = k > 0 and b["o"] < stop                   # opened under the stop: a stop fills at the open
            return done(STOP, b["o"] if gap else stop, b, "Hit the stop." + (" Gapped through it." if gap else ""))
        if k > 0 and b["h"] >= target - 1e-9:               # not in the fill candle: its order is unknown
            return done(TARGET, max(target, b["o"]) if b["o"] > target else target, b, "Reached the target.")
    last = after[-1]
    return done(OPEN, last["c"], last, "The candles end before the trade did.")


def _replay_short(limit, stop, target, start, until, flat, bars):
    """The short mirror of replay(): fills at the limit or higher, stop above, target below."""
    if not target < limit < stop:
        return {"result": NO_PLAN, "entry": None, "exit": None, "exit_time": None, "r": None,
                "note": "The plan's numbers are not usable."}
    after = [b for b in bars if b["minute"] >= start]
    entry, i = None, None
    for k, b in enumerate(after):
        if b["minute"] >= until:
            break
        if b["h"] >= limit - 1e-9:
            entry, i = round(max(limit, b["o"]), 2), k     # a gap up fills at the open, over the limit
            break
    if entry is None:
        return {"result": NO_FILL, "entry": None, "exit": None, "exit_time": None, "r": None,
                "note": "The price never came back up to the limit while the signal was good."}
    risk = stop - entry

    def done(result, price, b, note):
        price = round(price, 2)
        return {"result": result, "entry": entry, "exit": price, "exit_time": b["start"],
                "r": round((entry - price) / risk, 2) if risk > 0 else None, "note": note}

    for k, b in enumerate(after[i:]):
        if b["minute"] >= flat:
            return done(FLAT, b["o"], b, "Still open at the flat-by time.")
        if b["h"] >= stop - 1e-9:
            gap = k > 0 and b["o"] > stop                   # opened over the stop: a buy stop fills at the open
            return done(STOP, b["o"] if gap else stop, b, "Hit the buy stop." + (" Gapped through it." if gap else ""))
        if k > 0 and b["l"] <= target + 1e-9:
            return done(TARGET, min(target, b["o"]), b, "Reached the target.")
    last = after[-1]
    return done(OPEN, last["c"], last, "The candles end before the trade did.")


# ---- shadow entry arms (logging only; docs/MODELS.md) -----------------
# The same long slip, same stop and target, with the buy limit moved to a pullback level. Declared before any data
# was seen: two arms, a 60-minute resting window from the trigger candle's close, never above the real limit.
SHADOW_ARMS = ("vwap", "retest")
SHADOW_MINUTES = 60


def vwap_at(bars, minute):
    """Session VWAP over the 5-minute bars that had closed by `minute` (typical price x volume)."""
    pv = vol = 0.0
    for b in bars:
        if b["minute"] + 5 > minute:
            break
        pv += (b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
        vol += b["v"]
    return pv / vol if vol else None


def shadow(p, bars, spy=None):
    """{arm: replay result + limit + r_orig} for a long slip, or {} for a short or a slip with no plan.
    r_orig is in the real slip's risk (limit - stop), so every arm is measured in the same units: the same share
    count as the real slip, not re-sized. Nothing here changes a signal, a size or a fill."""
    if p.get("side") == "short":
        return {}
    try:
        limit, stop = float(p["limit"]), float(p["stop"])
        start = _minute(p.get("trigger_close_time") or p["valid_until"])
        flat = _minute(p.get("flat_by") or "15:55")
    except (KeyError, TypeError, ValueError):
        return {}
    risk = limit - stop
    if risk <= 0:
        return {}
    until = min(start + SHADOW_MINUTES, flat)
    levels = {"vwap": vwap_at(bars, start), "retest": (p.get("opening_range") or {}).get("high")}
    out = {}
    for arm in SHADOW_ARMS:
        lvl = levels[arm]
        if lvl is None:
            out[arm] = {"result": NO_PLAN, "entry": None, "exit": None, "exit_time": None, "r": None, "limit": None,
                        "r_orig": None, "note": "No level to buy at."}
            continue
        q = dict(p, limit=min(int(float(lvl) * 100 + 1e-6) / 100.0, limit), valid_until="%02d:%02d" % divmod(until, 60))
        o = replay(q, bars)
        o["limit"] = q["limit"]
        o["r_orig"] = round((o["exit"] - o["entry"]) / risk, 2) if o.get("exit") is not None else None
        out[arm] = o
    # candidate C4 (docs/MODELS.md section 5): the real slip, tagged by SPY's side of its VWAP at the trigger
    if spy:
        done = [b for b in spy if b["minute"] + 5 <= start]
        vw = vwap_at(spy, start)
        if done and vw:
            o = replay(p, bars)
            o["limit"] = limit
            o["r_orig"] = round((o["exit"] - o["entry"]) / risk, 2) if o.get("exit") is not None else None
            out["spy_with" if done[-1]["c"] > vw else "spy_against"] = o
    return out

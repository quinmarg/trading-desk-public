"""Settings: one JSON file, validated, and scaled to the account.

Every money limit is a percentage of the account, so the same settings work
at $400 and at $40,000. skills_config() turns them into the config.json the
day-trader-skill tools read.
"""
import json
import math
import re

from .paths import data_dir

DEFAULTS = {
    "mode": "paper",                 # "paper" or "live": separate journals (desk/mode.py). Changed only by its own switch
    "starting_balance": 400.0,       # what you funded the account with
    "account_type": "cash",          # "cash" (sales settle next business day) or "margin"
    "risk_per_trade_pct": 2.0,       # max loss per trade, % of the account
    "max_daily_loss_pct": 4.0,       # stop trading for the day after this
    "max_weekly_loss_pct": 8.0,      # no new entries for the rest of the week after this (0 = off; desk/breaker.py)
    "max_drawdown_pct": 15.0,        # no new entries once this far under the best point, until Reset stops (0 = off)
    "max_losing_streak": 0,          # no new entries after this many losers in a row, until Reset stops (0 = off)
    "max_trades_per_day": 2,
    "cash_buffer_pct": 5.0,          # never invested
    "max_position_pct": 95.0,        # of the account, in one stock
    "min_reward_risk": 1.0,
    "target_r": 2.0,                 # target = entry + target_r x risk
    "stop_rule": "or-mid",           # or-mid | or-low | pct:X | atr:K
    "chase_r": 0.2,                  # buy-limit ceiling = entry + chase_r x risk
    "signal_valid_minutes": 10,      # a trigger older than this is "missed"
    "or_minutes": 15,
    "min_price": 5.0,
    "min_stop_pct": 0.3,             # block a signal whose stop is closer than this, % of the entry (0 = off)
    "min_volume_x": 0.0,             # trigger-bar volume vs opening-range average (0 = off)
    "no_entries_before": "09:45",
    "no_entries_after": "15:30",
    "flat_by": "15:55",
    "est_cost_per_share": 0.01,      # your guess at slippage and spread, per share, in and out together (shown, never blocks)
    "min_edge_points": -5.0,         # hide signals whose Time Machine edge is below this
    "replays": 10000,
    "pdt_guard": False,
    "paused": False,                 # your own stop switch: no new signals while it is on
    "blocked": [],
    "watchlist": ["F", "SOFI", "PLTR", "AAL", "T", "INTC", "PFE", "BAC", "SNAP", "RIVN",
                  "HOOD", "UBER", "AMD", "NIO", "CCL", "KO", "CSCO", "VZ", "GM",
                  "DAL", "PYPL", "DKNG", "MARA", "SMCI", "NVDA", "AAPL", "TSLA", "AMZN", "MU"],
    "scan_universe": False,          # also scan every US stock (about 300 requests a pass)
    "universe_scan_every_min": 30,
    "scan_every_seconds": 300,
    "monitor_every_seconds": 60,
    "news_hours": 18,
    "sec_user_agent": "",            # "Your Name you@example.com" turns on SEC filings
    "ntfy_topic": "",                # phone alerts for ready signals (desk/notify.py); empty = off
    "ntfy_server": "https://ntfy.sh",
    "congress_members": ["pelosi"],
    "directions": "long",            # "long" | "short" | "both": which signals the desk looks for (docs/SHORTING.md)
    "short_approved": False,         # your broker approved this account for short selling; off = shorts are paper only
    "auto_paper": False,             # paper mode only: the desk takes ready signals itself in the practice account (desk/auto.py)
    "auto_paper_weak": False,        # auto paper also takes "weak" signals (odds under the floor), to learn from more trades
}

_RANGES = {
    "starting_balance": (1, 1e9), "risk_per_trade_pct": (0.1, 10), "max_daily_loss_pct": (0.2, 30),
    "max_weekly_loss_pct": (0, 50), "max_drawdown_pct": (0, 90), "max_losing_streak": (0, 20),
    "max_trades_per_day": (1, 50), "cash_buffer_pct": (0, 90), "max_position_pct": (1, 100),
    "min_reward_risk": (0.5, 10), "target_r": (0.5, 10), "chase_r": (0, 1),
    "signal_valid_minutes": (1, 120), "or_minutes": (5, 60), "min_price": (0, 1e6),
    "min_volume_x": (0, 20), "min_stop_pct": (0, 10), "est_cost_per_share": (0, 5), "min_edge_points": (-100, 100), "replays": (1000, 100000),
    "universe_scan_every_min": (5, 390), "scan_every_seconds": (60, 3600),
    "monitor_every_seconds": (20, 3600), "news_hours": (1, 240),
}


class SettingsError(ValueError):
    pass


def _hhmm(v, key):
    try:
        h, m = str(v).split(":")
        if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError
        return "%02d:%02d" % (int(h), int(m))
    except ValueError:
        raise SettingsError("%s must be a time like 09:45" % key)


def _tickers(v, key):
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    if not isinstance(v, list):
        raise SettingsError("%s must be a list of tickers" % key)
    out = []
    for t in v:
        t = str(t).strip().upper()
        if not t:
            continue
        if not (len(t) <= 7 and t.replace(".", "").isalpha()):
            raise SettingsError("%s: %r is not a ticker" % (key, t))
        if t not in out:
            out.append(t)
    return out


def validate(raw):
    """Returns a full, clean settings dict or raises SettingsError. Unknown keys are refused."""
    unknown = sorted(set(raw) - set(DEFAULTS))
    if unknown:
        raise SettingsError("unknown setting: %s" % ", ".join(unknown))
    s = dict(DEFAULTS)
    s.update(raw)
    for k, (lo, hi) in _RANGES.items():
        try:
            v = float(s[k])
        except (TypeError, ValueError):
            raise SettingsError("%s must be a number" % k)
        if isinstance(s[k], bool) or math.isnan(v) or not (lo <= v <= hi):
            raise SettingsError("%s must be between %g and %g" % (k, lo, hi))
        s[k] = int(v) if isinstance(DEFAULTS[k], int) else v
    if s["mode"] not in ("paper", "live"):
        raise SettingsError("mode must be paper or live")
    if s["account_type"] not in ("cash", "margin"):
        raise SettingsError("account_type must be cash or margin")
    for k in ("no_entries_before", "no_entries_after", "flat_by"):
        s[k] = _hhmm(s[k], k)
    if not (s["no_entries_before"] < s["no_entries_after"] <= s["flat_by"]):
        raise SettingsError("times must run no_entries_before < no_entries_after <= flat_by")
    rule = str(s["stop_rule"])
    head, _, tail = rule.partition(":")
    if rule not in ("or-mid", "or-low"):
        try:
            ok = head in ("pct", "atr") and float(tail) > 0
        except ValueError:
            ok = False
        if not ok:
            raise SettingsError("stop_rule must be or-mid, or-low, pct:X or atr:K")
    if s["max_daily_loss_pct"] < s["risk_per_trade_pct"]:
        raise SettingsError("max_daily_loss_pct cannot be under risk_per_trade_pct")
    if s["directions"] not in ("long", "short", "both"):
        raise SettingsError("directions must be long, short or both")
    for k in ("pdt_guard", "scan_universe", "paused", "short_approved", "auto_paper", "auto_paper_weak"):
        if not isinstance(s[k], bool):
            raise SettingsError("%s must be true or false" % k)
    s["blocked"] = _tickers(s["blocked"], "blocked")
    s["watchlist"] = _tickers(s["watchlist"], "watchlist")
    if not isinstance(s["congress_members"], list):
        raise SettingsError("congress_members must be a list of last names")
    s["congress_members"] = [str(m).strip().lower() for m in s["congress_members"] if str(m).strip()]
    s["sec_user_agent"] = str(s["sec_user_agent"]).strip()
    s["ntfy_topic"] = str(s["ntfy_topic"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{0,64}", s["ntfy_topic"]):
        raise SettingsError("ntfy_topic may only use letters, digits, - and _, at most 64")
    s["ntfy_server"] = str(s["ntfy_server"]).strip()
    if not re.fullmatch(r"https://[^\s/]+(/\S*)?", s["ntfy_server"]):
        raise SettingsError("ntfy_server must start with https://")
    return s


def path():
    return data_dir() / "settings.json"


def load():
    p = path()
    if not p.exists():
        return validate({})
    return validate(json.loads(p.read_text()))


def save(raw):
    s = validate(raw)
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2) + "\n")
    tmp.replace(path())
    return s


def update(changes):
    cur = load()
    cur.update(changes)
    return save(cur)


PAPER_TRADES_CAP = 50   # paper mode: no practical trades-a-day cap, so auto paper can learn; loss and cash limits still apply


def trades_cap(s):
    """Trades a day the desk allows: your setting in live mode, effectively none in paper mode."""
    return PAPER_TRADES_CAP if s.get("mode") == "paper" else s["max_trades_per_day"]


# Paper mode trades boldly so the log shows what bigger bets would do. Live keeps your settings.
PAPER_BOLD = {"risk_per_trade_pct": 5.0, "max_daily_loss_pct": 20.0, "max_weekly_loss_pct": 0.0,
              "max_drawdown_pct": 50.0, "cash_buffer_pct": 0.0, "max_position_pct": 100.0}


PAPER_LEVERAGE = 4.0    # paper mode buys with 4x the account, like a margin account's day-trading power


def leverage(s):
    return PAPER_LEVERAGE if s.get("mode") == "paper" else 1.0


def risk(s):
    """The risk settings in force: PAPER_BOLD in paper mode, your own in live mode."""
    return dict(s, **PAPER_BOLD) if s.get("mode") == "paper" else s


def limits(s, equity):
    """The dollar limits at this account size."""
    s = risk(s)
    eq = max(0.0, float(equity))
    return {
        "equity": round(eq, 2),
        "max_loss_per_trade": round(eq * s["risk_per_trade_pct"] / 100, 2),
        "max_daily_loss": round(eq * s["max_daily_loss_pct"] / 100, 2),
        "cash_buffer": round(eq * s["cash_buffer_pct"] / 100, 2),
        "max_position": round(eq * s["max_position_pct"] / 100 * leverage(s), 2),
        "trades_cap": trades_cap(s),
    }


def skills_config(s, equity):
    """The trader/config.json the day-trader-skill tools read, scaled to the account."""
    s = risk(s)
    lim = limits(s, equity)
    cfg = {
        "budget": lim["equity"],
        "cash_buffer_pct": s["cash_buffer_pct"],
        "max_position_pct": s["max_position_pct"],
        "max_order_usd": lim["max_position"],
        "min_order_usd": 5,
        "max_loss_per_trade_usd": lim["max_loss_per_trade"],
        "max_daily_loss_usd": lim["max_daily_loss"],
        "max_trades_per_day": trades_cap(s),
        "max_orders_per_day": max(10, trades_cap(s) * 3),
        "min_reward_risk": s["min_reward_risk"],
        "require_stop": True,
        "no_entries_before": s["no_entries_before"],
        "no_entries_after": s["no_entries_after"],
        "flat_by": s["flat_by"],
        "fractional": False,
        "broker": "your broker (you place it by hand)",
        "paper": False,
        "blocked": s["blocked"],
        "allow_options": False,
        "allow_margin": False,
        "allow_short": False,
        "pdt_guard": s["pdt_guard"],
    }
    if s["sec_user_agent"]:
        cfg["sec_user_agent"] = s["sec_user_agent"]
    return cfg

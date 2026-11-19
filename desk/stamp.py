"""A stamp on every signal: which desk, which copy of the skills and which
rules produced it. Without it a later review cannot tell which rules made
which trades, so no rule change can be judged.

The rules hash covers only settings that shape a signal or its size. Display
settings, lists of stocks and account links are left out, so adding a stock
to the watchlist does not start a new rule set.
"""
import hashlib
import json

from . import __version__
from . import settings as S
from .paths import ROOT

RULE_KEYS = (
    "account_type", "risk_per_trade_pct", "max_daily_loss_pct", "max_trades_per_day",
    "cash_buffer_pct", "max_position_pct", "min_reward_risk", "target_r", "stop_rule",
    "chase_r", "signal_valid_minutes", "or_minutes", "min_price", "min_stop_pct",
    "min_volume_x", "no_entries_before", "no_entries_after", "flat_by",
    "min_edge_points", "replays", "pdt_guard",
    "max_weekly_loss_pct", "max_drawdown_pct", "max_losing_streak",
    "directions", "short_approved",          # turning shorts on starts a new rule set (docs/SHORTING.md)
)


def rules(st):
    """The rules in force, so paper mode's bold limits, leverage and trade cap show in the review."""
    eff = S.risk(st)
    r = {k: eff[k] for k in RULE_KEYS if k in eff}
    if "mode" in st:
        r.update(max_trades_per_day=S.trades_cap(st), leverage=S.leverage(st))
    r.update({k: v for k, v in S.screen(st).items() if v})     # only when on, so old rule sets keep their code
    if st.get("auto_paper_weak") and st.get("mode") == "paper":
        r["auto_paper_weak"] = True
    if st.get("analyst") and (st.get("plan_filter") == "on" or (st.get("plan_filter") == "paper" and st.get("mode") == "paper")):
        r["plan_filter"] = True                              # the game plan holds signals back: a new rule set
    return r


def rules_hash(st):
    text = json.dumps(rules(st), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def skills_commit():
    try:
        return (ROOT / "vendor" / "PINNED_COMMIT").read_text().strip()[:7]
    except OSError:
        return "unknown"


def make(st, journal=None, now=None):
    """The stamp, and (when a journal is given) a note of what this rule set is,
    kept once per hash so the review can say what 'a1b2c3d4' meant."""
    h = rules_hash(st)
    if journal is not None:
        known = journal.get("rulesets", {})
        if h not in known:
            known[h] = {"first_seen": now, "rules": rules(st)}
            journal.put("rulesets", known)
    return {"desk": __version__, "skills": skills_commit(), "rules": h}

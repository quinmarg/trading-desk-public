"""Phone alerts through ntfy (https://ntfy.sh): one push per ready signal.

Off until you set an ntfy topic in Settings. The demo never pushes. A push
that fails is logged and dropped: it never breaks or slows a scan. Anyone
who knows the topic name on a public server can read the alerts.
"""
import json
import logging
import threading
import urllib.request

from .exports import chart_url
from .paths import account_name

DASHBOARD = "http://127.0.0.1:8787"
log = logging.getLogger(__name__)

SAMPLE = {"symbol": "TEST", "qty": 1, "limit": 10.00, "stop": 9.80, "target": 10.40, "valid_until": "10:25",
          "reward_risk": 2.0, "max_loss": 0.20, "odds": {"edge_points": 3.0},
          "warnings": ["This is a test alert from your Trading Desk. It is not a signal."],
          "news": [{"title": "Test headline", "source": "Trading Desk", "link": ""}]}


def message(sig, mode):
    """The ntfy JSON body for one signal (without the topic)."""
    news = [n for n in (sig.get("news") or []) if n.get("title")][:3]
    short = sig.get("side") == "short"
    lines = ["%s %d at %.2f or %s. Stop %.2f. Target %.2f. Good until %s."
             % ("Sell short" if short else "Buy", sig["qty"], sig["limit"], "higher" if short else "lower",
                sig["stop"], sig["target"], sig["valid_until"])]
    if short and sig.get("paper_only"):
        lines.append("Practice only: this account cannot really short.")
    lines.append("Live: place it at your broker by hand." if mode == "live" else
                 "Paper: practice account only, no real money.")
    extra = []
    if sig.get("reward_risk") is not None:
        extra.append("Reward:risk %s." % sig["reward_risk"])
    if sig.get("max_loss") is not None:
        extra.append("Max loss $%.2f." % sig["max_loss"])
    ep = (sig.get("odds") or {}).get("edge_points")
    if ep is not None:
        extra.append("Time Machine edge %+.1f points." % ep)
    if extra:
        lines.append(" ".join(extra))
    if sig.get("warnings"):
        lines.append("Note: %s" % sig["warnings"][0])
    for n in news:
        lines.append("• %s (%s)" % (n["title"], n.get("source") or "news"))
        if n.get("link"):
            lines.append(n["link"])
    links = [n["link"] for n in news if n.get("link")]
    actions = [{"action": "view", "label": "Article", "url": u} for u in links[:1]]
    actions.append({"action": "view", "label": "Chart", "url": chart_url(sig["symbol"])})
    actions.append({"action": "view", "label": "Desk", "url": DASHBOARD})
    tag = ("LIVE" if mode == "live" else "PAPER") + (" " + account_name() if account_name() else "")
    return {"title": "[%s] %s %s %s %.2f" % (tag, "SHORT" if short else "BUY",
                                              sig["symbol"], "≥" if short else "≤", sig["limit"]),
            "message": "\n".join(lines), "click": DASHBOARD,
            "actions": actions, "tags": ["chart_with_downwards_trend" if short else "chart_with_upwards_trend"],
            "priority": 4}


def post(st, body):
    """Sends one push now. Raises on any failure."""
    data = json.dumps(dict(body, topic=st["ntfy_topic"])).encode()
    req = urllib.request.Request(st["ntfy_server"], data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def _post_quietly(st, body):
    try:
        post(st, body)
    except Exception as e:                       # a lost push must never reach the scan
        log.warning("ntfy alert not sent: %s", e)


def send_signal(sig, st, mode, demo):
    """Pushes one ready signal in the background. Never raises. Returns the thread, or None if nothing is sent."""
    try:
        if demo or not st.get("ntfy_topic"):
            return None
        t = threading.Thread(target=_post_quietly, args=(dict(st), message(sig, mode)), daemon=True)
        t.start()
        return t
    except Exception as e:
        log.warning("ntfy alert not sent: %s", e)
        return None


def catalyst_message(row):
    """The ntfy body for one big new catalyst. It is a reason to look, not a signal."""
    lines = [row["reason"], row.get("status") or ""]
    if row.get("on_list"):
        lines.append("On today's scan list: the desk is watching it for a breakout.")
    lines.append("Not a signal. A trade still needs its opening-range breakout.")
    if row.get("link"):
        lines.append(row["link"])
    actions = ([{"action": "view", "label": "Source", "url": row["link"]}] if row.get("link") else []) + \
        [{"action": "view", "label": "Chart", "url": chart_url(row["symbol"])}, {"action": "view", "label": "Desk", "url": DASHBOARD}]
    return {"title": "[CATALYST] %s %d/100" % (row["symbol"], row["score"]), "message": "\n".join(l for l in lines if l),
            "click": DASHBOARD, "actions": actions, "tags": ["newspaper"], "priority": 3}


def send_catalyst(row, st):
    """Pushes one catalyst in the background, like send_signal. Never raises. The caller keeps the demo out."""
    try:
        if not st.get("ntfy_topic"):
            return None
        t = threading.Thread(target=_post_quietly, args=(dict(st), catalyst_message(row)), daemon=True)
        t.start()
        return t
    except Exception as e:
        log.warning("ntfy alert not sent: %s", e)
        return None


def send_body(body, st):
    """Pushes any prepared body (the game plan, desk/analyst.py) in the background. Never raises."""
    try:
        if not st.get("ntfy_topic"):
            return None
        t = threading.Thread(target=_post_quietly, args=(dict(st), dict(body, click=DASHBOARD)), daemon=True)
        t.start()
        return t
    except Exception as e:
        log.warning("ntfy alert not sent: %s", e)
        return None


def send_test(st, demo):
    """The Settings button: one sample alert, sent now, so you can check your phone. Raises ValueError with a reason."""
    if demo:
        raise ValueError("The demo never sends phone alerts. Run the desk without --demo to test them.")
    if not st.get("ntfy_topic"):
        raise ValueError("Set an ntfy topic in Settings and save it first.")
    try:
        post(st, message(SAMPLE, st["mode"]))
    except Exception as e:
        raise ValueError("Could not reach %s: %s" % (st["ntfy_server"], e))

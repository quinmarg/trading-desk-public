"""The Graph tab: how much each record has made or lost, trade by trade and day by day.

Reads closed trades only, from this desk's journal and from every extra paper
account (python3 -m desk --account NAME). Other accounts' journals are opened
read-only, so a graph never writes to a desk that is running elsewhere.
The two model accounts (desk/modelacct.py) hold for weeks, so closed trades
would hide most of their story: their line is the account's value each day
less its starting cash (made or lost, open positions marked at the close).
"""
import sqlite3
from pathlib import Path

from . import modelacct, paths
from .auto import AUTO


def _closed(db_path):
    """Closed trades of one journal file, oldest exit first. [] when the file does not exist yet."""
    p = Path(db_path)
    if not p.exists():
        return []
    db = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT symbol, exit_at, pnl, note FROM trades WHERE status='closed' AND pnl IS NOT NULL "
                          "ORDER BY exit_at, id").fetchall()
    except sqlite3.OperationalError:            # a journal made before the trades table: nothing closed
        rows = []
    finally:
        db.close()
    return [dict(r) for r in rows]


def curve(trades):
    """Running totals: all trades, the desk's own (auto paper) and yours. One point per closed trade."""
    tot = bot = you = 0.0
    points, days = [], {}
    wins = 0
    for t in trades:
        pnl = float(t["pnl"])
        auto = t.get("note") == AUTO
        tot += pnl
        bot += pnl if auto else 0.0
        you += 0.0 if auto else pnl
        wins += pnl > 0
        points.append({"at": t["exit_at"], "symbol": t["symbol"], "pnl": round(pnl, 2), "who": "bot" if auto else "you",
                       "total": round(tot, 2), "bot": round(bot, 2), "you": round(you, 2)})
        d = days.setdefault((t["exit_at"] or "")[:10], {"date": (t["exit_at"] or "")[:10], "pnl": 0.0, "trades": 0})
        d["pnl"] = round(d["pnl"] + pnl, 2)
        d["trades"] += 1
    return {"points": points, "days": list(days.values()), "total": round(tot, 2), "bot": round(bot, 2),
            "you": round(you, 2), "trades": len(trades), "wins": wins}


MODELS = ("combo", "winter3x")


def model_curve(name):
    """A model account's made-or-lost line from its model.json, one point a trading day."""
    a = modelacct.load(name).get("account") or {}
    start, pts = a.get("start") or 0.0, a.get("curve") or []
    closed = modelacct.journal_trades(name)
    return {"points": [{"at": c["date"] + " 16:00", "symbol": "", "pnl": 0.0, "who": "bot",
                        "total": round(c["equity"] - start, 2), "bot": round(c["equity"] - start, 2), "you": 0.0}
                       for c in pts],
            "days": [], "total": round(pts[-1]["equity"] - start, 2) if pts else 0.0,
            "bot": round(pts[-1]["equity"] - start, 2) if pts else 0.0, "you": 0.0,
            "trades": sum(1 for t in closed if t["status"] == "closed"),
            "wins": sum(1 for t in closed if t["status"] == "closed" and (t["pnl"] or 0) > 0), "model": True}


def summary(current_journal):
    """Every paper account's curve plus this desk's own record (which may be live)."""
    me = paths.account_name() or "main"
    out = []
    for name, d in paths.account_dirs().items():
        db = Path(current_journal) if name == me else d / "journal.db"
        c = model_curve(name) if name in MODELS and name != me else curve(_closed(db))
        out.append(dict(c, name=name, current=name == me,
                        live=name == me and Path(current_journal).name != "journal.db"))
    return {"accounts": out}

"""The journal: one SQLite file with the cash ledger, the signals and the trades.

Cash. Every dollar movement is a ledger row with the date it settles. In a
cash account the money from a sale cannot buy again until it settles (the
next business day), so "settled cash" is what the desk sizes trades against.
In a margin account a sale settles for the desk's purposes at once.

Equity = all ledger money (settled or not) + open positions at cost.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from . import settings as S
from .paths import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, date TEXT NOT NULL, kind TEXT NOT NULL,
  amount REAL NOT NULL, settles_on TEXT NOT NULL, trade_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, symbol TEXT NOT NULL, setup TEXT NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
  UNIQUE(date, symbol, setup));
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY, signal_id INTEGER, date TEXT NOT NULL, symbol TEXT NOT NULL,
  qty INTEGER NOT NULL, entry_price REAL NOT NULL, entry_at TEXT NOT NULL,
  stop REAL NOT NULL, target REAL NOT NULL, flat_by TEXT, status TEXT NOT NULL,
  exit_price REAL, exit_at TEXT, exit_reason TEXT, pnl REAL, r_multiple REAL, note TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, date TEXT NOT NULL, kind TEXT NOT NULL,
  symbol TEXT, message TEXT NOT NULL, key TEXT UNIQUE, seen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, date TEXT NOT NULL, symbol TEXT NOT NULL, decision TEXT NOT NULL,
  long TEXT, short TEXT, long_signal INTEGER, short_signal INTEGER);
CREATE INDEX IF NOT EXISTS decisions_date ON decisions(date);
CREATE TABLE IF NOT EXISTS scans(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, date TEXT NOT NULL, summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outcomes(
  signal_id INTEGER PRIMARY KEY, date TEXT NOT NULL, symbol TEXT NOT NULL, status TEXT NOT NULL,
  result TEXT NOT NULL, entry REAL, exit REAL, exit_time TEXT, r REAL, note TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow(
  signal_id INTEGER NOT NULL, arm TEXT NOT NULL, date TEXT NOT NULL, symbol TEXT NOT NULL, status TEXT NOT NULL,
  result TEXT NOT NULL, limit_price REAL, entry REAL, exit REAL, r_orig REAL, at TEXT NOT NULL,
  PRIMARY KEY(signal_id, arm));
"""

# Columns added after the first release. Each is added only when it is missing and has a default,
# so an old journal keeps working and the order other migrations run in does not matter.
ADDED_COLUMNS = (
    ("trades", "side", "TEXT NOT NULL DEFAULT 'long'"),      # 'long' or 'short'
)

SIGNAL_STATUSES = ("ready", "blocked", "weak", "missed", "taken", "skipped", "expired")
EXIT_REASONS = ("target", "stop", "flat", "manual")


class JournalError(ValueError):
    pass


class Journal:
    def __init__(self, path=None):
        self.path = str(path or (data_dir() / "journal.db"))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        with self._lock:
            for table, column, spec in ADDED_COLUMNS:
                have = {r["name"] for r in self._db.execute("PRAGMA table_info(%s)" % table).fetchall()}
                if column not in have:
                    try:
                        self._db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, spec))
                    except sqlite3.OperationalError as e:      # another process added it first
                        if "duplicate column" not in str(e).lower():
                            raise

    def close(self):
        self._db.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        rows = self._all(sql, args)
        return rows[0] if rows else None

    # ---- key / value -------------------------------------------------
    def get(self, key, default=None):
        r = self._one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def put(self, key, value):
        with self._tx() as db:
            db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

    # ---- cash --------------------------------------------------------
    def seed(self, starting_balance, now):
        """Funds the account once. Later changes go through deposit / withdraw / set_balance."""
        if self.get("seeded"):
            return False
        self._ledger("deposit", float(starting_balance), now, now[:10], None, "starting balance")
        self.put("seeded", True)
        return True

    def _ledger(self, kind, amount, now, settles_on, trade_id, note):
        with self._tx() as db:
            db.execute("INSERT INTO ledger(ts,date,kind,amount,settles_on,trade_id,note) VALUES(?,?,?,?,?,?,?)",
                       (now, now[:10], kind, round(float(amount), 2), settles_on, trade_id, note))

    def deposit(self, amount, now, note=""):
        if not amount > 0:
            raise JournalError("a deposit must be more than zero")
        self._ledger("deposit", amount, now, now[:10], None, note)

    def withdraw(self, amount, now, note=""):
        if not amount > 0:
            raise JournalError("a withdrawal must be more than zero")
        if amount > self.settled_cash(now[:10]) + 1e-9:
            raise JournalError("you cannot withdraw more than your settled cash")
        self._ledger("withdraw", -amount, now, now[:10], None, note)

    def set_balance(self, cash, now, note="matched to the broker"):
        """Makes total cash equal what the broker shows (fees, interest, rounding)."""
        if cash < 0:
            raise JournalError("cash cannot be negative")
        diff = round(float(cash) - self.cash(), 2)
        if diff:
            self._ledger("adjust", diff, now, now[:10], None, note)
        return diff

    def cash(self):
        return round(self._one("SELECT COALESCE(SUM(amount),0) s FROM ledger")["s"], 2)

    def settled_cash(self, today):
        r = self._one("SELECT COALESCE(SUM(amount),0) s FROM ledger WHERE settles_on<=?", (today,))
        return round(r["s"], 2)

    def buying_power(self, today):
        """Settled cash, or in paper mode leverage x the account less what is already held (it can go below zero)."""
        lev = S.leverage(S.load())
        if lev == 1:
            return self.settled_cash(today)
        return round(max(0.0, lev * self.equity() - self.positions_cost()), 2)

    def unsettled(self, today):
        return self._all("SELECT settles_on, ROUND(SUM(amount),2) amount FROM ledger WHERE settles_on>? "
                         "GROUP BY settles_on ORDER BY settles_on", (today,))

    def positions_cost(self):
        r = self._one("SELECT COALESCE(SUM(qty*entry_price),0) s FROM trades WHERE status='open'")
        return round(r["s"], 2)

    def equity(self):
        return round(self.cash() + self.positions_cost(), 2)

    def ledger(self, limit=100):
        return self._all("SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,))

    # ---- signals -----------------------------------------------------
    def add_signal(self, date, symbol, setup, status, payload, now):
        """One signal per symbol, setup and day. Returns its id, or None if it exists."""
        if status not in SIGNAL_STATUSES:
            raise JournalError("unknown signal status %r" % status)
        try:
            with self._tx() as db:
                cur = db.execute("INSERT INTO signals(date,symbol,setup,created_at,status,payload) VALUES(?,?,?,?,?,?)",
                                 (date, symbol, setup, now, status, json.dumps(payload)))
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def _sig(self, r):
        if r:
            r["payload"] = json.loads(r["payload"])
        return r

    def signal(self, sid):
        return self._sig(self._one("SELECT * FROM signals WHERE id=?", (sid,)))

    def signals(self, date=None, statuses=None, limit=200):
        sql, args = "SELECT * FROM signals WHERE 1=1", []
        if date:
            sql += " AND date=?"
            args.append(date)
        if statuses:
            sql += " AND status IN (%s)" % ",".join("?" * len(statuses))
            args += list(statuses)
        return [self._sig(r) for r in self._all(sql + " ORDER BY id DESC LIMIT ?", args + [limit])]

    def has_signal(self, date, symbol, setup):
        return bool(self._one("SELECT 1 x FROM signals WHERE date=? AND symbol=? AND setup=?", (date, symbol, setup)))

    def set_signal_status(self, sid, status, expect=None):
        if status not in SIGNAL_STATUSES:
            raise JournalError("unknown signal status %r" % status)
        with self._tx() as db:
            if expect:
                cur = db.execute("UPDATE signals SET status=? WHERE id=? AND status IN (%s)" % ",".join("?" * len(expect)),
                                 [status, sid] + list(expect))
            else:
                cur = db.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))
            return cur.rowcount == 1

    # ---- trades ------------------------------------------------------
    def open_trade(self, symbol, qty, price, stop, target, now, signal_id=None, flat_by=None, note="",
                   side="long"):
        """Records a fill. side="short" is a sell to open: the stop sits above the fill, and the full
        value of the short is set aside in cash until it is covered (no leverage)."""
        qty = int(qty)
        if side not in ("long", "short"):
            raise JournalError("side must be long or short")
        short = side == "short"
        if qty <= 0 or price <= 0:
            raise JournalError("shares and price must be more than zero")
        if short and not stop > price:
            raise JournalError("the stop on a short must be above your fill price")
        if not short and not stop < price:
            raise JournalError("the stop must be under your fill price")
        cost = round(qty * price, 2)
        if cost > self.buying_power(now[:10]) + 1e-9:
            raise JournalError(("a short of that size needs $%.2f set aside and you have $%.2f to trade with" if short
                                else "that costs $%.2f and you have $%.2f to trade with")
                               % (cost, self.buying_power(now[:10])))
        with self._tx() as db:
            if short and db.execute("SELECT 1 FROM trades WHERE status='open' AND symbol=? AND side='long'",
                                    (symbol.upper(),)).fetchone():
                raise JournalError("you have an open long in %s: selling would close it, not open a short" % symbol.upper())
            if not short and db.execute("SELECT 1 FROM trades WHERE status='open' AND symbol=? AND side='short'",
                                        (symbol.upper(),)).fetchone():
                raise JournalError("you have an open short in %s: buying would cover it, not open a long" % symbol.upper())
            cur = db.execute("INSERT INTO trades(signal_id,date,symbol,qty,entry_price,entry_at,stop,target,flat_by,status,note,"
                             "side) VALUES(?,?,?,?,?,?,?,?,?,'open',?,?)",
                             (signal_id, now[:10], symbol.upper(), qty, price, now, stop, target, flat_by, note,
                              side))
            tid = cur.lastrowid
            db.execute("INSERT INTO ledger(ts,date,kind,amount,settles_on,trade_id,note) VALUES(?,?,?,?,?,?,?)",
                       (now, now[:10], "short" if short else "buy", -cost, now[:10], tid,
                        ("sell short %d %s at %.2f (cash set aside)" if short else "buy %d %s at %.2f")
                        % (qty, symbol.upper(), price)))
            if signal_id:
                db.execute("UPDATE signals SET status='taken' WHERE id=?", (signal_id,))
        return tid

    def close_trade(self, tid, price, reason, now, settles_on):
        """Records the exit. A short is bought to cover: P&L = (entry - cover) x shares, and the cash
        set aside comes back plus or minus that P&L."""
        if reason not in EXIT_REASONS:
            raise JournalError("exit reason must be one of %s" % ", ".join(EXIT_REASONS))
        if price <= 0:
            raise JournalError("the exit price must be more than zero")
        with self._tx() as db:
            r = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
            if not r or r["status"] != "open":
                raise JournalError("no open trade with that id")
            short = r["side"] == "short"
            sign = -1 if short else 1
            pnl = round(sign * (price - r["entry_price"]) * r["qty"], 2)
            risk = sign * (r["entry_price"] - r["stop"]) * r["qty"]
            rmult = round(pnl / risk, 2) if risk > 0 else None
            back = round(r["entry_price"] * r["qty"] + pnl, 2) if short else round(price * r["qty"], 2)
            db.execute("UPDATE trades SET status='closed', exit_price=?, exit_at=?, exit_reason=?, pnl=?, r_multiple=? WHERE id=?",
                       (price, now, reason, pnl, rmult, tid))
            db.execute("INSERT INTO ledger(ts,date,kind,amount,settles_on,trade_id,note) VALUES(?,?,?,?,?,?,?)",
                       (now, now[:10], "cover" if short else "sell", back, settles_on, tid,
                        ("buy to cover %d %s at %.2f" if short else "sell %d %s at %.2f") % (r["qty"], r["symbol"], price)))
        return pnl

    def trade(self, tid):
        return self._one("SELECT * FROM trades WHERE id=?", (tid,))

    def open_trades(self):
        return self._all("SELECT * FROM trades WHERE status='open' ORDER BY id")

    def trades(self, date=None, limit=200):
        if date:
            return self._all("SELECT * FROM trades WHERE date=? ORDER BY id DESC LIMIT ?", (date, limit))
        return self._all("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def day(self, date):
        """Today's count, realised result and the loss still at risk at the stops."""
        rows = self.trades(date)
        realised = round(sum(r["pnl"] or 0 for r in rows if r["status"] == "closed"), 2)
        at_risk = round(sum(abs(r["entry_price"] - r["stop"]) * r["qty"] for r in rows if r["status"] == "open"), 2)
        return {"trades": len(rows), "realised": realised, "open_risk": at_risk,
                "open": sum(1 for r in rows if r["status"] == "open")}

    def stats(self):
        rows = [r for r in self.trades(limit=100000) if r["status"] == "closed"]
        wins = [r for r in rows if r["pnl"] > 0]
        losses = [r for r in rows if r["pnl"] < 0]
        rs = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
        return {"closed": len(rows), "wins": len(wins), "losses": len(losses),
                "win_rate": round(100 * len(wins) / len(rows), 1) if rows else None,
                "total_pnl": round(sum(r["pnl"] for r in rows), 2),
                "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
                "best": max((r["pnl"] for r in rows), default=None),
                "worst": min((r["pnl"] for r in rows), default=None)}

    # ---- decisions: one row per stock per scan (desk/decide.py) ---------
    def add_decisions(self, rows, now):
        if not rows:
            return
        with self._tx() as db:
            db.executemany("INSERT INTO decisions(ts,date,symbol,decision,long,short,long_signal,short_signal) "
                           "VALUES(?,?,?,?,?,?,?,?)",
                           [(now, now[:10], r["symbol"], r["decision"], r["long"], r["short"],
                             r["long_signal"], r["short_signal"]) for r in rows])

    def decisions(self, date=None, limit=5000):
        if date:
            return self._all("SELECT * FROM decisions WHERE date=? ORDER BY id DESC LIMIT ?", (date, limit))
        return self._all("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))

    # ---- scans and outcomes (for the review) ----
    def add_scan(self, summary):
        with self._tx() as db:
            db.execute("INSERT INTO scans(ts,date,summary) VALUES(?,?,?)",
                       (summary["at"], summary["at"][:10], json.dumps(summary)))

    def scans(self, date=None, limit=500):
        sql, args = "SELECT * FROM scans", []
        if date:
            sql, args = sql + " WHERE date=?", [date]
        rows = self._all(sql + " ORDER BY id DESC LIMIT ?", args + [limit])
        for r in rows:
            r["summary"] = json.loads(r["summary"])
        return rows

    def outcome_gaps(self, date=None):
        """Replays that got no candles: their dates (last 30 days), or with date, that day's signal ids."""
        if date:
            return {r["signal_id"] for r in self._all("SELECT signal_id FROM outcomes WHERE result='no data' AND date=?", (date,))}
        return [r["date"] for r in self._all("SELECT DISTINCT date FROM outcomes WHERE result='no data' "
                                             "AND date >= date('now','-30 day') ORDER BY date")]

    def set_outcome(self, signal_id, date, symbol, status, o, now):
        with self._tx() as db:
            db.execute("INSERT INTO outcomes(signal_id,date,symbol,status,result,entry,exit,exit_time,r,note,at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET status=excluded.status, "
                       "result=excluded.result, entry=excluded.entry, exit=excluded.exit, exit_time=excluded.exit_time, "
                       "r=excluded.r, note=excluded.note, at=excluded.at",
                       (signal_id, date, symbol, status, o["result"], o["entry"], o["exit"], o["exit_time"], o["r"],
                        o["note"], now))

    def set_shadow(self, signal_id, date, symbol, status, arms, now):
        """The shadow entry arms of one signal (desk/outcome.shadow): logging only, for the review's A/B."""
        with self._tx() as db:
            for arm, o in arms.items():
                db.execute("INSERT OR REPLACE INTO shadow(signal_id,arm,date,symbol,status,result,limit_price,entry,exit,"
                           "r_orig,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (signal_id, arm, date, symbol, status, o["result"],
                                                                       o.get("limit"), o["entry"], o["exit"], o.get("r_orig"), now))

    def shadows(self, limit=100000):
        return self._all("SELECT * FROM shadow ORDER BY signal_id, arm LIMIT ?", (limit,))

    def outcomes(self, date=None, limit=100000):
        if date:
            return self._all("SELECT * FROM outcomes WHERE date=? ORDER BY signal_id LIMIT ?", (date, limit))
        return self._all("SELECT * FROM outcomes ORDER BY signal_id LIMIT ?", (limit,))

    # ---- events (what the dashboard rings) ---------------------------
    def add_event(self, kind, message, now, symbol=None, key=None):
        """key makes an event ring once: a second add with the same key is ignored."""
        try:
            with self._tx() as db:
                cur = db.execute("INSERT INTO events(ts,date,kind,symbol,message,key) VALUES(?,?,?,?,?,?)",
                                 (now, now[:10], kind, symbol, message, key))
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def events(self, date=None, limit=60):
        if date:
            return self._all("SELECT * FROM events WHERE date=? ORDER BY id DESC LIMIT ?", (date, limit))
        return self._all("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    def mark_seen(self, up_to_id):
        with self._tx() as db:
            db.execute("UPDATE events SET seen=1 WHERE id<=?", (up_to_id,))

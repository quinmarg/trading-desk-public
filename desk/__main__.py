"""python3 -m desk            the live desk at http://127.0.0.1:8787
python3 -m desk --demo     the same desk on saved data from 2026-10-19 (no network)
python3 -m desk --account growth --tickers "TSLA NVDA AMD"
                           an extra paper account with its own cash, journal and tickers
python3 -m desk agent      Claude picks today's scan list from the candidates and says why (--apply uses it today)
python3 -m desk combo      the combined SPY paper book: bring it up to now and print it (paper only, never an order)
python3 -m desk winter3x   the winter 3x paper book (research/beat_spy finalist), the same way
python3 -m desk migrate-models   move the old data/combo.json and data/winter3x.json books into their own
                           practice accounts (data/accounts/combo, data/accounts/winter3x); safe to run twice
"""
import argparse
import json
import os
import socket
import sys
import webbrowser

from .paths import ROOT


def print_combo(src, name="combo"):
    """Bring a paper book (combo or winter3x) up to now (read-only Yahoo GETs) and print it. Paper only."""
    import importlib
    book = importlib.import_module("desk." + name)
    now = src.now()
    try:
        if book.due(now) or not book.load().get("days"):
            book.run(now)
    except Exception as e:
        book.note_error(now, e)
        print("Could not update the book: %s" % e)
    title = {"combo": "COMBINED SPY MODEL (paper; docs/MODELS.md)",
             "winter3x": "WINTER 3X BOOK (paper; research/beat_spy/REPORT.md)"}[name]
    print("%s, as of %s New York" % (title, now))
    print("\n".join(book.lines()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m desk", description="Trading Desk: day-trading signals you place by hand at your broker. It never places a real order.")
    ap.add_argument("command", nargs="?", choices=("run", "review", "agent", "combo", "winter3x", "migrate-models"), default="run",
                    help="run (default) starts the desk; review prints the record and exits; "
                         "agent has Claude pick today's scan list and exits; combo / winter3x update and print a paper book")
    ap.add_argument("--apply", action="store_true", help="with agent: make the picks today's scan list")
    ap.add_argument("--demo", action="store_true", help="run on saved data from Monday 2026-10-19, no network")
    ap.add_argument("--demo-now", default="2026-10-19 10:15", help='the demo clock, New York time')
    ap.add_argument("--port", type=int, default=None, help="8787 for the main desk; the first free from 8791 for an account")
    ap.add_argument("--account", help="an extra paper account (practice only), kept in data/accounts/NAME")
    ap.add_argument("--tickers", help='with --account: the tickers it trades, like "TSLA NVDA AMD" (no daily pick)')
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)     # data/desk.log gets each line as it happens
    except (AttributeError, ValueError):
        pass
    if a.demo and not os.environ.get("DESK_DATA"):
        os.environ["DESK_DATA"] = str(ROOT / "data-demo")   # demo trades never touch your real journal
    if a.account is not None or a.tickers:
        err = open_account(a)
        if err:
            ap.error(err)
    if a.port is None:
        a.port = free_port(8791) if a.account else 8787

    from .engine import Desk
    from .journal import Journal
    from .scheduler import Scheduler
    from .server import serve
    from .source import Demo, Live

    from . import mode as M
    from . import settings as S

    if a.command == "review":
        return print_review(Demo(a.demo_now) if a.demo else Live())
    if a.command in ("combo", "winter3x"):
        return print_combo(Live(), a.command)
    if a.command == "migrate-models":
        from . import modelacct
        for name in ("combo", "winter3x"):
            r = modelacct.migrate(name)
            print("%s: %s" % (name, "moved %d recorded days into %s, starting cash $%.2f; the old file is kept as %s.json"
                              ".migrated" % (r["days"], modelacct.folder(name), r["start_equity"], name) if r
                              else "nothing to move (already its own account, or no old book)"))
        return 0
    if a.command == "agent":
        if a.demo:
            ap.error("the agent needs today's market; drop --demo")
        return run_agent(Desk(Journal(M.journal_path(S.load()["mode"])), Live()), a.apply)

    which = S.load()["mode"]
    desk = Desk(Journal(M.journal_path(which)), Demo(a.demo_now) if a.demo else Live())
    sched = Scheduler(desk)
    httpd = serve(desk, sched, a.port)
    sched.start()
    url = "http://127.0.0.1:%d/" % a.port
    print("Trading Desk %s at %s   (Ctrl+C to stop)" % ("DEMO (saved data)" if a.demo else "on today's market", url))
    print("Record: %s." % ("PAPER (practice)" if which == "paper" else "LIVE (real money)")
          + (" Account: %s." % a.account if a.account else ""))
    st = S.load()
    if st["auto_paper"] and which == "paper":
        print("Auto paper is ON: the desk trades ready signals itself in the practice account (no real money).")
    print("The desk never places real orders: you place each one at your broker yourself.")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        sched.stop()
        httpd.server_close()
    return 0


def run_agent(desk, apply):
    """Prints Claude's picks with reasons; makes them today's scan list only with --apply."""
    from . import settings as S
    print("Researching today's list (daily ranges, screeners, headlines, then Claude)...")
    st, now = S.load(), desk.src.now()
    r = desk.pick_list(dict(st, watchlist_agent=True), now, save=apply)
    print("Picked by %s from %d stocks." % (r["by"], r["looked_at"]))
    if r.get("summary"):
        print("\n" + r["summary"])
    print()
    for p in r["symbols"]:
        print("  %-6s %s" % (p["symbol"], p["why"]))
    for e in r["errors"]:
        print("  note: %s" % e)
    if r["error"]:
        print("\n" + r["error"])
        return 1
    print("\n%s" % ("Today's scan list is set: %d stocks." % len(r["symbols"]) if apply else
                     "Not applied. Run again with --apply to make this today's scan list."))
    return 0


def open_account(a):
    """Points the desk at data/accounts/NAME and makes the account on first use: a copy of the
    main desk's settings, always paper. Returns an error message or None."""
    from .paths import ACCOUNT, data_dir
    if a.demo:
        return "--account does not work with --demo"
    if a.account is None:
        return "--tickers needs --account NAME"
    if not ACCOUNT.fullmatch(a.account) or a.account in ("main", "combo", "winter3x"):
        return "account names are lowercase letters, digits and -, up to 24, and not 'main', 'combo' or 'winter3x' " \
               "(the two model accounts)"
    home = data_dir()
    os.environ["DESK_DATA"] = str(home / "accounts" / a.account)
    os.environ["DESK_ACCOUNT"] = a.account
    from . import settings as S
    new = not S.path().exists()
    if new or a.tickers:
        main = home / "settings.json"
        st = json.loads(main.read_text()) if new and main.exists() else ({} if new else S.load())
        st["mode"] = "paper"
        if new:     # one hourly Claude look and one set of catalyst pushes is enough: the main desk already sends them
            st.update(analyst=False, catalyst_alerts=False)
        if a.tickers:
            t = a.tickers.replace(",", " ").split()
            st.update(core_watchlist=t, watchlist=t, auto_list="off")
        try:
            S.save(st)
        except S.SettingsError as e:
            return str(e)
        print("%s paper account %s in %s." % ("Made" if new else "Updated", a.account, data_dir()))
    return None


def free_port(start):
    """The first port from start that nothing on this computer listens on."""
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def print_review(source):
    """python3 -m desk review: both records as text, for "check the log and make changes". Starts nothing."""
    from . import mode as M
    from .engine import Desk
    from .journal import Journal

    shown = 0
    for which in M.MODES:
        path = M.journal_path(which)
        if not path.exists():
            continue
        j = Journal(path)
        try:
            desk = Desk.__new__(Desk)              # a reader only: no seeding, no scheduler, no server
            desk.j, desk.src = j, source
            print(desk.review(j, which)["text"])
            print("\n" + "=" * 72 + "\n")
            shown += 1
        finally:
            j.close()
    if not shown:
        print("No journal yet. Start the desk once (python3 -m desk) and record a trade first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

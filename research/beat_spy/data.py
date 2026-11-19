"""Free Yahoo daily bars, cached. Read-only GETs; the cache folder is git-ignored and never refreshed on purpose.

bars(sym) -> list of {date, o, c, adj, div} oldest first. `adj` is Yahoo's dividend- and split-adjusted close
(price indices have adj == c). `o` is None where the feed has no real open (many index feeds copy the close
into the open, or the previous close); callers then fill at the next close instead.
Run: python3 research/beat_spy/data.py   (fetches every symbol below once)
"""
import datetime
import json
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

CACHE = Path(__file__).resolve().parent / "cache"
NY = ZoneInfo("America/New_York")

US = ["SPY", "^GSPC", "^IRX", "^TNX", "SSO", "UPRO", "VFITX"]
# Indices the friend's lab never used (its rounds 1-5 used DAX N225 FTSE HSI TSX ASX CAC STOXX50 BVSP KS11 MXX
# NSEI SSMI AEX IBEX TWII STI NZ50 KLSE JKSE TA125 BFX ATX OMX and ^GSPC 1929-99). Chosen by availability only.
# Fixed before any test ran; tried and dropped for want of daily history on Yahoo: ^OSEAX ^IPSA PSEI.PS ^SET.BK
# ^MERV WIG20.WA ^CASE30. ^BSESN is India, whose Nifty the friend did use (flagged in the report).
FOREIGN = ["^BSESN", "000001.SS", "FTSEMIB.MI", "XU100.IS", "^ISEQ", "PSI20.LS", "^OMXC25", "^OMXH25", "^J203.JO"]
OTHER_US = ["^RUT", "^IXIC"]           # unused US indices: a weaker check, they move with SPY
SHILLER = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"


def _get(sym):
    q = "/v8/finance/chart/%s?period1=-1325635200&period2=%d&interval=1d&events=div%%2Csplit" % (
        urllib.request.quote(sym), int(time.time()))
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        for wait in (0, 5, 20):
            time.sleep(wait)
            try:
                req = urllib.request.Request("https://" + host + q, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001 - try again, then the other host
                last = e
    raise RuntimeError("Yahoo did not answer for %s: %s" % (sym, last))


def raw(sym, fetch=True):
    f = CACHE / (sym.replace("^", "_") + ".json")
    if f.exists():
        return json.loads(f.read_text())
    if not fetch:
        raise FileNotFoundError(f)
    doc = _get(sym)
    CACHE.mkdir(exist_ok=True)
    f.write_text(json.dumps(doc))
    time.sleep(1)
    return doc


def bars(sym, fetch=True):
    res = raw(sym, fetch)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    divs = {}
    for e in ((res.get("events") or {}).get("dividends") or {}).values():
        d = datetime.datetime.fromtimestamp(int(e["date"]), NY).strftime("%Y-%m-%d")
        divs[d] = divs.get(d, 0.0) + float(e["amount"])
    out, prev = [], None
    for i, t in enumerate(res["timestamp"]):
        c, a, o = q["close"][i], adj[i], q["open"][i]
        if c is None or a is None or c <= 0 or a <= 0:
            continue
        d = datetime.datetime.fromtimestamp(int(t), NY).strftime("%Y-%m-%d")
        if out and d == out[-1]["date"]:
            out.pop()
        # no real open: missing, zero, a copy of the close, or a copy of the previous close
        real = o is not None and o > 0 and o != c and (prev is None or o != prev)
        out.append({"date": d, "o": float(o) if real else None, "c": float(c), "adj": float(a),
                    "div": divs.get(d, 0.0)})
        prev = c
    return out


def shiller_yield(fetch=True):
    """Shiller's monthly S&P 500 data -> {"YYYY-MM": trailing dividend yield a year}. Used only before SPY (1993)."""
    f = CACHE / "shiller.csv"
    if not f.exists():
        if not fetch:
            raise FileNotFoundError(f)
        req = urllib.request.Request(SHILLER, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            CACHE.mkdir(exist_ok=True)
            f.write_bytes(r.read())
    out = {}
    for line in f.read_text().splitlines()[1:]:
        d, px, div = line.split(",")[:3]
        if px and div and float(px) > 0:
            out[d[:7]] = float(div) / float(px)
    return out


if __name__ == "__main__":
    shiller_yield()
    for s in (sys.argv[1:] or US + FOREIGN + OTHER_US):
        try:
            b = bars(s)
            opens = sum(1 for x in b if x["o"] is not None) / max(1, len(b))
            print("%-11s %s to %s  %5d days  real opens %3.0f%%" % (s, b[0]["date"], b[-1]["date"], len(b), 100 * opens))
        except Exception as e:  # noqa: BLE001
            print("%-11s FAILED %s" % (s, e))

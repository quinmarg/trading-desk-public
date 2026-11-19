"""Where things live. DESK_DATA moves the data folder (tests use a temp dir)."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "day-trader-skill"
STATIC = Path(__file__).resolve().parent / "static"
FIXTURES = VENDOR / "tests" / "fixtures"


def data_dir():
    d = Path(os.environ.get("DESK_DATA") or (ROOT / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


ACCOUNT = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")


def account_name():
    """'' for the main desk; a name for an extra paper account (python3 -m desk --account NAME)."""
    return os.environ.get("DESK_ACCOUNT", "")


def home_dir():
    """The main desk's data folder. Extra paper accounts live in its accounts/<name>/."""
    return data_dir().parent.parent if account_name() else data_dir()


def account_dirs():
    """{"main": folder, name: folder, ...} for the main desk and every extra paper account."""
    home = home_dir()
    out = {"main": home}
    if (home / "accounts").is_dir():
        out.update({d.name: d for d in sorted((home / "accounts").iterdir()) if d.is_dir() and ACCOUNT.fullmatch(d.name)})
    return out

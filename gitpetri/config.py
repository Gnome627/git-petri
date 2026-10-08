"""Accounts and settings in ~/.config/git-petri/config.json (mode 0600)."""

import json
import os
import signal
import subprocess
from pathlib import Path

DEFAULTS = {
    "interval": 45,      # seconds between polls while something is changing
    "max_interval": 300, # polls stretch towards this while nothing changes
    "fps": 12,
    "max_repos": 60,     # repositories fetched per account
    "active_repos": 12,  # of those, how many get branches / PRs / CI
    "active_days": 30,   # only repositories pushed this recently get branches / PRs / CI
    "stale_days": 7,     # repositories quiet for longer are left off the dish (d shows them)
    "branches": 6,
    "commits": 6,
    "pulls": 6,
    "runs": 40,
}


def path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "git-petri" / "config.json"


def load():
    try:
        cfg = json.loads(path().read_text())
    except FileNotFoundError:
        cfg = {}
    cfg.setdefault("accounts", [])
    cfg["settings"] = {**DEFAULTS, **cfg.get("settings", {})}
    return cfg


def save(cfg):
    p = path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = {k: v for k, v in cfg["settings"].items() if DEFAULTS.get(k) != v}
    body = json.dumps({"accounts": cfg["accounts"], "settings": settings}, indent=2) + "\n"
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.replace(tmp, p)


UNITS = {"h": 1 / 24, "d": 1.0, "w": 7.0, "m": 30.0}


def parse_period(text):
    """'3d', '12h', '2w', '1m' or a bare number of days -> days."""
    text = text.strip().lower()
    unit = UNITS.get(text[-1:])
    days = float(text[:-1]) * unit if unit else float(text)
    if not 0 < days < 3660:
        raise ValueError(text)
    return days


def format_period(days):
    if days < 1:
        return f"{days * 24:g}h"
    return f"{days / 7:g}w" if days >= 14 and days % 7 == 0 else f"{days:g}d"


def mtime():
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def _runtime():
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")


def register():
    """Mark this process as a running dish; returns the marker to unlink on exit."""
    marker = _runtime() / f"git-petri-{os.getpid()}.pid"
    marker.touch()
    return marker


def nudge():
    """Wake running dishes so they re-read the config now instead of at their next poll."""
    woken = 0
    for marker in _runtime().glob("git-petri-*.pid"):
        try:
            pid = int(marker.stem.rsplit("-", 1)[1])
            # The pid may have been recycled since a crash: only signal an actual git-petri.
            if b"petri" not in Path(f"/proc/{pid}/cmdline").read_bytes():
                raise ProcessLookupError
            os.kill(pid, signal.SIGUSR1)
            woken += 1
        except (OSError, ValueError):
            marker.unlink(missing_ok=True)
    return woken


def token(account):
    """An account stores either the token itself or a command that prints it."""
    cmd = account.get("token_cmd")
    if not cmd:
        return account.get("token", "")
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"token_cmd failed for {account['name']}: {cmd}")
    return out.stdout.strip()

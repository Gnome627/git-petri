"""Accounts and settings in ~/.config/git-petri/config.json (mode 0600)."""

import json
import os
import subprocess
from pathlib import Path

DEFAULTS = {
    "interval": 45,      # seconds between polls
    "fps": 12,
    "max_repos": 60,     # repositories fetched per account
    "active_repos": 12,  # of those, how many get branches / PRs / CI
    "active_days": 30,
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


def token(account):
    """An account stores either the token itself or a command that prints it."""
    cmd = account.get("token_cmd")
    if not cmd:
        return account.get("token", "")
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"token_cmd failed for {account['name']}: {cmd}")
    return out.stdout.strip()

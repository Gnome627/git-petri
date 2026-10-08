"""First-run and `add`: ask for a provider and a read-only token."""

import getpass
import shutil
import subprocess

from . import config
from .http import ApiError
from .providers import KINDS, make

MENU = (("github", "GitHub"), ("gitlab", "GitLab"), ("gitea", "Gitea / Forgejo"))
ACCENT, DIM, RED, GREEN, OFF = "\x1b[1;33m", "\x1b[2m", "\x1b[31m", "\x1b[32m", "\x1b[0m"


def _gh_logged_in():
    if not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "token"], capture_output=True).returncode == 0


def add_account(cfg):
    """Prompt for one account, verify the token, store it. Returns the account or None."""
    print(f"\n  {ACCENT}◉ git-petri{OFF}  connect a forge\n")
    for i, (_, title) in enumerate(MENU, 1):
        print(f"    {i}) {title}")
    choice = input("\n  provider [1]: ").strip() or "1"
    if choice not in ("1", "2", "3"):
        print(f"  {RED}unknown provider{OFF}")
        return None
    kind = MENU[int(choice) - 1][0]
    module = KINDS[kind][1]

    default = module.DEFAULT_URL
    url = input(f"  url [{default}]: " if default else "  instance url: ").strip() or default
    if not url:
        print(f"  {RED}an instance url is required{OFF}")
        return None
    if "://" not in url:
        url = "https://" + url
    if url.startswith("http://"):
        print(f"  {RED}warning:{OFF} plain http sends the token unencrypted")

    account = {"kind": kind, "url": url}
    if kind == "github" and url == default and _gh_logged_in():
        if input("  reuse the token from `gh auth token`? [Y/n]: ").strip().lower() in ("", "y"):
            account["token_cmd"] = "gh auth token"  # read on start, never copied to disk
    if "token_cmd" not in account:
        print(f"  {DIM}read-only is enough — {module.SCOPES}{OFF}")
        account["token"] = getpass.getpass("  token (hidden): ").strip()
        if not account["token"]:
            print(f"  {RED}no token given{OFF}")
            return None

    try:
        login = make(kind, url, config.token(account), cfg["settings"]).whoami()
    except (ApiError, RuntimeError, KeyError) as e:
        print(f"  {RED}✗ could not sign in: {e}{OFF}")
        return None
    taken = {a["name"] for a in cfg["accounts"]}
    name = base = kind
    n = 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    account["name"] = name
    cfg["accounts"].append(account)
    config.save(cfg)
    print(f"  {GREEN}✓{OFF} signed in as {login} — saved as “{name}” in {config.path()}")
    return account


def first_run(cfg):
    while not cfg["accounts"]:
        if add_account(cfg) is None and input("  try again? [Y/n]: ").strip().lower() == "n":
            return False
    while input("  add another forge? [y/N]: ").strip().lower() == "y":
        add_account(cfg)
    return True

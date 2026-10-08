"""git-petri — your forges as cultures on a petri dish."""

import argparse
import sys

from . import app, config, wizard
from .providers import Demo, make


def main(argv=None):
    ap = argparse.ArgumentParser(prog="git-petri", description=__doc__)
    ap.add_argument("command", nargs="?", default="run",
                    choices=("run", "add", "accounts", "remove", "activity"))
    ap.add_argument("name", nargs="?", metavar="value",
                    help="account name for `remove`; period for `activity` (3d, 12h, 2w, default)")
    ap.add_argument("--demo", action="store_true", help="synthetic data, no network or token")
    ap.add_argument("--interval", type=int, help="seconds between polls")
    ap.add_argument("--fps", type=int)
    ap.add_argument("--snapshot", type=float, metavar="SECONDS",
                    help="simulate the demo headlessly and print one frame")
    ap.add_argument("--size", default="120x40", help="frame size for --snapshot")
    ap.add_argument("--colour", action="store_true", help="keep colours in --snapshot")
    args = ap.parse_args(argv)

    cfg = config.load()
    settings = cfg["settings"]
    for key in ("interval", "fps"):
        if getattr(args, key):
            settings[key] = getattr(args, key)

    if args.snapshot is not None:
        w, h = (int(v) for v in args.size.lower().split("x"))
        app.snapshot(Demo(), args.snapshot, (w, h), args.colour)
        return 0
    if args.command == "accounts":
        for a in cfg["accounts"]:
            source = "token_cmd" if a.get("token_cmd") else "token"
            print(f"{a['name']:<12} {a['kind']:<7} {a['url']}  ({source})")
        if not cfg["accounts"]:
            print("no accounts — run `git-petri add`")
        return 0
    if args.command == "remove":
        keep = [a for a in cfg["accounts"] if a["name"] != args.name]
        if len(keep) == len(cfg["accounts"]):
            print(f"no account named {args.name!r}", file=sys.stderr)
            return 1
        cfg["accounts"] = keep
        config.save(cfg)
        return 0
    if args.command == "activity":
        if args.name:
            try:
                days = (config.DEFAULTS["stale_days"] if args.name == "default"
                        else config.parse_period(args.name))
            except ValueError:
                print(f"not a period: {args.name!r} — try 3d, 12h, 2w or default", file=sys.stderr)
                return 1
            settings["stale_days"] = days
            config.save(cfg)
        note = " — running dish updated" if args.name and config.nudge() else ""
        print(f"repositories pushed within {config.format_period(settings['stale_days'])} "
              f"are on the dish{note}")
        return 0
    if args.command == "add":
        return 0 if wizard.add_account(cfg) else 1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("git-petri needs a terminal", file=sys.stderr)
        return 1
    if args.demo:
        providers = [("demo", Demo())]
        settings["interval"] = args.interval or 3
    else:
        if not cfg["accounts"] and not wizard.first_run(cfg):
            return 1
        providers = []
        for a in cfg["accounts"]:
            try:
                providers.append((a["name"], make(a["kind"], a["url"], config.token(a), settings)))
            except Exception as e:
                print(f"{a['name']}: {e}", file=sys.stderr)
        if not providers:
            return 1
    try:
        app.run(providers, settings)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

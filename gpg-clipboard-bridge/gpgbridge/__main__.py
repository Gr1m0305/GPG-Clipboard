"""CLI: python -m gpgbridge {supervisor|bridge|diagnose|version}"""
from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gpgbridge", description="Google Play Games (PC) -> Windows clipboard helper")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("supervisor", help="tray app + watchdog (what the Scheduled Task runs)")
    b = sub.add_parser("bridge", help="run the clipboard bridge (console mode for debugging)")
    b.add_argument("--ipc", action="store_true", help="JSON events on stdout (used by the supervisor)")
    sub.add_parser("diagnose", help="print a report of Play Games / clipboard-sharing state")
    sub.add_parser("version")
    args = ap.parse_args(argv)

    if args.cmd == "supervisor":
        from .supervisor import main as run
        return run()
    if args.cmd == "bridge":
        from .bridge import main as run
        return run(ipc=args.ipc)
    if args.cmd == "diagnose":
        from .diagnose import main as run
        return run()
    if args.cmd == "version":
        print(__version__)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

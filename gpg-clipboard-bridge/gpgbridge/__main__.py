"""CLI: python -m gpgbridge {supervisor|bridge|diagnose|uninstall|selftest|version}

The packaged GPGClipboardBridge.exe takes the same subcommands. Started with none (the Start-menu
shortcut), it starts the tray helper, or says it is already running.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, runtime


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv and runtime.frozen():
        from .supervisor import main as run
        return run(force=True, interactive=True)

    ap = argparse.ArgumentParser(prog="gpgbridge", description="Google Play Games (PC) -> Windows clipboard helper")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("supervisor", help="tray app + watchdog (what starts at logon)")
    s.add_argument("--force", action="store_true", help="start even if Quit was chosen earlier this session")
    b = sub.add_parser("bridge", help="run the clipboard bridge (console mode for debugging)")
    b.add_argument("--ipc", action="store_true", help="JSON events on stdout (used by the supervisor)")
    sub.add_parser("diagnose", help="print a report of Play Games / clipboard-sharing state")
    u = sub.add_parser("uninstall", help="remove the installed helper (Settings > Apps runs this)")
    u.add_argument("--quiet", action="store_true", help="no dialogs")
    sub.add_parser("selftest", help="check that every module and dependency loads (used by the build)")
    sub.add_parser("version")
    args = ap.parse_args(argv)

    if args.cmd == "supervisor":
        from .supervisor import main as run
        return run(force=args.force)
    if args.cmd == "bridge":
        from .bridge import main as run
        return run(ipc=args.ipc)
    if args.cmd == "diagnose":
        from .diagnose import main as run
        return run()
    if args.cmd == "uninstall":
        from .installer import uninstall_main
        return uninstall_main(quiet=args.quiet)
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "version":
        _out(__version__)
        return 0
    ap.print_help()
    return 2


def _out(text: str) -> None:
    if sys.stdout is not None:
        print(text)


def selftest() -> int:
    """Import everything the tray helper and bridge need, including pystray's Windows backend."""
    import importlib

    for mod in ("psutil", "PIL.Image", "PIL.ImageDraw", "pystray", "pystray._win32",
                "gpgbridge.supervisor", "gpgbridge.bridge", "gpgbridge.diagnose", "gpgbridge.installer"):
        importlib.import_module(mod)
    from .supervisor import make_icon_image

    make_icon_image((40, 170, 90)).tobytes()
    _out(f"selftest ok {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

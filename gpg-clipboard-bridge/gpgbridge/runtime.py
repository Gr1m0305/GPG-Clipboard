"""Where the helper is running from: a source checkout (python -m gpgbridge) or the packaged exe."""
from __future__ import annotations

import sys
from pathlib import Path

EXE_NAME = "GPGClipboardBridge.exe"


def frozen() -> bool:
    """True inside the PyInstaller build (GPGClipboardBridge.exe)."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Folder holding the exe (packaged) or the project folder (source checkout)."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def self_command(*args: str) -> list[str]:
    """Command line that runs this same program with a subcommand, e.g. self_command("bridge", "--ipc")."""
    if frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", "gpgbridge", *args]


def restart_hint() -> str:
    if frozen():
        return "open GPG Clipboard Bridge from the Start menu"
    return "run start.ps1"

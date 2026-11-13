"""Health check: `python -m gpgbridge diagnose`, or tray > Health check (opens the report in Notepad)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections import Counter
from pathlib import Path

from . import __version__, gpglog, procdetect, runtime, win32
from .config import data_dir, load
from .diagnosis import is_tracking_stuck
from .logutil import log_file


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _task_state() -> str:
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", "GPG Clipboard Bridge", "/FO", "LIST"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if out.returncode != 0:
        return "not registered"
    for line in out.stdout.splitlines():
        if line.strip().lower().startswith("status:"):
            return "registered, " + line.split(":", 1)[1].strip()
    return "registered"


def report() -> str:
    lines: list[str] = []
    p = lines.append
    cfg = load(write_default=False)
    p(f"== GPG Clipboard Bridge {__version__} health check ==")
    p(f"Helper program           : {'installed exe' if runtime.frozen() else 'source checkout'} ({runtime.app_root()})")
    install = r"C:\Program Files\Google\Play Games"
    p(f"Play Games install       : {'found' if os.path.isdir(install) else 'NOT FOUND'} ({install})")
    st = procdetect.scan()
    p(f"Play Games client open   : {st.client_running}  pids={sorted(st.client_pids)}")
    p(f"Emulator (crosvm run-mp) : {st.emulator_running}  main_pid={st.vm_main_pid}  crosvm_pids={len(st.vm_pids)}")
    flags = procdetect.vm_boot_flags(st.vm_main_pid)
    for k in ("androidboot.kiwi.client_version", "androidboot.kiwi.adbproxy.enabled",
              "androidboot.kiwi.enable_devmode_sideloading", "androidboot.pcs.enable_file_transfer"):
        if k in flags:
            p(f"  {k} = {flags[k]}")
    games = win32.find_game_windows(set(st.vm_pids))
    for w in games:
        p(f"Game window              : hwnd={w.hwnd} title='{win32.game_title(w.title)} - …' rect={w.rect}")
    if st.vm_pids and not games:
        p("Game window              : none visible")
    ports = {pt: _port_open(pt) for pt in (5037, 5555, 6520, 38068)}
    p("ADB ports (localhost)    : " + ", ".join(f"{k}={'open' if v else 'closed'}" for k, v in ports.items()))

    p("")
    p(f"Service.log              : {cfg['service_log']} ({'exists' if os.path.exists(cfg['service_log']) else 'missing'})")
    tail = gpglog.LogTailer(cfg["service_log"])
    parser = gpglog.ServiceLogParser()
    events = parser.feed_many(tail.prime(16 * 1024 * 1024))
    counts = Counter(e.kind for e in events)
    p(f"Clipboard sharing enabled: {parser.sharing_enabled}")
    for kind in (gpglog.W2A_SENT, gpglog.A2W_RECEIVED, gpglog.A2W_APPLIED, gpglog.A2W_BLOCKED,
                 gpglog.DISPLAY_CHANGE):
        p(f"  {kind:<16} {counts.get(kind, 0)}")
    a2w = [e for e in events if e.kind in (gpglog.A2W_APPLIED, gpglog.A2W_BLOCKED)]
    for e in a2w[-5:]:
        p(f"  last: {e.ts}  {e.kind} {e.data.get('reason', '')}")
    ws = parser.window_state
    p(f"Tracked emulator window  : {ws}")
    stuck = is_tracking_stuck(ws, games)
    p(f"Tracking looks stuck     : {stuck}" + ("  -> close the game and relaunch it from Play Games" if stuck else ""))
    p("")
    p(f"Helper Scheduled Task    : {_task_state()}")
    p(f"Start with Windows       : {_startup_state()}")
    p(f"Helper log               : {log_file()}")
    p(f"Exports folder           : {cfg['exports_dir']}")
    return "\n".join(lines) + "\n"


def _startup_state() -> str:
    try:
        from . import installer
        run = installer.get_run_value()
        task = installer.task_enabled()
    except Exception as exc:  # pragma: no cover - diagnostics must never crash
        return f"unknown ({exc})"
    parts = (["Scheduled Task"] if task else []) + (["HKCU Run key"] if run else [])
    return "yes (" + " + ".join(parts) + ")" if parts else "NO (tray > Start with Windows to turn it on)"


def open_report() -> Path:
    """Write the report to a text file and open it (used by the tray and the windowed exe)."""
    path = data_dir() / "health-check.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = report()
    except Exception as exc:
        text = f"Health check failed: {exc!r}\n"
    path.write_text(text, encoding="utf-8")
    win32.open_path(str(path))
    return path


def main() -> int:
    if sys.stdout is None:  # windowed exe started without a console
        open_report()
        return 0
    print(report(), end="")
    return 0

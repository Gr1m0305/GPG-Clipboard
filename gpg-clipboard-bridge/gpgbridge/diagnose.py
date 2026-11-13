"""`python -m gpgbridge diagnose`: one-shot report used for setup checks and troubleshooting."""
from __future__ import annotations

import os
import socket
import subprocess
from collections import Counter

from . import gpglog, procdetect, win32
from .config import load
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


def main() -> int:
    cfg = load(write_default=False)
    p = print
    p("== GPG Clipboard Bridge diagnose ==")
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
    p(f"Helper log               : {log_file()}")
    p(f"Exports folder           : {cfg['exports_dir']}")
    return 0

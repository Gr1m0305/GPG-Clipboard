"""Supervisor / watchdog with a system-tray icon.

Started at Windows logon by the Scheduled Task (pythonw.exe, no console). Every
few seconds it checks (psutil) whether Google Play Games is open:
  Play Games opens  -> start the bridge child process
  Play Games closes -> stop the bridge (its clipboard listener is released)
  bridge crashes    -> restart it with back-off
Handles Play Games being open before the supervisor starts and being opened/closed
any number of times. Tray: Status, Pause, Open log, Open exports folder, Quit.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import APP_ID, APP_NAME, __version__, procdetect, win32
from .config import data_dir, load
from .logutil import log_file, setup_file_logging

log = logging.getLogger("supervisor")
bridge_log = logging.getLogger("bridge")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREATE_NO_WINDOW = 0x08000000
MUTEX_NAME = "Local\\gpg-clipboard-bridge-supervisor"
# The Scheduled Task re-launches the supervisor every 5 minutes (crash recovery). Tray > Quit
# writes this marker so it stays closed for the rest of the logon session.
QUIT_MARKER = data_dir() / "quit.marker"


def session_start_time() -> float:
    """Approximate start of the current logon session: oldest explorer.exe of this user."""
    import getpass

    import psutil

    me = getpass.getuser().lower()
    times = []
    for p in psutil.process_iter(["name", "username", "create_time"]):
        if (p.info.get("name") or "").lower() == "explorer.exe":
            user = (p.info.get("username") or "").lower()
            if user.endswith("\\" + me) or user == me:
                times.append(p.info["create_time"])
    return min(times) if times else psutil.boot_time()


def quit_marker_blocks_start() -> bool:
    try:
        quit_at = QUIT_MARKER.stat().st_mtime
    except OSError:
        return False
    if quit_at > session_start_time():
        return True
    QUIT_MARKER.unlink(missing_ok=True)  # quit happened in an earlier session
    return False

STATUS_TEXT = {
    "waiting_play_games": "Waiting for Play Games",
    "starting": "Play Games open, starting bridge",
    "waiting_emulator": "Play Games open, waiting for the game",
    "connected": "Connected",
    "stuck": "Connected, but clipboard sharing looks stuck",
    "paused": "Paused",
    "error": "Bridge error (see log)",
}
STATUS_COLOR = {
    "waiting_play_games": (128, 128, 128),
    "starting": (70, 130, 220),
    "waiting_emulator": (70, 130, 220),
    "connected": (40, 170, 90),
    "stuck": (230, 150, 20),
    "paused": (150, 150, 150),
    "error": (210, 50, 50),
}


def make_icon_image(rgb=(128, 128, 128)):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10, 8, 54, 60), radius=7, fill=rgb + (255,))
    d.rounded_rectangle((22, 3, 42, 15), radius=4, fill=(60, 60, 60, 255))
    d.rectangle((18, 24, 46, 52), fill=(255, 255, 255, 235))
    for y in (30, 37, 44):
        d.line((22, y, 42, y), fill=rgb + (255,), width=3)
    return img


class SingleInstance:
    def __init__(self, name: str):
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        self.handle = k32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


class Supervisor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.interval = float(cfg.get("process_poll_seconds", 2.5))
        self.icon = None
        self.paused = False
        self.quit_event = threading.Event()
        self.child: subprocess.Popen | None = None
        self.child_lock = threading.RLock()
        self.child_stopping = False
        self.status = "waiting_play_games"
        self.status_detail = ""
        self.play_games_open = False
        self.restart_delay = 2.0
        self.next_start_at = 0.0
        self._toast_times: dict[str, float] = {}

    # -- tray ----------------------------------------------------------------
    def status_line(self) -> str:
        text = STATUS_TEXT.get(self.status, self.status)
        if self.status in ("connected", "stuck") and self.status_detail:
            text += f" ({self.status_detail})"
        return text

    def _menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem(lambda _i: "Status: " + self.status_line(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Pause", self._toggle_pause, checked=lambda _i: self.paused),
            pystray.MenuItem("Open log", lambda _i, _m=None: self._open(log_file())),
            pystray.MenuItem("Open exports folder", lambda _i, _m=None: self._open(Path(self.cfg["exports_dir"]))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _open(self, path: Path) -> None:
        try:
            if path.suffix == "":
                path.mkdir(parents=True, exist_ok=True)
            win32.open_path(str(path))
        except OSError:
            log.exception("could not open %s", path)

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        self.paused = not self.paused
        log.info("paused" if self.paused else "resumed")
        if self.paused:
            self._stop_child()
            self._set_status("paused")
        else:
            self._set_status("waiting_play_games")
            self.next_start_at = 0.0

    def _quit(self, _icon=None, _item=None) -> None:
        log.info("quit requested from tray (stays off until next logon or start.ps1)")
        try:
            QUIT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            QUIT_MARKER.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            log.exception("could not write quit marker")
        self.quit_event.set()
        self._stop_child()
        if self.icon:
            self.icon.stop()

    def _set_status(self, status: str, detail: str = "") -> None:
        if (status, detail) == (self.status, self.status_detail):
            return
        prev = self.status
        self.status, self.status_detail = status, detail
        log.info("status: %s", self.status_line())
        if self.icon:
            self.icon.icon = make_icon_image(STATUS_COLOR.get(status, (128, 128, 128)))
            self.icon.title = f"{APP_NAME}: {self.status_line()}"[:127]
            try:
                self.icon.update_menu()
            except Exception:  # menu refresh is cosmetic
                pass
        if status == "stuck" and prev != "stuck":
            self.toast("Play Games clipboard sharing looks stuck",
                       "Play Games lost track of the game window (display change). Close the game and open it "
                       "again from Play Games before you press Copy.", key="stuck", every=300)

    def toast(self, title: str, message: str, key: str | None = None, every: float = 0.0) -> None:
        if not self.cfg.get("toasts", True) or not self.icon:
            return
        now = time.monotonic()
        if key and now - self._toast_times.get(key, -1e9) < every:
            return
        if key:
            self._toast_times[key] = now
        try:
            self.icon.notify(message[:255], title[:63])
        except Exception:
            log.exception("toast failed")

    # -- bridge child -----------------------------------------------------------
    def _start_child(self) -> None:
        with self.child_lock:
            if self.child and self.child.poll() is None:
                return
            cmd = [sys.executable, "-m", "gpgbridge", "bridge", "--ipc"]
            log.info("starting bridge: %s", " ".join(cmd))
            self.child_stopping = False
            self.child = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            child = self.child
        self._set_status("starting")
        threading.Thread(target=self._read_events, args=(child,), daemon=True, name="bridge-stdout").start()
        threading.Thread(target=self._read_stderr, args=(child,), daemon=True, name="bridge-stderr").start()

    def _stop_child(self) -> None:
        with self.child_lock:
            child, self.child = self.child, None
            self.child_stopping = True
        if not child or child.poll() is not None:
            return
        log.info("stopping bridge (pid %s)", child.pid)
        try:
            child.stdin.write("stop\n")
            child.stdin.flush()
            child.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            log.warning("bridge did not stop in time; killing it")
            child.kill()
            child.wait(timeout=5)
        log.info("bridge stopped (exit %s)", child.returncode)

    def _read_events(self, child: subprocess.Popen) -> None:
        for line in child.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                bridge_log.info("%s", line)
                continue
            try:
                self._handle_event(ev)
            except Exception:
                log.exception("failed to handle bridge event %r", ev)

    def _read_stderr(self, child: subprocess.Popen) -> None:
        for line in child.stderr:
            if line.strip():
                bridge_log.error("stderr: %s", line.rstrip())

    def _handle_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "log":
            bridge_log.log(int(ev.get("level", logging.INFO)), "%s", ev.get("msg", ""))
        elif kind == "status":
            state = ev.get("state")
            if state != "stopped" and not self.paused:
                self._set_status(state, ev.get("detail", ""))
        elif kind == "copied":
            what = "village export" if ev.get("village") else ("JSON" if ev.get("json") else "text")
            msg = f"Ready to paste ({what})."
            if ev.get("saved", "").endswith("export.json"):
                msg += " Also saved as export.json."
            self.toast(f"Copied {ev.get('chars', 0):,} characters from Play Games", msg, key="copied", every=3)
        elif kind == "blocked":
            self.toast("Play Games blocked the copy", ev.get("advice", "Press Copy again."), key="blocked", every=20)
        elif kind == "inbox_loaded":
            self.toast(f"Loaded {ev.get('name', 'file')}",
                       f"{ev.get('chars', 0):,} characters are on the clipboard and saved as export.json.",
                       key="inbox", every=2)
        elif kind == "sent_to_android":
            self.toast("Sent to Play Games", f"{ev.get('chars', 0):,} characters synced to the Android clipboard.",
                       key="w2a", every=5)

    # -- watchdog loop -------------------------------------------------------------
    def watch(self) -> None:
        log.info("watchdog running (poll every %.1fs)", self.interval)
        while not self.quit_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("watchdog tick failed")
            self.quit_event.wait(self.interval)
        self._stop_child()

    def _tick(self) -> None:
        state = procdetect.scan()
        if state.client_running != self.play_games_open:
            self.play_games_open = state.client_running
            log.info("Play Games %s (client pids %s, emulator %s)", "opened" if state.client_running else "closed",
                     sorted(state.client_pids), state.emulator_running)
            self.restart_delay, self.next_start_at = 2.0, 0.0
        if self.paused:
            return
        if not state.client_running:
            if self.child:
                self._stop_child()
            self._set_status("waiting_play_games")
            return
        with self.child_lock:
            child = self.child
        if child is not None and child.poll() is None:
            return
        if child is not None and not self.child_stopping:
            log.warning("bridge exited unexpectedly (code %s); restarting in %.0fs", child.returncode, self.restart_delay)
            self._set_status("error")
            self.next_start_at = time.monotonic() + self.restart_delay
            self.restart_delay = min(self.restart_delay * 2, 60.0)
            with self.child_lock:
                self.child = None
            return
        if time.monotonic() >= self.next_start_at:
            self._start_child()

    # -- entry ------------------------------------------------------------------------
    def run(self) -> int:
        import pystray

        self.icon = pystray.Icon(APP_ID, make_icon_image(STATUS_COLOR["waiting_play_games"]),
                                 f"{APP_NAME}: {self.status_line()}", self._menu())

        def setup(icon):
            icon.visible = True
            threading.Thread(target=self.watch, daemon=True, name="watchdog").start()

        self.icon.run(setup=setup)
        self.quit_event.set()
        self._stop_child()
        log.info("supervisor exiting")
        return 0


def main(force: bool = False) -> int:
    setup_file_logging()
    inst = SingleInstance(MUTEX_NAME)
    if inst.already_running:
        log.debug("another supervisor is already running; exiting")
        return 0
    if force:
        QUIT_MARKER.unlink(missing_ok=True)
    elif quit_marker_blocks_start():
        log.info("not starting: you chose Quit earlier in this logon session (run start.ps1 to start again)")
        return 0
    cfg = load()
    log.info("%s %s supervisor starting (pid %s, python %s, project %s)", APP_NAME, __version__, os.getpid(),
             sys.version.split()[0], PROJECT_ROOT)
    return Supervisor(cfg).run()

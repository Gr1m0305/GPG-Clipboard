"""The clipboard bridge process (started by the supervisor while Play Games is open).

Transport: Play Games' own clipboard sharing (the only legitimate Android ->
Windows channel on the consumer client, see PROGRESS.md). The bridge:

* listens to the Windows clipboard and attributes each change to its owner
  process; text written by Play Games' Service.exe is an in-game copy ->
  event "copied" (+ saved as latest.txt / export.json);
* follows Service.log: "Ignoring Android clipboard change" -> event "blocked"
  with a diagnosis and the fix; WindowState updates -> early "stuck" warning;
* watches the inbox folder (fallback) and loads dropped exports onto the clipboard;
* reports status: waiting_emulator / connected / stuck.

With --ipc, events and log records are JSON lines on stdout and commands
("stop") are read from stdin. Without it, it runs in a console for debugging.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass

from . import gpglog, procdetect, win32, winclip
from .diagnosis import diagnose_block, is_tracking_stuck
from .exports import ExportStore, InboxWatcher, describe, read_text_file
from .logutil import JsonLineHandler, json_dumps, setup_console_logging
from .tracker import Action, ClipboardTracker, Origin, classify_origin

log = logging.getLogger("bridge")

UNKNOWN_OWNER_GRACE = 1.5    # seconds to wait for Service.log evidence when the clipboard has no owner
APPLIED_EVIDENCE_WINDOW = 4.0
# Play Games writes with WPF/OLE: OleSetClipboard (delayed rendering) then OleFlushClipboard, retrying
# OpenClipboard 10 x 100 ms. Opening the clipboard during that window blocks us in GetClipboardData and
# makes Play Games' flush fail (seen 2026-11-13 17:21:59: CLIPBRD_E_CANT_OPEN). So we only read once the
# clipboard has been quiet this long.
SETTLE_PLAY_GAMES = 1.5
SETTLE_OTHER = 0.3
ERROR_EVIDENCE_WINDOW = 5.0  # a Play Games write error is harmless if its text reached the clipboard anyway
ERROR_REPORT_DELAY = 3.0


@dataclass
class ClipChange:
    t: float
    seq: int
    owner_pid: int


class Bridge:
    def __init__(self, cfg: dict, emit):
        self.cfg = cfg
        self.emit = emit
        self.own_pid = os.getpid()
        self.tracker = ClipboardTracker(repeat_window=float(cfg.get("repeat_window_seconds", 10)))
        self.parser = gpglog.ServiceLogParser()
        self.tailer = gpglog.LogTailer(cfg["service_log"])
        self.store = ExportStore(cfg["exports_dir"], int(cfg.get("history_keep", 20))) if cfg.get("save_exports", True) else None
        self.inbox = None
        if cfg.get("inbox_enabled", True) and cfg.get("inbox_dirs"):
            self.inbox = InboxWatcher(cfg["inbox_dirs"], cfg.get("inbox_extensions", (".json", ".txt")))
        self.listener = winclip.ClipboardListener(self._on_clip_change)
        self.changes: "queue.Queue[ClipChange]" = queue.Queue()
        self.pending: list[ClipChange] = []
        self.stop_event = threading.Event()

        self.gpg = procdetect.GpgState()
        self.game_windows: list[win32.WindowInfo] = []
        self.status: tuple[str, str] | None = None
        self.blocked_since_state = False      # a copy was dropped and no healthy WindowState since
        self.last_applied = -1e9               # monotonic time of last "Updating Windows clipboard."
        self.last_pg_change = -1e9             # monotonic time of last clipboard change owned by Play Games
        self.pending_errors: list[float] = []
        self.last_windows_text_len = 0

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> int:
        primed = self.tailer.prime()
        self.parser.feed_many(primed)  # restore current window state, no events emitted for history
        log.info("bridge started (pid %s); Service.log primed with %d lines; sharing_enabled=%s; tracked=%s",
                 self.own_pid, len(primed), self.parser.sharing_enabled, self.parser.window_state)
        self.listener.start()
        log_every = float(self.cfg.get("log_poll_seconds", 0.5))
        next_log = next_proc = next_inbox = 0.0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if now >= next_proc:
                    self._refresh_processes()
                    next_proc = now + 2.0
                if now >= next_log:
                    for ev in self.parser.feed_many(self.tailer.poll()):
                        self._on_log_event(ev)
                    next_log = now + log_every
                if self.inbox and now >= next_inbox:
                    for path in self.inbox.poll():
                        self._load_inbox_file(path)
                    next_inbox = now + 1.0
                self._drain_clipboard_changes()
                self._check_pending_errors()
                self.stop_event.wait(0.1)
        finally:
            self.listener.stop()
            self._set_status("stopped", "")
            log.info("bridge stopped; clipboard listener released")
        return 0

    def stop(self) -> None:
        self.stop_event.set()

    # -- processes / status --------------------------------------------------
    def _refresh_processes(self) -> None:
        try:
            self.gpg = procdetect.scan()
        except Exception:
            log.exception("process scan failed")
            return
        self.game_windows = win32.find_game_windows(set(self.gpg.vm_pids))
        if not self.gpg.emulator_running or not self.game_windows:
            self._set_status("waiting_emulator", "Play Games open, waiting for a game window")
            return
        title = win32.game_title(self.game_windows[0].title)
        if self.blocked_since_state or is_tracking_stuck(self.parser.window_state, self.game_windows):
            self._set_status("stuck", title)
        else:
            self._set_status("connected", title)

    def _set_status(self, state: str, detail: str) -> None:
        if self.status != (state, detail):
            self.status = (state, detail)
            self.emit({"type": "status", "state": state, "detail": detail})

    # -- clipboard -----------------------------------------------------------
    def _on_clip_change(self, seq: int, owner_pid: int) -> None:
        # runs on the listener thread: capture owner now, read text on the main thread
        self.changes.put(ClipChange(time.monotonic(), seq, owner_pid))

    def _drain_clipboard_changes(self) -> None:
        while True:
            try:
                self.pending.append(self.changes.get_nowait())
            except queue.Empty:
                break
        if not self.pending:
            return
        now = time.monotonic()
        keep = []
        latest_seq = winclip.sequence_number()
        for ch in self.pending:
            if ch.seq != latest_seq:
                continue  # superseded by a newer change, which has its own entry
            applied = abs(self.last_applied - ch.t) <= APPLIED_EVIDENCE_WINDOW
            origin = classify_origin(ch.owner_pid, self.own_pid, self.gpg.all_pids,
                                     win32.process_image(ch.owner_pid) if ch.owner_pid else None, applied)
            if origin == Origin.SELF:
                continue  # our own write: never re-open the clipboard for it
            settle = SETTLE_OTHER if origin == Origin.OTHER else SETTLE_PLAY_GAMES
            if origin == Origin.UNKNOWN:
                settle = max(settle, UNKNOWN_OWNER_GRACE)  # also wait for "Updating Windows clipboard."
            if now - ch.t < settle:
                keep.append(ch)  # let the writer finish (and flush) before we open the clipboard
                continue
            self._handle_change(ch, origin)
        self.pending = keep

    def _handle_change(self, ch: ClipChange, origin: Origin) -> None:
        try:
            text = winclip.read_text()
        except winclip.ClipboardBusy:
            log.warning("clipboard busy; skipped change seq=%s", ch.seq)
            return
        if origin == Origin.PLAY_GAMES and text:
            self.last_pg_change = ch.t
        decision = self.tracker.observe(text, origin)
        log.debug("clipboard seq=%s owner=%s origin=%s -> %s (%s)", ch.seq, ch.owner_pid, origin.value,
                  decision.action.value, decision.reason)
        if decision.action == Action.FROM_WINDOWS and text:
            self.last_windows_text_len = len(text)
        if decision.action != Action.FROM_PLAY_GAMES:
            return
        info = describe(text)
        saved = {}
        if self.store:
            try:
                saved = self.store.save(text, "play_games")
            except OSError:
                log.exception("could not save export")
        self.blocked_since_state = False
        log.info("copied %d chars from Play Games (json=%s village=%s) -> %s", info["chars"], info["json"],
                 info["village"], saved.get("export") or saved.get("latest"))
        self.emit({"type": "copied", **info, "saved": saved.get("export") or saved.get("latest", "")})

    # -- Service.log -----------------------------------------------------------
    def _on_log_event(self, ev: gpglog.LogEvent) -> None:
        if ev.kind == gpglog.A2W_RECEIVED:
            log.info("Play Games received an Android clipboard update (%s bytes)", ev.data.get("frame_size"))
        elif ev.kind == gpglog.A2W_APPLIED:
            self.last_applied = time.monotonic()
            log.info("Play Games is updating the Windows clipboard")
        elif ev.kind == gpglog.A2W_BLOCKED:
            self._on_blocked(ev)
        elif ev.kind == gpglog.A2W_ERROR:
            log.warning("Play Games reported a clipboard write error: %s", ev.line.split("ClipboardOperations: ")[-1])
            self.pending_errors.append(time.monotonic())  # only alert if the text did not arrive anyway
        elif ev.kind == gpglog.WINDOW_STATE:
            ws = ev.data["state"]
            log.info("Play Games now tracks window %s (%s, %s, %dx%d)", ws.window_handle, ws.visibility, ws.mode,
                     ws.width, ws.height)
            if ws.visibility.upper() == "NORMAL" and any(w.hwnd == ws.window_handle for w in self.game_windows):
                self.blocked_since_state = False
            self._refresh_processes()
        elif ev.kind == gpglog.DISPLAY_CHANGE:
            log.info("Play Games detected a display settings change")
        elif ev.kind == gpglog.SHARING_ENABLED:
            log.info("Play Games reports clipboard sharing is enabled")
        elif ev.kind == gpglog.W2A_SENT:
            if self.cfg.get("two_way"):
                self.emit({"type": "sent_to_android", "chars": self.last_windows_text_len})
        elif ev.kind == gpglog.GAME_SHOWN:
            self.blocked_since_state = False

    def _check_pending_errors(self) -> None:
        if not self.pending_errors:
            return
        now = time.monotonic()
        keep = []
        for t in self.pending_errors:
            if self.last_pg_change >= t - ERROR_EVIDENCE_WINDOW:
                log.info("Play Games' write error was harmless: its text reached the Windows clipboard")
            elif now - t < ERROR_REPORT_DELAY:
                keep.append(t)
            else:
                self.emit({"type": "blocked", "cause": "set_error",
                           "advice": "Play Games could not write the Windows clipboard. Press Copy again."})
        self.pending_errors = keep

    def _on_blocked(self, ev: gpglog.LogEvent) -> None:
        self._refresh_processes()
        diag = diagnose_block(ev.data.get("reason", "unknown"), win32.foreground_window(),
                              self.parser.window_state, self.game_windows)
        log.warning("Play Games DROPPED an in-game copy: %s | diagnosis=%s", ev.line.split("ClipboardModule: ")[-1], diag)
        if diag.get("cause") in ("tracked_window_mismatch", "tracked_window_not_normal"):
            self.blocked_since_state = True
        self.emit({"type": "blocked", **diag})
        self._refresh_processes()

    # -- inbox fallback --------------------------------------------------------
    def _load_inbox_file(self, path) -> None:
        try:
            text = read_text_file(path)
        except OSError:
            log.exception("could not read inbox file %s", path)
            return
        if not text.strip():
            return
        info = describe(text)
        if self.cfg.get("inbox_load_to_clipboard", True):
            self.tracker.note_self_write(text)
            self.last_windows_text_len = len(text)  # Play Games will sync it to Android
            try:
                winclip.write_text(text, self.listener.hwnd or None)
            except (winclip.ClipboardBusy, OSError, MemoryError):
                log.exception("could not put inbox file on the clipboard")
        saved = {}
        if self.store:
            try:
                saved = self.store.save(text, "inbox")
            except OSError:
                log.exception("could not save export")
        log.info("loaded inbox file %s (%d chars)", path, info["chars"])
        self.emit({"type": "inbox_loaded", "file": str(path), "name": path.name, **info,
                   "saved": saved.get("export") or saved.get("latest", "")})


# -- entry point ---------------------------------------------------------------

def _stdin_commands(bridge: Bridge) -> None:
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd == "stop":
            break
    bridge.stop()  # "stop" or EOF (supervisor gone) -> shut down


def main(ipc: bool = False) -> int:
    from .config import load

    cfg = load()
    lock = threading.Lock()

    if ipc:
        out = sys.stdout

        def emit(obj):
            with lock:
                out.write(json_dumps(obj) + "\n")
                out.flush()

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        h = JsonLineHandler(emit)
        h.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(h)
    else:
        setup_console_logging()

        def emit(obj):
            if obj.get("type") != "log":
                print("EVENT", json_dumps(obj), flush=True)

    bridge = Bridge(cfg, emit)
    if ipc:
        threading.Thread(target=_stdin_commands, args=(bridge,), daemon=True, name="stdin").start()
    else:
        print("Bridge running in console mode. Press Ctrl+C to stop.", flush=True)
    try:
        return bridge.run()
    except KeyboardInterrupt:
        bridge.stop()
        return 0

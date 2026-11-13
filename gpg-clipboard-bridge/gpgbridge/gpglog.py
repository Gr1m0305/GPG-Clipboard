"""Follow and parse Play Games' Service.log for clipboard-sharing events.

Log lines look like:
    261113 16:38:17.788+10 08 INFO  PcsDatagramWireProtocol: Received incoming message: PCS-4622 - UpdateWindowsClipboardRequest
    261113 16:38:17.802+10 71 INFO  ClipboardModule: Emulator window is not foreground. Ignoring Android clipboard change.
A WindowState update is a header line followed by one JSON-ish line:
    261113 15:06:37.288+10 01 INFO  EmulatorStateLogger: EmulatorState.WindowState updated:
    { "initGuestDisplaySize": { "width": 1280, "height": 1024 }, "window": { "hwnd": "200340", "visibility": "HIDDEN", ... "windowHandle": "200354" }, ... }

The file is opened with FILE_SHARE_DELETE and closed after each read so that
Play Games can always rotate it (Service.log -> Service-bkup-YYYYMMDD-NNNN.log).
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

LINE_RE = re.compile(r"^(\d{6} \d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2})\s+\d+\s+([A-Z]+)\s+(.*)$")
FRAME_RE = re.compile(r"Reading incoming message with frame buffer size: (\d+)")
WINDOW_OBJ_RE = re.compile(r'"window"\s*:\s*\{([^}]*)\}')
SIZE_RE = re.compile(r'"initGuestDisplaySize"\s*:\s*\{\s*"width"\s*:\s*(\d+)\s*,\s*"height"\s*:\s*(\d+)')


def _field(obj: str, name: str) -> str | None:
    m = re.search(r'"%s"\s*:\s*"([^"]*)"' % re.escape(name), obj)
    return m.group(1) if m else None


# kind constants
SHARING_ENABLED = "sharing_enabled"
A2W_RECEIVED = "a2w_received"        # Android -> Windows request reached Play Games
A2W_APPLIED = "a2w_applied"          # Play Games wrote it to the Windows clipboard
A2W_BLOCKED = "a2w_blocked"          # Play Games dropped it (data["reason"])
A2W_ERROR = "a2w_error"
NON_TEXT = "non_text"
W2A_SENT = "w2a_sent"                # Windows -> Android sync sent
W2A_SKIPPED = "w2a_skipped"
WINDOW_STATE = "window_state"
DISPLAY_CHANGE = "display_change"
GAME_EXIT = "game_exit"
GAME_SHOWN = "game_shown"

BLOCK_REASONS = {
    "Emulator window is not foreground.": "not_foreground",
    "Emulator is not running.": "emulator_not_running",
    "Clipboard data is null.": "null_data",
}

SIMPLE = [
    ("ClipboardModule: Clipboard sharing is enabled.", SHARING_ENABLED),
    ("ClipboardModule: Updating Windows clipboard.", A2W_APPLIED),
    ("Error while setting clipboard text", A2W_ERROR),
    ("Received non-text clipboard data", NON_TEXT),
    ("ClipboardModule: Updating Android clipboard with MIME type", W2A_SENT),
    ("PCS is not connected. Not updating Android clipboard.", W2A_SKIPPED),
    ("Detected host display settings change", DISPLAY_CHANGE),
    ("- UserExitGameFromVmRequest", GAME_EXIT),
    ("- ShowWindowRequest", GAME_SHOWN),
]


@dataclass(frozen=True)
class WindowState:
    hwnd: int            # CROSVM_1 child surface
    window_handle: int   # top-level HwndWrapper window
    visibility: str      # NORMAL / HIDDEN / MINIMIZED
    mode: str            # FULLSCREEN / WINDOWED ...
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class LogEvent:
    kind: str
    ts: str
    line: str
    data: dict = field(default_factory=dict)


def parse_window_state(text: str) -> WindowState | None:
    m = WINDOW_OBJ_RE.search(text)
    if not m:
        return None
    obj = m.group(1)
    hwnd, handle = _field(obj, "hwnd"), _field(obj, "windowHandle")
    if not hwnd or not handle:
        return None
    size = SIZE_RE.search(text)
    return WindowState(
        hwnd=int(hwnd),
        window_handle=int(handle),
        visibility=_field(obj, "visibility") or "",
        mode=_field(obj, "mode") or "",
        width=int(size.group(1)) if size else 0,
        height=int(size.group(2)) if size else 0,
    )


class ServiceLogParser:
    """Stateful line parser. Feed lines in order; returns zero or more events per line."""

    def __init__(self):
        self.window_state: WindowState | None = None
        self.sharing_enabled: bool | None = None
        self._pending_ws_ts: str | None = None
        self._last_frame_size = 0

    def feed(self, line: str) -> list[LogEvent]:
        line = line.rstrip("\r\n")
        m = LINE_RE.match(line)
        if not m:
            if self._pending_ws_ts is not None:
                ts, self._pending_ws_ts = self._pending_ws_ts, None
                ws = parse_window_state(line)
                if ws:
                    self.window_state = ws
                    return [LogEvent(WINDOW_STATE, ts, line, {"state": ws})]
            return []
        self._pending_ws_ts = None
        ts, _level, msg = m.groups()

        if "EmulatorState.WindowState updated:" in msg:
            self._pending_ws_ts = ts
            return []
        fm = FRAME_RE.search(msg)
        if fm:
            self._last_frame_size = int(fm.group(1))
            return []
        if msg.endswith("- UpdateWindowsClipboardRequest") and "Received incoming message" in msg:
            return [LogEvent(A2W_RECEIVED, ts, line, {"frame_size": self._last_frame_size})]
        if "Ignoring Android clipboard change." in msg and "ClipboardModule" in msg:
            reason = "unknown"
            for text, code in BLOCK_REASONS.items():
                if text in msg:
                    reason = code
            return [LogEvent(A2W_BLOCKED, ts, line, {"reason": reason})]
        for needle, kind in SIMPLE:
            if needle in msg:
                if kind == SHARING_ENABLED:
                    self.sharing_enabled = True
                return [LogEvent(kind, ts, line)]
        return []

    def feed_many(self, lines) -> list[LogEvent]:
        out: list[LogEvent] = []
        for ln in lines:
            out.extend(self.feed(ln))
        return out


# --- tailing ---------------------------------------------------------------

def _open_shared(path: str):
    """Open for reading with FILE_SHARE_READ|WRITE|DELETE so Play Games can still rotate the log."""
    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes
    import ctypes.wintypes as wt
    import msvcrt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.CreateFileW.restype = wt.HANDLE
    GENERIC_READ, SHARE_ALL, OPEN_EXISTING, NORMAL = 0x80000000, 0x7, 3, 0x80
    h = k32.CreateFileW(path, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, NORMAL, None)
    if h is None or h == wt.HANDLE(-1).value:
        err = ctypes.get_last_error()
        if err in (2, 3):
            raise FileNotFoundError(path)
        raise OSError(err, f"CreateFileW failed for {path}")
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "rb")


class LogTailer:
    """Returns complete new lines on each poll(); survives rotation and late creation."""

    MAX_CHUNK = 8 * 1024 * 1024

    def __init__(self, path: str, start_at_end: bool = True):
        self.path = path
        self.start_at_end = start_at_end
        self._ino: int | None = None
        self._offset = 0
        self._buf = b""
        self._was_missing = False

    def _stat(self):
        try:
            return os.stat(self.path)
        except (FileNotFoundError, PermissionError):
            return None

    def prime(self, max_bytes: int = 4 * 1024 * 1024) -> list[str]:
        """Return the last max_bytes worth of complete lines and start following from the end."""
        st = self._stat()
        if st is None:
            return []
        start = max(0, st.st_size - max_bytes)
        try:
            with _open_shared(self.path) as f:
                f.seek(start)
                data = f.read(st.st_size - start)
        except OSError:
            return []
        self._ino, self._offset, self._buf = st.st_ino, start + len(data), b""
        lines = data.split(b"\n")
        if start > 0 and lines:
            lines = lines[1:]  # first line is probably partial
        if lines and not data.endswith(b"\n"):
            self._buf = lines.pop()
        return [ln.decode("utf-8", "replace") for ln in lines]

    def poll(self) -> list[str]:
        st = self._stat()
        if st is None:
            self._was_missing = True
            return []
        if self._ino is None:
            self._ino = st.st_ino
            # a file that appeared while we were watching is new content, read it all
            self._offset = st.st_size if (self.start_at_end and not self._was_missing) else 0
        elif st.st_ino != self._ino or st.st_size < self._offset:
            # rotated or truncated: the new file is read from the beginning
            self._ino, self._offset, self._buf = st.st_ino, 0, b""
        if st.st_size <= self._offset:
            return []
        try:
            with _open_shared(self.path) as f:
                f.seek(self._offset)
                data = f.read(min(st.st_size - self._offset, self.MAX_CHUNK))
        except OSError:
            return []
        self._offset += len(data)
        data = self._buf + data
        lines = data.split(b"\n")
        self._buf = lines.pop()  # incomplete tail (b"" if data ended with newline)
        return [ln.decode("utf-8", "replace") for ln in lines]

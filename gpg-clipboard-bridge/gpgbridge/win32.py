"""Small ctypes helpers for Win32 windows and processes (read-only queries)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL

    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
    user32.EnumChildWindows.restype = wt.BOOL


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    cls: str
    title: str
    visible: bool
    iconic: bool
    rect: tuple[int, int, int, int]

    @property
    def offscreen(self) -> bool:
        # Play Games parks its hidden display surfaces at (-9999, -9999).
        return self.rect[0] <= -9000 and self.rect[1] <= -9000


def _h(value) -> int:
    return int(value or 0)


def process_image(pid: int) -> str | None:
    """Full path of a process image, or None if it cannot be queried."""
    if not IS_WINDOWS or pid <= 0:
        return None
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wt.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def window_pid(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_info(hwnd: int) -> WindowInfo:
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(max(length + 1, 1))
    user32.GetWindowTextW(hwnd, title, len(title))
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(
        hwnd=_h(hwnd),
        pid=window_pid(hwnd),
        cls=cls.value,
        title=title.value,
        visible=bool(user32.IsWindowVisible(hwnd)),
        iconic=bool(user32.IsIconic(hwnd)),
        rect=(rect.left, rect.top, rect.right, rect.bottom),
    )


def foreground_window() -> WindowInfo | None:
    if not IS_WINDOWS:
        return None
    hwnd = _h(user32.GetForegroundWindow())
    return window_info(hwnd) if hwnd else None


def top_level_windows(pids: set[int] | None = None) -> list[WindowInfo]:
    if not IS_WINDOWS:
        return []
    handles: list[int] = []

    def cb(hwnd, _lp):
        handles.append(_h(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    out = []
    for h in handles:
        if pids is not None and window_pid(h) not in pids:
            continue
        try:
            out.append(window_info(h))
        except OSError:
            continue
    return out


def is_game_window(w: WindowInfo) -> bool:
    """True for the visible Play Games game window (owned by crosvm.exe).

    Verified layout: top-level class 'HwndWrapper[DefaultDomain;;<guid>]', title
    '<Game> - <gamertag>', child 'CROSVM_1'. Hidden display surfaces share the
    class but are invisible and parked off-screen; WPF helpers are titled
    'Hidden Window' / 'MediaContextNotificationWindow' / etc.
    """
    if not w.visible or w.offscreen:
        return False
    if not w.cls.startswith("HwndWrapper["):
        return False
    if not w.title or w.title in {"Hidden Window", "MediaContextNotificationWindow", "SystemResourceNotifyWindow"}:
        return False
    return True


def game_title(title: str) -> str:
    """'Clash of Clans - SomeGamertag' -> 'Clash of Clans' (keeps the gamertag out of toasts)."""
    return title.rsplit(" - ", 1)[0] if " - " in title else title


def find_game_windows(crosvm_pids: set[int]) -> list[WindowInfo]:
    if not crosvm_pids:
        return []
    return [w for w in top_level_windows(crosvm_pids) if is_game_window(w)]


def open_path(path: str) -> None:
    """Open a file or folder with its default handler (Explorer/Notepad)."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 - user-requested "Open log"

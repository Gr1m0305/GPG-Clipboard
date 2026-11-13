"""Windows clipboard access via ctypes: read/write Unicode text and a change listener.

* Text is read as CF_UNICODETEXT using GlobalSize, so very large exports
  (hundreds of thousands of characters) are never truncated.
* ClipboardListener uses AddClipboardFormatListener on a hidden message-only
  window. It records the clipboard owner's PID at the moment of each change so
  the bridge can tell Play Games' writes apart from Windows-side copies.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

from .win32 import window_pid

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_CLIPBOARDUPDATE = 0x031D
HWND_MESSAGE = wt.HWND(-3)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wt.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wt.BOOL
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
user32.IsClipboardFormatAvailable.restype = wt.BOOL
user32.GetClipboardOwner.argtypes = []
user32.GetClipboardOwner.restype = wt.HWND
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetClipboardSequenceNumber.restype = wt.DWORD
user32.AddClipboardFormatListener.argtypes = [wt.HWND]
user32.AddClipboardFormatListener.restype = wt.BOOL
user32.RemoveClipboardFormatListener.argtypes = [wt.HWND]
user32.RemoveClipboardFormatListener.restype = wt.BOOL
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wt.ATOM
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.UnregisterClassW.restype = wt.BOOL
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.CreateWindowExW.restype = wt.HWND
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalFree.argtypes = [wt.HGLOBAL]
kernel32.GlobalFree.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t


class ClipboardBusy(Exception):
    """Another process holds the clipboard open."""


def sequence_number() -> int:
    return int(user32.GetClipboardSequenceNumber())


def owner_pid() -> int:
    """PID of the process that owns the clipboard right now (0 if none)."""
    return window_pid(int(user32.GetClipboardOwner() or 0))


def _open(hwnd: int | None, retries: int, delay: float) -> None:
    for _ in range(retries):
        if user32.OpenClipboard(hwnd):
            return
        time.sleep(delay)
    raise ClipboardBusy("clipboard is locked by another process")


def read_text(retries: int = 20, delay: float = 0.05) -> str | None:
    """Return the clipboard's Unicode text, or None if it holds no text."""
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    _open(None, retries, delay)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        size = kernel32.GlobalSize(handle)
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            text = ctypes.wstring_at(ptr, size // ctypes.sizeof(ctypes.c_wchar))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    nul = text.find("\x00")
    return text if nul < 0 else text[:nul]


def write_text(text: str, owner_hwnd: int | None = None, retries: int = 20, delay: float = 0.05) -> None:
    """Put Unicode text on the clipboard (owner = owner_hwnd, used for anti-loop attribution)."""
    data = ctypes.create_unicode_buffer(text)  # includes the terminating NUL
    nbytes = ctypes.sizeof(data)
    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, nbytes)
    if not hmem:
        raise MemoryError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(hmem)
    if not ptr:
        kernel32.GlobalFree(hmem)
        raise MemoryError("GlobalLock failed")
    ctypes.memmove(ptr, data, nbytes)
    kernel32.GlobalUnlock(hmem)
    try:
        _open(owner_hwnd, retries, delay)
    except ClipboardBusy:
        kernel32.GlobalFree(hmem)
        raise
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            raise OSError(ctypes.get_last_error(), "SetClipboardData failed")
        # On success the system owns hmem; do not free it.
    finally:
        user32.CloseClipboard()


class ClipboardListener:
    """Calls on_change(sequence, owner_pid) on its own thread for every clipboard change."""

    def __init__(self, on_change: Callable[[int, int], None]):
        self._on_change = on_change
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.hwnd: int = 0
        self._wndproc = WNDPROC(self._proc)  # keep a reference alive
        self._class_name = f"GpgClipboardBridge_{id(self):x}"
        self._error: BaseException | None = None

    def start(self, timeout: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._run, name="clipboard-listener", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("clipboard listener did not start")
        if self._error:
            raise self._error

    def stop(self, timeout: float = 3.0) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_CLIPBOARDUPDATE:
                self._on_change(sequence_number(), owner_pid())
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.RemoveClipboardFormatListener(hwnd)
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # never let an exception escape into the Win32 callback
            log.exception("clipboard listener callback failed")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name
        try:
            if not user32.RegisterClassExW(ctypes.byref(wc)):
                raise OSError(ctypes.get_last_error(), "RegisterClassExW failed")
            hwnd = user32.CreateWindowExW(0, self._class_name, "gpg-clipboard-bridge", 0, 0, 0, 0, 0,
                                          HWND_MESSAGE, None, hinst, None)
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            self.hwnd = int(hwnd)
            if not user32.AddClipboardFormatListener(hwnd):
                user32.DestroyWindow(hwnd)
                raise OSError(ctypes.get_last_error(), "AddClipboardFormatListener failed")
        except BaseException as exc:  # report to start()
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = 0
        user32.UnregisterClassW(self._class_name, hinst)
        log.debug("clipboard listener stopped")

"""Real Windows clipboard round trip. Opt-in because it touches your clipboard:

    $env:GPGBRIDGE_CLIPBOARD_TESTS = "1"; python -m pytest tests/test_winclip_integration.py
Your clipboard text is restored afterwards.
"""
import os
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("GPGBRIDGE_CLIPBOARD_TESTS") != "1",
    reason="set GPGBRIDGE_CLIPBOARD_TESTS=1 to run real clipboard tests",
)


@pytest.fixture
def winclip():
    from gpgbridge import winclip as wc

    saved = wc.read_text()
    yield wc
    if saved is not None:
        wc.write_text(saved)


def test_large_unicode_round_trip(winclip):
    text = ('{"tag":"#X","name":"Bäckerei ⚔️ 😀 中文"}\r\n' * 4000)
    assert len(text) > 150_000
    winclip.write_text(text)
    assert winclip.read_text() == text


def test_listener_reports_change_with_owner_pid(winclip):
    got = []
    ev = threading.Event()

    def on_change(seq, owner):
        got.append((seq, owner))
        ev.set()

    listener = winclip.ClipboardListener(on_change)
    listener.start()
    try:
        time.sleep(0.2)
        winclip.write_text("listener test", listener.hwnd)
        assert ev.wait(3), "no WM_CLIPBOARDUPDATE received"
        assert got[-1][1] == os.getpid()      # owner attribution -> 'self' (anti-loop)
    finally:
        listener.stop()
    assert not listener.running

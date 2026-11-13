"""Service.log parsing (real line formats from Play Games 26.10.842.1) and rotation-safe tailing."""
import os

from gpgbridge import gpglog
from gpgbridge.gpglog import LogTailer, ServiceLogParser

LINES = """\
261112 17:37:18.468+10 01 INFO  ClipboardModule: Clipboard sharing is enabled.
261113 14:32:52.469+10 108 INFO  ClipboardModule: Windows clipboard change detected.
261113 14:32:52.473+10 94 INFO  ClipboardModule: Updating Android clipboard with MIME type Text.
261113 15:06:37.261+10 01 INFO  AppSessionScope: Detected host display settings change, changing Android display settings
261113 15:06:37.288+10 01 INFO  EmulatorStateLogger: EmulatorState.WindowState updated:
{ "initGuestDisplaySize": { "width": 1920, "height": 1080 }, "window": { "hwnd": "200336", "visibility": "NORMAL", "mode": "FULLSCREEN", "windowHandle": "200350" }, "recommendedGuestDisplayDensity": { } }
261113 15:06:37.288+10 01 INFO  EmulatorStateLogger: EmulatorState.WindowState updated:
{ "initGuestDisplaySize": { "width": 1280, "height": 1024 }, "window": { "hwnd": "200340", "visibility": "HIDDEN", "mode": "FULLSCREEN", "windowHandle": "200354" }, "recommendedGuestDisplayDensity": { } }
261113 16:38:17.781+10 12 INFO  PcsDatagramWireProtocol: Reading incoming message with frame buffer size: 9133
261113 16:38:17.788+10 08 INFO  PcsDatagramWireProtocol: Received incoming message: PCS-4622 - UpdateWindowsClipboardRequest
261113 16:38:17.802+10 71 INFO  ClipboardModule: Emulator window is not foreground. Ignoring Android clipboard change.
261113 16:40:00.000+10 71 INFO  ClipboardModule: Updating Windows clipboard.
261113 16:41:00.000+10 71 INFO  ClipboardModule: Emulator is not running. Ignoring Android clipboard change.
""".splitlines()


def parse_all():
    p = ServiceLogParser()
    return p, p.feed_many(LINES)


def test_event_kinds_in_order():
    _, events = parse_all()
    assert [e.kind for e in events] == [
        gpglog.SHARING_ENABLED, gpglog.W2A_SENT, gpglog.DISPLAY_CHANGE, gpglog.WINDOW_STATE,
        gpglog.WINDOW_STATE, gpglog.A2W_RECEIVED, gpglog.A2W_BLOCKED, gpglog.A2W_APPLIED, gpglog.A2W_BLOCKED,
    ]


def test_block_reasons_and_frame_size():
    _, events = parse_all()
    received = next(e for e in events if e.kind == gpglog.A2W_RECEIVED)
    assert received.data["frame_size"] == 9133
    reasons = [e.data["reason"] for e in events if e.kind == gpglog.A2W_BLOCKED]
    assert reasons == ["not_foreground", "emulator_not_running"]


def test_last_window_state_is_the_hidden_surface():
    p, _ = parse_all()
    assert p.sharing_enabled is True
    ws = p.window_state
    assert (ws.hwnd, ws.window_handle, ws.visibility, ws.width, ws.height) == (200340, 200354, "HIDDEN", 1280, 1024)


def test_window_state_header_without_body_is_ignored():
    p = ServiceLogParser()
    out = p.feed_many([
        "261113 15:06:37.288+10 01 INFO  EmulatorStateLogger: EmulatorState.WindowState updated:",
        "261113 15:06:38.000+10 01 INFO  Something: else",
    ])
    assert out == [] and p.window_state is None


def test_unrelated_lines_produce_nothing():
    p = ServiceLogParser()
    assert p.feed("261113 16:38:20.300+10 12 INFO  PcsDatagramWireProtocol: Received incoming message: PCS-4623 - GuestLogEventsRequest") == []
    assert p.feed("\tsome continuation line") == []


# --- tailer ------------------------------------------------------------------------

def test_tailer_follows_appends_and_partial_lines(tmp_path):
    f = tmp_path / "Service.log"
    f.write_bytes(b"old line\n")
    t = LogTailer(str(f))
    assert t.poll() == []                        # starts at the end
    with open(f, "ab") as fh:
        fh.write(b"one\ntw")
    assert t.poll() == ["one"]
    with open(f, "ab") as fh:
        fh.write(b"o\nthree\n")
    assert t.poll() == ["two", "three"]


def test_tailer_handles_rotation(tmp_path):
    f = tmp_path / "Service.log"
    f.write_bytes(b"a\n")
    t = LogTailer(str(f))
    t.poll()
    os.replace(f, tmp_path / "Service-bkup-20261113-0001.log")   # Play Games rotates
    f.write_bytes(b"fresh 1\nfresh 2\n")
    assert t.poll() == ["fresh 1", "fresh 2"]


def test_tailer_does_not_block_rotation(tmp_path):
    f = tmp_path / "Service.log"
    f.write_bytes(b"x\n")
    t = LogTailer(str(f))
    t.poll()
    # file is not held open between polls, so renaming works at any time
    os.replace(f, tmp_path / "rotated.log")
    assert (tmp_path / "rotated.log").exists()


def test_tailer_waits_for_missing_file(tmp_path):
    f = tmp_path / "Service.log"
    t = LogTailer(str(f), start_at_end=True)
    assert t.poll() == []
    f.write_bytes(b"created later\n")
    assert t.poll() == ["created later"]   # appeared while watching: all of it is new
    with open(f, "ab") as fh:
        fh.write(b"new\n")
    assert t.poll() == ["new"]


def test_prime_returns_recent_lines_then_follows(tmp_path):
    f = tmp_path / "Service.log"
    f.write_bytes(b"".join(b"line %d\n" % i for i in range(100)))
    t = LogTailer(str(f))
    recent = [x for x in t.prime(max_bytes=40) if x]
    assert recent[-1] == "line 99" and "line 0" not in recent
    with open(f, "ab") as fh:
        fh.write(b"after\n")
    assert t.poll() == ["after"]

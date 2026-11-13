"""Bridge timing rules: never open the clipboard while Play Games is still writing; no false error alerts."""
import json

import pytest

from gpgbridge import bridge as br
from gpgbridge.procdetect import GpgState

PG_PID = 777
EXPORT = json.dumps({"tag": "#X", "timestamp": 1, "buildings": [], "units": [], "heroes": []})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = {"t": 100.0}
    reads = []
    events = []
    monkeypatch.setattr(br.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(br.winclip, "sequence_number", lambda: 5)

    def read_text():
        reads.append(clock["t"])
        return EXPORT

    monkeypatch.setattr(br.winclip, "read_text", read_text)
    monkeypatch.setattr(br.win32, "process_image", lambda pid: None)
    cfg = {"service_log": str(tmp_path / "Service.log"), "exports_dir": str(tmp_path / "exports"),
           "inbox_enabled": False}
    b = br.Bridge(cfg, events.append)
    b.gpg = GpgState(frozenset({PG_PID}), frozenset(), None)
    return b, clock, reads, events


def test_play_games_write_is_read_only_after_it_settles(setup):
    b, clock, reads, events = setup
    b._on_clip_change(5, PG_PID)
    for dt in (0.1, 0.5, 1.0, 1.4):           # Play Games may still be flushing: hands off
        clock["t"] = 100.0 + dt
        b._drain_clipboard_changes()
    assert reads == []
    clock["t"] = 101.6
    b._drain_clipboard_changes()
    assert len(reads) == 1
    assert [e["type"] for e in events] == ["copied"] and events[0]["chars"] == len(EXPORT)


def test_own_writes_are_never_read(setup):
    b, clock, reads, _ = setup
    b._on_clip_change(5, b.own_pid)
    clock["t"] += 10
    b._drain_clipboard_changes()
    assert reads == [] and b.pending == []


def test_superseded_change_is_dropped(setup, monkeypatch):
    b, clock, reads, _ = setup
    b._on_clip_change(4, PG_PID)               # older sequence number than the current (5)
    clock["t"] += 5
    b._drain_clipboard_changes()
    assert reads == []


def test_harmless_write_error_does_not_alert(setup):
    b, clock, _, events = setup
    b._on_clip_change(5, PG_PID)
    clock["t"] = 101.0
    b.pending_errors.append(clock["t"])        # Play Games logged CLIPBRD_E_CANT_OPEN
    clock["t"] = 101.6
    b._drain_clipboard_changes()               # ...but its text arrived
    clock["t"] = 105.0
    b._check_pending_errors()
    assert [e["type"] for e in events] == ["copied"]


def test_real_write_error_alerts_after_delay(setup):
    b, clock, _, events = setup
    b.pending_errors.append(clock["t"])
    b._check_pending_errors()
    assert events == []
    clock["t"] += br.ERROR_REPORT_DELAY + 0.1
    b._check_pending_errors()
    assert [e["type"] for e in events] == ["blocked"] and events[0]["cause"] == "set_error"

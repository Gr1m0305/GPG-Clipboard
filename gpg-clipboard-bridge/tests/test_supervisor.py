"""Supervisor watchdog: Play Games opened/closed repeatedly, already open at start, crash restart, pause."""
import pytest

from gpgbridge import supervisor as sup
from gpgbridge.procdetect import GpgState

OPEN = GpgState(frozenset({100}), frozenset({200}), 200)
CLOSED = GpgState()


class FakeChild:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    @property
    def returncode(self):
        return self.code


@pytest.fixture
def harness(monkeypatch):
    s = sup.Supervisor({"process_poll_seconds": 2.5, "toasts": False, "exports_dir": "x"})
    calls = []
    state = {"now": CLOSED}
    monkeypatch.setattr(sup.procdetect, "scan", lambda: state["now"])

    def start():
        calls.append("start")
        s.child = FakeChild()
        s.child_stopping = False

    def stop():
        if s.child is not None:
            calls.append("stop")
        s.child, s.child_stopping = None, True

    monkeypatch.setattr(s, "_start_child", start)
    monkeypatch.setattr(s, "_stop_child", stop)
    return s, state, calls


def test_already_open_at_startup_starts_bridge(harness):
    s, state, calls = harness
    state["now"] = OPEN
    s._tick()
    assert calls == ["start"]


def test_open_close_cycles(harness):
    s, state, calls = harness
    for now in (CLOSED, OPEN, OPEN, CLOSED, CLOSED, OPEN, CLOSED, OPEN):
        state["now"] = now
        s._tick()
    assert calls == ["start", "stop", "start", "stop", "start"]


def test_closed_sets_waiting_status(harness):
    s, state, _ = harness
    state["now"] = OPEN
    s._tick()
    state["now"] = CLOSED
    s._tick()
    assert s.status == "waiting_play_games"


def test_crashed_bridge_is_restarted_with_backoff(harness, monkeypatch):
    s, state, calls = harness
    clock = {"t": 1000.0}
    monkeypatch.setattr(sup.time, "monotonic", lambda: clock["t"])
    state["now"] = OPEN
    s._tick()
    s.child.code = 1                      # bridge died
    s._tick()
    assert s.status == "error" and calls == ["start"]
    s._tick()                             # still inside back-off window
    assert calls == ["start"]
    clock["t"] += 3
    s._tick()
    assert calls == ["start", "start"]


def test_pause_stops_and_blocks_restart(harness):
    s, state, calls = harness
    state["now"] = OPEN
    s._tick()
    s._toggle_pause()
    s._tick()
    assert calls == ["start", "stop"] and s.status == "paused"
    s._toggle_pause()
    s._tick()
    assert calls == ["start", "stop", "start"]

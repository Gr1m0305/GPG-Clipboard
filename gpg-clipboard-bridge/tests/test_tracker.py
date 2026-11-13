"""Clipboard-change detection and anti-loop logic."""
from gpgbridge.tracker import Action, ClipboardTracker, Origin, classify_origin

PG_EXE = r"C:\Program Files\Google\Play Games\current\service\Service.exe"


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make():
    clock = FakeClock()
    return ClipboardTracker(repeat_window=10, echo_window=120, clock=clock), clock


# --- origin -----------------------------------------------------------------

def test_origin_self():
    assert classify_origin(42, 42, {7}) == Origin.SELF


def test_origin_play_games_by_pid_or_path():
    assert classify_origin(7, 42, {7}) == Origin.PLAY_GAMES
    assert classify_origin(99, 42, set(), owner_exe=PG_EXE) == Origin.PLAY_GAMES


def test_origin_other_app():
    assert classify_origin(99, 42, {7}, owner_exe=r"C:\Windows\notepad.exe") == Origin.OTHER


def test_origin_no_owner_uses_log_evidence():
    assert classify_origin(0, 42, {7}, play_games_wrote_recently=True) == Origin.PLAY_GAMES
    assert classify_origin(0, 42, {7}, play_games_wrote_recently=False) == Origin.UNKNOWN


def test_play_games_services_is_not_play_games():
    svc = r"C:\Program Files\Google\Play Games Services\GooglePlayGamesServices.exe"
    assert classify_origin(99, 42, set(), owner_exe=svc) == Origin.OTHER


# --- change detection ----------------------------------------------------------

def test_new_text_from_play_games_is_reported():
    tr, _ = make()
    d = tr.observe('{"tag":"#ABC"}', Origin.PLAY_GAMES)
    assert d.action == Action.FROM_PLAY_GAMES and d.text == '{"tag":"#ABC"}'


def test_empty_or_non_text_ignored():
    tr, _ = make()
    assert tr.observe(None, Origin.PLAY_GAMES).action == Action.IGNORE
    assert tr.observe("", Origin.PLAY_GAMES).action == Action.IGNORE


def test_repeated_copy_presses_report_once_then_again_later():
    tr, clock = make()
    assert tr.observe("export", Origin.PLAY_GAMES).action == Action.FROM_PLAY_GAMES
    for _ in range(4):                       # user hammering the Copy button
        clock.t += 1
        assert tr.observe("export", Origin.PLAY_GAMES).reason == "repeat"
    clock.t += 30                            # minutes later: a deliberate new copy
    assert tr.observe("export", Origin.PLAY_GAMES).action == Action.FROM_PLAY_GAMES


def test_different_text_is_reported_immediately():
    tr, clock = make()
    tr.observe("a", Origin.PLAY_GAMES)
    clock.t += 1
    assert tr.observe("b", Origin.PLAY_GAMES).action == Action.FROM_PLAY_GAMES


# --- anti-loop -------------------------------------------------------------------

def test_own_writes_are_ignored():
    tr, _ = make()
    tr.note_self_write("from inbox")
    assert tr.observe("from inbox", Origin.SELF).action == Action.IGNORE


def test_own_write_echoed_back_by_play_games_is_ignored():
    tr, clock = make()
    tr.note_self_write("from inbox")
    clock.t += 2      # Play Games synced it to Android, Android echoed it back
    assert tr.observe("from inbox", Origin.PLAY_GAMES).reason == "echo-of-self"


def test_windows_copy_mirrored_back_is_not_from_play_games():
    tr, clock = make()
    assert tr.observe("typed in Discord", Origin.OTHER).action == Action.FROM_WINDOWS
    clock.t += 1
    assert tr.observe("typed in Discord", Origin.PLAY_GAMES).reason == "echo-of-windows"


def test_echo_protection_expires():
    tr, clock = make()
    tr.observe("same text", Origin.OTHER)
    clock.t += 500    # well past echo_window: a genuine in-game copy of identical text
    assert tr.observe("same text", Origin.PLAY_GAMES).action == Action.FROM_PLAY_GAMES


def test_large_unicode_text_round_trips_through_decision():
    tr, _ = make()
    big = '{"tag":"#X","name":"Bäckerei ⚔️ 😀"}' * 3000
    d = tr.observe(big, Origin.PLAY_GAMES)
    assert d.action == Action.FROM_PLAY_GAMES and d.text == big and len(d.text) == len(big)

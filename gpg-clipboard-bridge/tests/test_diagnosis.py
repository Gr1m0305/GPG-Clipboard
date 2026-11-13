"""Diagnosis of dropped copies, reproducing the state recorded on 2026-11-13 16:38."""
from gpgbridge.diagnosis import diagnose_block, is_tracking_stuck
from gpgbridge.gpglog import WindowState
from gpgbridge.win32 import WindowInfo

GAME = WindowInfo(200350, 19252, "HwndWrapper[DefaultDomain;;x]", "Clash of Clans - P", True, False, (-7, -7, 1927, 1087))
DISCORD = WindowInfo(66590, 13544, "Chrome_WidgetWin_1", "Discord", True, False, (-1928, 57, 8, 1113))
HIDDEN_SURFACE = WindowState(200340, 200354, "HIDDEN", "FULLSCREEN", 1280, 1024)
HEALTHY = WindowState(200336, 200350, "NORMAL", "FULLSCREEN", 1920, 1080)


def test_stuck_after_display_change():
    assert is_tracking_stuck(HIDDEN_SURFACE, [GAME])


def test_healthy_is_not_stuck():
    assert not is_tracking_stuck(HEALTHY, [GAME])


def test_unknown_state_or_no_game_window_is_not_stuck():
    assert not is_tracking_stuck(None, [GAME])
    assert not is_tracking_stuck(HIDDEN_SURFACE, [])


def test_block_with_game_in_front_but_wrong_tracked_window():
    d = diagnose_block("not_foreground", GAME, HIDDEN_SURFACE, [GAME])
    assert d["cause"] == "tracked_window_mismatch"
    assert d["foreground_is_game"] and d["tracked_window"] == 200354
    assert "launch it again" in d["advice"]


def test_block_when_game_really_was_not_in_front():
    d = diagnose_block("not_foreground", DISCORD, HEALTHY, [GAME])
    assert d["cause"] == "game_not_foreground"


def test_block_with_minimized_tracking():
    minimized = WindowState(200336, 200350, "MINIMIZED", "FULLSCREEN", 1920, 1080)
    assert diagnose_block("not_foreground", GAME, minimized, [GAME])["cause"] == "tracked_window_not_normal"


def test_emulator_not_running_reason():
    assert diagnose_block("emulator_not_running", GAME, HEALTHY, [GAME])["cause"] == "emulator_not_running"

"""Explain why Play Games dropped an Android -> Windows copy, and spot the 'stuck' state early."""
from __future__ import annotations

from .gpglog import WindowState
from .win32 import WindowInfo

FIX_RELAUNCH = ("Close the game (not just the Play Games window) and launch it again from Play Games, "
                "then press Copy again.")


def is_tracking_stuck(tracked: WindowState | None, game_windows: list[WindowInfo]) -> bool:
    """True when Play Games tracks a window other than the visible game window.

    Seen after a host display change: the last WindowState reported is a hidden
    off-screen surface, and from then on every copy is dropped as 'not foreground'.
    """
    if tracked is None or not game_windows:
        return False
    visible = {w.hwnd for w in game_windows}
    if tracked.window_handle not in visible:
        return True
    return tracked.visibility.upper() == "HIDDEN"


def diagnose_block(reason: str, foreground: WindowInfo | None, tracked: WindowState | None,
                   game_windows: list[WindowInfo]) -> dict:
    visible = {w.hwnd for w in game_windows}
    fg_is_game = bool(foreground and foreground.hwnd in visible)
    info = {
        "reason": reason,
        "foreground_hwnd": foreground.hwnd if foreground else 0,
        "foreground_class": foreground.cls if foreground else "",
        "foreground_is_game": fg_is_game,
        "tracked_window": tracked.window_handle if tracked else 0,
        "tracked_visibility": tracked.visibility if tracked else "",
        "tracked_size": f"{tracked.width}x{tracked.height}" if tracked else "",
        "game_windows": sorted(visible),
    }
    if reason == "emulator_not_running":
        info.update(cause="emulator_not_running", advice="Play Games says the emulator is not running. Restart the game.")
    elif reason != "not_foreground":
        info.update(cause=reason, advice="Press Copy again. If it keeps failing, restart the game.")
    elif fg_is_game and tracked and tracked.window_handle != foreground.hwnd:
        info.update(cause="tracked_window_mismatch",
                    advice="Play Games lost track of the game window after a display change. " + FIX_RELAUNCH)
    elif fg_is_game and tracked and tracked.visibility.upper() != "NORMAL":
        info.update(cause="tracked_window_not_normal",
                    advice=f"Play Games thinks the game window is {tracked.visibility.lower()}. " + FIX_RELAUNCH)
    elif not fg_is_game:
        info.update(cause="game_not_foreground",
                    advice="Keep the game window focused when you press Copy. If it was focused: " + FIX_RELAUNCH)
    else:
        info.update(cause="unknown", advice=FIX_RELAUNCH)
    return info

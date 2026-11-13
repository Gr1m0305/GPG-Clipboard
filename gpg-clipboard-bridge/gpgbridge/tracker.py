"""Pure decision logic: where did a clipboard change come from, and should we act on it?

Anti-loop rules
* Our own writes (inbox loads) are ignored, including when Play Games syncs them
  to Android and Android echoes them back through Play Games.
* Text that first appeared on the Windows side and is then mirrored back by
  Play Games (Windows -> Android -> Windows echo) is not reported as "from Play Games".
* Repeated presses of the in-game Copy button within `repeat_window` seconds
  give one notification, not five.
"""
from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .procdetect import is_play_games_path


class Origin(str, Enum):
    PLAY_GAMES = "play_games"
    SELF = "self"
    OTHER = "other"
    UNKNOWN = "unknown"   # clipboard has no owner window; decided with log evidence


def classify_origin(owner_pid: int, own_pid: int, play_games_pids, owner_exe: str | None = None,
                    play_games_wrote_recently: bool = False) -> Origin:
    if owner_pid and owner_pid == own_pid:
        return Origin.SELF
    if owner_pid and (owner_pid in play_games_pids or is_play_games_path(owner_exe)):
        return Origin.PLAY_GAMES
    if not owner_pid:
        return Origin.PLAY_GAMES if play_games_wrote_recently else Origin.UNKNOWN
    return Origin.OTHER


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


class Action(str, Enum):
    IGNORE = "ignore"
    FROM_PLAY_GAMES = "from_play_games"   # new text copied inside Android -> report + save
    FROM_WINDOWS = "from_windows"         # copied in a Windows app (Play Games syncs it to Android itself)


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    text: str | None = None


class ClipboardTracker:
    def __init__(self, repeat_window: float = 10.0, echo_window: float = 120.0,
                 clock: Callable[[], float] = time.monotonic, history: int = 32):
        self.repeat_window = repeat_window
        self.echo_window = echo_window
        self.clock = clock
        self._self_written: deque[tuple[str, float]] = deque(maxlen=history)
        self._windows_side: deque[tuple[str, float]] = deque(maxlen=history)
        self._last_pg: tuple[str, float] | None = None

    def note_self_write(self, text: str) -> None:
        """Call before writing to the clipboard ourselves."""
        self._self_written.append((text_hash(text), self.clock()))

    def _recent(self, hist, h: str) -> bool:
        now = self.clock()
        return any(hh == h and now - t <= self.echo_window for hh, t in hist)

    def observe(self, text: str | None, origin: Origin) -> Decision:
        if text is None or text == "":
            return Decision(Action.IGNORE, "empty-or-not-text")
        h = text_hash(text)
        now = self.clock()

        if origin == Origin.SELF:
            return Decision(Action.IGNORE, "self-write")

        if origin in (Origin.OTHER, Origin.UNKNOWN):
            if self._recent(self._self_written, h):
                return Decision(Action.IGNORE, "echo-of-self")
            self._windows_side.append((h, now))
            return Decision(Action.FROM_WINDOWS, "windows-copy", text)

        # Origin.PLAY_GAMES
        if self._recent(self._self_written, h):
            return Decision(Action.IGNORE, "echo-of-self")
        if self._recent(self._windows_side, h):
            return Decision(Action.IGNORE, "echo-of-windows")
        if self._last_pg and self._last_pg[0] == h and now - self._last_pg[1] <= self.repeat_window:
            self._last_pg = (h, now)
            return Decision(Action.IGNORE, "repeat")
        self._last_pg = (h, now)
        return Decision(Action.FROM_PLAY_GAMES, "android-copy", text)

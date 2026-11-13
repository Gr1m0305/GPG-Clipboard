"""Save Play Games copies as files (export.json for the bot's /import) and watch an inbox folder."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Top-level keys seen in Clash of Clans "Data Export" JSON. Matching two or more of
# these (plus a "tag") marks the text as a village export. Used for wording only.
VILLAGE_KEYS = {"tag", "timestamp", "helpers", "guardians", "buildings", "buildings2", "traps", "traps2",
                "decos", "obstacles", "units", "units2", "siege_machines", "heroes", "heroes2", "spells",
                "pets", "equipment", "house_parts", "skins", "sceneries", "boosts"}


def parse_json(text: str):
    s = text.lstrip("﻿").strip()
    if not s or s[0] not in "{[":
        return None
    try:
        return json.loads(s)
    except ValueError:
        return None


def is_village_export(obj) -> bool:
    return isinstance(obj, dict) and "tag" in obj and len(VILLAGE_KEYS & set(obj)) >= 3


def describe(text: str) -> dict:
    obj = parse_json(text)
    return {"chars": len(text), "json": obj is not None, "village": is_village_export(obj)}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # newline="" + utf-8: the bytes on disk are exactly the clipboard text, no truncation or CRLF rewriting
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


class ExportStore:
    def __init__(self, directory: str | Path, keep: int = 20):
        self.dir = Path(directory)
        self.keep = keep

    def save(self, text: str, source: str = "play_games", now: datetime | None = None) -> dict:
        now = now or datetime.now()
        info = describe(text)
        out = {"latest": str(self.dir / "latest.txt"), **info}
        _atomic_write(self.dir / "latest.txt", text)
        if info["json"]:
            _atomic_write(self.dir / "export.json", text)
            stamp = now.strftime("%Y%m%d-%H%M%S")
            hist = self.dir / "history" / f"export-{stamp}-{source}.json"
            _atomic_write(hist, text)
            out.update(export=str(self.dir / "export.json"), history=str(hist))
            self._prune()
        return out

    def _prune(self) -> None:
        hist = sorted((self.dir / "history").glob("export-*.json"))
        for old in hist[: max(0, len(hist) - self.keep)]:
            try:
                old.unlink()
            except OSError:
                pass


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


@dataclass
class _Seen:
    size: int
    mtime: float
    since: float


class InboxWatcher:
    """Polling folder watcher: yields files that appeared after start and stopped growing."""

    def __init__(self, dirs, extensions=(".json", ".txt"), settle_seconds: float = 1.0, clock=time.monotonic):
        self.dirs = [Path(d) for d in dirs]
        self.ext = {e.lower() for e in extensions}
        self.settle = settle_seconds
        self.clock = clock
        self._known: dict[Path, tuple[int, float]] = {}
        self._pending: dict[Path, _Seen] = {}
        for d in self.dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        for p, st in self._scan():
            self._known[p] = (st.st_size, st.st_mtime)  # existing files are not re-imported

    def _scan(self):
        for d in self.dirs:
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_file() and Path(e.name).suffix.lower() in self.ext:
                            yield Path(e.path), e.stat()
            except OSError:
                continue

    def poll(self) -> list[Path]:
        now = self.clock()
        ready = []
        for p, st in self._scan():
            sig = (st.st_size, st.st_mtime)
            if self._known.get(p) == sig:
                continue
            seen = self._pending.get(p)
            if seen is None or (seen.size, seen.mtime) != sig:
                self._pending[p] = _Seen(st.st_size, st.st_mtime, now)
                continue
            if now - seen.since >= self.settle and st.st_size > 0:
                ready.append(p)
                self._known[p] = sig
                del self._pending[p]
        return ready

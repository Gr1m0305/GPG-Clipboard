"""Export saving (exact bytes, JSON detection, history) and the inbox watcher."""
import json
from datetime import datetime, timedelta

from gpgbridge.exports import ExportStore, InboxWatcher, describe, is_village_export, read_text_file

VILLAGE = {"tag": "#2PP", "timestamp": 1794553000, "buildings": [{"data": 1000001, "lvl": 15}],
           "units": [], "heroes": [], "spells": []}


def test_describe_detects_village_export():
    text = json.dumps(VILLAGE)
    assert describe(text) == {"chars": len(text), "json": True, "village": True}
    assert describe("hello")["json"] is False
    assert not is_village_export({"tag": "#X"})


def test_save_writes_exact_text_and_export_json(tmp_path):
    store = ExportStore(tmp_path)
    # not valid JSON because of the trailing words -> only latest.txt is written
    text = json.dumps(VILLAGE, ensure_ascii=False, indent=1).replace("\n", "\r\n") + " Bäckerei ⚔️"
    out = store.save(text)
    assert (tmp_path / "latest.txt").read_bytes() == text.encode("utf-8")
    assert "export" not in out

    valid = json.dumps(dict(VILLAGE, name="Bäckerei ⚔️ 😀"), ensure_ascii=False).replace(",", ",\r\n")
    out = store.save(valid)
    assert (tmp_path / "export.json").read_bytes() == valid.encode("utf-8")   # CRLF and UTF-8 preserved
    assert out["village"] is True and out["export"].endswith("export.json")


def test_history_is_pruned(tmp_path):
    store = ExportStore(tmp_path, keep=3)
    t0 = datetime(2026, 11, 13, 12, 0, 0)
    for i in range(6):
        store.save(json.dumps({"tag": "#X", "i": i}), now=t0 + timedelta(seconds=i))
    hist = sorted((tmp_path / "history").glob("*.json"))
    assert len(hist) == 3 and hist[-1].name == "export-20261113-120005-play_games.json"


def test_large_text_is_not_truncated(tmp_path):
    big = json.dumps({"tag": "#X", "buildings": ["x" * 50] * 5000})
    assert len(big) > 250_000
    ExportStore(tmp_path).save(big)
    assert (tmp_path / "export.json").read_text(encoding="utf-8") == big


def test_read_text_file_handles_boms(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes("﻿{\"a\": \"ü\"}".encode("utf-8"))
    assert read_text_file(p) == '{"a": "ü"}'
    p.write_bytes('{"a": "ü"}'.encode("utf-16"))
    assert read_text_file(p) == '{"a": "ü"}'


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_inbox_picks_up_new_stable_files_only(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "old.json").write_text("{}", encoding="utf-8")
    clock = Clock()
    w = InboxWatcher([inbox], settle_seconds=1.0, clock=clock)
    assert w.poll() == []                              # pre-existing file ignored
    (inbox / "village.json").write_text(json.dumps(VILLAGE), encoding="utf-8")
    (inbox / "notes.md").write_text("ignored extension", encoding="utf-8")
    assert w.poll() == []                              # first sighting: wait for it to settle
    clock.t += 1.5
    assert [p.name for p in w.poll()] == ["village.json"]
    clock.t += 5
    assert w.poll() == []                              # not imported twice

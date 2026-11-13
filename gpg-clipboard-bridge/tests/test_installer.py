"""Installer pieces that don't touch the real system: task XML, Apps & features values, fallbacks, frozen paths."""
import datetime as dt
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from gpgbridge import __version__, installer, runtime

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
DAY = dt.date(2026, 11, 13)


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])  # ElementTree rejects the UTF-16 declaration on a str


def test_task_xml_logon_and_repeat():
    cmd = installer.installed_command(Path(r"C:\Users\A & B\AppData\Local\Programs\GPG Clipboard Bridge"))
    root = parse(installer.task_xml(cmd, r"PC\A & B", today=DAY))
    assert root.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text == r"PC\A & B"
    rep = root.find("t:Triggers/t:TimeTrigger/t:Repetition", NS)
    assert rep.find("t:Interval", NS).text == "PT5M"
    assert rep.find("t:StopAtDurationEnd", NS).text == "false"
    assert root.find("t:Triggers/t:TimeTrigger/t:StartBoundary", NS).text == "2026-11-13T00:00:00"
    s = root.find("t:Settings", NS)
    assert s.find("t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    assert s.find("t:ExecutionTimeLimit", NS).text == "PT0S"
    assert s.find("t:DisallowStartIfOnBatteries", NS).text == "false"
    p = root.find("t:Principals/t:Principal", NS)
    assert p.find("t:LogonType", NS).text == "InteractiveToken"
    assert p.find("t:RunLevel", NS).text == "LeastPrivilege"
    ex = root.find("t:Actions/t:Exec", NS)
    assert ex.find("t:Command", NS).text.endswith(r"A & B\AppData\Local\Programs\GPG Clipboard Bridge\GPGClipboardBridge.exe")
    assert ex.find("t:Arguments", NS).text == "supervisor"


def test_task_xml_without_logon_trigger():
    cmd = installer.StartCommand(r"C:\x\GPGClipboardBridge.exe", "supervisor", r"C:\x")
    root = parse(installer.task_xml(cmd, r"PC\me", logon_trigger=False, today=DAY))
    assert root.find("t:Triggers/t:LogonTrigger", NS) is None
    assert root.find("t:Triggers/t:TimeTrigger", NS) is not None


def test_uninstall_values():
    v = installer.uninstall_values(Path(r"C:\P\GPG Clipboard Bridge"), 35000, today=DAY)
    assert v["DisplayName"] == "GPG Clipboard Bridge" and v["DisplayVersion"] == __version__
    assert v["UninstallString"] == r'"C:\P\GPG Clipboard Bridge\GPGClipboardBridge.exe" uninstall'
    assert v["QuietUninstallString"].endswith("uninstall --quiet")
    assert v["InstallDate"] == "20261113" and v["EstimatedSize"] == 35000
    assert v["NoModify"] == 1 and v["NoRepair"] == 1


def test_run_command_line_is_quoted():
    cmd = installer.StartCommand(r"C:\Program Files\X\GPGClipboardBridge.exe", "supervisor", r"C:\Program Files\X")
    assert cmd.command_line == r'"C:\Program Files\X\GPGClipboardBridge.exe" supervisor'


@pytest.mark.parametrize("logon_ok, repeat_ok, expected, run_key", [
    (True, True, "task", False),
    (False, True, "run-key+task", True),
    (False, False, "run-key", True),
])
def test_register_startup_falls_back_to_run_key(monkeypatch, logon_ok, repeat_ok, expected, run_key):
    calls = {"run": None}
    monkeypatch.setattr(installer, "register_task", lambda cmd, logon_trigger=True: logon_ok if logon_trigger else repeat_ok)
    monkeypatch.setattr(installer, "set_run_value", lambda cmd: calls.__setitem__("run", "set"))
    monkeypatch.setattr(installer, "delete_run_value", lambda: calls.__setitem__("run", "deleted"))
    cmd = installer.StartCommand("x.exe", "supervisor", ".")
    assert installer.register_startup(cmd) == expected
    assert calls["run"] == ("set" if run_key else "deleted")


def test_copy_program_refuses_foreign_folder(tmp_path):
    src = tmp_path / "payload"
    src.mkdir()
    (src / "GPGClipboardBridge.exe").write_bytes(b"MZ")
    dst = tmp_path / "Documents"
    dst.mkdir()
    (dst / "thesis.docx").write_text("precious")
    with pytest.raises(installer.InstallError):
        installer.copy_program(src, dst)
    assert (dst / "thesis.docx").exists()


def test_copy_program_replaces_old_install(tmp_path):
    src = tmp_path / "payload"
    (src / "_internal").mkdir(parents=True)
    (src / "GPGClipboardBridge.exe").write_bytes(b"new")
    dst = tmp_path / "GPG Clipboard Bridge"
    (dst / "_internal").mkdir(parents=True)
    (dst / "GPGClipboardBridge.exe").write_bytes(b"old")
    (dst / "_internal" / "stale.pyd").write_bytes(b"x")
    installer.copy_program(src, dst)
    assert (dst / "GPGClipboardBridge.exe").read_bytes() == b"new"
    assert not (dst / "_internal" / "stale.pyd").exists()


def test_self_command_source_and_frozen(monkeypatch, tmp_path):
    assert runtime.self_command("bridge", "--ipc")[1:] == ["-m", "gpgbridge", "bridge", "--ipc"]
    exe = tmp_path / "GPGClipboardBridge.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert runtime.self_command("bridge", "--ipc") == [str(exe), "bridge", "--ipc"]
    assert runtime.app_root() == tmp_path
    assert installer.current_command() == installer.StartCommand(str(exe), "supervisor", str(tmp_path))

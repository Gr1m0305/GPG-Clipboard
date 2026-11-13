"""Configuration: defaults + optional %LOCALAPPDATA%\\gpg-clipboard-bridge\\config.json overrides."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import APP_ID

log = logging.getLogger(__name__)


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_ID


FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"
FOLDERID_PROGRAMS = "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"            # Start menu\Programs (this user)
FOLDERID_USER_PROGRAM_FILES = "{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}"  # %LOCALAPPDATA%\Programs


def known_folder(folder_id: str) -> str | None:
    """SHGetKnownFolderPath for the current user (follows OneDrive / folder redirection)."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        import uuid

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        guid = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wt.DWORD, wt.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        out = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ole32.CoTaskMemFree(out)
            return path or None
    except (OSError, AttributeError, ValueError):
        pass
    return None


def documents_dir() -> str:
    """The real Documents folder (follows OneDrive/known-folder redirection)."""
    return known_folder(FOLDERID_DOCUMENTS) or str(Path.home() / "Documents")


DEFAULTS: dict = {
    # supervisor
    "process_poll_seconds": 2.5,
    "toasts": True,
    # bridge
    "log_poll_seconds": 0.5,
    "play_games_log_dir": r"%LOCALAPPDATA%\Google\Play Games\Logs",
    "repeat_window_seconds": 10,
    "two_way": False,            # report Windows -> Android syncs (Play Games does the sync itself)
    # exports / fallback
    "save_exports": True,
    "exports_dir": r"{documents}\GPG Clipboard Exports",
    "history_keep": 20,
    "inbox_enabled": True,
    "inbox_dirs": [r"{exports_dir}\inbox"],
    "inbox_extensions": [".json", ".txt"],
    "inbox_load_to_clipboard": True,
}


def _expand(value):
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load(path: Path | None = None, write_default: bool = True) -> dict:
    if path is None and os.environ.get("GPGBRIDGE_CONFIG"):
        path, write_default = Path(os.environ["GPGBRIDGE_CONFIG"]), False
    path = path or data_dir() / "config.json"
    cfg = dict(DEFAULTS)
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable config %s: %s", path, exc)
    elif write_default:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = {"_comment": "Edit, then restart the helper: tray > Quit, then start it again "
                                   "(Start menu, start.ps1, or log off and on)."}
            doc.update(DEFAULTS)
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        except OSError:
            pass
    cfg = {k: _expand(v) for k, v in cfg.items()}
    if "{documents}" in cfg["exports_dir"]:
        cfg["exports_dir"] = cfg["exports_dir"].replace("{documents}", documents_dir())
    cfg["inbox_dirs"] = [d.replace("{exports_dir}", cfg["exports_dir"]) for d in cfg.get("inbox_dirs", [])]
    cfg["service_log"] = os.path.join(cfg["play_games_log_dir"], "Service.log")
    return cfg

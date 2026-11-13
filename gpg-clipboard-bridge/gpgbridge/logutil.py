"""Rotating file logging (supervisor) and JSON-over-stdout logging (bridge child process)."""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path

from .config import data_dir

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def log_file() -> Path:
    return data_dir() / "logs" / "gpg-clipboard-bridge.log"


def setup_file_logging(level=logging.INFO) -> Path:
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    if sys.stderr is not None:  # console runs (not pythonw)
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(console)
    return path


class JsonLineHandler(logging.Handler):
    """Bridge -> supervisor: each record becomes {"type":"log",...} on stdout."""

    def __init__(self, emit_fn):
        super().__init__()
        self._emit_fn = emit_fn

    def emit(self, record):
        try:
            self._emit_fn({"type": "log", "level": record.levelno, "name": record.name,
                           "msg": self.format(record)})
        except Exception:  # pragma: no cover
            self.handleError(record)


def setup_console_logging(level=logging.INFO) -> None:
    logging.basicConfig(level=level, format=FORMAT)


def json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=True, default=str)

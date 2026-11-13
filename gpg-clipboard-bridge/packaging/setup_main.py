"""Entry point of GPGClipboardBridge-Setup.exe (PyInstaller, onefile, windowed).

The finished program folder (GPGClipboardBridge.exe + _internal) is bundled as data under payload/ and
copied to %LOCALAPPDATA%\\Programs\\GPG Clipboard Bridge by gpgbridge.installer.install().

  GPGClipboardBridge-Setup.exe [/S | --silent] [--no-start] [--dir PATH]

For testing from source: python packaging/setup_main.py --payload <built program folder>
"""
import sys
from pathlib import Path

from gpgbridge.installer import setup_main


def main(argv: list[str]) -> int:
    payload = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "payload"
    if "--payload" in argv:
        i = argv.index("--payload")
        payload = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    return setup_main(argv, payload)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Entry point of GPGClipboardBridge.exe (PyInstaller, onedir, windowed). Same CLI as `python -m gpgbridge`."""
import sys

from gpgbridge.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

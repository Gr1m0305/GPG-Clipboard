"""Writes the build-time assets into OUT_DIR: icon.ico and PyInstaller version-resource files.

    python packaging/build_assets.py OUT_DIR
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gpgbridge import APP_NAME, __version__  # noqa: E402
from gpgbridge.supervisor import make_icon_image  # noqa: E402

VERSION_TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Gr1m0305'),
      StringStruct('FileDescription', {desc!r}),
      StringStruct('FileVersion', {ver!r}),
      StringStruct('InternalName', {internal!r}),
      StringStruct('OriginalFilename', {filename!r}),
      StringStruct('ProductName', {product!r}),
      StringStruct('ProductVersion', {ver!r})])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version_tuple(ver: str) -> tuple:
    nums = [int(x) for x in ver.split(".")[:4] if x.isdigit()]
    return tuple((nums + [0, 0, 0, 0])[:4])


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    img = make_icon_image((40, 170, 90), size=256)
    img.save(out / "icon.ico", format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for internal, filename, desc in (
        ("GPGClipboardBridge", "GPGClipboardBridge.exe", f"{APP_NAME} (Google Play Games clipboard helper)"),
        ("GPGClipboardBridge-Setup", "GPGClipboardBridge-Setup.exe", f"{APP_NAME} Setup"),
    ):
        (out / f"version-{internal}.txt").write_text(VERSION_TEMPLATE.format(
            tup=version_tuple(__version__), ver=__version__, desc=desc, internal=internal, filename=filename,
            product=APP_NAME), encoding="utf-8")
    print(f"assets for {__version__} written to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

# GPG Clipboard Bridge

Gets text you copy inside **Google Play Games for PC** (for example Clash of Clans → Settings → More Settings →
Data Export → **Copy to clipboard**) onto the **Windows** clipboard, so you can paste it into Discord. It also
saves every export as `export.json`, ready to attach to your bot's `/import`.

It starts by itself at Windows logon, sits in the system tray using almost no CPU, and switches on whenever
Google Play Games is open. You never launch it by hand.

**Download:** [GPGClipboardBridge-Setup.exe](https://github.com/Gr1m0305/GPG-Clipboard/releases/latest/download/GPGClipboardBridge-Setup.exe)
(latest release, Windows 10/11, nothing else to install). See [Install](#install).

## How it works (and why it is built this way)

Investigated on this PC with Play Games Beta 26.10.842.1 (details in [PROGRESS.md](PROGRESS.md)):

* **Play Games already has two-way clipboard sharing, and it is on by default.** Windows → Android always works.
  Android → Windows works too, but Play Games only accepts it while it thinks the game window is in front.
* After a **display change** (moving the game to another monitor, a monitor waking or reconnecting, or a
  resolution change), Play Games can start tracking a hidden off-screen window instead of the game. From then on
  it silently drops every in-game copy ("Emulator window is not foreground"). That is why "Copy to clipboard"
  seemed to do nothing.
* ADB is switched off in the consumer client and you can't install your own APK, so a third-party Android-side
  bridge is impossible without bypassing Google's protections. This tool does not bypass anything.

So the helper:

1. **Watches the Windows clipboard.** When Play Games writes text from the game, you get a notification
   "Copied 41,203 characters from Play Games", and the text is saved as `export.json` / `latest.txt`.
2. **Reads Play Games' log (read-only).** When Play Games drops a copy, you get "Play Games blocked the copy"
   with the exact fix. When it spots the stuck state early, the tray icon turns orange and warns you before you
   press Copy.
3. **Provides a file fallback:** `export.json`, an inbox folder, and "Copy last export to clipboard".

It never touches the game or the Play Games process. No injection, no memory reading, no input automation, no
modified files, nothing sent over the network.

## Install

### Download the installer (recommended)

Requirements: Windows 10 or 11 and Google Play Games for PC. Python is **not** needed.

1. Download **GPGClipboardBridge-Setup.exe** from the
   [latest release](https://github.com/Gr1m0305/GPG-Clipboard/releases/latest).
2. Double-click it. The exe is not code-signed, so Windows may show **"Windows protected your PC"**: click
   **More info → Run anyway**. (Your browser may also ask whether to keep the download: choose **Keep**.)
3. Click **Yes** to install. It installs for your Windows account only, with **no admin rights**, and:
   * copies the program to `%LOCALAPPDATA%\Programs\GPG Clipboard Bridge`
   * makes it **start automatically every time you sign in** (Scheduled Task *GPG Clipboard Bridge*, at logon
     and re-checked every 5 minutes; on PCs where that is not allowed, an entry in your Startup apps instead)
   * adds **GPG Clipboard Bridge** to the Start menu, and an entry in **Settings → Apps** for uninstalling
   * starts it right away
4. A clipboard icon appears in the system tray. It may be hidden under the **^** arrow next to the clock;
   drag it onto the taskbar to keep it visible.

That's it. To update, download the new Setup and run it: it replaces the old version and keeps your settings.

Silent install (for scripts): `GPGClipboardBridge-Setup.exe /S` (add `--no-start` to install without starting).

### Install from source (developers)

Requirements: **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/windows/), tick *Add
python.exe to PATH*, or `winget install -e --id Python.Python.3.12`).

1. Put the `gpg-clipboard-bridge` folder somewhere permanent. If it is inside OneDrive, right-click it →
   **Always keep on this device**.
2. Open PowerShell in that folder and run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   This creates a private Python environment in `%LOCALAPPDATA%\gpg-clipboard-bridge\venv`, installs psutil,
   pystray and Pillow, registers the same Scheduled Task **GPG Clipboard Bridge** (at logon, your user, hidden,
   no console), and starts it. No admin rights are normally needed; if Windows insists, it asks once.

Use one or the other. Both register the same task, so whichever you installed last is the one that starts.

### One-time Play Games / ADB settings

**None.** Clipboard sharing is built into Play Games and enabled by default. There is no ADB or developer
setting to switch on in the consumer client. ADB only exists in Google's separate *Developer Emulator*, which
is not needed. Neither installer downloads ADB or installs an APK.

## Test it

1. Open Google Play Games and start Clash of Clans. The tray tooltip changes to **Connected (Clash of Clans)**
   (green icon).
2. In the game: **Settings → More Settings → Data Export → Copy to clipboard**.
3. A notification appears: **"Copied N characters from Play Games"**.
4. Open Notepad and press **Ctrl+V**. The whole export is there. It is also saved in
   `Documents\GPG Clipboard Exports\export.json`.
5. Optional: copy text in Notepad and paste it into a text box in the game (Windows → Android, built into Play Games).

If step 3 says **"Play Games blocked the copy"**, see Troubleshooting. Tray icon → **Health check** gives a
report at any time (from a source install, `.\diagnose.ps1` does the same in the console).

### Getting it into Discord

* Short text: paste it.
* A full village export is usually longer than Discord allows in a message or slash-command text option
  (slash-command text options max out at 6,000 characters). Attach
  `Documents\GPG Clipboard Exports\export.json` as a file to `/import` instead. It is always the newest export.

## Tray menu

| Item | Does |
|------|------|
| Status | Waiting for Play Games / waiting for the game / **Connected** / Connected, but clipboard sharing looks stuck / Paused |
| Pause | Stops the bridge until you un-pause (Play Games' own sharing keeps working, you just get no notifications or saved files) |
| Open log | `%LOCALAPPDATA%\gpg-clipboard-bridge\logs\gpg-clipboard-bridge.log` (rotating, 5 × 1 MB) |
| Open exports folder | `Documents\GPG Clipboard Exports` |
| Copy last export to clipboard | Puts `export.json` back on the clipboard |
| Health check | Opens a report in Notepad: Play Games state, clipboard-sharing counters, whether it is stuck, start-up registration |
| Start with Windows | On by default. Untick it to stop the helper from starting at logon (it keeps running until you quit) |
| About | Opens the project page |
| Quit | Stops the helper until your next logon. To start it again sooner: Start menu → **GPG Clipboard Bridge** (source install: `.\start.ps1`) |

<!-- FALLBACK-START -->
## Fallback: export.json and the inbox folder

The live path depends on Play Games' own clipboard sharing, and Play Games sometimes drops copies (see
Troubleshooting). For that case, the helper also keeps files you can always use. It runs automatically while
Play Games is open, with nothing to start.

**Folder:** `Documents\GPG Clipboard Exports` (tray icon → **Open exports folder**)

| File | What it is |
|------|------------|
| `export.json` | The newest JSON export (from the game, or from the inbox). Attach it to `/import` as a file. |
| `latest.txt` | The newest text copied in Play Games, JSON or not. |
| `history\export-<date>-<time>-<source>.json` | The last 20 exports. |
| `inbox\` | Drop an export file here and it is loaded onto the clipboard and saved as `export.json`. |

### Steps: get the export as a file for `/import`

1. In Clash of Clans on Play Games: **Settings → More Settings → Data Export → Copy to clipboard**.
2. Watch for the Windows notification **"Copied N characters from Play Games"**.
   * If it says **"Play Games blocked the copy"**, close the game (not just the Play Games window), launch it again
     from Play Games, and press **Copy to clipboard** again.
3. In Discord, run `/import` and either paste (Ctrl+V), or attach `Documents\GPG Clipboard Exports\export.json`.
4. Copied something else since? Tray icon → **Copy last export to clipboard** puts the export back.

### Steps: the export comes from somewhere else (phone, another PC)

Play Games for PC has no shared folder, ADB or file transfer, so a file cannot come straight from the Android
side. If you can't get the copy through Play Games, export on your **phone** instead and send the text to the PC:

1. On the phone, in Clash of Clans: **Settings → More Settings → Data Export → Copy to clipboard**.
2. Paste it into anything that gets it to the PC as a file or text, for example Google Keep, a message to
   yourself, Phone Link, or Quick Share.
3. Save it on the PC as a `.json` or `.txt` file in `Documents\GPG Clipboard Exports\inbox\`.
4. Within about 2 seconds you get **"Loaded <file>"**: the text is on the clipboard and in `export.json`.

Files already in the inbox when the helper starts are not re-imported. Change or re-save a file to import it again.

*Why not screenshots?* An export is tens of thousands of characters of JSON. A screenshot cannot hold it
reliably, so screenshots are not used.
<!-- FALLBACK-END -->

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Notification **"Play Games blocked the copy"**, or the tray says *clipboard sharing looks stuck* (orange icon) | Play Games lost track of the game window after a display change and drops Android → Windows copies | **Close the game window** so the game exits and **launch it again from Play Games**, then press Copy again. If that doesn't help, quit Play Games completely (tray icon → Quit) and reopen it. Avoid moving the game between monitors before copying. |
| "Play Games blocked the copy", advice says *keep the game window focused* | Another window was in front when the copy arrived | Click into the game, then press Copy. |
| No notification at all after pressing Copy | Helper not running, or Play Games never received the copy | Check the tray icon. If it's missing, open **GPG Clipboard Bridge** from the Start menu. Tray → **Health check**: if `a2w_received` did not go up, Play Games did not get the copy from the game (try again, or update Play Games). |
| Tray icon missing after logon | Start with Windows switched off, you chose Quit earlier, or (source install) Python moved | Open **GPG Clipboard Bridge** from the Start menu, then tray → make sure **Start with Windows** is ticked. Source install: `.\start.ps1`, and re-run `setup.ps1` if you moved the folder or reinstalled Python. |
| "Windows protected your PC" when running Setup | The exe is not code-signed, so SmartScreen does not know it yet | **More info → Run anyway**. Compare the file's SHA-256 with `SHA256SUMS.txt` on the release page if you want to check it is the original. |
| Antivirus quarantines the exe | Some scanners flag unsigned PyInstaller-built programs | Restore it / add an exception, or install from source instead. |
| Pasted export is cut off in Discord | Discord's length limit, not the helper (the clipboard holds everything, check in Notepad) | Attach `export.json` instead. |
| `setup.ps1` says Python not found | Python missing, or only the Microsoft Store alias exists | Install Python from python.org with *Add to PATH*, or pass `-Python C:\path\to\python.exe`. |
| "running scripts is disabled on this system" | PowerShell execution policy | Use `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. |
| Inbox file not picked up | Wrong folder or extension, or the file was already there at start-up | Use `Documents\GPG Clipboard Exports\inbox`, `.json` or `.txt`. Re-save the file to import it again. |
| Helper fails at logon from a OneDrive folder | Files On-Demand removed the local copy | Right-click the folder → *Always keep on this device*. |

The log (tray → **Open log**) records every drop with a diagnosis line such as
`Play Games DROPPED an in-game copy ... cause=tracked_window_mismatch, foreground_hwnd=…, tracked_window=…`.

## Uninstall

**Installed with Setup:** Settings → Apps → **GPG Clipboard Bridge** → Uninstall. This stops the helper and
removes the program, the start-up task, the Start-menu shortcut, logs and settings. Your exports in
`Documents\GPG Clipboard Exports` are never deleted.

**Source install:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

This removes the Scheduled Task and stops the helper. Add `-RemoveData` to also delete
`%LOCALAPPDATA%\gpg-clipboard-bridge` (venv, logs, config). Your exports are never deleted.

## Configuration

`%LOCALAPPDATA%\gpg-clipboard-bridge\config.json` is created on first run. To apply changes, tray → Quit, then
start it again from the Start menu (source install: `.\start.ps1`).

| Key | Default | Meaning |
|-----|---------|---------|
| `toasts` | `true` | Windows notifications |
| `process_poll_seconds` | `2.5` | How often the supervisor checks for Play Games |
| `two_way` | `false` | Also notify when Windows text is synced to Android (Play Games always does that sync itself; this only adds notifications) |
| `save_exports` | `true` | Write `latest.txt` / `export.json` / history |
| `exports_dir` | `{documents}\GPG Clipboard Exports` | Export folder (`{documents}` = your real Documents folder) |
| `history_keep` | `20` | Number of exports kept in `history\` |
| `inbox_enabled`, `inbox_dirs`, `inbox_extensions`, `inbox_load_to_clipboard` | on, `{exports_dir}\inbox`, `.json`/`.txt`, `true` | Inbox fallback |
| `repeat_window_seconds` | `10` | Repeated Copy presses within this window produce one notification |

## Files

```
gpg-clipboard-bridge/
  setup.ps1  uninstall.ps1  start.ps1  diagnose.ps1   source install
  build.ps1         builds dist\GPGClipboardBridge-Setup.exe (PyInstaller)
  packaging/        exe entry points + icon/version-resource generator
  RELEASE_NOTES.md  text of the GitHub release
  gpgbridge/
    installer.py    Setup / uninstall: program folder, start-up task, shortcut, Apps entry
    runtime.py      source checkout vs packaged exe
    supervisor.py   tray + watchdog (what starts at logon)
    bridge.py       clipboard bridge child process
    winclip.py      Windows clipboard read/write + change listener (ctypes)
    gpglog.py       Play Games Service.log follower/parser
    tracker.py      change detection + anti-loop
    procdetect.py   Play Games / emulator process detection
    diagnosis.py    why a copy was dropped
    exports.py      export.json / history / inbox
    win32.py        window helpers
    diagnose.py     health report
  tests/            unit tests (pytest)
  PROGRESS.md       investigation notes and decisions
```

## Development

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev
```

```powershell
& "$env:LOCALAPPDATA\gpg-clipboard-bridge\venv\Scripts\python.exe" -m pytest
```

Real-clipboard tests are opt-in (they restore your clipboard afterwards): set `GPGBRIDGE_CLIPBOARD_TESTS=1`.
Run the bridge in a console with `python -m gpgbridge bridge` to watch events live (stop the tray app first).

### Building the installer and releasing

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

This makes a build venv in `%LOCALAPPDATA%\gpg-clipboard-bridge\build` with the pinned versions in
`requirements-build.txt`, runs the tests, builds `GPGClipboardBridge.exe` (one folder, no console) and checks
that it starts (`selftest`), then packs it into the single-file `dist\GPGClipboardBridge-Setup.exe` and writes
`dist\SHA256SUMS.txt`.

To publish a release, bump `__version__` in `gpgbridge/__init__.py`, update `RELEASE_NOTES.md`, commit, then
push a matching tag. GitHub Actions (`.github/workflows/release.yml` in the repository root) runs the same
`build.ps1` on a clean Windows machine and attaches the Setup exe and checksum to the release:

```powershell
git tag v1.0.0
```

```powershell
git push origin main v1.0.0
```

# PROGRESS — gpg-clipboard-bridge

Resume notes for a context reset. Update after every part.

| Part | Status | Commit |
|------|--------|--------|
| 1. Feasibility research | done | part 1 commit |
| 2. Bridge | done | part 2 commit |
| 3. Supervisor / tray / task / setup | pending | |
| 4. Fallback (file capture / inbox) | pending | |
| 5. README + unit tests | pending | |

Machine used for verification: Windows 10 Home 19045, Google Play Games **Beta 26.10.842.1**
(`androidboot.kiwi.client_version=26.10.842.1`, product-channel "Beta"), Python 3.14.0.
Clash of Clans was running during the investigation (2026-11-13).

---

## Part 1 — Feasibility findings (all verified on this machine unless marked)

### TL;DR

1. **Play Games already has built-in two-way clipboard sharing, and it is enabled.**
   `Service.log` logs `ClipboardModule: Clipboard sharing is enabled.` on every start.
   * Windows → Android works: `Windows clipboard change detected.` → `Updating Android clipboard with MIME type Text.`
     → Android logs `ClipboardHandler: updateAndroidClipboard()` (40 successful syncs in the logs).
   * Android → Windows exists too: when you pressed **Copy to clipboard** in the game (13 times on
     2026-11-13 16:38–16:39), Android logged `KiwiClipboardController: Successfully updated Windows clipboard.`
     and Service received `UpdateWindowsClipboardRequest` (frame size 9,133 bytes, which is the village export).
   * **However, every one of those 13 was dropped on the Windows side:**
     `ClipboardModule: Emulator window is not foreground. Ignoring Android clipboard change.`
     That is the whole bug the user is seeing. The text gets to Windows and Play Games throws it away.
2. **ADB is not available** on the consumer install (boot flag `androidboot.kiwi.adbproxy.enabled=0`, no
   listening TCP ports owned by any Play Games process, `localhost:5555/6520/38068` closed).
3. **Installing your own APK is not possible** on the consumer install (no ADB, `enable_devmode_sideloading=false`,
   `pcs.enable_file_transfer=false`, the in-client store only offers Google's PC catalogue).
4. So the only legitimate Android → Windows channel is Play Games' own clipboard sharing. The tool is built
   around it: watch it, prove when it worked, detect when Play Games drops a copy and tell the user the fix,
   and save every export as a file (`export.json`) ready for the bot's `/import`.

### 1. Does the emulator expose ADB?

Verified **no** for the consumer client:

* Full `crosvm.exe run-mp` command line (the VM) contains `androidboot.kiwi.adbproxy.enabled=0
  androidboot.kiwi.adbproxy.port=38068`, so the in-guest ADB proxy is switched off at boot.
* `Get-NetTCPConnection -State Listen`: no listener is owned by `crosvm.exe`, `Service.exe`, `bstrace.exe` or
  `crashpad_handler.exe`. Host↔guest traffic uses vsock and named pipes (`--cid=3`, `--service-pipe-name=…`,
  `androidboot.pcs.use_vsock=true`), not TCP.
* `Test-NetConnection 127.0.0.1` on ports 5555, 6520 (developer emulator port) and 38068: all closed.
* There is no "ADB over TCP" or developer setting in the consumer client UI. Turning the flag on would mean
  editing Google's client or boot parameters, which is ruled out (it bypasses Google's protections).
* ADB only exists in the separate **Google Play Games on PC Developer Emulator**, a different product for
  developers (`adb connect localhost:6520`). Per Google's docs, "Unlike the player experience, you can install
  and debug your own packages" there ([developer.android.com/games/playgames/pg-emulator](https://developer.android.com/games/playgames/pg-emulator)).
  It is not the client the user plays Clash of Clans in, so it is not a solution.

### 2. Reading the Android clipboard from ADB / a companion app on modern Android

All of this is moot without ADB or an APK, but for the record:

* Android 10+: an app can read the clipboard only if it is the default IME or currently has focus
  ([Android 10 privacy changes, "Limited access to clipboard data"](https://developer.android.com/about/versions/10/privacy/changes#clipboard-data)).
  A background `getPrimaryClip()` returns null.
* `adb shell cmd clipboard` / `service call clipboard N …`: the transaction codes change between Android
  versions and the call goes through the same background check. Not reliable on Android 10+. (Not tested here
  because there is no ADB.)
* A companion app with `OnPrimaryClipChangedListener`: the callback fires, but the app cannot read the data
  unless it is in the foreground or is the IME. Briefly bringing an activity to the front works on phones, but
  would fight the game for focus.
* An accessibility service cannot read the clipboard directly. It can read on-screen text nodes, but the export
  text is not on screen.
* A share or paste target app needs the game to offer "Share". The Clash of Clans Data Export only offers
  "Copy to clipboard", and you can't install the target app anyway.
* None of these are needed. Play Games' own guest service (`KiwiClipboardController`, a privileged system
  component) already reads the clipboard and sends it to Windows.

### 3. Built-in clipboard sync in Play Games?

**Yes, it exists and is on by default.** I found no user-facing toggle, and none is needed. Evidence from
`%LOCALAPPDATA%\Google\Play Games\Logs\Service.log` and `AndroidSerial.log`:

```
Service:  ClipboardModule: Clipboard sharing is enabled.
Service:  ClipboardModule: Windows clipboard change detected.
Service:  ClipboardModule: Updating Android clipboard with MIME type Text.
Android:  ClipboardHandler: updateAndroidClipboard(), mimeType: MIME_TYPE_TEXT
Android:  PcsUserServicePeer: UserHandle{0} binder onUpdateWindowsClipboard()
Android:  KiwiClipboardController: Successfully updated Windows clipboard.
Service:  PcsDatagramWireProtocol: Received incoming message: PCS-4622 - UpdateWindowsClipboardRequest
Service:  ClipboardModule: Emulator window is not foreground. Ignoring Android clipboard change.
```

Other drop reasons found in `ServiceLib.dll` strings (plain string search, no decompiling):
`Clipboard data is null. Ignoring Android clipboard change.`, `Emulator is not running. Ignoring Android
clipboard change.`, `Received non-text clipboard data. Currently not supported.` The success path logs
`Updating Windows clipboard.`

#### Why "Emulator window is not foreground"?

The user was clicking inside the game, so the game window was in front. What went wrong is which window Play
Games thinks is "the emulator window":

* `ClipboardModule` has `ObserveKiwiEmulatorStatesAndEventsAsync` and `IsEmulatorWindowForeground` (type and
  method names in `ServiceLib.dll`). It follows the emulator's reported **WindowState**, which `EmulatorStateLogger`
  logs as `{ "hwnd": <CROSVM_1 child>, "visibility": …, "windowHandle": <top-level> }`.
* Play Games runs in multi-window mode (`is_multi_window=True`, `--gpu … multi-display,max-num-displays=5`).
  crosvm owns one visible game window (class `HwndWrapper[DefaultDomain;;…]`, title `Clash of Clans - <gamertag>`)
  and several hidden off-screen surfaces at (-9999,-9999). One of them is a 1280x1024 secondary display.
* Normal start-up (every session in the logs): the hidden 1280x1024 surface is reported first, then the game
  window as `NORMAL`. The last tracked state is the real game window.
* At 14:59:30 and 15:06:37, `AppSessionScope: Detected host display settings change` fired (a monitor or
  display change: `Change MonitorHandle for GameSetting …`). Both surfaces were re-reported, and **the hidden
  1280x1024 surface came last** (`hwnd 200340 HIDDEN, windowHandle 200354`).
* From then on every Android → Windows copy was dropped (16:38–16:39), even though the foreground window was the
  visible game window `200350`.
* This rules out the simple rule "is a crosvm window in front?", which would have passed. The evidence fits
  "the foreground window must equal the *last reported* WindowState handle", and after a display change that is
  a hidden surface. **This is an inference, not confirmed by reading code.** Decompiling the client was
  deliberately not done. The bridge logs the foreground window and the tracked state on every drop, which will
  confirm or refute this the first time it happens again.
* Experiment (16:57): minimizing and restoring the game window from code made Play Games log a new WindowState
  for the right window (`200336 MINIMIZED`), but the restore was *not* reported. Minimize/restore is therefore
  not a clean automatic fix, and the bridge does not do it.
* What resets the state cleanly (seen in the logs): **closing the game and launching it again from Play Games**
  (`UserExitGameFromVmRequest` → `HideWindowRequest`; launch → `ShowWindowRequest` → game window `NORMAL`
  reported last), or restarting Play Games.

### 4. Can I install an APK on consumer Play Games?

**No.** No ADB (above), boot flags `androidboot.kiwi.enable_devmode_sideloading=false` and
`androidboot.pcs.enable_file_transfer=false`, no file manager, Play Store or package-installer UI, and the client
store only offers Google's PC catalogue. Getting around any of that would bypass Google's protections. So **no
companion APK** is built.

### 5. Windows process names and window titles (verified)

| What | Process | Path | Notes |
|------|---------|------|-------|
| Play Games client (open = running) | `Service.exe` | `C:\Program Files\Google\Play Games\current\service\Service.exe` | Started by `Bootstrapper.exe`; command line e.g. `"googleplaygames://launch/?id=com.supercell.clashofclans…"`. Owns hidden WPF windows titled `Google Play Games` / `Hidden Window`. |
| VM main | `crosvm.exe` with arg `run-mp` | `C:\Program Files\Google\Play Games\current\emulator\crosvm.exe` | Child of Service.exe. Present = emulator running. |
| VM devices | `crosvm.exe` (`run-main`, `run-spu`, `run-slirp`, `run-metrics`, `device block/net/gpu`) | same | `device gpu` owns the game window. |
| Game window | owned by crosvm `device gpu` | — | Top-level class `HwndWrapper[DefaultDomain;;<guid>]`, title `<Game> - <gamertag>` (here `Clash of Clans - <gamertag>`), child class `CROSVM_1` title `crosvm`. Hidden surfaces: same classes, off-screen at (-9999,-9999), not visible. |
| Helpers | `bstrace.exe`, `crashpad_handler.exe` | `…\current\emulator\` | Children of Service.exe. |
| **Not** "open" | `GooglePlayGamesServices.exe` | `C:\Program Files\Google\Play Games Services\` | Windows service, always running. Must be excluded. |

Detection rule used by the tool:
* *Play Games open* = a process named `Service.exe` whose path contains `\Google\Play Games\` (not `Play Games Services`).
* *Emulator running* = `crosvm.exe` under `\Google\Play Games\` with `run-mp` in its command line.
* *Ready* = emulator running and a visible crosvm `HwndWrapper[...]` top-level window with a non-empty title.

Log files: `%LOCALAPPDATA%\Google\Play Games\Logs\Service.log` (rotated to `Service-bkup-YYYYMMDD-NNNN.log`),
`AndroidSerial.log` (guest logcat).

### Chosen approach and fallback order

1. **Primary: Play Games' native clipboard sharing + a Windows helper (no ADB, no APK).**
   * A hidden clipboard listener (`AddClipboardFormatListener`) sees each clipboard change and works out which
     process owns it. When `Service.exe` from Play Games writes text, it toasts "Copied N characters from Play
     Games" and saves `export.json` (and `latest.txt`).
   * `Service.log` is followed with share-delete access, so it never blocks Play Games' log rotation. When Play
     Games drops a copy, the tool toasts the fix ("close the game and reopen it from Play Games, then press
     Copy again") and logs a diagnosis (foreground window vs tracked window).
   * Proactive warning: if the last tracked WindowState is a hidden surface while the game window is visible,
     the tray shows "Clipboard sharing is stuck" before you press Copy.
   * Windows → Android is native and always on. The optional "two-way" setting only reports those syncs.
2. **Fallback: file-based.** Every Play Games export is written to `Documents\GPG Clipboard Exports\export.json`
   for attaching to `/import`. An inbox folder is watched: drop a `.json`/`.txt` export there (for example, exported
   on a phone and sent to the PC) and it is loaded onto the Windows clipboard and saved as `export.json`.
3. **Not possible on consumer Play Games:** ADB polling and a companion APK (listener, accessibility service or
   share target). These would only work on the Developer Emulator. Not built, see above.

---

## Part 2 — Bridge (done)

Package `gpgbridge/` (Python 3.10+, deps: psutil, pystray, Pillow; clipboard and Win32 via ctypes, no pywin32):

| Module | Role |
|--------|------|
| `win32.py` | window enumeration, foreground window, process image path, `is_game_window()` |
| `winclip.py` | CF_UNICODETEXT read/write (GlobalSize-based, no truncation) and `ClipboardListener` (message-only window + `AddClipboardFormatListener`, captures owner PID per change) |
| `procdetect.py` | `classify()` (pure) + `scan()` (psutil) → client/emulator running |
| `gpglog.py` | `ServiceLogParser` (clipboard events, WindowState, display change) + `LogTailer` (FILE_SHARE_DELETE, rotation-safe, `prime()` restores current state) |
| `tracker.py` | `classify_origin()` + `ClipboardTracker` anti-loop: ignores self-writes, Windows→Android→Windows echoes, and repeated Copy presses within 10 s |
| `diagnosis.py` | `diagnose_block()` (why a copy was dropped + fix), `is_tracking_stuck()` |
| `exports.py` | `ExportStore` (latest.txt / export.json / history, atomic UTF-8 writes) + `InboxWatcher` |
| `bridge.py` | ties it together; `--ipc` = JSON events on stdout, `stop` on stdin |
| `diagnose.py` | `python -m gpgbridge diagnose` report |

Behaviour:
* Origin of a clipboard change = owner process. Play Games' `Service.exe` or crosvm → in-game copy. Our own PID → self.
  No owner → wait 1.5 s for `Updating Windows clipboard.` in Service.log.
* "Reconnect": the bridge re-scans processes every 2 s and follows Service.log across rotation and late creation,
  so starting the emulator after the helper just works.
* Two-way: Windows → Android is done natively by Play Games. `"two_way": true` in config.json only adds
  "Sent N characters to Play Games" notifications.

Verified (2026-11-13, live Play Games):
* `diagnose` output: sharing enabled, 34 Windows→Android syncs, 13 Android→Windows received / 13 blocked
  (`not_foreground`), ADB ports closed, game window found.
* Smoke test (`bridge --ipc`, temp config): status `connected (Clash of Clans)`; a PowerShell `Set-Clipboard`
  was classified as a Windows copy (no false "from Play Games"); a 72,964-char UTF-8 JSON (emoji, umlauts)
  dropped in the inbox was put on the clipboard and saved to `export.json` byte-identical; Play Games then synced
  it to Android; `stop` released the listener and exited 0.
* **Not yet verified:** a real in-game Copy reaching Windows. Needs Play Games' tracking to be healthy, which
  needs a game relaunch, and a human pressing Copy in the game.

Decisions taken without asking (per working rules):
* Config override for tests: env `GPGBRIDGE_CONFIG=<path to config.json>`.
* Exports default to `{documents}\GPG Clipboard Exports`, using the real (OneDrive-redirected) Documents known folder.
* No ADB is downloaded by `setup.ps1`, because it cannot connect to the consumer client.
* Runtime data (venv, logs, config.json) goes to `%LOCALAPPDATA%\gpg-clipboard-bridge`, not the OneDrive-synced repo.
* The bridge never minimizes, moves or sends keys to the game window. The only fix it suggests is the verified
  relaunch, because the minimize/restore experiment left Play Games tracking `MINIMIZED`.

Gets text you copy inside **Google Play Games for PC** (for example Clash of Clans → Settings → More Settings →
Data Export → **Copy to clipboard**) onto the **Windows** clipboard, so you can paste it into Discord. Every
export is also saved as `Documents\GPG Clipboard Exports\export.json`, ready to attach to `/import`.

### Install

1. Download **GPGClipboardBridge-Setup.exe** below.
2. Run it. Windows may say **"Windows protected your PC"** because the exe is not code-signed: click
   **More info → Run anyway**.
3. Click **Yes**. It installs for your account only, with no admin rights and nothing else to install (no
   Python). It starts right away and then **every time you sign in to Windows**.
4. Look for the clipboard icon in the system tray (click **^** next to the clock if you can't see it).

### Use

Open Clash of Clans in Google Play Games → **Settings → More Settings → Data Export → Copy to clipboard**. Wait
for the **"Copied N characters from Play Games"** notification, then paste in Discord, or attach
`export.json` (a full export is longer than Discord's 6,000-character limit for a slash-command option).

If you get **"Play Games blocked the copy"**: close the game, launch it again from Play Games, and copy again.
Play Games' own clipboard sharing gets stuck after display changes (moving the game to another monitor, a
monitor waking up). The helper detects this and tells you.

### Uninstall

Settings → Apps → **GPG Clipboard Bridge** → Uninstall. Your saved exports are kept.

### Safety

The helper only reads the Windows clipboard and Play Games' own log file. It never touches the game or the Play
Games process: no injection, no memory reading, no input automation, no modified files, no network access.

`SHA256SUMS.txt` holds the checksum of the Setup exe. This release was built by GitHub Actions from the tagged
source with `gpg-clipboard-bridge/build.ps1`.

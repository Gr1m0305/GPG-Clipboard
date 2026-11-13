# GPG Clipboard Bridge

Gets text you copy inside **Google Play Games for PC** (for example Clash of Clans → Settings → More Settings →
Data Export → **Copy to clipboard**) onto the **Windows** clipboard, so you can paste it into Discord. It also
saves every export as `export.json`, ready to attach to your bot's `/import`.

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

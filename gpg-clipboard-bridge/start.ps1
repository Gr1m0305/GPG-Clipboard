# Starts the helper again after "Quit" from the tray (normally it starts by itself at logon).
$ErrorActionPreference = 'Stop'
Remove-Item (Join-Path $env:LOCALAPPDATA 'gpg-clipboard-bridge\quit.marker') -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName 'GPG Clipboard Bridge'
Write-Host 'Started. Look for the clipboard icon in the system tray.'

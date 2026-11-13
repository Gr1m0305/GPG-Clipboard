<#
.SYNOPSIS
  Stops GPG Clipboard Bridge and removes its Scheduled Task.
.PARAMETER RemoveData
  Also delete %LOCALAPPDATA%\gpg-clipboard-bridge (venv, logs, config). Exports are never deleted.
.PARAMETER KeepTask
  Only stop running processes (used by setup.ps1 before re-registering).
#>
[CmdletBinding()]
param([switch]$RemoveData, [switch]$KeepTask, [switch]$Quiet)

$ErrorActionPreference = 'Stop'
$TaskName = 'GPG Clipboard Bridge'
$DataDir  = Join-Path $env:LOCALAPPDATA 'gpg-clipboard-bridge'

function Say($m) { if (-not $Quiet) { Write-Host $m } }

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $KeepTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "Removed Scheduled Task '$TaskName'."
    }
} elseif (-not $KeepTask) {
    Say "Scheduled Task '$TaskName' was not registered."
}

# Stop the supervisor and the bridge (python/pythonw running "-m gpgbridge", or the packaged exe).
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='GPGClipboardBridge.exe'" |
    Where-Object { $_.Name -eq 'GPGClipboardBridge.exe' -or $_.CommandLine -match '-m gpgbridge (supervisor|bridge)' }
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Say "Stopped pid $($p.ProcessId)." } catch { }
}
if (-not $procs) { Say 'No helper processes were running.' }

if ($RemoveData -and (Test-Path $DataDir)) {
    Remove-Item -Recurse -Force $DataDir
    Say "Deleted $DataDir."
}
Say 'Uninstall complete. (Exports in Documents\GPG Clipboard Exports were left alone.)'

<#
.SYNOPSIS
  Installs GPG Clipboard Bridge for the current Windows user and starts it.

.DESCRIPTION
  1. Finds Python 3.10+ (py launcher or python on PATH).
  2. Creates a virtual environment in %LOCALAPPDATA%\gpg-clipboard-bridge\venv and installs
     requirements.txt (psutil, pystray, Pillow).
  3. Registers the Scheduled Task "GPG Clipboard Bridge": runs the supervisor hidden
     (pythonw.exe) at logon for the current user, re-checked every 5 minutes so it
     comes back if it ever crashes.
  4. Starts it now.

  ADB / platform-tools and a companion APK are NOT installed: the consumer Google Play
  Games client has ADB disabled and does not allow sideloading (see PROGRESS.md), and the
  bridge uses Play Games' own clipboard sharing instead.

.PARAMETER Python
  Path to a specific python.exe to use (optional).
.PARAMETER NoStart
  Register everything but do not start the helper now.
.PARAMETER Dev
  Also install pytest for running the unit tests.
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$NoStart,
    [switch]$Dev,
    [string]$ForUser = ""   # internal: used when the script re-launches itself elevated
)

$ErrorActionPreference = 'Stop'
$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir  = Join-Path $env:LOCALAPPDATA 'gpg-clipboard-bridge'
$Venv     = Join-Path $DataDir 'venv'
$VenvPy   = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw  = Join-Path $Venv 'Scripts\pythonw.exe'
$TaskName = 'GPG Clipboard Bridge'
$User     = if ($ForUser) { $ForUser } else { "$env:USERDOMAIN\$env:USERNAME" }

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Test-PythonCandidate([string[]]$cmd) {
    try {
        $exe = $cmd[0]; $rest = @(); if ($cmd.Count -gt 1) { $rest = $cmd[1..($cmd.Count - 1)] }
        $out = & $exe @rest -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq 'True') { return $out[0] }
    } catch { }
    return $null
}

function Find-Python {
    if ($Python) {
        $p = Test-PythonCandidate @($Python)
        if ($p) { return $p }
        throw "The Python you passed ($Python) is missing or older than 3.10."
    }
    foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
        if (Get-Command $cand[0] -ErrorAction SilentlyContinue) {
            $p = Test-PythonCandidate $cand
            if ($p -and $p -notlike '*WindowsApps*') { return $p }
        }
    }
    throw @"
Python 3.10 or newer was not found.
Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"),
or run:  winget install -e --id Python.Python.3.12
then run this script again.
"@
}

function Register-BridgeTask {
    $action = New-ScheduledTaskAction -Execute $VenvPyw -Argument '-m gpgbridge supervisor' -WorkingDirectory $Root
    $atLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
    # Safety net: re-run every 5 minutes. MultipleInstances=IgnoreNew + the supervisor's own
    # single-instance mutex make this a no-op while it is running.
    $every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atLogon, $every5) `
        -Settings $settings -Principal $principal -Force `
        -Description 'Copies Google Play Games (PC) clipboard exports to the Windows clipboard. Installed by gpg-clipboard-bridge\setup.ps1.' | Out-Null
}

# --- elevated re-entry: only register the task --------------------------------------
if ($ForUser) {
    Register-BridgeTask
    Write-Host "Scheduled Task registered for $User."
    exit 0
}

Write-Step "Project folder: $Root"
Write-Step 'Looking for Python 3.10+'
$py = Find-Python
Write-Host "    using $py"

Write-Step "Creating virtual environment in $Venv"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
if (-not (Test-Path $VenvPy)) { & $py -m venv $Venv; if ($LASTEXITCODE) { throw 'venv creation failed' } }

Write-Step 'Installing dependencies (psutil, pystray, Pillow)'
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $VenvPy -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE) { throw 'pip install failed' }
if ($Dev) { & $VenvPy -m pip install --disable-pip-version-check -q pytest }

Write-Step 'Checking the package'
Push-Location $Root
try { & $VenvPy -c "import gpgbridge.supervisor, gpgbridge.bridge; print('    ok')"; if ($LASTEXITCODE) { throw 'import check failed' } }
finally { Pop-Location }

Write-Step 'ADB / companion APK'
Write-Host '    not needed: consumer Play Games has ADB disabled and blocks sideloading; the bridge uses'
Write-Host "    Play Games' built-in clipboard sharing. Nothing to download."

Write-Step "Stopping any running copy"
& (Join-Path $Root 'uninstall.ps1') -KeepTask -Quiet

Write-Step "Registering Scheduled Task '$TaskName' (at logon, $User)"
try {
    Register-BridgeTask
} catch {
    Write-Warning "Registering the task needs elevation on this PC ($($_.Exception.Message.Trim())). Asking for admin rights..."
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ForUser `"$User`""
    $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw 'Task registration failed.' }
}
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "    state: $($task.State)"

if (-not $NoStart) {
    Write-Step 'Starting the helper now'
    Remove-Item (Join-Path $DataDir 'quit.marker') -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*gpgbridge supervisor*' }
    if ($running) { Write-Host "    running (pid $($running.ProcessId -join ', ')) - look for the clipboard icon in the tray." }
    else { Write-Warning "The helper did not start. Check $DataDir\logs\gpg-clipboard-bridge.log" }
}

Write-Host ''
Write-Host 'Done. The helper now starts automatically at every logon and watches for Google Play Games.' -ForegroundColor Green
Write-Host "Exports are saved to: $(& $VenvPy -c "import sys; sys.path.insert(0, r'$Root'); from gpgbridge.config import load; print(load()['exports_dir'])")"
Write-Host 'Run a health check any time with:  .\diagnose.ps1'

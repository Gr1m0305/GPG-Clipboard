<#
.SYNOPSIS
  Builds dist\GPGClipboardBridge-Setup.exe, the download attached to GitHub releases.

.DESCRIPTION
  1. Creates a build virtual environment (outside the project folder, so OneDrive does not sync it)
     with the pinned packages from requirements-build.txt.
  2. Runs the unit tests.
  3. PyInstaller: GPGClipboardBridge.exe (one folder, no console window) = the program. Runs its selftest.
  4. PyInstaller: GPGClipboardBridge-Setup.exe (single file, no console window) with that folder inside.
  5. Writes dist\SHA256SUMS.txt.

  The GitHub Actions workflow (.github/workflows/release.yml) runs this same script when a v* tag is pushed.

.PARAMETER Python
  Python 3.10+ to build with (default: py -3, then python on PATH).
.PARAMETER WorkDir
  Scratch folder for the venv and PyInstaller (default: %LOCALAPPDATA%\gpg-clipboard-bridge\build).
.PARAMETER OutDir
  Where the Setup exe goes (default: .\dist).
.PARAMETER SkipTests
  Do not run pytest first.
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$WorkDir = "",
    [string]$OutDir = "",
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $WorkDir) {
    $WorkDir = if ($env:RUNNER_TEMP) { Join-Path $env:RUNNER_TEMP 'gpgbridge-build' }
               else { Join-Path $env:LOCALAPPDATA 'gpg-clipboard-bridge\build' }
}
if (-not $OutDir) { $OutDir = Join-Path $Root 'dist' }
$Venv   = Join-Path $WorkDir 'venv'
$VPy    = Join-Path $Venv 'Scripts\python.exe'
$Assets = Join-Path $WorkDir 'assets'
$AppOut = Join-Path $WorkDir 'app'
$AppDir = Join-Path $AppOut 'GPGClipboardBridge'
$Spec   = Join-Path $WorkDir 'spec'
$Tmp    = Join-Path $WorkDir 'pyi-work'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# Native tools write progress to stderr; Windows PowerShell 5.1 would turn that into terminating errors.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Command } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Find-Python {
    $cands = if ($Python) { , @($Python) } else { @(@('py', '-3'), @('python')) }
    foreach ($c in $cands) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @(); if ($c.Count -gt 1) { $rest = $c[1..($c.Count - 1)] }
        try {
            $out = & $c[0] @rest -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq 'True' -and $out[0] -notlike '*WindowsApps*') {
                return $out[0]
            }
        } catch { }
    }
    throw 'Python 3.10+ not found. Install it from python.org or pass -Python C:\path\to\python.exe.'
}

Write-Step "Work folder: $WorkDir"
New-Item -ItemType Directory -Force -Path $WorkDir, $OutDir | Out-Null
$py = Find-Python
Write-Host "    python: $py"

Write-Step 'Build environment'
if (-not (Test-Path $VPy)) { Invoke-Native 'venv' { & $py -m venv $Venv } }
Invoke-Native 'pip upgrade' { & $VPy -m pip install --disable-pip-version-check -q --upgrade pip }
Invoke-Native 'pip install' { & $VPy -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements-build.txt') }
& $VPy -c "import PyInstaller, sys; print('    PyInstaller', PyInstaller.__version__, '/ Python', sys.version.split()[0])"

if (-not $SkipTests) {
    Write-Step 'Unit tests'
    Push-Location $Root
    try { Invoke-Native 'pytest' { & $VPy -m pytest -p no:cacheprovider } } finally { Pop-Location }
}

Write-Step 'Icon and version resources'
Invoke-Native 'build_assets' { & $VPy (Join-Path $Root 'packaging\build_assets.py') $Assets }
$Icon = Join-Path $Assets 'icon.ico'

$common = @('--noconfirm', '--clean', '--log-level', 'WARN', '--windowed', '--noupx',
            '--paths', $Root, '--specpath', $Spec, '--workpath', $Tmp, '--icon', $Icon,
            '--exclude-module', 'tkinter', '--exclude-module', 'pytest')

Write-Step 'PyInstaller: GPGClipboardBridge.exe (the program)'
if (Test-Path $AppOut) { Remove-Item -Recurse -Force $AppOut }
Invoke-Native 'PyInstaller (app)' {
    & $VPy -m PyInstaller @common --onedir --name GPGClipboardBridge `
        --version-file (Join-Path $Assets 'version-GPGClipboardBridge.txt') `
        --hidden-import pystray._win32 --distpath $AppOut (Join-Path $Root 'packaging\app_main.py')
}
$exe = Join-Path $AppDir 'GPGClipboardBridge.exe'

Write-Step 'Selftest of the built exe'
$stdout = Join-Path $WorkDir 'selftest.out'
$stderr = Join-Path $WorkDir 'selftest.err'
$p = Start-Process -FilePath $exe -ArgumentList 'selftest' -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$result = (Get-Content $stdout -Raw -ErrorAction SilentlyContinue)
if ($p.ExitCode -ne 0 -or $result -notmatch 'selftest ok') {
    Get-Content $stderr -ErrorAction SilentlyContinue | Write-Host
    throw "selftest failed (exit $($p.ExitCode)): $result"
}
Write-Host "    $($result.Trim())"

Write-Step 'PyInstaller: GPGClipboardBridge-Setup.exe (the download)'
Invoke-Native 'PyInstaller (setup)' {
    & $VPy -m PyInstaller @common --onefile --name GPGClipboardBridge-Setup `
        --version-file (Join-Path $Assets 'version-GPGClipboardBridge-Setup.txt') `
        --exclude-module PIL --exclude-module pystray `
        --add-data "$AppDir;payload" --distpath $OutDir (Join-Path $Root 'packaging\setup_main.py')
}
$setup = Join-Path $OutDir 'GPGClipboardBridge-Setup.exe'

$hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
Set-Content -Path (Join-Path $OutDir 'SHA256SUMS.txt') -Value "$hash  GPGClipboardBridge-Setup.exe" -Encoding ascii
$mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host ''
Write-Host "Built $setup ($mb MB)" -ForegroundColor Green
Write-Host "SHA256 $hash"

# Prints a health report: Play Games processes, clipboard-sharing events, tracked window, task state.
$py = Join-Path $env:LOCALAPPDATA 'gpg-clipboard-bridge\venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Error 'Not installed yet - run setup.ps1 first.'; exit 1 }
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $PSScriptRoot
try { & $py -m gpgbridge diagnose } finally { Pop-Location }

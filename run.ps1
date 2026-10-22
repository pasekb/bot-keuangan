# Jalankan bot memakai virtualenv proyek tanpa perlu aktivasi manual.
# Pemakaian:  .\run.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtualenv belum ada. Membuat .venv dan memasang dependensi..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Gagal membuat .venv. Pastikan Python 3.11+ terpasang."
    }
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Gagal memasang dependensi."
    }
}

& $VenvPython -m app.main
exit $LASTEXITCODE

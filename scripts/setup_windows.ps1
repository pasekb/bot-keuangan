# Setup Python + virtualenv untuk bot_keuangan di Windows.
# Jalankan dari root proyek:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#
# Script ini:
#   1. mencari Python 3.11+ yang sudah terpasang,
#   2. memasang Python 3.12 lewat winget bila belum ada,
#   3. membuat ulang .venv,
#   4. memasang dependensi,
#   5. menjalankan unit test.

$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-PythonCommand {
    param([string]$Command, [string[]]$Arguments)

    try {
        $version = & $Command @Arguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) {
            return $null
        }
        $parts = $version.Trim().Split(".")
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -eq 3 -and $minor -ge 11) {
            return $version.Trim()
        }
    } catch {
        return $null
    }
    return $null
}

function Install-PythonDownload {
    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

    Write-Host "Mengunduh Python 3.12.10 dari python.org..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing

    Write-Host "Memasang Python (mode diam, tanpa admin)..."
    $process = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_pip=1"
    ) -Wait -PassThru

    Remove-Item $installer -Force -ErrorAction SilentlyContinue

    if ($process.ExitCode -ne 0) {
        throw "Installer Python keluar dengan kode $($process.ExitCode)."
    }
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($selector in @("-3.12", "-3")) {
            $version = Test-PythonCommand -Command "py" -Arguments @($selector)
            if ($version) {
                return @{ Command = "py"; Arguments = @($selector); Version = $version }
            }
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $version = Test-PythonCommand -Command "python" -Arguments @()
        if ($version) {
            return @{ Command = "python"; Arguments = @(); Version = $version }
        }
    }

    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )) {
        if (Test-Path $candidate) {
            $version = Test-PythonCommand -Command $candidate -Arguments @()
            if ($version) {
                return @{ Command = $candidate; Arguments = @(); Version = $version }
            }
        }
    }

    return $null
}

Write-Host "== 1. Cari Python =="
$python = Find-Python

if (-not $python) {
    Write-Host "Python 3.11+ tidak ditemukan."

    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Memasang Python 3.12 lewat winget..."
        winget install --id Python.Python.3.12 -e --source winget `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            $installed = $true
        } else {
            Write-Host "winget gagal (exit code $LASTEXITCODE), beralih ke unduhan python.org."
        }
    } else {
        Write-Host "winget tidak tersedia, memakai unduhan python.org."
    }

    if (-not $installed) {
        Install-PythonDownload
    }

    Refresh-Path
    $python = Find-Python
    if (-not $python) {
        throw "Python terpasang tetapi belum terdeteksi. Tutup PowerShell, buka lagi, lalu jalankan script ini sekali lagi."
    }
}

Write-Host ("Python {0} ditemukan: {1}" -f $python.Version, $python.Command)

Write-Host "== 2. Buat virtualenv =="
if (Test-Path ".venv") {
    Write-Host "Menghapus .venv lama..."
    Remove-Item ".venv" -Recurse -Force
}

& $python.Command @($python.Arguments) -m venv .venv
if ($LASTEXITCODE -ne 0) {
    throw "Gagal membuat .venv."
}

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "File $venvPython tidak ada. Pembuatan virtualenv gagal."
}

Write-Host "== 3. Pasang dependensi =="
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Gagal memperbarui pip." }

& $venvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Gagal memasang dependensi." }

Write-Host "== 4. Unit test =="
& $venvPython -m pytest -q
$testExit = $LASTEXITCODE

Write-Host ""
Write-Host "Selesai."
Write-Host "Jalankan bot : .\run.ps1"
Write-Host "Manual       : .\.venv\Scripts\python.exe -m app.main"
Write-Host "Tes AI       : .\.venv\Scripts\python.exe scripts\probe_ai.py"
Write-Host "Tes ulang    : .\.venv\Scripts\python.exe -m pytest -q"

if ($testExit -ne 0) {
    throw "Unit test gagal (exit code $testExit). Baca output di atas."
}

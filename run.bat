@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtualenv belum ada. Membuat .venv dan memasang dependensi...
    python -m venv .venv
    if errorlevel 1 (
        echo Gagal membuat .venv. Pastikan Python 3.11+ terpasang.
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Gagal memasang dependensi.
        exit /b 1
    )
)

.venv\Scripts\python.exe -m app.main
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%

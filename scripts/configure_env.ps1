# Isi otomatis nilai .env yang kosong / salah untuk bot_keuangan.
# Jalankan dari root proyek:
#   powershell -ExecutionPolicy Bypass -File scripts\configure_env.ps1
#
# Script ini:
#   1. memperbaiki AI_BASE_URL,
#   2. memperbaiki GOOGLE_SERVICE_ACCOUNT_FILE ke file JSON yang ada,
#   3. membuat WEB_PASSWORD dan WEB_SECRET_KEY acak bila masih kosong,
#   4. memastikan tidak ada nilai wajib yang kosong.

$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
$EnvPath = Join-Path $Root ".env"

if (-not (Test-Path $EnvPath)) {
    throw "File .env tidak ditemukan. Jalankan: Copy-Item .env.example .env"
}

$content = Get-Content -LiteralPath $EnvPath -Raw

function New-RandomToken {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

# --- AI ---
$content = [regex]::Replace(
    $content,
    "(?m)^AI_BASE_URL=.*$",
    "AI_BASE_URL=https://ai.sumopod.com/v1"
)

# --- Google service account ---
$jsonFiles = @(Get-ChildItem -LiteralPath (Join-Path $Root "credentials") -Filter "*.json" -File -ErrorAction SilentlyContinue)
if ($jsonFiles.Count -eq 0) {
    throw "Tidak ada file JSON di folder credentials\."
}
if ($jsonFiles.Count -gt 1) {
    Write-Host "Ditemukan lebih dari satu file kredensial:"
    $jsonFiles | ForEach-Object { Write-Host ("  - credentials\{0}" -f $_.Name) }
    throw "Sisakan satu file service account JSON di folder credentials\, lalu jalankan script lagi."
}

$credentialRelative = "credentials/" + $jsonFiles[0].Name
$content = [regex]::Replace(
    $content,
    "(?m)^GOOGLE_SERVICE_ACCOUNT_FILE=.*$",
    "GOOGLE_SERVICE_ACCOUNT_FILE=$credentialRelative"
)

# --- Web secrets ---
$generatedPassword = $null

if ($content -match "(?m)^WEB_PASSWORD=\s*$") {
    $generatedPassword = New-RandomToken
    $content = [regex]::Replace($content, "(?m)^WEB_PASSWORD=\s*$", "WEB_PASSWORD=$generatedPassword")
}

if ($content -match "(?m)^WEB_SECRET_KEY=\s*$") {
    $secretKey = New-RandomToken
    $content = [regex]::Replace($content, "(?m)^WEB_SECRET_KEY=\s*$", "WEB_SECRET_KEY=$secretKey")
}

# Tulis UTF-8 tanpa BOM agar dibaca pydantic dengan benar.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($EnvPath, $content, $utf8NoBom)

# --- Validasi nilai wajib ---
$required = @(
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_IDS",
    "SUMOPOD_API_KEY",
    "GOOGLE_SHEET_ID",
    "WEB_PASSWORD",
    "WEB_SECRET_KEY"
)

$missing = @()
foreach ($key in $required) {
    if ($content -notmatch "(?m)^$key=\s*\S+") {
        $missing += $key
    }
}

Write-Host "== .env diperbarui =="
Write-Host "AI_BASE_URL        : https://ai.sumopod.com/v1"
Write-Host "Service account    : $credentialRelative"

if ($generatedPassword) {
    Write-Host ""
    Write-Host "WEB_PASSWORD baru (simpan untuk login dashboard):"
    Write-Host "  $generatedPassword"
    Write-Host ""
}

if ($missing.Count -gt 0) {
    throw ("Nilai wajib masih kosong: " + ($missing -join ", "))
}

Write-Host "Semua nilai wajib sudah terisi."

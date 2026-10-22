# Bot Keuangan

Bot Telegram untuk mencatat pemasukan/pengeluaran dengan bahasa bebas, plus web
dashboard. Data disimpan di **Google Sheets** milikmu sendiri; AI hanya dipakai
untuk membaca pesan, bukan untuk menyimpan angka.

- **Bot**: Python 3.12 + `python-telegram-bot`
- **AI**: DeepSeek V4 Flash lewat Sumopod AI (OpenAI-compatible)
- **Data**: Google Sheets (sheet `Transaksi`, `Kategori`, `Pengaturan`)
- **Dashboard**: FastAPI + Jinja2, grafik dibuat dengan CSS (tanpa CDN/dependensi JS)
- **Deploy**: Docker Compose di VPS Ubuntu

---

## Fitur

| Fitur | Keterangan |
|---|---|
| Catat lewat chat | `makan siang 25rb tadi` → bot menampilkan kartu konfirmasi |
| Foto struk | Kirim foto/nota belanja → AI vision membaca total akhir → konfirmasi |
| Keterangan tambahan | Caption foto atau tombol **📝 Keterangan** sebelum menyimpan |
| Konfirmasi wajib | Tidak ada data tersimpan tanpa menekan **✅ Simpan** |
| Edit sebelum simpan | Tombol **✏️ Edit** untuk mengirim ulang teks yang benar |
| Parser cadangan | Tetap bisa mencatat saat AI timeout/rate limit (`25rb`, `1,5jt`, `25.000`) |
| Anti duplikat | Peringatan bila teks sama dikirim dalam 2 menit |
| `/undo` | Membatalkan transaksi terakhir (soft delete, masih ada jejak) |
| `/saldo` | Ringkasan bulan berjalan + saldo total |
| `/kategori` | Daftar kategori aktif |
| Dashboard | Ringkasan bulanan, donut kategori, tren harian, CRUD transaksi, ekspor CSV |
| Keamanan | Allowlist user Telegram, password dashboard, rate limit login, CSRF |

---

## Struktur Proyek

```
app/
├─ main.py              # jalankan bot + web dalam satu proses
├─ config.py            # konfigurasi dari .env
├─ models.py            # model Pydantic
├─ sheets/              # koneksi, skema, repository (cache + lock + retry)
├─ ai/                  # prompt, client Zen, parser, fallback regex
├─ bot/                 # handler Telegram, keyboard, format pesan
├─ services/            # logika draft/konfirmasi + agregasi laporan
└─ web/                 # dashboard FastAPI, template, CSS/JS
scripts/probe_ai.py     # uji koneksi AI tanpa menyentuh Sheets
tests/                  # unit test
deploy/                 # unit systemd
```

Skema sheet yang dibuat otomatis:

| Sheet | Kolom |
|---|---|
| `Transaksi` | id, tanggal, tipe, nominal, kategori, catatan, akun, sumber, status, dibuat_pada, diubah_pada, chat_id |
| `Kategori` | nama, tipe, emoji, aktif, urutan |
| `Pengaturan` | kunci, nilai |

Sheet lain di spreadsheet yang sama **tidak disentuh**.

---

## 1. Prasyarat

- Python 3.11+ (disarankan 3.12)
- Spreadsheet Google yang sudah ada
- Bot Telegram (token dari @BotFather)
- API key Sumopod AI

### 1a. Google Cloud + Service Account

1. Buka <https://console.cloud.google.com> → buat project baru.
2. **APIs & Services → Library** → aktifkan:
   - *Google Sheets API*
   - *Google Drive API*
3. **IAM & Admin → Service Accounts → Create Service Account**
   - Nama bebas, misal `bot-keuangan`
   - Role tidak perlu diberikan di level project
4. Buka service account tersebut → tab **Keys → Add Key → Create new key → JSON**.
5. Simpan file JSON ke `credentials/service-account.json`.
6. Salin **email service account** (format `nama@project.iam.gserviceaccount.com`).
7. Buka spreadsheet → **Share** → tempel email tersebut → akses **Editor**.
8. Salin **Spreadsheet ID** dari URL:
   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

### 1b. Telegram

1. Chat @BotFather → `/newbot` → simpan token.
2. Chat @userinfobot → salin **numeric ID** kamu.
3. Token dan ID akan dipakai di `.env`. Bot akan mengabaikan pesan dari ID lain.

### 1c. Sumopod AI

1. Masuk <https://ai.sumopod.com> → menu **AI** → **API Keys** → buat API key.
2. Endpoint: `https://ai.sumopod.com/v1`
3. Model: `deepseek-v4-flash`

> Biaya pemakaian mengikuti harga model di dashboard Sumopod. Kalau ingin model
> lain, cukup ganti `AI_MODEL` (dan `AI_BASE_URL` bila perlu) tanpa mengubah kode.
> Parser cadangan tetap berfungsi walau AI mati total.

---

## 2. Konfigurasi

```bash
cp .env.example .env
```

Isi `.env`:

| Variabel | Wajib | Keterangan |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ya | token dari BotFather |
| `TELEGRAM_ALLOWED_USER_IDS` | ya | ID Telegram kamu, pisahkan koma bila lebih dari satu |
| `SUMOPOD_API_KEY` | ya | API key Sumopod AI |
| `AI_BASE_URL` | tidak | default `https://ai.sumopod.com/v1` |
| `AI_MODEL` | tidak | default `deepseek-v4-flash` |
| `AI_TIMEOUT_SECONDS` | tidak | default `20` |
| `AI_VISION_MODEL` | tidak | model gambar untuk foto struk, default `glm-5v-turbo` |
| `AI_VISION_TIMEOUT_SECONDS` | tidak | default `45` |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | ya | default `credentials/service-account.json` |
| `GOOGLE_SHEET_ID` | ya | ID spreadsheet |
| `TIMEZONE` | tidak | default `Asia/Jakarta` |
| `DEFAULT_ACCOUNT` | tidak | default `Cash` |
| `WEB_PASSWORD` | ya | password dashboard |
| `WEB_SECRET_KEY` | ya | kunci tanda tangan cookie session |
| `WEB_HOST` / `WEB_PORT` | tidak | default `0.0.0.0` / `8000` |
| `SECURE_COOKIES` | tidak | `true` hanya jika dashboard sudah HTTPS |

Generate password dan secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Jalankan dua kali: sekali untuk `WEB_PASSWORD`, sekali untuk `WEB_SECRET_KEY`.

---

## 3. Jalankan Lokal

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m app.main
```

Cara paling aman di Windows — launcher otomatis memakai `.venv`, tanpa perlu
aktivasi manual:

```powershell
.\run.ps1
```

Atau klik dua kali `run.bat`.

Kalau muncul `ModuleNotFoundError: No module named 'uvicorn'`, artinya perintah
dijalankan dengan Python global, bukan `.venv`. Pakai `.\run.ps1` atau:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.main
```

Saat pertama kali jalan, bot membuat sheet `Transaksi`, `Kategori`, `Pengaturan`
beserta kategori awal dan format kolom.

- Telegram: kirim pesan ke bot kamu.
- Dashboard: <http://127.0.0.1:8000>

### Uji koneksi AI

```bash
python scripts/probe_ai.py
python scripts/probe_ai.py "kopi 18rb"
```

Script ini tidak menyentuh Google Sheets, jadi cocok untuk memastikan API key
dan model bekerja.

Uji model vision dengan gambar struk:

```bash
python scripts/probe_ai.py --image path/ke/struk.jpg
```

### Pakai foto struk

1. Kirim foto struk ke bot. Bisa juga kirim sebagai **file** agar resolusi penuh.
2. Tambahkan caption bila perlu, misal `belanja bulanan`.
3. Bot menampilkan total akhir, merchant, dan ringkasan item.
4. Tambah keterangan lewat tombol **📝 Keterangan** bila masih kurang.
5. Tekan **✅ Simpan**.

Satu struk disimpan sebagai **satu transaksi** memakai total akhir. Ringkasan
item masuk kolom `catatan`. Gambar tidak disimpan ke disk atau spreadsheet.

### Unit test

```bash
pytest -q
```

---

## 4. Deploy ke VPS Sumopod (Ubuntu)

Asumsi: Ubuntu 22.04/24.04, akses root/sudo, IP publik tersedia.

### 4a. Instal Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
```

Jika kamu tidak nyaman menjalankan script langsung, gunakan panduan resmi
Docker untuk Ubuntu, lalu pastikan `docker compose version` berfungsi.

### 4b. Unggah proyek

Dari komputer lokal:

```bash
rsync -av --exclude .venv --exclude .env --exclude credentials \
  ./ user@IP_VPS:/opt/bot_keuangan/
```

Lalu di server:

```bash
cd /opt/bot_keuangan
mkdir -p credentials
nano .env                              # isi semua variabel
nano credentials/service-account.json  # tempel isi file JSON
chmod 600 .env
# Container berjalan sebagai UID 10001, jadi file kredensial harus bisa dibacanya
sudo chown 10001:10001 credentials/service-account.json
chmod 600 credentials/service-account.json
```

### 4c. Jalankan

```bash
docker compose up -d --build
docker compose logs -f
```

Buka `http://IP_VPS:8000`.

### 4d. Firewall (penting)

Batasi port dashboard hanya untuk IP kamu:

```bash
sudo ufw allow OpenSSH
sudo ufw allow from IP_PUBLIK_KAMU to any port 8000 proto tcp
sudo ufw enable
```

Jika IP kamu dinamis, alternatif yang lebih aman: pasang Cloudflare Tunnel
atau domain + Caddy (HTTPS otomatis), lalu set `SECURE_COOKIES=true`.

### 4e. Auto-start setelah reboot

```bash
sudo cp deploy/bot-keuangan.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bot-keuangan
sudo systemctl status bot-keuangan
```

Perintah operasional:

```bash
docker compose logs -f --tail=100
docker compose restart
docker compose down
```

Update kode:

```bash
rsync ...   # dari lokal
cd /opt/bot_keuangan
docker compose up -d --build
```

---

## 5. Keamanan

- `TELEGRAM_ALLOWED_USER_IDS` **wajib** diisi. Tanpa itu semua pesan ditolak.
- Dashboard tanpa HTTPS mengirim password dalam plaintext. Karena itu:
  - gunakan password acak 32+ karakter,
  - batasi port 8000 di firewall,
  - untuk jangka panjang pakai domain + Caddy atau Cloudflare Tunnel.
- Login dibatasi 5 percobaan / 15 menit per IP.
- Semua form dashboard memakai CSRF token; cookie `HttpOnly` + `SameSite=Strict`.
- `.env` dan `credentials/*.json` tidak masuk git dan tidak masuk image Docker.
- Teks transaksi dan foto struk dikirim ke provider model AI (Sumopod AI).
  Pertimbangkan hal ini sebelum mencatat informasi sensitif.
- Foto struk diproses di memori dan tidak disimpan ke disk maupun spreadsheet.
- `.env.example` hanya berisi placeholder. Jangan menaruh token/API key asli di
  file yang ikut dibagikan atau di-commit.

---

## 6. Backup

- **Google Sheets** menyimpan versi otomatis: *File → Version history*.
- Dashboard menyediakan **Ekspor CSV** sesuai filter (bulan/kategori/pencarian).
- Saran: unduh CSV sebulan sekali, simpan di luar VPS.
- Service account key dan `.env` sebaiknya disimpan juga di password manager
  atau penyimpanan terenkripsi.

---

## 7. Troubleshooting

| Gejala | Penyebab umum | Solusi |
|---|---|---|
| Bot diam saja | ID Telegram tidak ada di allowlist | cek `TELEGRAM_ALLOWED_USER_IDS`, lihat log |
| `403 PERMISSION_DENIED` dari Google | sheet belum di-share ke email service account | share sebagai Editor |
| `SpreadsheetNotFound` | `GOOGLE_SHEET_ID` salah atau API belum aktif | cek ID dan aktifkan Sheets API |
| `Sheet ... sudah ada dengan header berbeda` | sheet dengan nama sama punya kolom lain | ganti nama sheet lama |
| Selalu memakai parser cadangan | API key/model salah atau rate limit | jalankan `python scripts/probe_ai.py`, cek log |
| `Fitur foto struk belum aktif` | `AI_VISION_MODEL` kosong | isi model vision di `.env`, restart |
| `Struk tidak terbaca` | foto buram/terlalu kecil | kirim sebagai file, foto lebih terang, atau ketik manual |
| Foto struk gagal diproses | model vision tidak mendukung gambar | ganti `AI_VISION_MODEL` (mis. `glm-5v-turbo`), cek log |
| `Nominal tidak valid` di dashboard | format nominal tidak dikenali | pakai `25000`, `25rb`, atau `25.000` |
| Dashboard tidak bisa dibuka | port/firewall | cek `docker compose ps`, `ufw status` |
| Login selalu gagal | password `.env` berubah tapi container belum restart | `docker compose restart` |

Log:

```bash
docker compose logs -f
```

---

## 8. Pengembangan

Menambah kategori: edit sheet `Kategori` (nama, tipe, emoji, aktif, urutan).
Cache kategori 60 detik; tunggu sebentar atau restart container.

Mengganti model AI: ubah `AI_MODEL` di `.env` lalu restart. Selama endpoint
OpenAI-compatible, tidak ada perubahan kode.

Migrasi ke database relasional (SQLite/Postgres) bila data sudah puluhan ribu
baris: ganti implementasi `SheetsRepository` dengan interface yang sama
(`list_transactions`, `add_transaction`, `update_transaction`,
`delete_transaction`, `undo_last`, `categories`).

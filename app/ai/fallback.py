"""Parser deterministik tanpa AI: dipakai saat model gagal atau rate limit."""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.models import Category, ParsedTransaction, TransactionType
from app.utils.money import parse_amount

INCOME_MARKERS = (
    "gaji",
    "bonus",
    "thr",
    "komisi",
    "dividen",
    "jual",
    "jualan",
    "terima",
    "menerima",
    "masuk",
    "income",
    "refund",
    "cashback",
    "untung",
    "profit",
    "honor",
    "fee",
    "dapat",
)

EXPENSE_MARKERS = (
    "beli",
    "bayar",
    "makan",
    "minum",
    "belanja",
    "isi",
    "topup",
    "top up",
    "tagihan",
    "sewa",
    "keluar",
    "transfer",
    "donasi",
)

CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Makan & Minum",
        (
            "makan",
            "minum",
            "kopi",
            "restoran",
            "warung",
            "nasi",
            "ayam",
            "bakso",
            "sate",
            "cafe",
            "kafe",
            "jajan",
            "snack",
            "gofood",
            "grabfood",
            "shopeefood",
            "sarapan",
            "lunch",
            "dinner",
            "boba",
            "teh",
            "roti",
        ),
    ),
    (
        "Transportasi",
        (
            "bensin",
            "pertalite",
            "pertamax",
            "solar",
            "grab",
            "gojek",
            "ojek",
            "taksi",
            "taxi",
            "bus",
            "kereta",
            "transjakarta",
            "parkir",
            "tol",
            "tiket pesawat",
            "bengkel",
            "servis",
            "ganti oli",
        ),
    ),
    (
        "Belanja",
        (
            "belanja",
            "shopee",
            "tokopedia",
            "lazada",
            "indomaret",
            "alfamart",
            "supermarket",
            "pasar",
            "baju",
            "sepatu",
            "skincare",
            "kosmetik",
            "perabot",
        ),
    ),
    (
        "Tagihan",
        (
            "listrik",
            "pln",
            "pdam",
            "internet",
            "wifi",
            "pulsa",
            "kuota",
            "token",
            "tagihan",
            "cicilan",
            "kartu kredit",
            "bpjs",
            "asuransi",
            "iuran",
            "langganan",
        ),
    ),
    (
        "Kesehatan",
        (
            "obat",
            "dokter",
            "klinik",
            "rumah sakit",
            "apotek",
            "vitamin",
            "gym",
            "medical",
            "fisioterapi",
        ),
    ),
    (
        "Hiburan",
        (
            "nonton",
            "bioskop",
            "netflix",
            "spotify",
            "game",
            "steam",
            "konser",
            "liburan",
            "wisata",
            "hotel",
            "karaoke",
        ),
    ),
    (
        "Pendidikan",
        ("buku", "kursus", "sekolah", "kuliah", "seminar", "udemy", "spp", "les"),
    ),
    (
        "Rumah",
        (
            "sewa",
            "kontrakan",
            "furnitur",
            "renovasi",
            "sabun",
            "deterjen",
            "kebersihan",
            "galon",
        ),
    ),
    (
        "Donasi",
        ("donasi", "sedekah", "zakat", "infaq", "sumbangan", "masjid", "gereja", "pura", "vihara"),
    ),
    ("Gaji", ("gaji", "payroll", "upah")),
    ("Bonus", ("bonus", "thr", "komisi", "insentif")),
    ("Investasi", ("dividen", "bunga", "reksadana", "saham", "crypto", "kripto")),
    ("Penjualan", ("jual", "jualan", "penjualan", "omzet", "order")),
)

RELATIVE_DAYS = (
    ("kemarin lusa", -2),
    ("kemarin", -1),
    ("minggu lalu", -7),
    ("bulan lalu", -30),
    ("hari ini", 0),
    ("tadi", 0),
    ("barusan", 0),
)


def guess_type(text: str) -> TransactionType:
    lowered = text.lower()
    income_score = sum(1 for word in INCOME_MARKERS if word in lowered)
    expense_score = sum(1 for word in EXPENSE_MARKERS if word in lowered)
    if income_score > expense_score:
        return TransactionType.INCOME
    if income_score == expense_score and income_score > 0:
        strong_income = ("masuk", "terima", "menerima", "dapat", "gaji", "bonus", "jual")
        if any(word in lowered for word in strong_income):
            return TransactionType.INCOME
    return TransactionType.EXPENSE


def guess_category(text: str, categories: list[Category], tx_type: TransactionType) -> str:
    lowered = text.lower()
    available = {cat.name.lower(): cat.name for cat in categories}
    same_type = {cat.name.lower() for cat in categories if cat.type is tx_type}

    best_name: str | None = None
    best_score = 0
    for category_name, keywords in CATEGORY_KEYWORDS:
        if available and category_name.lower() not in available:
            continue
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_score = score
            best_name = available.get(category_name.lower(), category_name)

    if best_name and (not same_type or best_name.lower() in same_type):
        return best_name

    for cat in categories:
        if cat.type is tx_type and cat.name.lower() in {"lainnya", "lain-lain", "other"}:
            return cat.name
    return "Lainnya"


def guess_date(text: str, today: date) -> date:
    lowered = text.lower()
    for phrase, offset in RELATIVE_DAYS:
        if phrase in lowered:
            return today + timedelta(days=offset)
    return today


def _clean_note(text: str) -> str:
    note = re.sub(r"\s+", " ", text).strip()
    note = re.sub(r"^(catat|record|input)\s+", "", note, flags=re.IGNORECASE)
    return note[:200]


def parse_fallback(
    text: str,
    *,
    categories: list[Category],
    today: date,
    default_account: str = "Cash",
) -> ParsedTransaction | None:
    amount = parse_amount(text)
    if amount is None or amount <= 0:
        return None

    tx_type = guess_type(text)
    category = guess_category(text, categories, tx_type)
    return ParsedTransaction(
        type=tx_type,
        amount=amount,
        category=category,
        note=_clean_note(text),
        date=guess_date(text, today),
        account=default_account,
        confidence=0.45,
        source="fallback",
    )

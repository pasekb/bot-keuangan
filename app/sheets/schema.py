"""Definisi sheet dan data awal."""

from __future__ import annotations

from app.models import TransactionType

TRANSACTIONS_SHEET = "Transaksi"
CATEGORIES_SHEET = "Kategori"
SETTINGS_SHEET = "Pengaturan"

TRANSACTION_HEADERS = [
    "id",
    "tanggal",
    "tipe",
    "nominal",
    "kategori",
    "catatan",
    "akun",
    "sumber",
    "status",
    "dibuat_pada",
    "diubah_pada",
    "chat_id",
]

CATEGORY_HEADERS = ["nama", "tipe", "emoji", "aktif", "urutan"]
SETTINGS_HEADERS = ["kunci", "nilai"]

# (nama, tipe, emoji, urutan)
DEFAULT_CATEGORIES: tuple[tuple[str, TransactionType, str, int], ...] = (
    ("Makan & Minum", TransactionType.EXPENSE, "🍜", 1),
    ("Transportasi", TransactionType.EXPENSE, "🚗", 2),
    ("Belanja", TransactionType.EXPENSE, "🛒", 3),
    ("Tagihan", TransactionType.EXPENSE, "🧾", 4),
    ("Kesehatan", TransactionType.EXPENSE, "💊", 5),
    ("Hiburan", TransactionType.EXPENSE, "🎬", 6),
    ("Pendidikan", TransactionType.EXPENSE, "📚", 7),
    ("Rumah", TransactionType.EXPENSE, "🏠", 8),
    ("Donasi", TransactionType.EXPENSE, "🙏", 9),
    ("Lainnya", TransactionType.EXPENSE, "📦", 10),
    ("Gaji", TransactionType.INCOME, "💰", 1),
    ("Bonus", TransactionType.INCOME, "🎁", 2),
    ("Investasi", TransactionType.INCOME, "📈", 3),
    ("Penjualan", TransactionType.INCOME, "🏷️", 4),
    ("Lainnya", TransactionType.INCOME, "📦", 5),
)

DEFAULT_SETTINGS = {
    "timezone": "Asia/Jakarta",
    "mata_uang": "IDR",
    "akun_default": "Cash",
}


def category_emoji_map(categories) -> dict[str, str]:
    """Map nama kategori -> emoji, dengan fallback aman."""
    mapping: dict[str, str] = {}
    for category in categories:
        mapping.setdefault(category.name, category.emoji)
    return mapping

"""Format pesan Telegram."""

from __future__ import annotations

import html

from app.models import Category, ParsedTransaction, Transaction, TransactionType
from app.services.reports import Summary
from app.utils.dates import format_date, month_label
from app.utils.money import format_rupiah

SOURCE_LABEL = {
    "ai": "AI DeepSeek",
    "struk": "AI vision (struk)",
    "fallback": "parser cadangan",
    "manual": "input manual",
}


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def _confidence_label(confidence: float) -> str:
    try:
        percent = round(confidence * 100)
    except (TypeError, ValueError):
        return "tidak diketahui"
    return f"{percent}%"


def transaction_card(tx: ParsedTransaction, emoji: str) -> str:
    note = esc(tx.note) if tx.note else "—"
    source = SOURCE_LABEL.get(tx.source, tx.source)
    return (
        f"{emoji} <b>{tx.type.label}</b> · {esc(tx.category)}\n"
        f"<b>{format_rupiah(tx.amount)}</b>\n"
        f"📝 {note}\n"
        f"📅 {format_date(tx.date)} · 💳 {esc(tx.account)}\n"
        f"<i>Sumber: {esc(source)} · keyakinan {_confidence_label(tx.confidence)}</i>"
    )


def confirmed_card(tx: Transaction, emoji: str) -> str:
    return (
        "✅ <b>Tersimpan</b>\n"
        f"{emoji} {esc(tx.category)} · {format_rupiah(tx.amount)}\n"
        f"📝 {esc(tx.note) if tx.note else '—'}\n"
        f"📅 {format_date(tx.date)} · 💳 {esc(tx.account)}"
    )


def summary_text(summary: Summary) -> str:
    return (
        f"📊 <b>Ringkasan {month_label(summary.month)}</b>\n"
        f"Pemasukan: {format_rupiah(summary.income)}\n"
        f"Pengeluaran: {format_rupiah(summary.expense)}\n"
        f"Selisih: {format_rupiah(summary.net)}\n"
        f"Saldo total: {format_rupiah(summary.balance)}"
    )


def categories_text(categories: list[Category]) -> str:
    if not categories:
        return "Belum ada kategori di spreadsheet."

    lines = ["🗂️ <b>Kategori</b>"]
    for tx_type in (TransactionType.EXPENSE, TransactionType.INCOME):
        group = [cat for cat in categories if cat.type is tx_type]
        if not group:
            continue
        lines.append(f"\n<b>{tx_type.label}</b>")
        lines.extend(f"{cat.emoji} {esc(cat.name)}" for cat in group)
    return "\n".join(lines)


def help_text() -> str:
    return (
        "💰 <b>Bot Keuangan</b>\n\n"
        "Kirim pesan bebas, bot akan mengekstrak transaksi dan meminta konfirmasi "
        "sebelum menyimpan.\n\n"
        "<b>Contoh</b>\n"
        "• makan siang 25rb tadi\n"
        "• bensin 50k kemarin\n"
        "• gaji 8jt masuk\n"
        "• kopi 18.000 + parkir 5rb\n\n"
        "<b>Foto struk</b>\n"
        "Kirim foto struk belanja — bot membaca total akhir lalu meminta konfirmasi.\n"
        "Tambah keterangan lewat caption foto atau tombol 📝 Keterangan.\n"
        "Untuk teks struk kecil, kirim sebagai file agar lebih jelas.\n\n"
        "<b>Perintah</b>\n"
        "/saldo — ringkasan bulan ini\n"
        "/undo — batalkan transaksi terakhir\n"
        "/kategori — daftar kategori\n"
        "/help — bantuan ini\n\n"
        "Dashboard web: lihat README pada proyek."
    )


def start_text(first_name: str | None = None) -> str:
    greeting = f"Halo {esc(first_name)}!" if first_name else "Halo!"
    return f"{greeting}\n\n{help_text()}"

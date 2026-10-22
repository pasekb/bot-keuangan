"""Inline keyboard untuk konfirmasi transaksi."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CONFIRM_PATTERN = r"^tx:(simpan|edit|batal|catatan):([0-9a-f]{32})$"


def confirm_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Simpan", callback_data=f"tx:simpan:{draft_id}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"tx:edit:{draft_id}"),
            ],
            [
                InlineKeyboardButton("📝 Keterangan", callback_data=f"tx:catatan:{draft_id}"),
                InlineKeyboardButton("❌ Batal", callback_data=f"tx:batal:{draft_id}"),
            ],
        ]
    )


def cancel_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Batal", callback_data=f"tx:batal:{draft_id}"),
            ]
        ]
    )

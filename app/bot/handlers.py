"""Handler Telegram: pesan bebas, konfirmasi, dan perintah."""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot.keyboards import CONFIRM_PATTERN, cancel_keyboard, confirm_keyboard
from app.bot.ui import (
    categories_text,
    confirmed_card,
    esc,
    help_text,
    start_text,
    summary_text,
    transaction_card,
)
from app.config import Settings
from app.services.reports import Summary
from app.services.transactions import TransactionService
from app.utils.money import format_rupiah

logger = logging.getLogger(__name__)

FALLBACK_EMOJI = "📦"
MAX_MESSAGE_LENGTH = 1000
MAX_PHOTO_BYTES = 10 * 1024 * 1024
SUPPORTED_PHOTO_MIME = {"image/jpeg", "image/png", "image/webp"}


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _service(context: ContextTypes.DEFAULT_TYPE) -> TransactionService:
    return context.application.bot_data["service"]


def _is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    settings = _settings(context)
    if not settings.allowed_user_ids:
        logger.warning("TELEGRAM_ALLOWED_USER_IDS kosong; semua pesan ditolak")
        return False
    return bool(user and user.id in settings.allowed_user_ids)


async def _typing(update: Update) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    try:
        await chat.send_action(ChatAction.TYPING)
    except Exception:  # pragma: no cover - indikator tidak krusial
        pass


async def _draft_text(service: TransactionService, draft) -> str:
    emoji = (await service.category_emoji()).get(draft.transaction.category, FALLBACK_EMOJI)
    card = transaction_card(draft.transaction, emoji)
    if draft.duplicate:
        card += "\n\n⚠️ <i>Mirip transaksi yang baru kamu catat. Periksa dulu ya.</i>"
    return card


def _image_attachment(message) -> tuple[str, str, int | None] | None:
    """Ambil file_id, MIME, dan ukuran dari foto atau dokumen gambar."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, "image/jpeg", photo.file_size
    document = message.document
    if document is not None and (document.mime_type or "").startswith("image/"):
        return document.file_id, document.mime_type or "image/jpeg", document.file_size
    return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context) or update.message is None:
        return
    user = update.effective_user
    await update.message.reply_text(
        start_text(user.first_name if user else None), parse_mode=ParseMode.HTML
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context) or update.message is None:
        return
    await update.message.reply_text(help_text(), parse_mode=ParseMode.HTML)


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context) or update.message is None:
        return
    await _typing(update)
    summary: Summary = await _service(context).month_summary(fresh=True)
    await update.message.reply_text(summary_text(summary), parse_mode=ParseMode.HTML)


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context) or update.message is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    transaction = await _service(context).undo(chat.id)
    if transaction is None:
        await update.message.reply_text("Tidak ada transaksi yang bisa dibatalkan.")
        return
    await update.message.reply_text(
        "🗑️ <b>Dibatalkan</b>\n"
        f"{esc(transaction.category)} · {esc(transaction.note) or '—'}\n"
        f"Nominal: {format_rupiah(transaction.amount)}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context) or update.message is None:
        return
    categories = await _service(context).categories()
    await update.message.reply_text(categories_text(categories), parse_mode=ParseMode.HTML)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context):
        return
    message = update.message
    chat = update.effective_chat
    if message is None or chat is None or not message.text:
        return

    text = message.text.strip()
    if not text:
        return
    if len(text) > MAX_MESSAGE_LENGTH:
        await message.reply_text("Pesan terlalu panjang. Maksimal 1000 karakter.")
        return

    service = _service(context)
    pending = service.note_context(chat.id)
    if pending is not None:
        draft = service.update_note(chat.id, pending.id, text)
        if draft is not None:
            await message.reply_text(
                await _draft_text(service, draft),
                reply_markup=confirm_keyboard(draft.id),
                parse_mode=ParseMode.HTML,
            )
            return

    await _typing(update)
    try:
        result = await service.prepare(chat.id, text)
    except Exception:
        logger.exception("Gagal memproses pesan pengguna")
        await message.reply_text("⚠️ Terjadi kendala saat membaca pesan. Coba lagi sebentar.")
        return

    if result.status == "clarify":
        prefix = "💬 " if result.is_question else "❓ "
        await message.reply_text(prefix + (result.question or "Bisa jelaskan transaksinya?"))
        return

    draft = result.draft
    if draft is None:
        await message.reply_text("⚠️ Tidak ada transaksi yang bisa diproses.")
        return

    await message.reply_text(
        await _draft_text(service, draft),
        reply_markup=confirm_keyboard(draft.id),
        parse_mode=ParseMode.HTML,
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context):
        return
    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    attachment = _image_attachment(message)
    if attachment is None:
        await message.reply_text("Kirim foto struk (JPG/PNG/WEBP) atau file gambar.")
        return

    file_id, mime_type, file_size = attachment
    if mime_type not in SUPPORTED_PHOTO_MIME:
        await message.reply_text("Format gambar tidak didukung. Kirim JPG, PNG, atau WEBP.")
        return
    if file_size is not None and file_size > MAX_PHOTO_BYTES:
        await message.reply_text("Gambar terlalu besar. Maksimal 10 MB.")
        return

    await _typing(update)
    try:
        telegram_file = await context.bot.get_file(file_id)
        image_bytes = bytes(await telegram_file.download_as_bytearray())
    except Exception:
        logger.exception("Gagal mengunduh foto struk")
        await message.reply_text("⚠️ Gagal mengunduh gambar. Coba kirim ulang.")
        return

    if not image_bytes:
        await message.reply_text("⚠️ Gambar kosong. Coba kirim ulang.")
        return
    if len(image_bytes) > MAX_PHOTO_BYTES:
        await message.reply_text("Gambar terlalu besar. Maksimal 10 MB.")
        return

    service = _service(context)
    try:
        result = await service.prepare_from_image(
            chat.id,
            image_bytes,
            mime_type,
            message.caption or "",
        )
    except Exception:
        logger.exception("Gagal memproses foto struk")
        await message.reply_text("⚠️ Terjadi kendala saat membaca struk. Coba lagi sebentar.")
        return

    if result.status == "clarify":
        await message.reply_text("📷 " + (result.question or "Struk tidak terbaca. Coba kirim ulang."))
        return

    draft = result.draft
    if draft is None:
        await message.reply_text("⚠️ Tidak ada transaksi yang bisa diproses dari struk.")
        return

    await message.reply_text(
        await _draft_text(service, draft),
        reply_markup=confirm_keyboard(draft.id),
        parse_mode=ParseMode.HTML,
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.message is None:
        return

    settings = _settings(context)
    if not settings.allowed_user_ids or query.from_user.id not in settings.allowed_user_ids:
        await query.answer("Bot ini privat.", show_alert=True)
        return

    match = re.match(CONFIRM_PATTERN, query.data or "")
    if not match:
        await query.answer()
        return

    action, draft_id = match.groups()
    chat_id = query.message.chat_id
    service = _service(context)
    draft = service.get_draft(draft_id)

    if draft is None or draft.chat_id != chat_id:
        await query.answer()
        try:
            await query.edit_message_text(
                "⌛ Sesi konfirmasi kedaluwarsa. Kirim ulang transaksinya ya."
            )
        except Exception:
            pass
        return

    await query.answer()

    if action == "batal":
        service.cancel(draft_id)
        await query.edit_message_text("❌ Dibatalkan. Tidak ada data yang disimpan.")
        return

    if action == "edit":
        service.clear_note(chat_id)
        service.start_edit(chat_id, draft_id)
        await query.edit_message_text(
            "✏️ Kirim ulang teks yang sudah diperbaiki.\n"
            "Contoh: makan siang 30rb (bukan 25rb)."
        )
        return

    if action == "catatan":
        if not service.start_note(chat_id, draft_id):
            await query.edit_message_text(
                "⌛ Sesi konfirmasi kedaluwarsa. Kirim ulang transaksinya ya."
            )
            return
        await query.edit_message_text(
            "📝 Kirim keterangan tambahan untuk transaksi ini.\n"
            "Contoh: belanja bulanan, patungan dengan Andi, atau arisan.",
            reply_markup=cancel_keyboard(draft_id),
        )
        return

    try:
        transaction = await service.confirm(chat_id, draft_id)
    except Exception:
        logger.exception("Gagal menyimpan transaksi")
        await query.edit_message_text(
            "⚠️ Gagal menyimpan ke Google Sheets. Coba lagi beberapa saat."
        )
        return

    emoji = (await service.category_emoji()).get(transaction.category, FALLBACK_EMOJI)
    summary = await service.month_summary(transaction.date.replace(day=1), fresh=True)
    text = confirmed_card(transaction, emoji) + "\n\n" + summary_text(summary)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error saat memproses update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ada kesalahan tak terduga. Coba lagi ya."
            )
        except Exception:
            pass


def build_application(settings: Settings, service: TransactionService) -> Application:
    application = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    application.bot_data["settings"] = settings
    application.bot_data["service"] = service

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("saldo", cmd_saldo))
    application.add_handler(CommandHandler("undo", cmd_undo))
    application.add_handler(CommandHandler("kategori", cmd_kategori))
    application.add_handler(CallbackQueryHandler(on_callback, pattern=CONFIRM_PATTERN))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo)
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
    return application

"""Logika bisnis transaksi: draft, konfirmasi, undo, ringkasan."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from app.ai.parser import MAX_NOTE_LENGTH, ParseOutcome, TransactionParser
from app.models import Category, ParsedTransaction, Transaction
from app.services.reports import Summary, summarize
from app.sheets.repository import SheetsRepository

DUPLICATE_WINDOW_SECONDS = 120.0


@dataclass
class Draft:
    id: str
    chat_id: int
    transaction: ParsedTransaction
    raw_text: str
    duplicate: bool = False
    created_at: float = field(default_factory=time.monotonic)


class DraftStore:
    """Penyimpanan draft di memori dengan TTL. Cukup untuk satu proses bot."""

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, Draft] = {}
        self._edit: dict[int, str] = {}
        self._note: dict[int, str] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [key for key, draft in self._items.items() if now - draft.created_at > self._ttl]
        for key in expired:
            self._items.pop(key, None)
        for chat_id, draft_id in list(self._edit.items()):
            if draft_id not in self._items:
                self._edit.pop(chat_id, None)
        for chat_id, draft_id in list(self._note.items()):
            if draft_id not in self._items:
                self._note.pop(chat_id, None)

    def put(self, draft: Draft) -> None:
        self._cleanup()
        self._items[draft.id] = draft

    def get(self, draft_id: str) -> Draft | None:
        self._cleanup()
        return self._items.get(draft_id)

    def pop(self, draft_id: str) -> Draft | None:
        self._cleanup()
        draft = self._items.pop(draft_id, None)
        if draft is not None:
            for chat_id, current in list(self._edit.items()):
                if current == draft_id:
                    self._edit.pop(chat_id, None)
            for chat_id, current in list(self._note.items()):
                if current == draft_id:
                    self._note.pop(chat_id, None)
        return draft

    def start_edit(self, chat_id: int, draft_id: str) -> None:
        if draft_id in self._items:
            self._edit[chat_id] = draft_id

    def edit_context(self, chat_id: int) -> Draft | None:
        self._cleanup()
        draft_id = self._edit.get(chat_id)
        return self._items.get(draft_id) if draft_id else None

    def clear_edit(self, chat_id: int) -> None:
        self._edit.pop(chat_id, None)

    def start_note(self, chat_id: int, draft_id: str) -> bool:
        if draft_id not in self._items:
            return False
        self._note[chat_id] = draft_id
        return True

    def note_context(self, chat_id: int) -> Draft | None:
        self._cleanup()
        draft_id = self._note.get(chat_id)
        return self._items.get(draft_id) if draft_id else None

    def clear_note(self, chat_id: int) -> None:
        self._note.pop(chat_id, None)


class PreparedResult:
    __slots__ = ("status", "draft", "question", "is_question", "duplicate")

    def __init__(
        self,
        status: Literal["ok", "clarify", "error"],
        *,
        draft: Draft | None = None,
        question: str | None = None,
        is_question: bool = False,
        duplicate: bool = False,
    ) -> None:
        self.status = status
        self.draft = draft
        self.question = question
        self.is_question = is_question
        self.duplicate = duplicate


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


class TransactionService:
    def __init__(
        self,
        repository: SheetsRepository,
        parser: TransactionParser,
        *,
        timezone,
        default_account: str = "Cash",
    ) -> None:
        self._repo = repository
        self._parser = parser
        self._tz = timezone
        self._default_account = default_account
        self._drafts = DraftStore()
        self._recent_hashes: dict[tuple[int, str], float] = {}

    # ---------- draft ----------

    async def prepare(self, chat_id: int, text: str) -> PreparedResult:
        categories = await self._repo.categories()
        edit_draft = self._drafts.edit_context(chat_id)
        context_note = None
        if edit_draft is not None:
            previous = edit_draft.transaction
            context_note = (
                f"tipe={previous.type.value}; nominal={previous.amount}; "
                f"kategori={previous.category}; catatan={previous.note}; "
                f"tanggal={previous.date.isoformat()}; akun={previous.account}"
            )

        outcome: ParseOutcome = await self._parser.parse(
            text,
            categories,
            context_note=context_note,
        )

        if outcome.status != "ok" or outcome.transaction is None:
            return PreparedResult(
                "clarify",
                question=outcome.question or "Bisa jelaskan transaksinya?",
                is_question=outcome.is_question,
            )

        if edit_draft is not None:
            self._drafts.pop(edit_draft.id)
            self._drafts.clear_edit(chat_id)

        is_duplicate = self._check_duplicate(chat_id, text)
        draft = Draft(
            id=uuid.uuid4().hex,
            chat_id=chat_id,
            transaction=outcome.transaction,
            raw_text=text,
            duplicate=is_duplicate,
        )
        self._drafts.put(draft)
        return PreparedResult("ok", draft=draft, duplicate=is_duplicate)

    async def prepare_from_image(
        self,
        chat_id: int,
        image_bytes: bytes,
        mime_type: str,
        caption: str | None = None,
    ) -> PreparedResult:
        categories = await self._repo.categories()
        edit_draft = self._drafts.edit_context(chat_id)
        context_note = None
        if edit_draft is not None:
            previous = edit_draft.transaction
            context_note = (
                f"tipe={previous.type.value}; nominal={previous.amount}; "
                f"kategori={previous.category}; catatan={previous.note}; "
                f"tanggal={previous.date.isoformat()}; akun={previous.account}"
            )

        outcome = await self._parser.parse_image(
            image_bytes,
            mime_type,
            categories,
            caption=caption,
            context_note=context_note,
        )

        if outcome.status != "ok" or outcome.transaction is None:
            return PreparedResult(
                "clarify",
                question=outcome.question or "Struk tidak terbaca. Coba kirim ulang.",
                is_question=outcome.is_question,
            )

        if edit_draft is not None:
            self._drafts.pop(edit_draft.id)
            self._drafts.clear_edit(chat_id)

        clean_caption = " ".join((caption or "").split())
        if clean_caption:
            note = outcome.transaction.note.strip()
            if clean_caption.lower() not in note.lower():
                combined = f"{note} · {clean_caption}" if note else clean_caption
                outcome.transaction.note = combined[:MAX_NOTE_LENGTH]

        digest = hashlib.sha256(
            image_bytes + b"\x00" + clean_caption.lower().encode("utf-8")
        ).hexdigest()
        is_duplicate = self._check_duplicate(chat_id, f"img:{digest}")
        draft = Draft(
            id=uuid.uuid4().hex,
            chat_id=chat_id,
            transaction=outcome.transaction,
            raw_text=clean_caption or "[foto struk]",
            duplicate=is_duplicate,
        )
        self._drafts.put(draft)
        return PreparedResult("ok", draft=draft, duplicate=is_duplicate)

    def update_note(self, chat_id: int, draft_id: str, text: str) -> Draft | None:
        """Tambahkan keterangan manual ke draft yang sudah terbaca."""
        draft = self._drafts.get(draft_id)
        if draft is None or draft.chat_id != chat_id:
            self._drafts.clear_note(chat_id)
            return None

        extra = " ".join((text or "").split())
        if not extra:
            return None

        current = draft.transaction.note.strip()
        combined = f"{current} · {extra}" if current else extra
        draft.transaction.note = combined[:MAX_NOTE_LENGTH]
        self._drafts.clear_note(chat_id)
        return draft

    def start_note(self, chat_id: int, draft_id: str) -> bool:
        return self._drafts.start_note(chat_id, draft_id)

    def note_context(self, chat_id: int) -> Draft | None:
        return self._drafts.note_context(chat_id)

    def clear_note(self, chat_id: int) -> None:
        self._drafts.clear_note(chat_id)

    def get_draft(self, draft_id: str) -> Draft | None:
        return self._drafts.get(draft_id)

    def start_edit(self, chat_id: int, draft_id: str) -> None:
        self._drafts.start_edit(chat_id, draft_id)

    def cancel(self, draft_id: str) -> None:
        self._drafts.pop(draft_id)

    async def confirm(self, chat_id: int, draft_id: str) -> Transaction:
        draft = self._drafts.pop(draft_id)
        if draft is None or draft.chat_id != chat_id:
            raise LookupError("Draft tidak ditemukan atau sudah kedaluwarsa")

        parsed = draft.transaction
        now = datetime.now(self._tz)
        transaction = Transaction(
            id=uuid.uuid4().hex,
            date=parsed.date,
            type=parsed.type,
            amount=parsed.amount,
            category=parsed.category,
            note=parsed.note,
            account=parsed.account or self._default_account,
            source=parsed.source,
            status="aktif",
            created_at=now,
            updated_at=now,
            chat_id=chat_id,
        )
        return await self._repo.add_transaction(transaction)

    # ---------- lain-lain ----------

    async def undo(self, chat_id: int) -> Transaction | None:
        return await self._repo.undo_last(chat_id)

    async def month_summary(
        self, month: date | None = None, *, fresh: bool = False
    ) -> Summary:
        transactions = await self._repo.list_transactions(fresh=fresh)
        return summarize(transactions, month or datetime.now(self._tz).date().replace(day=1))

    async def categories(self) -> list[Category]:
        return await self._repo.categories()

    async def category_emoji(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for category in await self._repo.categories():
            mapping.setdefault(category.name, category.emoji)
        return mapping

    def _check_duplicate(self, chat_id: int, text: str) -> bool:
        now = time.monotonic()
        digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
        key = (chat_id, digest)
        previous = self._recent_hashes.get(key)
        self._recent_hashes[key] = now

        # buang entri lama supaya dict tidak tumbuh tanpa batas
        if len(self._recent_hashes) > 500:
            cutoff = now - DUPLICATE_WINDOW_SECONDS
            self._recent_hashes = {
                k: v for k, v in self._recent_hashes.items() if v >= cutoff
            }

        return previous is not None and (now - previous) <= DUPLICATE_WINDOW_SECONDS

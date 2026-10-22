from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.ai.parser import ParseOutcome, TransactionParser
from app.models import Category, ParsedTransaction, Transaction, TransactionType
from app.services.transactions import TransactionService
from app.sheets.schema import DEFAULT_CATEGORIES

JAKARTA = ZoneInfo("Asia/Jakarta")


class FakeRepository:
    def __init__(self) -> None:
        self.transactions: list[Transaction] = []
        self.categories_list = [
            Category(name=name, type=tx_type, emoji=emoji, order=order)
            for name, tx_type, emoji, order in DEFAULT_CATEGORIES
        ]

    async def categories(self, fresh: bool = False) -> list[Category]:
        return list(self.categories_list)

    async def add_transaction(self, transaction: Transaction) -> Transaction:
        self.transactions.append(transaction)
        return transaction

    async def list_transactions(self, fresh: bool = False) -> list[Transaction]:
        return [tx for tx in self.transactions if tx.is_active]

    async def undo_last(self, chat_id: int) -> Transaction | None:
        candidates = [
            tx for tx in self.transactions if tx.chat_id == chat_id and tx.is_active
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda item: item.created_at)
        latest.status = "dihapus"
        return latest


@pytest.fixture()
def service() -> TransactionService:
    return TransactionService(
        FakeRepository(),  # type: ignore[arg-type]
        TransactionParser(ai_client=None, timezone_name="Asia/Jakarta"),
        timezone=JAKARTA,
    )


async def test_prepare_and_confirm(service: TransactionService) -> None:
    result = await service.prepare(42, "makan siang 25rb tadi")
    assert result.status == "ok"
    assert result.draft is not None
    assert result.duplicate is False

    transaction = await service.confirm(42, result.draft.id)
    assert transaction.amount == 25_000
    assert transaction.chat_id == 42
    assert transaction.category == "Makan & Minum"
    assert len(service._repo.transactions) == 1  # type: ignore[attr-defined]


async def test_confirm_rejects_other_chat(service: TransactionService) -> None:
    result = await service.prepare(42, "kopi 18rb")
    assert result.draft is not None
    with pytest.raises(LookupError):
        await service.confirm(99, result.draft.id)


async def test_duplicate_detection(service: TransactionService) -> None:
    await service.prepare(7, "bensin 50rb")
    second = await service.prepare(7, "Bensin  50rb")
    assert second.duplicate is True


async def test_clarify_when_no_amount(service: TransactionService) -> None:
    result = await service.prepare(7, "makan siang")
    assert result.status == "clarify"
    assert result.question


async def test_undo_removes_last(service: TransactionService) -> None:
    result = await service.prepare(7, "kopi 18rb")
    assert result.draft is not None
    await service.confirm(7, result.draft.id)

    undone = await service.undo(7)
    assert undone is not None
    assert undone.status == "dihapus"

    assert await service.undo(7) is None
    summary = await service.month_summary()
    assert summary.expense == 0


class FakeImageParser:
    def __init__(self, amount: int = 42_000) -> None:
        self.amount = amount
        self.captions: list[str] = []

    async def parse_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        categories: list[Category],
        *,
        caption: str | None = None,
        context_note: str | None = None,
    ) -> ParseOutcome:
        self.captions.append(caption or "")
        return ParseOutcome.ok(
            ParsedTransaction(
                type=TransactionType.EXPENSE,
                amount=self.amount,
                category="Belanja",
                note="Indomaret — beras, minyak",
                date=date(2026, 10, 20),
                source="struk",
                confidence=0.9,
            )
        )


async def test_prepare_from_image_and_confirm() -> None:
    repo = FakeRepository()
    parser = FakeImageParser()
    service = TransactionService(repo, parser, timezone=JAKARTA)  # type: ignore[arg-type]

    result = await service.prepare_from_image(5, b"struk-bytes", "image/jpeg", "bulan ini")
    assert result.status == "ok"
    assert result.draft is not None
    assert result.draft.transaction.source == "struk"
    assert parser.captions == ["bulan ini"]

    transaction = await service.confirm(5, result.draft.id)
    assert transaction.amount == 42_000
    assert transaction.source == "struk"
    assert repo.transactions[-1].note.startswith("Indomaret")


async def test_prepare_from_image_detects_duplicate() -> None:
    repo = FakeRepository()
    service = TransactionService(
        repo, FakeImageParser(), timezone=JAKARTA  # type: ignore[arg-type]
    )

    first = await service.prepare_from_image(5, b"same-image", "image/png", "")
    second = await service.prepare_from_image(5, b"same-image", "image/png", "")
    assert first.duplicate is False
    assert second.duplicate is True


async def test_update_note_appends_and_truncates(service: TransactionService) -> None:
    result = await service.prepare(9, "kopi 18rb")
    assert result.draft is not None

    assert service.start_note(9, result.draft.id) is True
    draft = service.update_note(9, result.draft.id, "  patungan   dengan Andi ")
    assert draft is not None
    assert "kopi" in draft.transaction.note.lower()
    assert draft.transaction.note.endswith("patungan dengan Andi")

    draft = service.update_note(9, result.draft.id, "x" * 500)
    assert draft is not None
    assert len(draft.transaction.note) <= 200


async def test_note_context_cleared_after_confirm(service: TransactionService) -> None:
    result = await service.prepare(3, "bensin 50rb")
    assert result.draft is not None
    service.start_note(3, result.draft.id)
    await service.confirm(3, result.draft.id)
    assert service.note_context(3) is None


async def test_edit_flow_replaces_draft(service: TransactionService) -> None:
    first = await service.prepare(1, "makan 20rb")
    assert first.draft is not None
    service.start_edit(1, first.draft.id)

    corrected = await service.prepare(1, "makan 30rb")
    assert corrected.status == "ok"
    assert corrected.draft is not None
    assert corrected.draft.transaction.amount == 30_000
    # draft lama sudah tidak berlaku
    assert service.get_draft(first.draft.id) is None

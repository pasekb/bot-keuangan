from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.ai.parser import TransactionParser, extract_json_object, normalize_category
from app.models import AITransaction, Category, TransactionType
from app.sheets.schema import DEFAULT_CATEGORIES

JAKARTA = ZoneInfo("Asia/Jakarta")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=JAKARTA)


def categories() -> list[Category]:
    return [
        Category(name=name, type=tx_type, emoji=emoji, order=order)
        for name, tx_type, emoji, order in DEFAULT_CATEGORIES
    ]


class FakeAI:
    def __init__(self, payload: str | None) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, messages):  # noqa: ANN001
        self.calls += 1
        return self.payload


class FakeVisionAI(FakeAI):
    def __init__(self, payload: str | None) -> None:
        super().__init__(payload)
        self.messages: list[dict] | None = None

    async def complete_vision_json(self, messages):  # noqa: ANN001
        self.calls += 1
        self.messages = messages
        return self.payload


def ai_payload(**overrides) -> str:
    transaction = {
        "tipe": "pengeluaran",
        "nominal": 25000,
        "kategori": "Makan & Minum",
        "catatan": "makan siang",
        "tanggal": "2026-10-20",
        "akun": "Cash",
    }
    transaction.update(overrides.pop("transaksi", {}))
    data = {
        "intent": "catat",
        "transaksi": transaction,
        "keyakinan": 0.93,
        "pertanyaan": None,
    }
    data.update(overrides)
    return json.dumps(data)


def test_extract_json_object_handles_markdown() -> None:
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object("prefix {\"a\": 2} suffix") == {"a": 2}
    assert extract_json_object("tidak ada json") is None


def test_ai_transaction_parses_indonesian_keys() -> None:
    tx = AITransaction.model_validate(
        {
            "tipe": "pemasukan",
            "nominal": "8jt",
            "kategori": "Gaji",
            "tanggal": "19/10/2026",
            "catatan": "gaji oktober",
        }
    )
    assert tx.type is TransactionType.INCOME
    assert tx.amount == 8_000_000
    assert tx.date == date(2026, 10, 19)


def test_normalize_category() -> None:
    cats = categories()
    assert normalize_category("makan", TransactionType.EXPENSE, cats) == "Makan & Minum"
    assert normalize_category("Gaji", TransactionType.INCOME, cats) == "Gaji"
    assert normalize_category("tidak ada", TransactionType.EXPENSE, cats) == "Lainnya"


async def test_parser_uses_ai() -> None:
    parser = TransactionParser(ai_client=FakeAI(ai_payload()), timezone_name="Asia/Jakarta")
    outcome = await parser.parse("makan siang 25rb", categories(), now=NOW)
    assert outcome.status == "ok"
    assert outcome.transaction is not None
    assert outcome.transaction.amount == 25_000
    assert outcome.transaction.category == "Makan & Minum"
    assert outcome.transaction.date == date(2026, 10, 20)
    assert outcome.source == "ai"


async def test_parser_clamps_future_date() -> None:
    parser = TransactionParser(
        ai_client=FakeAI(ai_payload(transaksi={"tanggal": "2027-01-01"})),
        timezone_name="Asia/Jakarta",
    )
    outcome = await parser.parse("makan siang 25rb", categories(), now=NOW)
    assert outcome.transaction is not None
    assert outcome.transaction.date == NOW.date()


async def test_parser_asks_for_amount() -> None:
    payload = json.dumps(
        {
            "intent": "tidak_jelas",
            "transaksi": None,
            "keyakinan": 0.2,
            "pertanyaan": "Berapa nominalnya?",
        }
    )
    parser = TransactionParser(ai_client=FakeAI(payload), timezone_name="Asia/Jakarta")
    outcome = await parser.parse("makan siang", categories(), now=NOW)
    assert outcome.status == "clarify"
    assert outcome.question == "Berapa nominalnya?"


async def test_parser_falls_back_when_json_invalid() -> None:
    ai = FakeAI("bukan json")
    parser = TransactionParser(ai_client=ai, timezone_name="Asia/Jakarta")
    outcome = await parser.parse("makan siang 25rb", categories(), now=NOW)
    assert outcome.status == "ok"
    assert outcome.transaction is not None
    assert outcome.transaction.source == "fallback"
    assert outcome.transaction.amount == 25_000
    # satu percobaan awal + satu percobaan repair
    assert ai.calls == 2


async def test_parser_without_ai_uses_fallback() -> None:
    parser = TransactionParser(ai_client=None, timezone_name="Asia/Jakarta")
    outcome = await parser.parse("gaji 8jt masuk", categories(), now=NOW)
    assert outcome.status == "ok"
    assert outcome.transaction.type is TransactionType.INCOME
    assert outcome.transaction.category == "Gaji"
    assert outcome.transaction.amount == 8_000_000


async def test_fallback_relative_date() -> None:
    parser = TransactionParser(ai_client=None, timezone_name="Asia/Jakarta")
    outcome = await parser.parse("kopi 18rb kemarin", categories(), now=NOW)
    assert outcome.transaction is not None
    assert outcome.transaction.date == date(2026, 10, 19)


async def test_parse_image_sends_data_url_and_caption() -> None:
    ai = FakeVisionAI(
        ai_payload(
            transaksi={
                "nominal": 87500,
                "kategori": "Belanja",
                "catatan": "Indomaret — beras, minyak",
            }
        )
    )
    parser = TransactionParser(ai_client=ai, timezone_name="Asia/Jakarta")
    outcome = await parser.parse_image(
        b"\x89PNG\r\n\x1a\nfake",
        "image/png",
        categories(),
        caption="belanja bulanan",
        now=NOW,
    )

    assert outcome.status == "ok"
    assert outcome.transaction is not None
    assert outcome.transaction.amount == 87_500
    assert outcome.transaction.source == "struk"
    assert ai.messages is not None

    user_content = ai.messages[1]["content"]
    assert isinstance(user_content, list)
    text_part = next(part for part in user_content if part["type"] == "text")
    image_part = next(part for part in user_content if part["type"] == "image_url")
    assert "belanja bulanan" in text_part["text"]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


async def test_parse_image_rejects_unsupported_mime() -> None:
    ai = FakeVisionAI(ai_payload())
    parser = TransactionParser(ai_client=ai, timezone_name="Asia/Jakarta")
    outcome = await parser.parse_image(b"gif", "image/gif", categories(), now=NOW)
    assert outcome.status == "clarify"
    assert "Format gambar" in (outcome.question or "")
    assert ai.calls == 0


async def test_parse_image_without_vision_client_asks_manual() -> None:
    parser = TransactionParser(ai_client=FakeAI(ai_payload()), timezone_name="Asia/Jakarta")
    outcome = await parser.parse_image(b"data", "image/jpeg", categories(), now=NOW)
    assert outcome.status == "clarify"
    assert "AI_VISION_MODEL" in (outcome.question or "")


async def test_parse_image_repairs_invalid_json() -> None:
    ai = FakeVisionAI("bukan json")
    parser = TransactionParser(ai_client=ai, timezone_name="Asia/Jakarta")
    outcome = await parser.parse_image(b"data", "image/jpeg", categories(), now=NOW)
    assert outcome.status == "clarify"
    assert ai.calls == 2

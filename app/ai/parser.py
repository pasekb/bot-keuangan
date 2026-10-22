from __future__ import annotations

import base64
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai.client import AIClient
from app.ai.fallback import parse_fallback
from app.ai.prompt import build_image_messages, build_messages, build_repair_messages
from app.models import (
    AIParseResult,
    Category,
    ParsedTransaction,
    TransactionType,
)
from app.utils.money import parse_amount

logger = logging.getLogger(__name__)

MAX_NOTE_LENGTH = 200
CLARIFY_DEFAULT = "Nominalnya berapa? Contoh: makan siang 25rb"
CLARIFY_IMAGE_DEFAULT = (
    "Struk tidak terbaca dengan jelas. Coba foto ulang lebih terang, "
    "kirim sebagai file, atau ketik transaksinya manual."
)
SUPPORTED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})


def extract_json_object(raw: str | None) -> dict | None:
    """Ambil objek JSON pertama dari output model, termasuk yang dibungkus markdown."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        import json

        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def normalize_category(
    name: str,
    tx_type: TransactionType,
    categories: list[Category],
) -> str:
    target = (name or "").strip().lower()
    same_type = [cat for cat in categories if cat.type is tx_type]
    options = same_type or categories
    if not options:
        return "Lainnya"

    for cat in options:
        if cat.name.strip().lower() == target:
            return cat.name

    if target:
        for cat in options:
            lowered = cat.name.lower()
            if target in lowered or lowered in target:
                return cat.name

    for cat in options:
        if cat.name.strip().lower() in {"lainnya", "lain-lain", "other"}:
            return cat.name
    return options[0].name


class TransactionParser:
    def __init__(
        self,
        *,
        ai_client: AIClient | None,
        timezone_name: str = "Asia/Jakarta",
        currency: str = "IDR",
        default_account: str = "Cash",
    ) -> None:
        self._ai = ai_client
        self._timezone_name = timezone_name
        self._currency = currency
        self._default_account = default_account
        self._tz = ZoneInfo(timezone_name)

    def now(self) -> datetime:
        return datetime.now(self._tz)

    async def parse(
        self,
        text: str,
        categories: list[Category],
        *,
        context_note: str | None = None,
        now: datetime | None = None,
    ) -> "ParseOutcome":
        text = (text or "").strip()
        now = now or self.now()
        today = now.date()

        if len(text) < 2:
            return ParseOutcome.clarify("Tulis transaksinya, contoh: kopi 18rb", source="system")

        if self._ai is not None:
            messages = build_messages(
                text=text,
                now=now,
                timezone_name=self._timezone_name,
                currency=self._currency,
                categories=categories,
                default_account=self._default_account,
                context_note=context_note,
            )
            raw = await self._ai.complete_json(messages)
            result = self._decode(raw)
            if result is None and raw:
                raw_repaired = await self._ai.complete_json(
                    build_repair_messages(raw, "JSON tidak valid atau tidak sesuai skema")
                )
                result = self._decode(raw_repaired)
            if result is not None:
                outcome = self._from_ai(result, categories, today)
                if outcome is not None:
                    return outcome

        fallback = parse_fallback(
            text,
            categories=categories,
            today=today,
            default_account=self._default_account,
        )
        if fallback is not None:
            return ParseOutcome.ok(fallback)
        return ParseOutcome.clarify(CLARIFY_DEFAULT, source="fallback")

    async def parse_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        categories: list[Category],
        *,
        caption: str | None = None,
        context_note: str | None = None,
        now: datetime | None = None,
    ) -> "ParseOutcome":
        """Ekstrak transaksi dari foto struk memakai model AI vision."""
        mime = (mime_type or "").split(";")[0].strip().lower()
        if mime not in SUPPORTED_IMAGE_MIME:
            return ParseOutcome.clarify(
                "Format gambar tidak didukung. Kirim JPG, PNG, atau WEBP.",
                source="vision",
            )
        if not image_bytes:
            return ParseOutcome.clarify(
                "Gambar kosong atau gagal diunduh. Coba kirim ulang.",
                source="vision",
            )

        complete_vision = getattr(self._ai, "complete_vision_json", None)
        if complete_vision is None:
            return ParseOutcome.clarify(
                "Fitur foto struk belum aktif. Isi AI_VISION_MODEL di .env.",
                source="vision",
            )

        now = now or self.now()
        today = now.date()
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        messages = build_image_messages(
            image_data_url=data_url,
            caption=caption,
            now=now,
            timezone_name=self._timezone_name,
            currency=self._currency,
            categories=categories,
            default_account=self._default_account,
            context_note=context_note,
        )

        raw = await complete_vision(messages)
        result = self._decode(raw)
        if result is None and raw:
            raw_repaired = await complete_vision(
                build_repair_messages(raw, "JSON tidak valid atau tidak sesuai skema")
            )
            result = self._decode(raw_repaired)

        if result is not None:
            outcome = self._from_ai(result, categories, today, source="struk")
            if outcome is not None:
                if outcome.status == "clarify" and not outcome.question:
                    outcome.question = CLARIFY_IMAGE_DEFAULT
                return outcome

        return ParseOutcome.clarify(CLARIFY_IMAGE_DEFAULT, source="vision")

    # ---------- internal ----------

    def _decode(self, raw: str | None) -> AIParseResult | None:
        data = extract_json_object(raw)
        if data is None:
            return None
        try:
            return AIParseResult.model_validate(data)
        except Exception as exc:
            logger.info("Output AI tidak lolos validasi: %s", exc)
            return None

    def _from_ai(
        self,
        result: AIParseResult,
        categories: list[Category],
        today: date,
        *,
        source: str = "ai",
    ) -> "ParseOutcome | None":
        intent = result.intent
        if intent in {"tanya", "tidak_jelas"} or result.transaction is None:
            question = (result.question or "").strip()
            if intent == "tanya" and question:
                return ParseOutcome.clarify(question, source="ai", is_question=True)
            return ParseOutcome.clarify(question or CLARIFY_DEFAULT, source="ai")

        src = result.transaction
        amount = parse_amount(src.amount)
        if amount is None or amount <= 0:
            return ParseOutcome.clarify(
                (result.question or CLARIFY_DEFAULT).strip(), source="ai"
            )

        tx_date = src.date
        if tx_date.year < 2000 or tx_date > today + timedelta(days=1):
            tx_date = today

        category = normalize_category(src.category, src.type, categories)
        note = " ".join((src.note or "").split())[:MAX_NOTE_LENGTH]
        confidence = result.confidence
        if not isinstance(confidence, (int, float)) or confidence != confidence:
            confidence = 0.0
        confidence = max(0.0, min(1.0, float(confidence)))

        return ParseOutcome.ok(
            ParsedTransaction(
                type=src.type,
                amount=amount,
                category=category,
                note=note,
                date=tx_date,
                account=(src.account or self._default_account).strip()
                or self._default_account,
                confidence=confidence,
                source=source,
            )
        )


class ParseOutcome:
    __slots__ = ("status", "transaction", "question", "source", "is_question")

    def __init__(
        self,
        status: str,
        transaction: ParsedTransaction | None = None,
        question: str | None = None,
        source: str = "ai",
        is_question: bool = False,
    ) -> None:
        self.status = status
        self.transaction = transaction
        self.question = question
        self.source = source
        self.is_question = is_question

    @classmethod
    def ok(cls, transaction: ParsedTransaction) -> "ParseOutcome":
        return cls("ok", transaction=transaction, source=transaction.source)

    @classmethod
    def clarify(
        cls, question: str, *, source: str = "ai", is_question: bool = False
    ) -> "ParseOutcome":
        return cls("clarify", question=question, source=source, is_question=is_question)

    def __repr__(self) -> str:  # pragma: no cover - bantuan debug
        return f"ParseOutcome(status={self.status!r}, transaction={self.transaction!r})"

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.utils.money import parse_amount

# Alias tipe: nama field `date` + default akan menimpa kelas `date` di namespace
# class sehingga pydantic gagal membaca anotasinya.
DateType = date


class TransactionType(str, Enum):
    EXPENSE = "pengeluaran"
    INCOME = "pemasukan"

    @property
    def label(self) -> str:
        return "Pengeluaran" if self is TransactionType.EXPENSE else "Pemasukan"

    @property
    def sign(self) -> int:
        return -1 if self is TransactionType.EXPENSE else 1

    @classmethod
    def parse(cls, value: Any) -> "TransactionType":
        text = str(value or "").strip().lower()
        if text in {"pemasukan", "masuk", "income", "in", "kredit", "credit"}:
            return cls.INCOME
        return cls.EXPENSE


class Category(BaseModel):
    name: str
    type: TransactionType
    emoji: str = "📦"
    active: bool = True
    order: int = 0


class Transaction(BaseModel):
    id: str
    date: date
    type: TransactionType
    amount: int
    category: str
    note: str = ""
    account: str = "Cash"
    source: str = "ai"
    status: str = "aktif"
    created_at: datetime
    updated_at: datetime
    chat_id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "aktif"


class ParsedTransaction(BaseModel):
    """Transaksi hasil parsing AI/fallback, belum disimpan."""

    type: TransactionType
    amount: int
    category: str
    note: str = ""
    date: date
    account: str = "Cash"
    confidence: float = 0.0
    source: str = "ai"


class AITransaction(BaseModel):
    """DTO keluaran model AI (kunci bahasa Indonesia)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: TransactionType = Field(alias="tipe")
    amount: int = Field(alias="nominal")
    category: str = Field(default="Lainnya", alias="kategori")
    note: str = Field(default="", alias="catatan")
    date: DateType = Field(alias="tanggal")
    account: str = Field(default="Cash", alias="akun")

    @field_validator("category", "note", "account", mode="before")
    @classmethod
    def _default_text(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            return {"category": "Lainnya", "note": "", "account": "Cash"}[info.field_name]
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _parse_type(cls, value: Any) -> TransactionType:
        return TransactionType.parse(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: Any) -> int:
        parsed = parse_amount(value)
        if parsed is None:
            raise ValueError(f"nominal tidak valid: {value!r}")
        return parsed

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return date.today()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        raise ValueError(f"format tanggal tidak dikenali: {value!r}")


class AIParseResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    intent: str = Field(default="catat", alias="intent")
    transaction: AITransaction | None = Field(default=None, alias="transaksi")
    confidence: float = Field(default=0.0, alias="keyakinan")
    question: str | None = Field(default=None, alias="pertanyaan")

    @field_validator("intent", mode="before")
    @classmethod
    def _normalize_intent(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        allowed = {"catat", "tanya", "koreksi", "tidak_jelas"}
        return text if text in allowed else "catat"

    @field_validator("confidence", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.0 if value is None else value

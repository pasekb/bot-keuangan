"""Repository Google Sheets dengan cache in-memory dan lock untuk penulisan."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from app.models import Category, Transaction, TransactionType
from app.sheets.client import SheetsClient
from app.sheets.schema import (
    CATEGORIES_SHEET,
    CATEGORY_HEADERS,
    DEFAULT_CATEGORIES,
    DEFAULT_SETTINGS,
    SETTINGS_HEADERS,
    SETTINGS_SHEET,
    TRANSACTIONS_SHEET,
    TRANSACTION_HEADERS,
)
from app.utils.money import parse_amount

logger = logging.getLogger(__name__)


class TransactionNotFound(LookupError):
    pass


def _parse_datetime(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def transaction_to_row(tx: Transaction) -> list[str]:
    return [
        tx.id,
        tx.date.isoformat(),
        tx.type.value,
        str(tx.amount),
        tx.category,
        tx.note,
        tx.account,
        tx.source,
        tx.status,
        tx.created_at.isoformat(),
        tx.updated_at.isoformat(),
        str(tx.chat_id) if tx.chat_id is not None else "",
    ]


def row_to_transaction(record: dict[str, str]) -> Transaction | None:
    tx_id = (record.get("id") or "").strip()
    date_text = (record.get("tanggal") or "").strip()
    if not tx_id or not date_text:
        return None

    try:
        tx_date = date.fromisoformat(date_text[:10])
    except ValueError:
        logger.warning("Baris transaksi %s punya tanggal tidak valid: %r", tx_id, date_text)
        return None

    amount = parse_amount(record.get("nominal"))
    if amount is None:
        logger.warning("Baris transaksi %s punya nominal tidak valid: %r", tx_id, record.get("nominal"))
        return None

    created_at = _parse_datetime(record.get("dibuat_pada")) or datetime.now(timezone.utc)
    updated_at = _parse_datetime(record.get("diubah_pada")) or created_at

    chat_id_raw = (record.get("chat_id") or "").strip()
    chat_id = int(chat_id_raw) if chat_id_raw.isdigit() else None

    return Transaction(
        id=tx_id,
        date=tx_date,
        type=TransactionType.parse(record.get("tipe")),
        amount=amount,
        category=(record.get("kategori") or "Lainnya").strip() or "Lainnya",
        note=(record.get("catatan") or "").strip(),
        account=(record.get("akun") or "Cash").strip() or "Cash",
        source=(record.get("sumber") or "ai").strip() or "ai",
        status=(record.get("status") or "aktif").strip() or "aktif",
        created_at=created_at,
        updated_at=updated_at,
        chat_id=chat_id,
    )


def category_to_row(category: Category) -> list[str]:
    return [
        category.name,
        category.type.value,
        category.emoji,
        "TRUE" if category.active else "FALSE",
        str(category.order),
    ]


def row_to_category(record: dict[str, str]) -> Category | None:
    name = (record.get("nama") or "").strip()
    if not name:
        return None
    active_raw = (record.get("aktif") or "").strip().lower()
    order_raw = (record.get("urutan") or "").strip()
    try:
        order = int(float(order_raw)) if order_raw else 0
    except ValueError:
        order = 0
    return Category(
        name=name,
        type=TransactionType.parse(record.get("tipe")),
        emoji=(record.get("emoji") or "📦").strip() or "📦",
        active=active_raw not in {"false", "0", "tidak", "no"},
        order=order,
    )


class SheetsRepository:
    def __init__(
        self,
        client: SheetsClient,
        *,
        default_account: str = "Cash",
        timezone_name: str = "Asia/Jakarta",
        currency: str = "IDR",
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._default_account = default_account
        self._timezone_name = timezone_name
        self._currency = currency
        self._cache_ttl = cache_ttl_seconds

        self._write_lock = asyncio.Lock()

        self._transactions: list[Transaction] | None = None
        self._transactions_at = 0.0
        self._categories: list[Category] | None = None
        self._categories_at = 0.0
        self._settings: dict[str, str] | None = None
        self._settings_at = 0.0

    # ---------- inisialisasi ----------

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._client.ensure_table(TRANSACTIONS_SHEET, TRANSACTION_HEADERS)
        self._client.ensure_table(CATEGORIES_SHEET, CATEGORY_HEADERS)
        self._client.ensure_table(SETTINGS_SHEET, SETTINGS_HEADERS)

        if not self._client.read_records(CATEGORIES_SHEET):
            for name, tx_type, emoji, order in DEFAULT_CATEGORIES:
                self._client.append_row(
                    CATEGORIES_SHEET,
                    category_to_row(
                        Category(name=name, type=tx_type, emoji=emoji, order=order)
                    ),
                )
            logger.info("Kategori awal dimasukkan ke spreadsheet")

        existing_settings = {
            (row.get("kunci") or "").strip()
            for row in self._client.read_records(SETTINGS_SHEET)
        }
        defaults = {
            **DEFAULT_SETTINGS,
            "timezone": self._timezone_name,
            "mata_uang": self._currency,
            "akun_default": self._default_account,
        }
        for key, value in defaults.items():
            if key not in existing_settings:
                self._client.append_row(SETTINGS_SHEET, [key, value])

        for title in (TRANSACTIONS_SHEET, CATEGORIES_SHEET, SETTINGS_SHEET):
            self._client.format_table(title)

        self._invalidate()

    # ---------- helper cache ----------

    def _invalidate(self) -> None:
        self._transactions = None
        self._transactions_at = 0.0
        self._categories = None
        self._categories_at = 0.0
        self._settings = None
        self._settings_at = 0.0

    @staticmethod
    def _is_fresh(cached_at: float, ttl: float) -> bool:
        return cached_at > 0 and (time.monotonic() - cached_at) < ttl

    async def _all_transactions(self, fresh: bool = False) -> list[Transaction]:
        if not fresh and self._transactions is not None and self._is_fresh(
            self._transactions_at, self._cache_ttl
        ):
            return list(self._transactions)

        records = await asyncio.to_thread(
            self._client.call_with_retry,
            lambda: self._client.read_records(TRANSACTIONS_SHEET),
        )
        parsed = [tx for row in records if (tx := row_to_transaction(row)) is not None]
        parsed.sort(key=lambda item: (item.date, item.created_at))
        self._transactions = parsed
        self._transactions_at = time.monotonic()
        return list(parsed)

    async def list_transactions(self, fresh: bool = False) -> list[Transaction]:
        transactions = await self._all_transactions(fresh=fresh)
        return [tx for tx in transactions if tx.is_active]

    async def get_transaction(self, transaction_id: str) -> Transaction | None:
        for tx in await self._all_transactions(fresh=True):
            if tx.id == transaction_id:
                return tx
        return None

    async def add_transaction(self, transaction: Transaction) -> Transaction:
        row = transaction_to_row(transaction)
        async with self._write_lock:
            await asyncio.to_thread(
                self._client.call_with_retry,
                lambda: self._client.append_row(TRANSACTIONS_SHEET, row),
            )
            self._invalidate()
        return transaction

    async def update_transaction(self, transaction: Transaction) -> Transaction:
        row = transaction_to_row(transaction)
        async with self._write_lock:
            row_number = await asyncio.to_thread(
                self._client.call_with_retry,
                lambda: self._client.find_row(TRANSACTIONS_SHEET, transaction.id),
            )
            if row_number is None:
                raise TransactionNotFound(transaction.id)
            await asyncio.to_thread(
                self._client.call_with_retry,
                lambda: self._client.update_row(TRANSACTIONS_SHEET, row_number, row),
            )
            self._invalidate()
        return transaction

    async def delete_transaction(
        self, transaction_id: str, *, soft: bool = True
    ) -> Transaction:
        transaction = await self.get_transaction(transaction_id)
        if transaction is None:
            raise TransactionNotFound(transaction_id)
        if soft:
            transaction.status = "dihapus"
        transaction.updated_at = datetime.now(timezone.utc)
        return await self.update_transaction(transaction)

    async def undo_last(self, chat_id: int) -> Transaction | None:
        transactions = await self.list_transactions(fresh=True)
        candidates = [tx for tx in transactions if tx.chat_id == chat_id]
        if not candidates:
            return None
        latest = max(candidates, key=lambda item: item.created_at)
        return await self.delete_transaction(latest.id)

    # ---------- kategori ----------

    async def categories(self, fresh: bool = False) -> list[Category]:
        if not fresh and self._categories is not None and self._is_fresh(
            self._categories_at, self._cache_ttl
        ):
            return list(self._categories)

        records = await asyncio.to_thread(
            self._client.call_with_retry,
            lambda: self._client.read_records(CATEGORIES_SHEET),
        )
        parsed = [cat for row in records if (cat := row_to_category(row)) is not None]
        parsed = [cat for cat in parsed if cat.active]
        parsed.sort(key=lambda item: (item.order, item.name))
        self._categories = parsed
        self._categories_at = time.monotonic()
        return list(parsed)

    # ---------- pengaturan ----------

    async def settings(self, fresh: bool = False) -> dict[str, str]:
        if not fresh and self._settings is not None and self._is_fresh(
            self._settings_at, self._cache_ttl
        ):
            return dict(self._settings)

        records = await asyncio.to_thread(
            self._client.call_with_retry,
            lambda: self._client.read_records(SETTINGS_SHEET),
        )
        settings: dict[str, str] = {}
        for row in records:
            key = (row.get("kunci") or "").strip()
            if key:
                settings[key] = (row.get("nilai") or "").strip()
        self._settings = settings
        self._settings_at = time.monotonic()
        return dict(settings)

    # ---------- util ----------

    @property
    def default_account(self) -> str:
        return self._default_account

    async def default_account_value(self) -> str:
        settings = await self.settings()
        return settings.get("akun_default") or self._default_account

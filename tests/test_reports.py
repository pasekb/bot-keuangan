from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.models import Transaction, TransactionType
from app.services.reports import (
    category_breakdown,
    daily_points,
    donut_gradient,
    filter_transactions,
    recent,
    summarize,
)


def make_tx(
    *,
    amount: int,
    tx_type: TransactionType,
    category: str,
    day: int,
    month: int = 10,
    year: int = 2026,
    note: str = "",
    status: str = "aktif",
    chat_id: int | None = 1,
) -> Transaction:
    now = datetime(year, month, day, 10, 0, tzinfo=timezone.utc)
    return Transaction(
        id=uuid4().hex,
        date=date(year, month, day),
        type=tx_type,
        amount=amount,
        category=category,
        note=note,
        account="Cash",
        source="manual",
        status=status,
        created_at=now,
        updated_at=now,
        chat_id=chat_id,
    )


@pytest.fixture()
def transactions() -> list[Transaction]:
    return [
        make_tx(amount=8_000_000, tx_type=TransactionType.INCOME, category="Gaji", day=1),
        make_tx(amount=25_000, tx_type=TransactionType.EXPENSE, category="Makan & Minum", day=2),
        make_tx(amount=50_000, tx_type=TransactionType.EXPENSE, category="Transportasi", day=2),
        make_tx(amount=75_000, tx_type=TransactionType.EXPENSE, category="Makan & Minum", day=5),
        make_tx(amount=99_000, tx_type=TransactionType.EXPENSE, category="Hiburan", day=5, status="dihapus"),
        make_tx(amount=1_000_000, tx_type=TransactionType.EXPENSE, category="Belanja", day=15, month=9),
    ]


def test_summary_counts_active_only(transactions: list[Transaction]) -> None:
    summary = summarize(transactions, date(2026, 10, 1))
    assert summary.income == 8_000_000
    assert summary.expense == 150_000
    assert summary.net == 7_850_000
    assert summary.count == 4
    # saldo seluruh waktu termasuk transaksi September, tanpa yang dihapus
    assert summary.balance == 8_000_000 - 150_000 - 1_000_000


def test_category_breakdown(transactions: list[Transaction]) -> None:
    slices = category_breakdown(
        transactions, date(2026, 10, 1), TransactionType.EXPENSE
    )
    assert [item.name for item in slices] == ["Makan & Minum", "Transportasi"]
    assert slices[0].total == 100_000
    assert slices[0].share == pytest.approx(2 / 3, rel=1e-6)
    assert slices[1].share == pytest.approx(1 / 3, rel=1e-6)


def test_donut_gradient(transactions: list[Transaction]) -> None:
    slices = category_breakdown(
        transactions, date(2026, 10, 1), TransactionType.EXPENSE
    )
    gradient = donut_gradient(slices)
    assert gradient.startswith("conic-gradient(")
    assert "100.00%" in gradient


def test_daily_points(transactions: list[Transaction]) -> None:
    points = daily_points(transactions, date(2026, 10, 1))
    assert len(points) == 31
    assert points[1].total == 75_000
    assert points[1].height == 100
    assert points[4].total == 75_000
    assert points[0].total == 0


def test_filter_transactions(transactions: list[Transaction]) -> None:
    items, total = filter_transactions(
        transactions,
        month=date(2026, 10, 1),
        tx_type=TransactionType.EXPENSE,
        query="makan",
    )
    assert total == 2
    assert items[0].amount == 75_000

    items, total = filter_transactions(transactions, category="Transportasi")
    assert total == 1
    assert items[0].amount == 50_000


def test_recent_sorted_desc(transactions: list[Transaction]) -> None:
    items = recent(transactions, 3)
    assert len(items) == 3
    assert items[0].date >= items[1].date

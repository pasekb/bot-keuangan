"""Agregasi laporan (fungsi murni, mudah diuji)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from app.models import Category, Transaction, TransactionType
from app.utils.dates import month_bounds

PALETTE = (
    "#f97316",
    "#3b82f6",
    "#22c55e",
    "#a855f7",
    "#ef4444",
    "#14b8a6",
    "#eab308",
    "#ec4899",
    "#6366f1",
    "#84cc16",
)


@dataclass(frozen=True)
class Summary:
    month: date
    income: int
    expense: int
    net: int
    balance: int
    count: int


@dataclass(frozen=True)
class CategorySlice:
    name: str
    emoji: str
    total: int
    share: float
    color: str


@dataclass(frozen=True)
class DayPoint:
    date: date
    total: int
    height: int


def active_only(transactions: list[Transaction]) -> list[Transaction]:
    return [tx for tx in transactions if tx.is_active]


def in_month(transactions: list[Transaction], month: date) -> list[Transaction]:
    start, end = month_bounds(month)
    return [tx for tx in transactions if start <= tx.date <= end]


def summarize(transactions: list[Transaction], month: date) -> Summary:
    """Ringkasan bulan tertentu + saldo seluruh waktu."""
    active = active_only(transactions)
    monthly = in_month(active, month)
    income = sum(tx.amount for tx in monthly if tx.type is TransactionType.INCOME)
    expense = sum(tx.amount for tx in monthly if tx.type is TransactionType.EXPENSE)
    total_income = sum(tx.amount for tx in active if tx.type is TransactionType.INCOME)
    total_expense = sum(tx.amount for tx in active if tx.type is TransactionType.EXPENSE)
    return Summary(
        month=month,
        income=income,
        expense=expense,
        net=income - expense,
        balance=total_income - total_expense,
        count=len(monthly),
    )


def category_breakdown(
    transactions: list[Transaction],
    month: date,
    tx_type: TransactionType,
    categories: list[Category] | None = None,
) -> list[CategorySlice]:
    emoji_map: dict[str, str] = {}
    for category in categories or []:
        emoji_map.setdefault(category.name, category.emoji)

    totals: dict[str, int] = {}
    for tx in in_month(active_only(transactions), month):
        if tx.type is not tx_type:
            continue
        totals[tx.category] = totals.get(tx.category, 0) + tx.amount

    grand_total = sum(totals.values())
    if grand_total <= 0:
        return []

    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    slices: list[CategorySlice] = []
    for index, (name, total) in enumerate(ordered):
        slices.append(
            CategorySlice(
                name=name,
                emoji=emoji_map.get(name, "📦"),
                total=total,
                share=total / grand_total,
                color=PALETTE[index % len(PALETTE)],
            )
        )
    return slices


def donut_gradient(slices: list[CategorySlice]) -> str:
    if not slices:
        return "conic-gradient(#e5e7eb 0 100%)"
    stops: list[str] = []
    cursor = 0.0
    for item in slices:
        start = cursor
        cursor = min(100.0, cursor + item.share * 100)
        stops.append(f"{item.color} {start:.2f}% {cursor:.2f}%")
    if cursor < 100.0:
        stops.append(f"{slices[-1].color} {cursor:.2f}% 100%")
    return "conic-gradient(" + ", ".join(stops) + ")"


def daily_points(
    transactions: list[Transaction],
    month: date,
    tx_type: TransactionType = TransactionType.EXPENSE,
) -> list[DayPoint]:
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    totals = {day: 0 for day in range(1, days_in_month + 1)}
    for tx in in_month(active_only(transactions), month):
        if tx.type is tx_type:
            totals[tx.date.day] += tx.amount
    peak = max(totals.values(), default=0)
    points: list[DayPoint] = []
    for day, total in totals.items():
        if peak <= 0 or total <= 0:
            height = 0
        else:
            height = max(3, round(total / peak * 100))
        points.append(
            DayPoint(date=date(month.year, month.month, day), total=total, height=height)
        )
    return points


def recent(transactions: list[Transaction], limit: int = 10) -> list[Transaction]:
    active = active_only(transactions)
    active.sort(key=lambda tx: (tx.date, tx.created_at), reverse=True)
    return active[:limit]


def filter_transactions(
    transactions: list[Transaction],
    *,
    month: date | None = None,
    tx_type: TransactionType | None = None,
    category: str | None = None,
    query: str | None = None,
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[Transaction], int]:
    items = active_only(transactions)
    if month is not None:
        items = in_month(items, month)
    if tx_type is not None:
        items = [tx for tx in items if tx.type is tx_type]
    if category:
        items = [tx for tx in items if tx.category == category]
    if query:
        needle = query.strip().lower()
        items = [
            tx
            for tx in items
            if needle in tx.note.lower() or needle in tx.category.lower()
        ]
    items.sort(key=lambda tx: (tx.date, tx.created_at), reverse=True)
    total = len(items)
    page = max(1, page)
    start = (page - 1) * per_page
    return items[start : start + per_page], total

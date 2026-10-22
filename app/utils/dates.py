from __future__ import annotations

import calendar
from datetime import date

MONTHS_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

DAY_NAMES_ID = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)


def format_date(value: date, with_year: bool = True) -> str:
    label = f"{value.day} {MONTHS_ID[value.month - 1]}"
    return f"{label} {value.year}" if with_year else label


def format_date_short(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


def month_start(value: str | None, today: date | None = None) -> date:
    """Parse 'YYYY-MM' menjadi tanggal 1. Fallback ke bulan berjalan."""
    today = today or date.today()
    if value:
        try:
            year_str, month_str = value.split("-")[:2]
            year, month = int(year_str), int(month_str)
            if 1 <= month <= 12 and 1970 <= year <= 2200:
                return date(year, month, 1)
        except (ValueError, TypeError):
            pass
    return today.replace(day=1)


def iso_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def month_label(value: date) -> str:
    return f"{MONTHS_ID[value.month - 1]} {value.year}"


def shift_month(value: date, delta: int) -> date:
    index = value.year * 12 + (value.month - 1) + delta
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def month_bounds(value: date) -> tuple[date, date]:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=1), value.replace(day=last_day)

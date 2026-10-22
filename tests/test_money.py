from __future__ import annotations

import pytest

from app.utils.money import format_rupiah, parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("25rb", 25_000),
        ("25 k", 25_000),
        ("25.000", 25_000),
        ("Rp 25.000", 25_000),
        ("1,5jt", 1_500_000),
        ("1.5 juta", 1_500_000),
        ("2,5 jt", 2_500_000),
        ("12,5jt", 12_500_000),
        ("gaji 8jt", 8_000_000),
        ("1.250.000", 1_250_000),
        ("makan 25", 25_000),
        ("2 kopi 50rb", 50_000),
        ("5000", 5_000),
        ("beli laptop 2mio", 2_000_000),
        ("denda 1miliar", 1_000_000_000),
    ],
)
def test_parse_amount(raw: str, expected: int) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "tanpa angka", None, "0", "abc"])
def test_parse_amount_invalid(raw) -> None:
    assert parse_amount(raw) is None


def test_parse_amount_accepts_numbers() -> None:
    assert parse_amount(25_000) == 25_000
    assert parse_amount(25_000.4) == 25_000


def test_format_rupiah() -> None:
    assert format_rupiah(25_000) == "Rp 25.000"
    assert format_rupiah(0) == "Rp 0"
    assert format_rupiah(-5_000) == "-Rp 5.000"
    assert format_rupiah(1_250_000) == "Rp 1.250.000"

from __future__ import annotations

import re
from typing import Any

# Angka + satuan opsional. Contoh yang didukung:
#   25.000 / 25,000 / 25rb / 25k / 1,5jt / 1.5 juta / Rp 25000 / 2mio
_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*"
    r"(jt|juta|juta-an|ribu|rb|k|miliar|mio|m)?(?!\w)",
    re.IGNORECASE,
)

_SCALES = {
    "jt": 1_000_000,
    "juta": 1_000_000,
    "juta-an": 1_000_000,
    "rb": 1_000,
    "ribu": 1_000,
    "k": 1_000,
    "miliar": 1_000_000_000,
    "mio": 1_000_000,
    "m": 1_000_000,
}

MAX_AMOUNT = 1_000_000_000_000  # 1 triliun


def _normalize_numeric_text(text: str) -> str:
    """Ubah '25.000' / '1,5' / '1.500,75' jadi string desimal gaya Python."""
    value = text.strip()
    if not value:
        return value
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        head, _, tail = value.rpartition(",")
        if len(tail) == 3:
            value = head + tail
        else:
            value = head + "." + tail
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
    return value


def parse_amount(raw: Any) -> int | None:
    """Ambil nominal rupiah dari teks bebas atau angka.

    Mengembalikan None bila tidak ada angka yang masuk akal.
    Bila ada beberapa angka, ambil yang terbesar (biasanya total nominal).
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 < raw <= MAX_AMOUNT else None
    if isinstance(raw, float):
        value = int(round(raw))
        return value if 0 < value <= MAX_AMOUNT else None

    text = str(raw).lower()
    text = text.replace("rp", " ").replace("idr", " ").replace("rupiah", " ")

    candidates: list[int] = []
    for number, unit in _AMOUNT_PATTERN.findall(text):
        normalized = _normalize_numeric_text(number)
        try:
            number_value = float(normalized)
        except ValueError:
            continue
        unit = (unit or "").lower()
        scale = _SCALES.get(unit)
        if scale:
            value = number_value * scale
        elif number_value < 1000:
            # Chat Indonesia: "makan 25" hampir selalu berarti 25 ribu.
            value = number_value * 1000
        else:
            value = number_value
        value_int = int(round(value))
        if 0 < value_int <= MAX_AMOUNT:
            candidates.append(value_int)

    if not candidates:
        return None
    return max(candidates)


def format_rupiah(amount: int | float) -> str:
    """Format nominal sebagai Rupiah tanpa desimal: Rp 25.000."""
    value = int(round(amount))
    sign = "-" if value < 0 else ""
    return f"{sign}Rp {abs(value):,}".replace(",", ".")

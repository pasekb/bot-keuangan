"""Uji cepat koneksi ke model AI tanpa menyentuh Google Sheets.

Jalankan dari root proyek:
    python scripts/probe_ai.py
    python scripts/probe_ai.py "kopi 18rb"
    python scripts/probe_ai.py --image path/ke/struk.jpg
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.client import AIClient  # noqa: E402
from app.ai.parser import TransactionParser  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import Category  # noqa: E402
from app.sheets.schema import DEFAULT_CATEGORIES  # noqa: E402

SAMPLES = [
    "makan siang 25rb tadi",
    "bensin 50k kemarin",
    "gaji 8jt masuk",
    "kopi 18rb + parkir 5rb",
    "beli laptop 12,5jt",
]


async def main() -> int:
    settings = get_settings()
    ai = AIClient(
        api_key=settings.sumopod_api_key.get_secret_value(),
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        vision_model=settings.ai_vision_model,
        timeout_seconds=settings.ai_timeout_seconds,
        vision_timeout_seconds=settings.ai_vision_timeout_seconds,
    )
    parser = TransactionParser(
        ai_client=ai,
        timezone_name=settings.timezone,
        currency=settings.currency,
        default_account=settings.default_account,
    )
    categories = [
        Category(name=name, type=tx_type, emoji=emoji, order=order)
        for name, tx_type, emoji, order in DEFAULT_CATEGORIES
    ]

    args = sys.argv[1:]
    image_path: str | None = None
    if "--image" in args:
        index = args.index("--image")
        try:
            image_path = args[index + 1]
        except IndexError:
            print("Pemakaian: python scripts/probe_ai.py --image path/ke/struk.jpg")
            return 2
        del args[index : index + 2]

    print(f"Model teks   : {settings.ai_model}")
    print(f"Model vision : {settings.ai_vision_model}")
    print(f"URL          : {settings.ai_base_url}")
    print()

    if image_path is not None:
        path = Path(image_path)
        if not path.is_file():
            print(f"File tidak ditemukan: {path}")
            return 2
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(path.suffix.lower(), "image/jpeg")
        outcome = await parser.parse_image(
            path.read_bytes(), mime, categories, caption=" ".join(args) or None
        )
        await ai.close()
        if outcome.status == "ok" and outcome.transaction is not None:
            tx = outcome.transaction
            print(
                f"OK   {path.name} -> {tx.type.value} {tx.amount} "
                f"[{tx.category}] {tx.date} ({tx.source}, {tx.confidence:.2f})\n"
                f"     catatan: {tx.note}"
            )
            return 0
        print(f"?    {path.name} -> {outcome.question} (source={outcome.source})")
        return 1

    texts = args or SAMPLES
    ok = 0
    for text in texts:
        outcome = await parser.parse(text, categories)
        if outcome.status == "ok" and outcome.transaction is not None:
            tx = outcome.transaction
            print(
                f"OK   {text!r} -> {tx.type.value} {tx.amount} "
                f"[{tx.category}] {tx.date} ({tx.source}, {tx.confidence:.2f})"
            )
            ok += 1
        else:
            print(f"?    {text!r} -> {outcome.question} (source={outcome.source})")

    await ai.close()
    print(f"\n{ok}/{len(texts)} berhasil diparse")
    return 0 if ok == len(texts) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

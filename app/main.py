"""Entry point: jalankan bot Telegram dan dashboard dalam satu proses."""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from app.ai.client import AIClient
from app.ai.parser import TransactionParser
from app.bot.handlers import build_application
from app.config import get_settings
from app.services.transactions import TransactionService
from app.sheets.client import SheetsClient
from app.sheets.repository import SheetsRepository
from app.web.routes import create_web_app

logger = logging.getLogger("bot_keuangan")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    if not settings.allowed_user_ids:
        logger.warning(
            "TELEGRAM_ALLOWED_USER_IDS kosong: bot akan menolak semua pesan. "
            "Isi dengan ID Telegram kamu."
        )

    sheets = SheetsClient(
        credentials_file=settings.google_service_account_file,
        spreadsheet_id=settings.google_sheet_id,
    )
    repository = SheetsRepository(
        sheets,
        default_account=settings.default_account,
        timezone_name=settings.timezone,
        currency=settings.currency,
    )
    await repository.initialize()
    logger.info("Google Sheets siap dipakai")

    ai_client = AIClient(
        api_key=settings.sumopod_api_key.get_secret_value(),
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        vision_model=settings.ai_vision_model,
        timeout_seconds=settings.ai_timeout_seconds,
        vision_timeout_seconds=settings.ai_vision_timeout_seconds,
    )
    parser = TransactionParser(
        ai_client=ai_client,
        timezone_name=settings.timezone,
        currency=settings.currency,
        default_account=settings.default_account,
    )
    service = TransactionService(
        repository,
        parser,
        timezone=settings.tzinfo,
        default_account=settings.default_account,
    )

    telegram_app = build_application(settings, service)
    web_app = create_web_app(settings, repository)

    server = uvicorn.Server(
        uvicorn.Config(
            web_app,
            host=settings.web_host,
            port=settings.web_port,
            log_level=settings.log_level.lower(),
            access_log=False,
            proxy_headers=True,
        )
    )

    await telegram_app.initialize()
    await telegram_app.start()
    if telegram_app.updater is None:
        raise RuntimeError("Updater Telegram tidak tersedia")
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    logger.info(
        "Bot aktif (polling). Dashboard: http://%s:%s | model AI: %s",
        settings.web_host,
        settings.web_port,
        settings.ai_model,
    )

    try:
        await server.serve()
    finally:
        logger.info("Menghentikan bot...")
        if telegram_app.updater.running:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        await ai_client.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

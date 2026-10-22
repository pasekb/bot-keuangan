from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi aplikasi dari environment / file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: SecretStr
    telegram_allowed_user_ids: str = ""

    # AI provider (OpenAI-compatible, default Sumopod AI)
    sumopod_api_key: SecretStr
    ai_base_url: str = "https://ai.sumopod.com/v1"
    ai_model: str = "deepseek-v4-flash"
    ai_timeout_seconds: float = 20.0
    ai_vision_model: str = "glm-5v-turbo"
    ai_vision_timeout_seconds: float = 45.0

    # Google Sheets
    google_service_account_file: Path = Path("credentials/service-account.json")
    google_sheet_id: str

    # Aplikasi
    timezone: str = "Asia/Jakarta"
    currency: str = "IDR"
    default_account: str = "Cash"
    log_level: str = "INFO"

    # Web dashboard
    web_password: SecretStr
    web_secret_key: SecretStr
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8000, ge=1, le=65535)
    secure_cookies: bool = False

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        ids: set[int] = set()
        for chunk in self.telegram_allowed_user_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.add(int(chunk))
            except ValueError as exc:
                raise ValueError(
                    f"TELEGRAM_ALLOWED_USER_IDS berisi nilai tidak valid: {chunk!r}"
                ) from exc
        return frozenset(ids)

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

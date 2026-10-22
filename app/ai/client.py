from __future__ import annotations

import asyncio
import logging

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class AIClient:
    """Client OpenAI-compatible untuk Sumopod AI (default DeepSeek V4 Flash)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        vision_model: str | None = None,
        timeout_seconds: float = 20.0,
        vision_timeout_seconds: float = 45.0,
    ) -> None:
        self._model = model
        self._vision_model = (vision_model or model).strip() or model
        self._vision_timeout = vision_timeout_seconds
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._semaphore = asyncio.Semaphore(2)
        self._json_mode: bool | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def vision_model(self) -> str:
        return self._vision_model

    async def complete_json(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """Kirim percakapan dan kembalikan isi pesan. None bila gagal."""
        target_model = model or self._model
        async with self._semaphore:
            for attempt in range(2):
                payload: dict = {
                    "model": target_model,
                    "messages": messages,
                    "temperature": 0,
                }
                if self._json_mode is not False:
                    payload["response_format"] = {"type": "json_object"}

                try:
                    request_kwargs = {"timeout": timeout} if timeout is not None else {}
                    response = await self._client.chat.completions.create(
                        **payload, **request_kwargs
                    )
                except BadRequestError as exc:
                    if self._json_mode is not False:
                        logger.info(
                            "response_format tidak didukung model %s, ulangi tanpa JSON mode",
                            target_model,
                        )
                        self._json_mode = False
                        continue
                    logger.warning("Permintaan AI ditolak: %s", exc)
                    return None
                except RateLimitError:
                    if attempt == 0:
                        logger.warning("Rate limit AI, mencoba sekali lagi")
                        await asyncio.sleep(2.0)
                        continue
                    logger.warning("Rate limit AI tetap terjadi, memakai fallback")
                    return None
                except (APITimeoutError, APIConnectionError):
                    if attempt == 0:
                        logger.warning("AI timeout/koneksi gagal, mencoba sekali lagi")
                        await asyncio.sleep(1.0)
                        continue
                    logger.warning("AI tidak dapat dihubungi, memakai fallback")
                    return None
                except APIStatusError as exc:
                    logger.warning("AI mengembalikan status %s: %s", exc.status_code, exc)
                    return None
                except Exception:
                    logger.exception("Kesalahan tak terduga saat memanggil AI")
                    return None

                if self._json_mode is None:
                    self._json_mode = True
                if not response.choices:
                    return None
                content = response.choices[0].message.content
                return content.strip() if content else None
        return None

    async def complete_vision_json(self, messages: list[dict]) -> str | None:
        """Baca gambar (struk) dan kembalikan JSON. None bila gagal."""
        return await self.complete_json(
            messages,
            model=self._vision_model,
            timeout=self._vision_timeout,
        )

    async def close(self) -> None:
        await self._client.close()

"""Keamanan dashboard: rate limit login, password, CSRF."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict

from starlette.requests import Request


def hash_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def verify_password(candidate: str, expected: str) -> bool:
    if not expected:
        return False
    return secrets.compare_digest(hash_secret(candidate), hash_secret(expected))


class LoginRateLimiter:
    """Batasi percobaan login per alamat IP dalam jendela waktu tertentu."""

    def __init__(self, max_attempts: int = 5, window_seconds: float = 900.0) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self._window
        kept = [stamp for stamp in self._attempts.get(key, []) if stamp >= cutoff]
        if kept:
            self._attempts[key] = kept
        else:
            self._attempts.pop(key, None)
        return kept

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        return len(self._prune(key, now)) >= self._max_attempts

    def register_failure(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._prune(key, now)
        attempts.append(now)
        self._attempts[key] = attempts

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


def get_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return str(token)


def verify_csrf(request: Request, token: str | None) -> bool:
    expected = request.session.get("csrf")
    if not expected or not token:
        return False
    return secrets.compare_digest(str(expected), str(token))


def rotate_csrf(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session["csrf"] = token
    return token

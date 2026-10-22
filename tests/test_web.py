from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import Category, Transaction, TransactionType
from app.sheets.schema import DEFAULT_CATEGORIES
from app.web.routes import create_web_app

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class FakeRepository:
    def __init__(self) -> None:
        today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
        created = datetime.now(ZoneInfo("Asia/Jakarta"))
        self.transactions: list[Transaction] = [
            Transaction(
                id=uuid4().hex,
                date=today,
                type=TransactionType.EXPENSE,
                amount=25_000,
                category="Makan & Minum",
                note="makan siang",
                account="Cash",
                source="manual",
                status="aktif",
                created_at=created,
                updated_at=created,
                chat_id=None,
            )
        ]
        self.categories_list = [
            Category(name=name, type=tx_type, emoji=emoji, order=order)
            for name, tx_type, emoji, order in DEFAULT_CATEGORIES
        ]

    async def list_transactions(self, fresh: bool = False) -> list[Transaction]:
        return list(self.transactions)

    async def categories(self, fresh: bool = False) -> list[Category]:
        return list(self.categories_list)

    async def get_transaction(self, transaction_id: str) -> Transaction | None:
        for tx in self.transactions:
            if tx.id == transaction_id:
                return tx
        return None

    async def add_transaction(self, transaction: Transaction) -> Transaction:
        self.transactions.append(transaction)
        return transaction

    async def update_transaction(self, transaction: Transaction) -> Transaction:
        for index, current in enumerate(self.transactions):
            if current.id == transaction.id:
                self.transactions[index] = transaction
                return transaction
        raise LookupError(transaction.id)

    async def delete_transaction(self, transaction_id: str, *, soft: bool = True):
        tx = await self.get_transaction(transaction_id)
        if tx is None:
            raise LookupError(transaction_id)
        tx.status = "dihapus"
        return tx


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="123:abc",
        telegram_allowed_user_ids="1",
        sumopod_api_key="key",
        google_sheet_id="sheet",
        google_service_account_file=Path("credentials/test.json"),
        web_password="password-rahasia",
        web_secret_key="x" * 40,
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    repo = FakeRepository()
    app = create_web_app(settings, repo)  # type: ignore[arg-type]
    app.state.repo = repo  # type: ignore[attr-defined]
    return TestClient(app)


def login(client: TestClient) -> str:
    page = client.get("/login")
    token = CSRF_RE.search(page.text).group(1)
    response = client.post(
        "/login",
        data={"password": "password-rahasia", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return token


def test_requires_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_wrong_password(client: TestClient) -> None:
    page = client.get("/login")
    token = CSRF_RE.search(page.text).group(1)
    response = client.post(
        "/login",
        data={"password": "salah", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_dashboard_after_login(client: TestClient) -> None:
    login(client)
    response = client.get("/")
    assert response.status_code == 200
    assert "Ringkasan" in response.text
    assert "Rp 25.000" in response.text


def test_create_transaction(client: TestClient) -> None:
    login(client)
    page = client.get("/transaksi")
    token = CSRF_RE.search(page.text).group(1)
    response = client.post(
        "/transaksi",
        data={
            "csrf_token": token,
            "tipe": "pengeluaran",
            "tanggal": "2026-10-03",
            "nominal": "40rb",
            "kategori": "Transportasi",
            "catatan": "bensin",
            "akun": "Cash",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = client.get("/transaksi")
    assert "bensin" in page.text
    assert "Rp 40.000" in page.text


def test_create_transaction_rejects_bad_amount(client: TestClient) -> None:
    login(client)
    page = client.get("/transaksi")
    token = CSRF_RE.search(page.text).group(1)
    response = client.post(
        "/transaksi",
        data={
            "csrf_token": token,
            "tipe": "pengeluaran",
            "tanggal": "2026-10-03",
            "nominal": "abc",
            "kategori": "Transportasi",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_export_csv(client: TestClient) -> None:
    login(client)
    response = client.get("/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "makan siang" in response.text


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

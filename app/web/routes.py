"""Web dashboard (FastAPI + Jinja2)."""

from __future__ import annotations

import csv
import io
import math
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from app import __version__
from app.config import Settings
from app.models import Category, Transaction, TransactionType
from app.services.reports import (
    category_breakdown,
    daily_points,
    donut_gradient,
    filter_transactions,
    recent,
    summarize,
)
from app.sheets.repository import SheetsRepository, TransactionNotFound
from app.utils.dates import (
    format_date,
    iso_month,
    month_label,
    month_start,
    shift_month,
)
from app.utils.money import format_rupiah, parse_amount
from app.web.security import (
    LoginRateLimiter,
    get_csrf,
    rotate_csrf,
    verify_csrf,
    verify_password,
)

PER_PAGE = 25
BASE_DIR = Path(__file__).parent


def _optional_month(value: str | None) -> date | None:
    if not value:
        return None
    try:
        year_str, month_str = value.split("-")[:2]
        return date(int(year_str), int(month_str), 1)
    except (ValueError, TypeError):
        return None


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _redirect_with_error(url: str, message: str) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{separator}error={quote(message)}", status_code=303)


def _forbidden(message: str = "CSRF token tidak valid") -> HTMLResponse:
    return HTMLResponse(
        f"<h1>403</h1><p>{message}</p><p><a href='/'>Kembali</a></p>",
        status_code=403,
    )


def create_web_app(settings: Settings, repository: SheetsRepository) -> FastAPI:
    app = FastAPI(title="Bot Keuangan", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_secret_key.get_secret_value(),
        session_cookie="bk_session",
        max_age=60 * 60 * 12,
        same_site="lax",
        https_only=settings.secure_cookies,
    )

    static_dir = BASE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["rupiah"] = format_rupiah
    templates.env.filters["tanggal"] = format_date

    limiter = LoginRateLimiter()
    expected_password = settings.web_password.get_secret_value()

    def now_local() -> datetime:
        return datetime.now(settings.tzinfo)

    def require_auth(request: Request) -> None:
        if request.session.get("auth") is not True:
            raise HTTPException(status_code=303, headers={"Location": "/login"})

    def base_context(request: Request, active: str) -> dict:
        return {
            "request": request,
            "csrf": get_csrf(request),
            "active": active,
            "show_nav": request.session.get("auth") is True,
            "year": now_local().year,
            "version": __version__,
        }

    # ---------- auth ----------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if request.session.get("auth") is True:
            return RedirectResponse("/", status_code=303)
        context = base_context(request, "login")
        context.update({"error": None, "show_nav": False})
        return templates.TemplateResponse(request=request, name="login.html", context=context)

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        password: str = Form(...),
        csrf_token: str = Form(default=""),
    ) -> Response:
        if not verify_csrf(request, csrf_token):
            return _forbidden()
        context = base_context(request, "login")
        context["show_nav"] = False

        key = _client_key(request)
        if limiter.is_blocked(key):
            context["error"] = "Terlalu banyak percobaan. Coba lagi dalam 15 menit."
            return templates.TemplateResponse(
                request=request, name="login.html", context=context, status_code=429
            )

        if not verify_password(password, expected_password):
            limiter.register_failure(key)
            context["error"] = "Password salah."
            return templates.TemplateResponse(
                request=request, name="login.html", context=context, status_code=401
            )

        limiter.reset(key)
        request.session["auth"] = True
        rotate_csrf(request)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request, csrf_token: str = Form(default="")) -> Response:
        if not verify_csrf(request, csrf_token):
            return _forbidden()
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ---------- dashboard ----------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        bulan: str | None = Query(default=None),
        _: None = Depends(require_auth),
    ) -> Response:
        today = now_local().date()
        month = month_start(bulan, today)
        transactions = await repository.list_transactions()
        categories = await repository.categories()
        summary = summarize(transactions, month)
        slices = category_breakdown(
            transactions, month, TransactionType.EXPENSE, categories
        )

        context = base_context(request, "dashboard")
        context.update(
            {
                "month": month,
                "month_value": iso_month(month),
                "month_label": month_label(month),
                "prev_month": iso_month(shift_month(month, -1)),
                "next_month": iso_month(shift_month(month, 1)),
                "is_current_month": month == today.replace(day=1),
                "summary": summary,
                "slices": slices,
                "donut": donut_gradient(slices),
                "daily": daily_points(transactions, month),
                "recent_txs": recent(transactions, 10),
                "emoji_map": {cat.name: cat.emoji for cat in categories},
                "error": request.query_params.get("error"),
            }
        )
        return templates.TemplateResponse(request=request, name="dashboard.html", context=context)

    # ---------- transaksi ----------

    @app.get("/transaksi", response_class=HTMLResponse)
    async def transactions_page(
        request: Request,
        bulan: str = Query(default=""),
        tipe: str = Query(default=""),
        kategori: str = Query(default=""),
        q: str = Query(default=""),
        page: int = Query(default=1),
        _: None = Depends(require_auth),
    ) -> Response:
        today = now_local().date()
        month = _optional_month(bulan)
        tx_type = TransactionType(tipe) if tipe in {"pengeluaran", "pemasukan"} else None
        transactions = await repository.list_transactions()
        categories = await repository.categories()

        all_items, total = filter_transactions(
            transactions,
            month=month,
            tx_type=tx_type,
            category=kategori or None,
            query=q or None,
            page=1,
            per_page=1_000_000,
        )
        pages = max(1, math.ceil(total / PER_PAGE))
        page = min(max(1, page), pages)
        start = (page - 1) * PER_PAGE
        items = all_items[start : start + PER_PAGE]

        filtered_income = sum(
            tx.amount for tx in all_items if tx.type is TransactionType.INCOME
        )
        filtered_expense = sum(
            tx.amount for tx in all_items if tx.type is TransactionType.EXPENSE
        )

        query_params = {
            key: value
            for key, value in {
                "bulan": bulan,
                "tipe": tipe,
                "kategori": kategori,
                "q": q,
            }.items()
            if value
        }

        context = base_context(request, "transaksi")
        context.update(
            {
                "items": items,
                "total": total,
                "page": page,
                "pages": pages,
                "month": month,
                "month_value": iso_month(month) if month else "",
                "tipe": tipe,
                "kategori": kategori,
                "q": q,
                "categories": categories,
                "category_names": sorted({cat.name for cat in categories}),
                "today_iso": today.isoformat(),
                "filtered_income": filtered_income,
                "filtered_expense": filtered_expense,
                "base_query": urlencode(query_params),
                "error": request.query_params.get("error"),
            }
        )
        return templates.TemplateResponse(
            request=request, name="transactions.html", context=context
        )

    async def _validate_category(
        raw: str, tx_type: TransactionType
    ) -> tuple[str | None, list[Category]]:
        categories = await repository.categories()
        target = (raw or "").strip().lower()
        for category in categories:
            if category.type is tx_type and category.name.lower() == target:
                return category.name, categories
        return None, categories

    @app.post("/transaksi")
    async def create_transaction(
        request: Request,
        tipe: str = Form(...),
        tanggal: str = Form(...),
        nominal: str = Form(...),
        kategori: str = Form(...),
        catatan: str = Form(default=""),
        akun: str = Form(default=""),
        csrf_token: str = Form(default=""),
        _: None = Depends(require_auth),
    ) -> Response:
        if not verify_csrf(request, csrf_token):
            return _forbidden()
        try:
            tx_type = TransactionType(tipe)
        except ValueError:
            return _redirect_with_error("/transaksi", "Tipe transaksi tidak valid.")

        amount = parse_amount(nominal)
        if amount is None or amount <= 0:
            return _redirect_with_error("/transaksi", "Nominal tidak valid.")

        try:
            tx_date = date.fromisoformat(tanggal)
        except ValueError:
            return _redirect_with_error("/transaksi", "Tanggal tidak valid.")

        category, _ = await _validate_category(kategori, tx_type)
        if category is None:
            return _redirect_with_error("/transaksi", "Kategori tidak dikenal.")

        now = now_local()
        transaction = Transaction(
            id=uuid.uuid4().hex,
            date=tx_date,
            type=tx_type,
            amount=amount,
            category=category,
            note=catatan.strip()[:200],
            account=(akun.strip() or settings.default_account),
            source="manual",
            status="aktif",
            created_at=now,
            updated_at=now,
            chat_id=None,
        )
        await repository.add_transaction(transaction)
        return RedirectResponse("/transaksi", status_code=303)

    @app.get("/transaksi/{tx_id}/edit", response_class=HTMLResponse)
    async def edit_page(
        request: Request,
        tx_id: str,
        _: None = Depends(require_auth),
    ) -> Response:
        transaction = await repository.get_transaction(tx_id)
        if transaction is None:
            return _redirect_with_error("/transaksi", "Transaksi tidak ditemukan.")
        categories = await repository.categories()
        context = base_context(request, "transaksi")
        context.update(
            {
                "transaction": transaction,
                "categories": categories,
                "today_iso": now_local().date().isoformat(),
                "error": request.query_params.get("error"),
            }
        )
        return templates.TemplateResponse(request=request, name="edit.html", context=context)

    @app.post("/transaksi/{tx_id}/edit")
    async def update_transaction(
        request: Request,
        tx_id: str,
        tipe: str = Form(...),
        tanggal: str = Form(...),
        nominal: str = Form(...),
        kategori: str = Form(...),
        catatan: str = Form(default=""),
        akun: str = Form(default=""),
        csrf_token: str = Form(default=""),
        _: None = Depends(require_auth),
    ) -> Response:
        if not verify_csrf(request, csrf_token):
            return _forbidden()
        transaction = await repository.get_transaction(tx_id)
        if transaction is None:
            return _redirect_with_error("/transaksi", "Transaksi tidak ditemukan.")

        try:
            tx_type = TransactionType(tipe)
        except ValueError:
            return _redirect_with_error(f"/transaksi/{tx_id}/edit", "Tipe tidak valid.")
        amount = parse_amount(nominal)
        if amount is None or amount <= 0:
            return _redirect_with_error(f"/transaksi/{tx_id}/edit", "Nominal tidak valid.")
        try:
            tx_date = date.fromisoformat(tanggal)
        except ValueError:
            return _redirect_with_error(f"/transaksi/{tx_id}/edit", "Tanggal tidak valid.")

        category, _ = await _validate_category(kategori, tx_type)
        if category is None:
            return _redirect_with_error(f"/transaksi/{tx_id}/edit", "Kategori tidak dikenal.")

        transaction.date = tx_date
        transaction.type = tx_type
        transaction.amount = amount
        transaction.category = category
        transaction.note = catatan.strip()[:200]
        transaction.account = akun.strip() or settings.default_account
        transaction.updated_at = now_local()
        try:
            await repository.update_transaction(transaction)
        except TransactionNotFound:
            return _redirect_with_error("/transaksi", "Transaksi sudah tidak ada.")
        return RedirectResponse("/transaksi", status_code=303)

    @app.post("/transaksi/{tx_id}/hapus")
    async def delete_transaction(
        request: Request,
        tx_id: str,
        csrf_token: str = Form(default=""),
        _: None = Depends(require_auth),
    ) -> Response:
        if not verify_csrf(request, csrf_token):
            return _forbidden()
        try:
            await repository.delete_transaction(tx_id)
        except TransactionNotFound:
            return _redirect_with_error("/transaksi", "Transaksi tidak ditemukan.")
        return RedirectResponse("/transaksi", status_code=303)

    # ---------- export ----------

    @app.get("/export.csv")
    async def export_csv(
        request: Request,
        bulan: str = Query(default=""),
        tipe: str = Query(default=""),
        kategori: str = Query(default=""),
        q: str = Query(default=""),
        _: None = Depends(require_auth),
    ) -> Response:
        month = _optional_month(bulan)
        tx_type = TransactionType(tipe) if tipe in {"pengeluaran", "pemasukan"} else None
        transactions = await repository.list_transactions()
        items, _ = filter_transactions(
            transactions,
            month=month,
            tx_type=tx_type,
            category=kategori or None,
            query=q or None,
            page=1,
            per_page=1_000_000,
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "tanggal", "tipe", "nominal", "kategori", "catatan", "akun", "sumber"]
        )
        for tx in items:
            writer.writerow(
                [
                    tx.id,
                    tx.date.isoformat(),
                    tx.type.value,
                    tx.amount,
                    tx.category,
                    tx.note,
                    tx.account,
                    tx.source,
                ]
            )
        filename = f"transaksi-{iso_month(month) if month else 'semua'}.csv"
        content = "\ufeff" + buffer.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app

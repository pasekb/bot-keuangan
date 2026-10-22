"""Lapisan tipis di atas gspread: koneksi, pembuatan sheet, baca/tulis."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

import gspread
from gspread.exceptions import APIError, WorksheetNotFound

from app.sheets.schema import TRANSACTIONS_SHEET, TRANSACTION_HEADERS

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SheetSchemaError(RuntimeError):
    """Header sheet yang sudah ada tidak sesuai dengan yang diharapkan."""


@dataclass
class SheetTable:
    worksheet: Any
    headers: list[str]


class SheetsClient:
    """Akses Google Sheets yang tahan terhadap rate limit sementara."""

    def __init__(self, credentials_file: Path | str, spreadsheet_id: str) -> None:
        self._credentials_file = Path(credentials_file)
        self._spreadsheet_id = spreadsheet_id.strip()
        self._spreadsheet: Any | None = None
        self._tables: dict[str, SheetTable] = {}

    # ---------- koneksi ----------

    def connect(self) -> "SheetsClient":
        if not self._credentials_file.exists():
            raise FileNotFoundError(
                f"File service account tidak ditemukan: {self._credentials_file}. "
                "Unduh JSON dari Google Cloud lalu simpan di path tersebut."
            )
        if not self._spreadsheet_id:
            raise ValueError("GOOGLE_SHEET_ID belum diisi.")

        client = gspread.service_account(filename=str(self._credentials_file))
        self._spreadsheet = client.open_by_key(self._spreadsheet_id)
        return self

    @property
    def spreadsheet(self) -> Any:
        if self._spreadsheet is None:
            self.connect()
        return self._spreadsheet

    # ---------- retry ----------

    def call_with_retry(self, fn: Callable[[], T], attempts: int = 4) -> T:
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return fn()
            except APIError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                last_error = exc
                if status in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    logger.warning("Google Sheets error %s, retry %s/%s", status, attempt + 1, attempts)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            except (ConnectionError, TimeoutError) as exc:
                last_error = exc
                if attempt < attempts - 1:
                    logger.warning("Koneksi ke Google gagal, retry %s/%s", attempt + 1, attempts)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise RuntimeError("Permintaan Google Sheets gagal") from last_error

    # ---------- struktur sheet ----------

    def ensure_table(self, title: str, headers: list[str]) -> SheetTable:
        if title in self._tables:
            return self._tables[title]

        spreadsheet = self.spreadsheet
        try:
            worksheet = spreadsheet.worksheet(title)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=title, rows=1000, cols=max(len(headers), 8)
            )
            logger.info("Sheet %r dibuat", title)

        existing = [cell.strip() for cell in worksheet.row_values(1)]
        if not any(existing):
            worksheet.update(values=[headers], range_name="A1")
        else:
            existing = existing[: len(headers)]
            if existing != headers:
                raise SheetSchemaError(
                    f"Sheet {title!r} sudah ada dengan header berbeda.\n"
                    f"Diharapkan: {headers}\nDitemukan: {existing}\n"
                    "Ganti nama sheet lama atau hapus isinya."
                )

        table = SheetTable(worksheet=worksheet, headers=list(headers))
        self._tables[title] = table
        return table

    def table(self, title: str) -> SheetTable:
        try:
            return self._tables[title]
        except KeyError as exc:
            raise KeyError(f"Sheet {title!r} belum diinisialisasi") from exc

    def read_records(self, title: str) -> list[dict[str, str]]:
        table = self.table(title)
        values: list[list[str]] = table.worksheet.get_all_values()
        if not values:
            return []

        header = [cell.strip() for cell in values[0]]
        records: list[dict[str, str]] = []
        for row in values[1:]:
            if not any(cell.strip() for cell in row):
                continue
            record: dict[str, str] = {}
            for index, column in enumerate(header):
                if not column:
                    continue
                record[column] = row[index] if index < len(row) else ""
            records.append(record)
        return records

    def append_row(self, title: str, values: list[str]) -> None:
        table = self.table(title)
        # RAW: simpan tanggal & id sebagai teks apa adanya, tanpa auto-format Sheets.
        table.worksheet.append_row(values, value_input_option="RAW")

    def update_row(self, title: str, row_number: int, values: list[str]) -> None:
        table = self.table(title)
        end_cell = gspread.utils.rowcol_to_a1(row_number, len(values))
        table.worksheet.update(
            values=[values], range_name=f"A{row_number}:{end_cell}"
        )

    def find_row(self, title: str, value: str, column: int = 1) -> int | None:
        table = self.table(title)
        try:
            column_values = table.worksheet.col_values(column)
        except gspread.exceptions.GSpreadException:
            return None
        try:
            return column_values.index(value) + 1
        except ValueError:
            return None

    # ---------- formatting opsional ----------

    def format_table(self, title: str) -> None:
        """Kosmetik: header tebal, freeze baris, format angka nominal."""
        try:
            table = self.table(title)
            worksheet = table.worksheet
            requests: list[dict[str, Any]] = [
                {
                    "repeatCell": {
                        "range": {"sheetId": worksheet.id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": worksheet.id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
            ]
            if title == TRANSACTIONS_SHEET and "nominal" in TRANSACTION_HEADERS:
                column_index = TRANSACTION_HEADERS.index("nominal")
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": worksheet.id,
                                "startRowIndex": 1,
                                "startColumnIndex": column_index,
                                "endColumnIndex": column_index + 1,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}
                                }
                            },
                            "fields": "userEnteredFormat.numberFormat",
                        }
                    }
                )
            self.spreadsheet.batch_update({"requests": requests})
        except Exception:  # pragma: no cover - formatting tidak boleh memblokir startup
            logger.warning("Gagal menerapkan format pada sheet %r", title, exc_info=True)

"""Excel exports: a thin wrapper over openpyxl with the house header style and number formats.

    book = ExcelBook()
    book.add_table(
        "Mizan",
        [ExcelColumn("Hesap"), ExcelColumn("Borç", "money"), ExcelColumn("Alacak", "money")],
        rows,
        title="Mizan - 2026/03",
        total_columns=("Borç", "Alacak"),
    )
    content = book.to_bytes()

Decimals are written as numbers (never text) so that the sheet stays calculable; Excel shows them
with the user's own separators. Sheets that need custom layouts or formulas use `add_sheet()` and the
`style_header` / `auto_width` helpers on the raw worksheet.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ColumnKind = Literal["text", "int", "money", "qty", "price", "pct", "date", "datetime"]

NUMBER_FORMATS: dict[str, str] = {
    "int": "#,##0",
    "money": "#,##0.00",
    "qty": "#,##0.###",
    "price": "#,##0.00####",
    "pct": "0.00",
    "date": "DD.MM.YYYY",
    "datetime": "DD.MM.YYYY HH:MM",
}

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
_TITLE_FONT = Font(bold=True, size=13)
_TOTAL_FONT = Font(bold=True)
_THIN = Side(style="thin", color="8C8C8C")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_MAX_SHEET_TITLE = 31
_MIN_WIDTH = 8
_MAX_WIDTH = 60
_RIGHT_ALIGNED = {"int", "money", "qty", "price", "pct"}


@dataclass(frozen=True, slots=True)
class ExcelColumn:
    title: str
    kind: ColumnKind = "text"
    width: float | None = None  # characters; None sizes the column to its content


def style_header(cells: Iterable[Cell]) -> None:
    """Apply the house header style (bold white on blue, centred, bordered)."""
    for cell in cells:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT
        cell.border = _BORDER


def _display_length(cell: Cell) -> int:
    value = cell.value
    if value is None:
        return 0
    if isinstance(value, str) and value.startswith("="):
        return 12  # a formula's result length is unknown; assume a typical amount
    if isinstance(value, datetime):
        return 16
    if isinstance(value, date):
        return 10
    if isinstance(value, (int, float, Decimal)):
        return len(f"{value:,}") + 2
    return max(len(line) for line in str(value).split("\n"))


def auto_width(sheet: Worksheet, *, skip_rows: int = 0) -> None:
    """Size every column to its longest cell. `skip_rows` leading rows (a wide title) are ignored."""
    widths: dict[int, int] = {}
    for row in sheet.iter_rows(min_row=skip_rows + 1):
        for cell in row:
            widths[cell.column] = max(widths.get(cell.column, 0), _display_length(cell))
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = max(_MIN_WIDTH, min(width + 2, _MAX_WIDTH))


class ExcelBook:
    def __init__(self) -> None:
        self._workbook = Workbook()
        self._workbook.remove(self._workbook.active)
        self._titles: set[str] = set()

    def _sheet_title(self, title: str) -> str:
        cleaned = _INVALID_SHEET_CHARS.sub(" ", title).strip()[:_MAX_SHEET_TITLE] or "Sayfa"
        candidate, counter = cleaned, 2
        while candidate.lower() in self._titles:
            suffix = f" ({counter})"
            candidate = cleaned[: _MAX_SHEET_TITLE - len(suffix)] + suffix
            counter += 1
        self._titles.add(candidate.lower())
        return candidate

    def add_sheet(self, title: str) -> Worksheet:
        """An empty worksheet for custom layouts; the title is made valid and unique for Excel."""
        return self._workbook.create_sheet(self._sheet_title(title))

    def add_table(
        self,
        sheet_title: str,
        columns: Sequence[ExcelColumn],
        rows: Iterable[Sequence[Any]],
        *,
        title: str | None = None,
        total_columns: Sequence[str] = (),
    ) -> Worksheet:
        """A sheet with an optional title line, a styled frozen header with auto-filter and typed columns.

        `total_columns` names the columns that get a `SUM` formula in a bold "TOPLAM" row.
        """
        if not columns:
            raise ValueError("A table needs at least one column")
        unknown = set(total_columns) - {column.title for column in columns}
        if unknown:
            raise ValueError(f"total_columns refers to unknown columns: {sorted(unknown)}")
        sheet = self.add_sheet(sheet_title)
        header_row = 1
        if title:
            sheet.cell(row=1, column=1, value=title).font = _TITLE_FONT
            header_row = 3
        for index, column in enumerate(columns, start=1):
            sheet.cell(row=header_row, column=index, value=column.title)
        style_header(sheet[header_row])
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

        last_data_row = header_row
        for values in rows:
            if len(values) != len(columns):
                raise ValueError(f"Row has {len(values)} values for {len(columns)} columns")
            last_data_row += 1
            for index, (value, column) in enumerate(zip(values, columns, strict=True), start=1):
                cell = sheet.cell(row=last_data_row, column=index, value=value)
                if cell.data_type == "f":
                    # Data is never a formula: text such as a partner name starting with "=" must not
                    # be evaluated by Excel (formula injection).
                    cell.data_type = "s"
                self._format_cell(cell, column)

        last_letter = get_column_letter(len(columns))
        sheet.auto_filter.ref = f"A{header_row}:{last_letter}{last_data_row}"

        if total_columns and last_data_row > header_row:
            total_row = last_data_row + 1
            sheet.cell(row=total_row, column=1, value="TOPLAM").font = _TOTAL_FONT
            for index, column in enumerate(columns, start=1):
                if column.title in total_columns:
                    letter = get_column_letter(index)
                    formula = f"=SUM({letter}{header_row + 1}:{letter}{last_data_row})"
                    cell = sheet.cell(row=total_row, column=index, value=formula)
                    cell.font = _TOTAL_FONT
                    self._format_cell(cell, column)

        auto_width(sheet, skip_rows=header_row - 1)
        for index, column in enumerate(columns, start=1):
            if column.width is not None:
                sheet.column_dimensions[get_column_letter(index)].width = column.width
        return sheet

    @staticmethod
    def _format_cell(cell: Cell, column: ExcelColumn) -> None:
        number_format = NUMBER_FORMATS.get(column.kind)
        if number_format:
            cell.number_format = number_format
        if column.kind in _RIGHT_ALIGNED:
            cell.alignment = Alignment(horizontal="right")

    def to_bytes(self) -> bytes:
        if not self._workbook.sheetnames:
            raise ValueError("The workbook has no sheets")
        buffer = io.BytesIO()
        self._workbook.save(buffer)
        return buffer.getvalue()

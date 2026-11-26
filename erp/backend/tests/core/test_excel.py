"""Excel helper: styled header, typed columns, totals, widths, raw sheets."""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.core.excel import NUMBER_FORMATS, XLSX_MIME, ExcelBook, ExcelColumn, auto_width, style_header

COLUMNS = [
    ExcelColumn("Hesap Kodu"),
    ExcelColumn("Hesap Adı"),
    ExcelColumn("Tarih", "date"),
    ExcelColumn("Miktar", "qty"),
    ExcelColumn("Borç", "money"),
    ExcelColumn("Alacak", "money"),
    ExcelColumn("Adet", "int"),
]
ROWS = [
    ["100.01", "Merkez Kasa", date(2026, 3, 1), Decimal("12.500"), Decimal("1234.56"), Decimal("0.00"), 3],
    [
        "320.01",
        "Yurtiçi Satıcılar",
        date(2026, 3, 15),
        Decimal("1.000"),
        Decimal("0.00"),
        Decimal("987654.32"),
        12,
    ],
    [
        "770.01",
        "Genel Yönetim Malzeme Giderleri (çok uzun bir açıklama)",
        None,
        None,
        Decimal("10.10"),
        None,
        0,
    ],
]


def _load(content: bytes, **options):
    assert content[:2] == b"PK"
    return load_workbook(io.BytesIO(content), **options)


def test_table_sheet_layout() -> None:
    book = ExcelBook()
    book.add_table("Mizan", COLUMNS, ROWS, title="Mizan - Mart 2026", total_columns=("Borç", "Alacak"))

    sheet = _load(book.to_bytes())["Mizan"]

    assert sheet["A1"].value == "Mizan - Mart 2026"
    assert sheet["A1"].font.bold
    assert [cell.value for cell in sheet[3]] == [column.title for column in COLUMNS]
    assert sheet.freeze_panes == "A4"
    assert sheet.auto_filter.ref == "A3:G6"
    assert [cell.value for cell in sheet[4]] == [
        "100.01",
        "Merkez Kasa",
        datetime(2026, 3, 1),
        12.5,
        1234.56,
        0,
        3,
    ]
    assert sheet["E7"].value == "=SUM(E4:E6)"
    assert sheet["F7"].value == "=SUM(F4:F6)"
    assert sheet["A7"].value == "TOPLAM"
    assert sheet["A7"].font.bold and sheet["E7"].font.bold
    assert sheet["D7"].value is None


def test_header_style_and_number_formats() -> None:
    book = ExcelBook()
    book.add_table("Liste", COLUMNS, ROWS)

    sheet = _load(book.to_bytes())["Liste"]

    for cell in sheet[1]:
        assert cell.font.bold
        assert cell.font.color.rgb == "00FFFFFF"
        assert cell.fill.fgColor.rgb == "001F4E78"
        assert cell.alignment.horizontal == "center"
        assert cell.border.bottom.style == "thin"
    assert sheet.freeze_panes == "A2"
    assert sheet["C2"].number_format == NUMBER_FORMATS["date"] == "DD.MM.YYYY"
    assert sheet["D2"].number_format == "#,##0.###"
    assert sheet["E2"].number_format == sheet["F3"].number_format == "#,##0.00"
    assert sheet["G2"].number_format == "#,##0"
    assert sheet["A2"].number_format == "General"
    assert sheet["E2"].alignment.horizontal == "right"
    assert sheet["A2"].data_type == "s"  # account codes stay text, "100.01" is not a number
    assert sheet["E2"].data_type == "n"


def test_decimals_are_stored_as_numbers_and_sum_formulas_are_live() -> None:
    book = ExcelBook()
    book.add_table(
        "Tutarlar",
        [ExcelColumn("Tutar", "money")],
        [[Decimal("0.10")], [Decimal("0.20")]],
        total_columns=["Tutar"],
    )

    sheet = _load(book.to_bytes())["Tutarlar"]

    assert (sheet["A2"].value, sheet["A3"].value) == (0.1, 0.2)
    assert sheet["A4"].value == "=SUM(A2:A3)"
    assert sheet["A4"].data_type == "f"


def test_text_that_looks_like_a_formula_stays_text() -> None:
    book = ExcelBook()
    book.add_table(
        "Cariler",
        [ExcelColumn("Ad"), ExcelColumn("Not")],
        [['=HYPERLINK("http://kotu.example","Tıkla")', "=1+1"], ["+90 232 000 00 00", "-5 gün"]],
    )

    sheet = _load(book.to_bytes())["Cariler"]

    assert sheet["A2"].value == '=HYPERLINK("http://kotu.example","Tıkla")'
    assert [sheet[ref].data_type for ref in ("A2", "B2", "A3", "B3")] == ["s", "s", "s", "s"]


def test_column_widths_follow_the_content() -> None:
    book = ExcelBook()
    book.add_table(
        "Genişlik",
        [ExcelColumn("K"), ExcelColumn("Açıklama"), ExcelColumn("Sabit", width=40)],
        [["1", "x" * 30, "a"], ["2", "y" * 200, "b"]],
        title="Sütun genişliklerini etkilemeyen çok uzun bir rapor başlığı",
    )

    dimensions = _load(book.to_bytes())["Genişlik"].column_dimensions

    assert dimensions["A"].width == 8  # minimum width, the long title in A1 is ignored
    assert dimensions["B"].width == 60  # capped
    assert dimensions["C"].width == 40  # explicit


def test_sheet_titles_are_made_valid_and_unique() -> None:
    book = ExcelBook()
    for title in ("Mizan: 2026/03 [TRY]", "Mizan: 2026/03 [TRY]", "Çok uzun bir sayfa adı " * 3, ""):
        book.add_table(title, [ExcelColumn("A")], [["1"]])

    names = _load(book.to_bytes()).sheetnames

    assert names[0] == "Mizan  2026 03  TRY"
    assert names[1] == "Mizan  2026 03  TRY (2)"
    assert len(names[2]) == 31
    assert names[3] == "Sayfa"
    assert len(set(names)) == 4


def test_empty_table_and_turkish_text() -> None:
    book = ExcelBook()
    book.add_table("Boş", [ExcelColumn("Şirket"), ExcelColumn("Tutar", "money")], [], total_columns=["Tutar"])
    book.add_table("Türkçe", [ExcelColumn("Ad")], [["ğüşıöç ĞÜŞİÖÇ"]])

    workbook = _load(book.to_bytes())

    assert workbook["Boş"].max_row == 1
    assert workbook["Boş"].auto_filter.ref == "A1:B1"
    assert workbook["Türkçe"]["A2"].value == "ğüşıöç ĞÜŞİÖÇ"


def test_raw_sheet_with_formulas_and_helpers() -> None:
    book = ExcelBook()
    sheet = book.add_sheet("Mukayese")
    sheet.append(["Kalem", "Miktar", "Birim Fiyat", "Tutar"])
    sheet.append(["Rulman 6204", Decimal("100"), Decimal("85.5"), "=B2*C2"])
    style_header(sheet[1])
    sheet["D2"].number_format = NUMBER_FORMATS["money"]
    auto_width(sheet)
    rates = book.add_sheet("Kurlar")
    rates.append(["USD", Decimal("41.25")])

    workbook = _load(book.to_bytes())

    assert workbook.sheetnames == ["Mukayese", "Kurlar"]
    assert workbook["Mukayese"]["D2"].value == "=B2*C2"
    assert workbook["Mukayese"]["A1"].font.bold
    assert workbook["Mukayese"].column_dimensions["A"].width == len("Rulman 6204") + 2
    assert workbook["Kurlar"]["B1"].value == 41.25


def test_invalid_usage_is_rejected() -> None:
    book = ExcelBook()

    with pytest.raises(ValueError, match="no sheets"):
        book.to_bytes()
    with pytest.raises(ValueError, match="3 values for 2 columns"):
        book.add_table("Hata", [ExcelColumn("A"), ExcelColumn("B")], [[1, 2, 3]])
    with pytest.raises(ValueError, match="unknown columns"):
        book.add_table("Hata 2", [ExcelColumn("A")], [], total_columns=["Yok"])
    with pytest.raises(ValueError, match="at least one column"):
        book.add_table("Hata 3", [], [])


def test_mime_type_constant() -> None:
    assert XLSX_MIME == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

"""PDF builder: valid documents, Turkish text, layout options and the number formatting helpers."""

from __future__ import annotations

import io
import struct
import zlib
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.pdf import (
    Cell,
    Column,
    Letterhead,
    PdfBuilder,
    Signer,
    TextBlock,
    fmt_date,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_qty,
)
from tests import factories

TURKISH = "ğüşıöç ĞÜŞİÖÇ İstanbul Iğdır ağaç çığlık"
A4 = (595.28, 841.89)
A3 = (841.89, 1190.55)


def _png(width: int = 4, height: int = 2) -> bytes:
    """A tiny valid RGB PNG (solid colour)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + b"\x1f\x4e\x78" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _read(content: bytes) -> PdfReader:
    assert content.startswith(b"%PDF-")
    assert content.rstrip().endswith(b"%%EOF")
    return PdfReader(io.BytesIO(content))


def _text(reader: PdfReader) -> str:
    return "\n".join(page.extract_text() for page in reader.pages)


def _size(reader: PdfReader, page: int = 0) -> tuple[float, float]:
    box = reader.pages[page].mediabox
    return round(float(box.width), 2), round(float(box.height), 2)


def _purchase_order() -> PdfBuilder:
    pdf = PdfBuilder(
        document_title="Sipariş SIP0000012", watermark="TASLAK", footer_text="SIP0000012 / Rev. 1"
    )
    pdf.letterhead(
        Letterhead(
            legal_name="Örnek Sanayi ve Ticaret A.Ş.",
            address_lines=["Organize Sanayi Bölgesi 5. Cadde No: 12", "Çiğli / İzmir"],
            tax_office="Çiğli",
            tax_number="0000000000",
            phone="+90 232 000 00 00",
            email="satinalma@ornek.example",
            website="www.ornek.example",
            logo=_png(),
        )
    )
    pdf.title("SATINALMA SİPARİŞİ", "Sipariş No: SIP0000012")
    pdf.meta_grid(
        [
            ("Sipariş No", "SIP0000012"),
            ("Tarih", fmt_date(date(2026, 3, 15))),
            ("Revizyon", "1"),
            ("Para Birimi", "TRY"),
        ]
    )
    pdf.text_blocks(
        [
            TextBlock(
                "Deneme Tedarikçi Ltd. Şti.\nGüneşli Mah. Işık Sok. No: 4\nBağcılar / İstanbul", "Tedarikçi"
            ),
            TextBlock("Merkez Depo\nÇiğli / İzmir", "Teslimat Adresi"),
        ]
    )
    pdf.table(
        [
            Column("No", width=10, align="center"),
            Column("Açıklama"),
            Column("Miktar", width=22, align="right"),
            Column("Birim", width=16, align="center"),
            Column("Birim Fiyat", width=28, align="right"),
            Column("Tutar", width=30, align="right"),
        ],
        [
            [
                1,
                "Çelik sac 2 mm (ölçüye göre kesilmiş)",
                fmt_qty("120.5"),
                "KG",
                fmt_number("42.5", 4),
                fmt_money("5121.25"),
            ],
            [2, "Şişirme ağzı contası", fmt_qty(40), "ADET", fmt_number("18", 4), fmt_money(720)],
            [Cell("Ara Toplam", bold=True, colspan=5, align="right"), Cell(fmt_money("5841.25"), bold=True)],
        ],
    )
    pdf.totals(
        [
            ("Ara Toplam", fmt_money("5841.25")),
            ("KDV %20", fmt_money("1168.25")),
            ("Genel Toplam", fmt_money("7009.50", "TRY")),
        ]
    )
    pdf.text("Ödeme: 30 gün vadeli.\nTeslim süresi: 10 iş günü.", heading="Notlar", boxed=True)
    pdf.signatures([Signer("Hazırlayan", "Ayşe Yılmaz"), Signer("Onaylayan", "Mehmet Öztürk", "15.03.2026")])
    return pdf


def test_document_is_a_valid_pdf_with_turkish_text() -> None:
    reader = _read(_purchase_order().build())
    text = _text(reader)

    assert len(reader.pages) == 1
    assert _size(reader) == A4
    for expected in (
        "Örnek Sanayi ve Ticaret A.Ş.",
        "Vergi Dairesi: Çiğli",
        "Vergi No: 0000000000",
        "SATINALMA SİPARİŞİ",
        "Tedarikçi",
        "Bağcılar / İstanbul",
        "Çelik sac 2 mm (ölçüye göre kesilmiş)",
        "Şişirme ağzı contası",
        "5.121,25",
        "Genel Toplam",
        "7.009,50 TRY",
        "Ödeme: 30 gün vadeli.",
        "Hazırlayan",
        "Mehmet Öztürk",
        "TASLAK",
        "SIP0000012 / Rev. 1",
        "Sayfa 1 / 1",
    ):
        assert expected in text, expected
    assert reader.metadata.title == "Sipariş SIP0000012"


@pytest.mark.parametrize("character", list("ğüşıöçĞÜŞİÖÇ"))
def test_every_turkish_letter_survives_extraction(character: str) -> None:
    pdf = PdfBuilder(document_title="Türkçe karakterler")
    pdf.title(f"Başlık {character}")
    pdf.text(TURKISH)
    pdf.table([Column("Sütun")], [[f"hücre {character}"]])

    text = _text(_read(pdf.build()))

    assert f"Başlık {character}" in text
    assert f"hücre {character}" in text
    assert TURKISH in text


def test_fonts_are_the_embedded_dejavu_faces() -> None:
    reader = _read(_purchase_order().build())

    fonts = {
        str(font["/BaseFont"])
        for page in reader.pages
        for font in (ref.get_object() for ref in page["/Resources"]["/Font"].values())
    }
    assert fonts
    assert all("DejaVuSans" in name for name in fonts)
    assert any("Bold" in name for name in fonts)


def test_long_table_repeats_its_header_and_numbers_the_pages() -> None:
    pdf = PdfBuilder(document_title="Uzun liste", footer_text="MZN-2026/03")
    pdf.table(
        [Column("Hesap Kodu", width=30), Column("Hesap Adı"), Column("Bakiye", width=35, align="right")],
        [
            [f"{100 + index}", f"Hesap satırı {index}", fmt_money(index * Decimal("1234.56"))]
            for index in range(150)
        ],
        header_groups=[("Hesap", 2), ("Tutarlar", 1)],
        zebra=True,
    )

    reader = _read(pdf.build())

    assert len(reader.pages) >= 3
    total = len(reader.pages)
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        assert "Hesap Kodu" in text and "Hesap Adı" in text and "Tutarlar" in text
        assert f"Sayfa {number} / {total}" in text
        assert "MZN-2026/03" in text
    assert "Hesap satırı 149" in reader.pages[-1].extract_text()


@pytest.mark.parametrize(
    ("page_size", "landscape", "expected"),
    [
        ("A4", False, A4),
        ("A4", True, A4[::-1]),
        ("A3", False, A3),
        ("A3", True, A3[::-1]),
    ],
)
def test_page_formats(page_size: str, landscape: bool, expected: tuple[float, float]) -> None:
    pdf = PdfBuilder(document_title="Biçim", page_size=page_size, landscape=landscape)
    pdf.title("FİYAT MUKAYESE FORMU")

    assert _size(_read(pdf.build())) == expected


def test_landscape_comparison_layout_with_vendor_groups_and_marks() -> None:
    vendors = ["Tedarikçi A", "Tedarikçi B", "Tedarikçi C"]
    columns = [
        Column("No", width=10, align="center"),
        Column("Malzeme / Hizmet"),
        Column("Birim", width=14, align="center"),
        Column("Miktar", width=18, align="right"),
    ]
    for _ in vendors:
        columns += [Column("Birim Fiyat", width=24, align="right"), Column("Tutar", width=28, align="right")]
    pdf = PdfBuilder(document_title="Mukayese MKY0000003", page_size="A4", landscape=True, font_size=8)
    pdf.title("FİYAT MUKAYESE FORMU")
    pdf.table(
        columns,
        [
            [
                1,
                "Rulman 6204",
                "ADET",
                fmt_qty(100),
                fmt_number("85", 4),
                Cell(fmt_money(8500), background="#c6efce", bold=True),
                fmt_number("92", 4),
                fmt_money(9200),
                Cell("TEKLİF VERİLMEDİ", colspan=2, align="center", color="#9c0006"),
            ],
            [
                2,
                "Nakliye",
                "SET",
                fmt_qty(1),
                Cell("DAHİL", align="center"),
                "-",
                "1.250,0000",
                "1.250,00",
                "-",
                "-",
            ],
        ],
        header_groups=[("", 4), *((vendor, 2) for vendor in vendors)],
    )
    pdf.signatures([Signer("Satınalma"), Signer("Teknik Onay"), Signer("Genel Müdür")], boxed=True)

    reader = _read(pdf.build())
    text = _text(reader)

    assert _size(reader) == A4[::-1]
    assert all(vendor in text for vendor in vendors)
    assert "TEKLİF VERİLMEDİ" in text and "DAHİL" in text and "Genel Müdür" in text


def test_user_text_is_escaped_not_interpreted_as_markup() -> None:
    pdf = PdfBuilder(document_title="Kaçış")
    pdf.text("Ölçü <b>10 & 20</b> mm < 30 mm", heading="A&B <Not>")
    pdf.table([Column("Açıklama")], [["<i>eğik değil</i> & tam metin"]])

    text = _text(_read(pdf.build()))

    assert "Ölçü <b>10 & 20</b> mm < 30 mm" in text
    assert "A&B <Not>" in text
    assert "<i>eğik değil</i> & tam metin" in text


def test_watermark_is_optional_and_on_every_page() -> None:
    def build(watermark: str | None) -> PdfReader:
        pdf = PdfBuilder(document_title="Filigran", watermark=watermark)
        pdf.text("Birinci sayfa")
        pdf.page_break()
        pdf.text("İkinci sayfa")
        return _read(pdf.build())

    draft, clean = build("TASLAK"), build(None)

    assert [("TASLAK" in page.extract_text()) for page in draft.pages] == [True, True]
    assert "TASLAK" not in _text(clean)
    assert len(clean.pages) == 2


def test_letterhead_from_company_row(db: Session) -> None:
    company = factories.make_company(
        db,
        name="Örnek",
        legal_name="Örnek Makine Sanayi A.Ş.",
        address="Atatürk Bulvarı No: 1",
        district="Çankaya",
        city="Ankara",
        tax_office="Çankaya",
        tax_number="0000000000",
        logo=_png(),
    )

    letterhead = Letterhead.from_company(company)
    pdf = PdfBuilder(document_title="Antet")
    pdf.letterhead(letterhead)
    reader = _read(pdf.build())

    assert letterhead.address_lines == ["Atatürk Bulvarı No: 1", "Çankaya / Ankara"]
    assert letterhead.logo == _png()
    text = _text(reader)
    assert "Örnek Makine Sanayi A.Ş." in text and "Çankaya / Ankara" in text
    assert len(list(reader.pages[0].images)) == 1


def test_letterhead_without_logo_and_optional_fields() -> None:
    pdf = PdfBuilder(document_title="Antet")
    pdf.letterhead(Letterhead(legal_name="Yalın Ticaret Ltd. Şti."))

    reader = _read(pdf.build())

    assert "Yalın Ticaret Ltd. Şti." in _text(reader)
    assert "Vergi" not in _text(reader)
    assert list(reader.pages[0].images) == []


def test_invalid_table_definitions_are_rejected() -> None:
    pdf = PdfBuilder(document_title="Hatalar")

    with pytest.raises(ValueError, match="does not fit 2 columns"):
        pdf.table([Column("A"), Column("B")], [["yalnızca bir hücre"]])
    with pytest.raises(ValueError, match="does not fit 2 columns"):
        pdf.table([Column("A"), Column("B")], [[Cell("çok geniş", colspan=3)]])
    with pytest.raises(ValueError, match="header_groups"):
        pdf.table([Column("A"), Column("B")], [["1", "2"]], header_groups=[("Grup", 1)])
    with pytest.raises(ValueError, match="at least one column"):
        pdf.table([], [])
    with pytest.raises(ValueError, match="no room"):
        pdf.table([Column("A", width=500), Column("B")], [["1", "2"]])


def test_fixed_columns_wider_than_the_page_are_scaled_down() -> None:
    pdf = PdfBuilder(document_title="Geniş tablo")
    pdf.table(
        [Column(f"Sütun {index}", width=60) for index in range(6)], [[f"değer {index}" for index in range(6)]]
    )

    reader = _read(pdf.build())

    assert len(reader.pages) == 1
    assert "değer 5" in _text(reader)


def test_builder_renders_once_and_empty_documents_still_render() -> None:
    pdf = PdfBuilder(document_title="Boş")

    reader = _read(pdf.build())

    assert len(reader.pages) == 1
    assert "Sayfa 1 / 1" in _text(reader)
    with pytest.raises(RuntimeError, match="only be called once"):
        pdf.build()


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        ("1234.5", 2, "1.234,50"),
        (Decimal("1234567.891"), 2, "1.234.567,89"),
        (Decimal("0.005"), 2, "0,01"),
        (Decimal("2.345"), 2, "2,35"),
        (Decimal("-1234.5"), 2, "-1.234,50"),
        (Decimal("-0.001"), 2, "0,00"),
        (0, 2, "0,00"),
        (1500, 0, "1.500"),
        ("42.123456", 4, "42,1235"),
        (None, 2, ""),
    ],
)
def test_fmt_number(value: object, decimals: int, expected: str) -> None:
    assert fmt_number(value, decimals) == expected


def test_money_quantity_percentage_and_date_helpers() -> None:
    assert fmt_money("1234.56") == "1.234,56"
    assert fmt_money(Decimal("7009.5"), "TRY") == "7.009,50 TRY"
    assert fmt_money(None, "TRY") == ""
    assert fmt_qty(Decimal("12.500")) == "12,5"
    assert fmt_qty(Decimal("1200.000")) == "1.200"
    assert fmt_qty("0.125") == "0,125"
    assert fmt_qty("3.14159", 2) == "3,14"
    assert fmt_qty(None) == ""
    assert fmt_pct(20) == "%20"
    assert fmt_pct(Decimal("7.50")) == "%7,5"
    assert fmt_pct(None) == ""
    assert fmt_date(date(2026, 3, 5)) == "05.03.2026"
    assert fmt_date(None) == ""

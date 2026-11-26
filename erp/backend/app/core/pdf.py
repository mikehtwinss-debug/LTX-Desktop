"""PDF documents: a small builder over ReportLab platypus with the bundled DejaVu fonts.

    pdf = PdfBuilder(document_title="Sipariş SIP0000012", watermark="TASLAK", footer_text="SIP0000012")
    pdf.letterhead(Letterhead.from_company(company))
    pdf.title("SATINALMA SİPARİŞİ")
    pdf.meta_grid([("Sipariş No", "SIP0000012"), ("Tarih", fmt_date(order_date))])
    pdf.table([Column("Açıklama"), Column("Tutar", width=28, align="right")], rows)
    pdf.totals([("Ara Toplam", fmt_money(net)), ("Genel Toplam", fmt_money(gross, "TRY"))])
    pdf.signatures([Signer("Hazırlayan", "A. Yılmaz"), Signer("Onaylayan")])
    content = pdf.build()

Every text argument is plain text (escaped by the builder); numbers and dates are formatted by the
caller with the `fmt_*` helpers, which use the Turkish conventions (`1.234,56`, `31.12.2026`).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from pathlib import Path
from typing import Any, Literal, Self
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A3, A4
from reportlab.lib.pagesizes import landscape as landscape_size
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
)

FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"

Align = Literal["left", "center", "right"]
PageSize = Literal["A4", "A3"]
Number = Decimal | int | str

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_PAGE_SIZES = {"A4": A4, "A3": A3}
_ALIGNMENTS = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
_SEPARATOR_SWAP = str.maketrans({",": ".", ".": ","})
_LINE_COLOR = colors.HexColor("#8c8c8c")
_HEADER_BACKGROUND = colors.HexColor("#e8ecf1")
_ZEBRA_BACKGROUND = colors.HexColor("#f6f7f9")
_WATERMARK_COLOR = colors.HexColor("#b0b0b0")
_FOOTER_HEIGHT = 8 * mm
_fonts_registered = False


def fmt_number(value: Number | None, decimals: int = 2) -> str:
    """Turkish number format: `fmt_number("1234.5")` -> `1.234,50`. None becomes an empty string."""
    if value is None:
        return ""
    quantum = Decimal(1).scaleb(-decimals)
    rounded = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    return f"{rounded:,.{decimals}f}".translate(_SEPARATOR_SWAP)


def fmt_money(value: Number | None, currency: str | None = None) -> str:
    """Amount with two decimals, optionally followed by the currency code: `1.234,56 TRY`."""
    text = fmt_number(value, 2)
    return f"{text} {currency}" if text and currency else text


def fmt_qty(value: Number | None, decimals: int = 3) -> str:
    """Quantity with up to `decimals` decimals and no trailing zeros: `12,5`."""
    text = fmt_number(value, decimals)
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def fmt_pct(value: Number | None) -> str:
    """Percentage in Turkish notation: `%20`, `%7,5`."""
    text = fmt_qty(value, 2)
    return f"%{text}" if text else ""


def fmt_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _register_fonts() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont(FONT, _FONT_DIR / "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, _FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)
    _fonts_registered = True


def _markup(text: Any) -> str:
    return "" if text is None else escape(str(text)).replace("\n", "<br/>")


@dataclass(frozen=True, slots=True)
class Letterhead:
    legal_name: str
    address_lines: Sequence[str] = ()
    tax_office: str | None = None
    tax_number: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    logo: bytes | None = None  # PNG or JPEG

    @classmethod
    def from_company(cls, company: Any) -> Letterhead:
        """Build from an `org_company` row (the logo column is loaded on access)."""
        locality = " / ".join(part for part in (company.district, company.city) if part)
        return cls(
            legal_name=company.legal_name,
            address_lines=[line for line in (company.address, locality) if line],
            tax_office=company.tax_office,
            tax_number=company.tax_number,
            phone=company.phone,
            email=company.email,
            website=company.website,
            logo=company.logo,
        )


@dataclass(frozen=True, slots=True)
class Column:
    """Table column. `width` is in millimetres; columns without one share the remaining width by `weight`."""

    title: str
    width: float | None = None
    align: Align = "left"
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class Cell:
    """A table cell that needs more than plain text: emphasis, colours (`#rrggbb`) or a column span."""

    value: Any = ""
    bold: bool = False
    background: str | None = None
    color: str | None = None
    align: Align | None = None
    colspan: int = 1


@dataclass(frozen=True, slots=True)
class TextBlock:
    body: str
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class Signer:
    title: str
    name: str | None = None
    note: str | None = None  # e.g. the approval date


class _NumberedCanvas(Canvas):
    """Canvas that knows the total page count, so the footer can say `Sayfa x / y`."""

    def __init__(self, *args: Any, footer_text: str | None = None, margin: float = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._footer_text = footer_text
        self._margin = margin
        self._page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (ReportLab API name)
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        width, _ = self._pagesize
        self.saveState()
        self.setFont(FONT, 7)
        self.setFillColor(colors.HexColor("#555555"))
        if self._footer_text:
            self.drawString(self._margin, _FOOTER_HEIGHT, self._footer_text)
        self.drawRightString(width - self._margin, _FOOTER_HEIGHT, f"Sayfa {self._pageNumber} / {total}")
        self.restoreState()


class PdfBuilder:
    """Collects document parts top to bottom and renders them with `build()`."""

    def __init__(
        self,
        *,
        document_title: str,
        page_size: PageSize = "A4",
        landscape: bool = False,
        margin_mm: float = 12,
        font_size: float = 9,
        watermark: str | None = None,
        footer_text: str | None = None,
    ) -> None:
        _register_fonts()
        size = _PAGE_SIZES[page_size]
        self._page_size = landscape_size(size) if landscape else size
        self._margin = margin_mm * mm
        self._document_title = document_title
        self._font_size = font_size
        self._watermark = watermark
        self._footer_text = footer_text
        self._story: list[Flowable] = []
        self._styles: dict[tuple[Any, ...], ParagraphStyle] = {}
        self._built = False

    @property
    def content_width(self) -> float:
        """Usable width between the margins, in points."""
        return self._page_size[0] - 2 * self._margin

    def _style(
        self,
        *,
        size: float | None = None,
        bold: bool = False,
        align: Align = "left",
        color: str | None = None,
    ) -> ParagraphStyle:
        size = size or self._font_size
        key = (size, bold, align, color)
        if key not in self._styles:
            self._styles[key] = ParagraphStyle(
                f"erp-{len(self._styles)}",
                fontName=FONT_BOLD if bold else FONT,
                fontSize=size,
                leading=size * 1.25,
                alignment=_ALIGNMENTS[align],
                textColor=colors.HexColor(color) if color else colors.black,
            )
        return self._styles[key]

    def _paragraph(self, text: Any, **style: Any) -> Paragraph:
        return Paragraph(_markup(text), self._style(**style))

    def _table(self, data: list[list[Any]], style: Sequence[tuple[Any, ...]], **options: Any) -> Table:
        table = Table(data, **options)
        # Plain-string cells (the fillers of spans) would otherwise pull in ReportLab's default Helvetica.
        table.setStyle([("FONT", (0, 0), (-1, -1), FONT, self._font_size), *style])
        return table

    def spacer(self, height_mm: float = 4) -> Self:
        self._story.append(Spacer(1, height_mm * mm))
        return self

    def page_break(self) -> Self:
        self._story.append(PageBreak())
        return self

    def letterhead(self, letterhead: Letterhead, *, logo_box_mm: tuple[float, float] = (45, 22)) -> Self:
        """Company header: optional logo on the left, legal name, address and tax details beside it."""
        lines = [self._paragraph(letterhead.legal_name, size=self._font_size + 3, bold=True)]
        small = self._font_size - 1
        lines.extend(self._paragraph(line, size=small) for line in letterhead.address_lines)
        tax = "   ".join(
            f"{label}: {value}"
            for label, value in (
                ("Vergi Dairesi", letterhead.tax_office),
                ("Vergi No", letterhead.tax_number),
            )
            if value
        )
        contact = "   ".join(
            f"{label}: {value}"
            for label, value in (
                ("Tel", letterhead.phone),
                ("E-posta", letterhead.email),
                ("Web", letterhead.website),
            )
            if value
        )
        lines.extend(self._paragraph(line, size=small) for line in (tax, contact) if line)

        row: list[Any] = [lines]
        widths = [self.content_width]
        if letterhead.logo:
            logo = self._logo(letterhead.logo, logo_box_mm)
            logo_width = logo.drawWidth + 4 * mm
            row = [logo, lines]
            widths = [logo_width, self.content_width - logo_width]
        style = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        self._story.append(self._table([row], style, colWidths=widths))
        self._story.append(
            HRFlowable(width="100%", thickness=0.8, color=_LINE_COLOR, spaceBefore=3, spaceAfter=6)
        )
        return self

    @staticmethod
    def _logo(data: bytes, box_mm: tuple[float, float]) -> Image:
        width, height = ImageReader(io.BytesIO(data)).getSize()
        scale = min(box_mm[0] * mm / width, box_mm[1] * mm / height)
        return Image(io.BytesIO(data), width=width * scale, height=height * scale)

    def title(self, text: str, subtitle: str | None = None) -> Self:
        self._story.append(self._paragraph(text, size=self._font_size + 5, bold=True, align="center"))
        if subtitle:
            self._story.append(self._paragraph(subtitle, align="center"))
        self._story.append(Spacer(1, 4 * mm))
        return self

    def meta_grid(
        self, items: Sequence[tuple[str, Any]], *, columns: int = 2, label_width_mm: float = 30
    ) -> Self:
        """Label/value pairs laid out in `columns` pairs per row (document number, date, vendor ...)."""
        if columns < 1:
            raise ValueError("columns must be at least 1")
        label_width = label_width_mm * mm
        value_width = self.content_width / columns - label_width
        if value_width <= 0:
            raise ValueError("label_width_mm leaves no room for the values")
        cells = [(self._paragraph(label, bold=True), self._paragraph(value)) for label, value in items]
        rows = []
        for start in range(0, len(cells), columns):
            row: list[Any] = []
            for pair in cells[start : start + columns]:
                row.extend(pair)
            row.extend([""] * (2 * columns - len(row)))
            rows.append(row)
        if rows:
            style = [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
            self._story.append(self._table(rows, style, colWidths=[label_width, value_width] * columns))
            self._story.append(Spacer(1, 4 * mm))
        return self

    def _column_widths(self, columns: Sequence[Column]) -> list[float]:
        fixed = sum(column.width * mm for column in columns if column.width is not None)
        flexible_weight = sum(column.weight for column in columns if column.width is None)
        if flexible_weight:
            remaining = self.content_width - fixed
            if remaining <= 0:
                raise ValueError("Fixed column widths leave no room for the flexible columns")
            return [
                column.width * mm if column.width is not None else remaining * column.weight / flexible_weight
                for column in columns
            ]
        # Only fixed widths: scale them to the page so the table never overflows the margins.
        scale = min(1.0, self.content_width / fixed)
        return [column.width * mm * scale for column in columns if column.width is not None]

    def table(
        self,
        columns: Sequence[Column],
        rows: Sequence[Sequence[Any]],
        *,
        header_groups: Sequence[tuple[str, int]] | None = None,
        font_size: float | None = None,
        zebra: bool = False,
    ) -> Self:
        """Line table whose header repeats on every page.

        A row holds one entry per column: plain values, or `Cell` objects for emphasis, colours and
        column spans (a cell with `colspan=n` stands for n columns). `header_groups` adds a first
        header row of `(title, span)` groups above the column titles, e.g. one group per vendor.
        """
        if not columns:
            raise ValueError("A table needs at least one column")
        size = font_size or self._font_size - 1
        count = len(columns)
        data: list[list[Any]] = []
        commands: list[tuple[Any, ...]] = []

        if header_groups:
            if sum(span for _, span in header_groups) != count:
                raise ValueError("header_groups must cover every column exactly once")
            group_row: list[Any] = []
            for group_title, span in header_groups:
                start = len(group_row)
                group_row.append(self._paragraph(group_title, size=size, bold=True, align="center"))
                group_row.extend([""] * (span - 1))
                if span > 1:
                    commands.append(("SPAN", (start, 0), (start + span - 1, 0)))
            data.append(group_row)
        data.append(
            [self._paragraph(column.title, size=size, bold=True, align="center") for column in columns]
        )
        header_count = len(data)

        for row in rows:
            row_index = len(data)
            rendered: list[Any] = []
            for entry in row:
                cell = entry if isinstance(entry, Cell) else Cell(entry)
                start = len(rendered)
                if start >= count or cell.colspan < 1 or start + cell.colspan > count:
                    raise ValueError(f"Table row {row_index - header_count + 1} does not fit {count} columns")
                align = cell.align or columns[start].align
                rendered.append(
                    self._paragraph(cell.value, size=size, bold=cell.bold, align=align, color=cell.color)
                )
                rendered.extend([""] * (cell.colspan - 1))
                end = start + cell.colspan - 1
                if cell.colspan > 1:
                    commands.append(("SPAN", (start, row_index), (end, row_index)))
                if cell.background:
                    commands.append(
                        ("BACKGROUND", (start, row_index), (end, row_index), colors.HexColor(cell.background))
                    )
            if len(rendered) != count:
                raise ValueError(f"Table row {row_index - header_count + 1} does not fit {count} columns")
            data.append(rendered)

        style: list[tuple[Any, ...]] = [
            ("GRID", (0, 0), (-1, -1), 0.4, _LINE_COLOR),
            ("BACKGROUND", (0, 0), (-1, header_count - 1), _HEADER_BACKGROUND),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if zebra and len(data) > header_count:
            style.append(("ROWBACKGROUNDS", (0, header_count), (-1, -1), [colors.white, _ZEBRA_BACKGROUND]))
        widths = self._column_widths(columns)
        self._story.append(self._table(data, style + commands, colWidths=widths, repeatRows=header_count))
        self._story.append(Spacer(1, 3 * mm))
        return self

    def totals(
        self, rows: Sequence[tuple[str, Any]], *, width_mm: float = 85, emphasize_last: bool = True
    ) -> Self:
        """Right-aligned box of label/amount rows; the last row (the grand total) is emphasised."""
        if not rows:
            return self
        width = min(width_mm * mm, self.content_width)
        data = []
        for index, (label, value) in enumerate(rows):
            bold = emphasize_last and index == len(rows) - 1
            data.append([self._paragraph(label, bold=bold), self._paragraph(value, bold=bold, align="right")])
        style: list[tuple[Any, ...]] = [
            ("GRID", (0, 0), (-1, -1), 0.4, _LINE_COLOR),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if emphasize_last:
            style.append(("BACKGROUND", (0, -1), (-1, -1), _HEADER_BACKGROUND))
        table = self._table(data, style, colWidths=[width * 0.55, width * 0.45], hAlign="RIGHT")
        self._story.append(KeepTogether([table, Spacer(1, 4 * mm)]))
        return self

    def text(self, body: str, *, heading: str | None = None, boxed: bool = False) -> Self:
        """Free text across the full width (notes, terms). Long text continues on the next page."""
        style = self._style()
        if boxed:
            style = ParagraphStyle(
                f"{style.name}-boxed",
                parent=style,
                borderColor=_LINE_COLOR,
                borderWidth=0.5,
                borderPadding=4,
                leftIndent=4,
                rightIndent=4,
                spaceBefore=4,
                spaceAfter=4,
            )
        markup = _markup(body)
        if heading:
            markup = f"<b>{_markup(heading)}</b><br/>{markup}"
        self._story.append(Paragraph(markup, style))
        self._story.append(Spacer(1, 4 * mm))
        return self

    def text_blocks(self, blocks: Sequence[TextBlock], *, boxed: bool = True) -> Self:
        """Text panels side by side in equal columns (vendor | delivery address, terms | notes)."""
        if not blocks:
            return self
        cells = []
        for block in blocks:
            parts = [self._paragraph(block.heading, bold=True)] if block.heading else []
            parts.append(self._paragraph(block.body))
            cells.append(parts)
        style: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if boxed:
            style.append(("GRID", (0, 0), (-1, -1), 0.4, _LINE_COLOR))
        else:
            style.append(("LEFTPADDING", (0, 0), (-1, -1), 0))
        widths = [self.content_width / len(blocks)] * len(blocks)
        self._story.append(self._table([cells], style, colWidths=widths))
        self._story.append(Spacer(1, 4 * mm))
        return self

    def signatures(self, signers: Sequence[Signer], *, boxed: bool = False, space_mm: float = 16) -> Self:
        """One signature area per signer: title, room to sign, then name and note (e.g. approval date)."""
        if not signers:
            return self
        titles = [self._paragraph(signer.title, bold=True, align="center") for signer in signers]
        names = [
            [
                self._paragraph(line, size=self._font_size - 1, align="center")
                for line in (signer.name, signer.note)
                if line
            ]
            or ""
            for signer in signers
        ]
        style: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if boxed:
            style.append(("GRID", (0, 0), (-1, 0), 0.4, _LINE_COLOR))
            style.append(("BOX", (0, 0), (-1, -1), 0.4, _LINE_COLOR))
            style.append(("LINEBEFORE", (1, 1), (-1, -1), 0.4, _LINE_COLOR))
            style.append(("BACKGROUND", (0, 0), (-1, 0), _HEADER_BACKGROUND))
        table = self._table(
            [titles, [""] * len(signers), names],
            style,
            colWidths=[self.content_width / len(signers)] * len(signers),
            rowHeights=[None, space_mm * mm, None],
        )
        self._story.append(KeepTogether([Spacer(1, 4 * mm), table]))
        return self

    def _draw_watermark(self, canvas: Canvas, document: SimpleDocTemplate) -> None:
        if not self._watermark:
            return
        width, height = self._page_size
        canvas.saveState()
        canvas.setFillColor(_WATERMARK_COLOR)
        canvas.setFillAlpha(0.22)
        canvas.setFont(FONT_BOLD, min(width, height) / max(len(self._watermark), 4) * 1.1)
        canvas.translate(width / 2, height / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, self._watermark)
        canvas.restoreState()

    def build(self) -> bytes:
        """Render the collected parts. A builder renders once."""
        if self._built:
            raise RuntimeError("PdfBuilder.build() can only be called once")
        self._built = True
        buffer = io.BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=self._page_size,
            leftMargin=self._margin,
            rightMargin=self._margin,
            topMargin=self._margin,
            bottomMargin=self._margin + _FOOTER_HEIGHT,
            title=self._document_title,
            author="ERP",
            # Otherwise every page would reference the non-embedded standard font Helvetica.
            initialFontName=FONT,
        )
        document.build(
            self._story or [Spacer(1, 1)],
            onFirstPage=self._draw_watermark,
            onLaterPages=self._draw_watermark,
            canvasmaker=partial(_NumberedCanvas, footer_text=self._footer_text, margin=self._margin),
        )
        return buffer.getvalue()

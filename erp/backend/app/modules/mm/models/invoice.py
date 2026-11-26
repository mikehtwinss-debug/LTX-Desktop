"""Supplier invoices verified against purchase orders."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, currency_ref, ref
from app.core.types import Money, Qty, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.co.models import CostCenter
    from app.modules.fi.models.gl import GLAccount, JournalEntry, TaxCode
    from app.modules.fi.models.partners import PaymentTerm, Vendor
    from app.modules.mm.models.purchasing import PurchaseOrderLine


class SupplierInvoiceStatus(enum.StrEnum):
    POSTED = "POSTED"
    BLOCKED = "BLOCKED"
    REVERSED = "REVERSED"


class SupplierInvoice(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "mm_supplier_invoice"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        Index(
            "uq_mm_supplier_invoice_vendor_reference",
            "company_id",
            "vendor_id",
            "reference",
            unique=True,
            postgresql_where="status <> 'REVERSED'",
        ),
        Index("ix_mm_supplier_invoice_company_id_posting_date", "company_id", "posting_date"),
        Index("ix_mm_supplier_invoice_company_id_status", "company_id", "status"),
        CheckConstraint("exchange_rate > 0", name="exchange_rate_positive"),
        CheckConstraint("net_total >= 0 AND tax_total >= 0 AND gross_total >= 0", name="totals_non_negative"),
    )

    number: Mapped[str] = mapped_column(String(24))
    vendor_id: Mapped[int] = ref("fi_vendor.id", index=True)
    reference: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date] = mapped_column(Date)
    posting_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    payment_term_id: Mapped[int | None] = ref("fi_payment_term.id")
    currency_code: Mapped[str] = currency_ref()
    exchange_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    net_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    gross_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    status: Mapped[SupplierInvoiceStatus] = mapped_column(
        enum_type(SupplierInvoiceStatus), default=SupplierInvoiceStatus.POSTED
    )
    block_reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    released_by_id: Mapped[int | None] = ref("auth_user.id")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_entry_id: Mapped[int] = ref("fi_journal_entry.id", index=True)
    ettn: Mapped[str | None] = mapped_column(String(36))

    vendor: Mapped[Vendor] = relationship(foreign_keys=[vendor_id])
    payment_term: Mapped[PaymentTerm | None] = relationship(foreign_keys=[payment_term_id])
    journal_entry: Mapped[JournalEntry] = relationship(foreign_keys=[journal_entry_id])
    lines: Mapped[list[SupplierInvoiceLine]] = relationship(
        back_populates="invoice",
        foreign_keys="SupplierInvoiceLine.invoice_id",
        cascade="all, delete-orphan",
        order_by="SupplierInvoiceLine.line_no",
    )


class SupplierInvoiceLine(IdMixin, TimestampMixin, Base):
    """PO-based line, or an unplanned cost line (freight etc.) when `po_line_id` is NULL."""

    __tablename__ = "mm_supplier_invoice_line"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("net_amount >= 0 AND tax_amount >= 0", name="amounts_non_negative"),
    )

    invoice_id: Mapped[int] = ref("mm_supplier_invoice.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    po_line_id: Mapped[int | None] = ref("mm_purchase_order_line.id", index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    net_amount: Mapped[Decimal] = mapped_column(Money)
    tax_code_id: Mapped[int | None] = ref("fi_tax_code.id")
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    gl_account_id: Mapped[int | None] = ref("fi_gl_account.id")
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    # Signed: positive when the invoice exceeds the value posted at goods receipt.
    variance_local: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    text: Mapped[str | None] = mapped_column(String(255))

    invoice: Mapped[SupplierInvoice] = relationship(back_populates="lines", foreign_keys=[invoice_id])
    po_line: Mapped[PurchaseOrderLine | None] = relationship(foreign_keys=[po_line_id])
    tax_code: Mapped[TaxCode | None] = relationship(foreign_keys=[tax_code_id])
    gl_account: Mapped[GLAccount | None] = relationship(foreign_keys=[gl_account_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])

"""FI invoices and payments (sub-ledger documents posted through the journal engine)."""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, currency_ref, ref
from app.core.types import Money, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.co.models import CostCenter
    from app.modules.fi.models.gl import GLAccount, JournalEntry, TaxCode
    from app.modules.fi.models.partners import Customer, PaymentTerm, Vendor
    from app.modules.fi.models.treasury import TreasuryAccount


class InvoiceKind(enum.StrEnum):
    VENDOR_INVOICE = "VENDOR_INVOICE"
    VENDOR_CREDIT = "VENDOR_CREDIT"
    CUSTOMER_INVOICE = "CUSTOMER_INVOICE"
    CUSTOMER_CREDIT = "CUSTOMER_CREDIT"


class DocumentStatus(enum.StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentDirection(enum.StrEnum):
    OUT = "OUT"
    IN = "IN"


class PaymentMethod(enum.StrEnum):
    HAVALE = "HAVALE"
    NAKIT = "NAKIT"
    KREDI_KARTI = "KREDI_KARTI"
    DIGER = "DIGER"


class Invoice(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "fi_invoice"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        CheckConstraint("num_nonnulls(vendor_id, customer_id) = 1", name="single_partner"),
        CheckConstraint("exchange_rate > 0", name="exchange_rate_positive"),
        CheckConstraint("net_total >= 0 AND tax_total >= 0 AND gross_total >= 0", name="totals_non_negative"),
        Index("ix_fi_invoice_company_id_posting_date", "company_id", "posting_date"),
    )

    kind: Mapped[InvoiceKind] = mapped_column(enum_type(InvoiceKind))
    number: Mapped[str] = mapped_column(String(24))
    vendor_id: Mapped[int | None] = ref("fi_vendor.id", index=True)
    customer_id: Mapped[int | None] = ref("fi_customer.id", index=True)
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
    text: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[DocumentStatus] = mapped_column(enum_type(DocumentStatus), default=DocumentStatus.POSTED)
    journal_entry_id: Mapped[int] = ref("fi_journal_entry.id", index=True)

    vendor: Mapped[Vendor | None] = relationship(foreign_keys=[vendor_id])
    customer: Mapped[Customer | None] = relationship(foreign_keys=[customer_id])
    payment_term: Mapped[PaymentTerm | None] = relationship(foreign_keys=[payment_term_id])
    journal_entry: Mapped[JournalEntry] = relationship(foreign_keys=[journal_entry_id])
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        foreign_keys="InvoiceLine.invoice_id",
        cascade="all, delete-orphan",
        order_by="InvoiceLine.line_no",
    )


class InvoiceLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "fi_invoice_line"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no"),
        CheckConstraint("net_amount >= 0 AND tax_amount >= 0", name="amounts_non_negative"),
    )

    invoice_id: Mapped[int] = ref("fi_invoice.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    gl_account_id: Mapped[int] = ref("fi_gl_account.id")
    description: Mapped[str | None] = mapped_column(String(255))
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    net_amount: Mapped[Decimal] = mapped_column(Money)
    tax_code_id: Mapped[int | None] = ref("fi_tax_code.id")
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))

    invoice: Mapped[Invoice] = relationship(back_populates="lines", foreign_keys=[invoice_id])
    gl_account: Mapped[GLAccount] = relationship(foreign_keys=[gl_account_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])
    tax_code: Mapped[TaxCode | None] = relationship(foreign_keys=[tax_code_id])


class Payment(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "fi_payment"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        CheckConstraint("num_nonnulls(vendor_id, customer_id) <= 1", name="single_partner"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("exchange_rate > 0", name="exchange_rate_positive"),
        Index("ix_fi_payment_company_id_payment_date", "company_id", "payment_date"),
    )

    number: Mapped[str] = mapped_column(String(24))
    direction: Mapped[PaymentDirection] = mapped_column(enum_type(PaymentDirection))
    vendor_id: Mapped[int | None] = ref("fi_vendor.id", index=True)
    customer_id: Mapped[int | None] = ref("fi_customer.id", index=True)
    treasury_account_id: Mapped[int] = ref("fi_treasury_account.id", index=True)
    payment_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency_code: Mapped[str] = currency_ref()
    exchange_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    method: Mapped[PaymentMethod] = mapped_column(enum_type(PaymentMethod), default=PaymentMethod.HAVALE)
    reference: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[DocumentStatus] = mapped_column(enum_type(DocumentStatus), default=DocumentStatus.POSTED)
    journal_entry_id: Mapped[int] = ref("fi_journal_entry.id", index=True)
    clearing_id: Mapped[int | None] = ref("fi_clearing.id", index=True)

    vendor: Mapped[Vendor | None] = relationship(foreign_keys=[vendor_id])
    customer: Mapped[Customer | None] = relationship(foreign_keys=[customer_id])
    treasury_account: Mapped[TreasuryAccount] = relationship(foreign_keys=[treasury_account_id])
    journal_entry: Mapped[JournalEntry] = relationship(foreign_keys=[journal_entry_id])

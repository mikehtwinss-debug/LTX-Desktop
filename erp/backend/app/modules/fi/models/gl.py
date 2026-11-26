"""General ledger: accounts, periods, tax codes, journal entries, clearing, reflection rules."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, currency_ref, ref
from app.core.types import Money, Pct, Qty, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.co.models import CostCenter
    from app.modules.fi.models.partners import Customer, Vendor


class AccountType(enum.StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"
    COST = "COST"
    OFFBALANCE = "OFFBALANCE"
    TECHNICAL = "TECHNICAL"


class Side(enum.StrEnum):
    DEBIT = "D"
    CREDIT = "C"


class ReconType(enum.StrEnum):
    NONE = "NONE"
    VENDOR = "VENDOR"
    CUSTOMER = "CUSTOMER"


class PeriodStatus(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TaxType(enum.StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class FiDocType(enum.StrEnum):
    GL = "GL"
    VI = "VI"  # vendor invoice
    VC = "VC"  # vendor credit
    VP = "VP"  # vendor payment
    CI = "CI"  # customer invoice
    CC = "CC"  # customer credit
    CP = "CP"  # customer payment
    MD = "MD"  # material document
    IV = "IV"  # MM invoice verification
    FX = "FX"  # exchange difference
    RF = "RF"  # reflection
    OP = "OP"  # opening
    CL = "CL"  # closing


class JournalStatus(enum.StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ClearingStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    RESET = "RESET"


class GLAccount(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "fi_gl_account"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("normal_side IN ('D', 'C')", name="normal_side_valid"),
        CheckConstraint("level >= 1", name="level_positive"),
    )

    code: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = ref("fi_gl_account.id", index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    account_type: Mapped[AccountType] = mapped_column(enum_type(AccountType))
    normal_side: Mapped[Side] = mapped_column(enum_type(Side))
    is_postable: Mapped[bool] = mapped_column(Boolean, default=True)
    recon_type: Mapped[ReconType] = mapped_column(enum_type(ReconType), default=ReconType.NONE)
    requires_cost_center: Mapped[bool] = mapped_column(Boolean, default=False)
    currency_code: Mapped[str | None] = currency_ref()
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)

    parent: Mapped[GLAccount | None] = relationship(
        back_populates="children", foreign_keys=[parent_id], remote_side="GLAccount.id"
    )
    children: Mapped[list[GLAccount]] = relationship(
        back_populates="parent", foreign_keys="GLAccount.parent_id", order_by="GLAccount.code"
    )


class Period(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "fi_period"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "year", "period"),
        CheckConstraint("period BETWEEN 1 AND 12", name="period_range"),
        CheckConstraint("end_date >= start_date", name="date_range"),
        Index("ix_fi_period_company_id_start_date", "company_id", "start_date"),
    )

    year: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[PeriodStatus] = mapped_column(enum_type(PeriodStatus), default=PeriodStatus.OPEN)


class TaxCode(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "fi_tax_code"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("rate >= 0", name="rate_non_negative"),
    )

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    tax_type: Mapped[TaxType] = mapped_column(enum_type(TaxType))
    rate: Mapped[Decimal] = mapped_column(Pct)
    gl_account_id: Mapped[int] = ref("fi_gl_account.id", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    gl_account: Mapped[GLAccount] = relationship(foreign_keys=[gl_account_id])


class JournalEntry(IdMixin, TimestampMixin, CompanyMixin, Base):
    """Posted journal entry. A trigger rejects DELETE and any UPDATE outside the bookkeeping columns."""

    __tablename__ = "fi_journal_entry"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "number"),
        CheckConstraint("period BETWEEN 1 AND 12", name="period_range"),
        CheckConstraint("exchange_rate > 0", name="exchange_rate_positive"),
        CheckConstraint("total_local >= 0", name="total_local_non_negative"),
        Index("ix_fi_journal_entry_company_id_posting_date", "company_id", "posting_date"),
        Index("ix_fi_journal_entry_company_id_fiscal_year_period", "company_id", "fiscal_year", "period"),
        Index("ix_fi_journal_entry_source", "company_id", "source_type", "source_id"),
    )

    fiscal_year: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(24))
    doc_type: Mapped[FiDocType] = mapped_column(enum_type(FiDocType))
    posting_date: Mapped[date] = mapped_column(Date)
    document_date: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(64))
    header_text: Mapped[str | None] = mapped_column(String(255))
    currency_code: Mapped[str] = currency_ref()
    exchange_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    status: Mapped[JournalStatus] = mapped_column(enum_type(JournalStatus), default=JournalStatus.POSTED)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    reversal_of_id: Mapped[int | None] = ref("fi_journal_entry.id", index=True)
    reversed_by_id: Mapped[int | None] = ref("fi_journal_entry.id")
    reversal_reason: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    journal_no: Mapped[int | None] = mapped_column(BigInteger)
    total_local: Mapped[Decimal] = mapped_column(Money)

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry",
        foreign_keys="JournalLine.entry_id",
        cascade="all, delete-orphan",
        order_by="JournalLine.line_no",
    )


class JournalLine(IdMixin, Base):
    """Journal line. Carries no timestamps: the entry does, and the line is immutable after posting
    except for the open-item bookkeeping columns."""

    __tablename__ = "fi_journal_line"
    __table_args__ = (
        UniqueConstraint("entry_id", "line_no"),
        CheckConstraint("side IN ('D', 'C')", name="side_valid"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("amount_local >= 0", name="amount_local_non_negative"),
        CheckConstraint("amount > 0 OR amount_local > 0", name="amount_present"),
        CheckConstraint("open_amount >= 0", name="open_amount_non_negative"),
        CheckConstraint("open_amount_local >= 0", name="open_amount_local_non_negative"),
        CheckConstraint("num_nonnulls(vendor_id, customer_id) <= 1", name="single_partner"),
        Index("ix_fi_journal_line_account_date", "company_id", "gl_account_id", "posting_date"),
        Index("ix_fi_journal_line_company_id_posting_date", "company_id", "posting_date"),
        Index(
            "ix_fi_journal_line_vendor_date",
            "vendor_id",
            "posting_date",
            postgresql_where="vendor_id IS NOT NULL",
        ),
        Index(
            "ix_fi_journal_line_customer_date",
            "customer_id",
            "posting_date",
            postgresql_where="customer_id IS NOT NULL",
        ),
        Index(
            "ix_fi_journal_line_vendor_open",
            "vendor_id",
            "due_date",
            postgresql_where="vendor_id IS NOT NULL AND is_open_item AND cleared_at IS NULL",
        ),
        Index(
            "ix_fi_journal_line_customer_open",
            "customer_id",
            "due_date",
            postgresql_where="customer_id IS NOT NULL AND is_open_item AND cleared_at IS NULL",
        ),
        Index(
            "ix_fi_journal_line_cost_center_id",
            "cost_center_id",
            postgresql_where="cost_center_id IS NOT NULL",
        ),
        Index("ix_fi_journal_line_tax_code_id", "tax_code_id", postgresql_where="tax_code_id IS NOT NULL"),
        Index("ix_fi_journal_line_material_id", "material_id", postgresql_where="material_id IS NOT NULL"),
    )

    entry_id: Mapped[int] = ref("fi_journal_entry.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    company_id: Mapped[int] = ref("org_company.id")
    posting_date: Mapped[date] = mapped_column(Date)
    gl_account_id: Mapped[int] = ref("fi_gl_account.id")
    side: Mapped[Side] = mapped_column(enum_type(Side))
    amount: Mapped[Decimal] = mapped_column(Money)
    amount_local: Mapped[Decimal] = mapped_column(Money)
    vendor_id: Mapped[int | None] = ref("fi_vendor.id")
    customer_id: Mapped[int | None] = ref("fi_customer.id")
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    internal_order_id: Mapped[int | None] = ref("co_internal_order.id")
    profit_center_id: Mapped[int | None] = ref("co_profit_center.id")
    tax_code_id: Mapped[int | None] = ref("fi_tax_code.id")
    tax_base_local: Mapped[Decimal | None] = mapped_column(Money)
    is_tax_line: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    payment_term_id: Mapped[int | None] = ref("fi_payment_term.id")
    payment_block: Mapped[bool] = mapped_column(Boolean, default=False)
    material_id: Mapped[int | None] = ref("mm_material.id")
    plant_id: Mapped[int | None] = ref("org_plant.id")
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    uom_id: Mapped[int | None] = ref("org_uom.id")
    assignment: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(String(255))
    is_open_item: Mapped[bool] = mapped_column(Boolean, default=False)
    open_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    open_amount_local: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entry: Mapped[JournalEntry] = relationship(back_populates="lines", foreign_keys=[entry_id])
    gl_account: Mapped[GLAccount] = relationship(foreign_keys=[gl_account_id])
    vendor: Mapped[Vendor | None] = relationship(foreign_keys=[vendor_id])
    customer: Mapped[Customer | None] = relationship(foreign_keys=[customer_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])
    tax_code: Mapped[TaxCode | None] = relationship(foreign_keys=[tax_code_id])


class Clearing(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "fi_clearing"

    clearing_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ClearingStatus] = mapped_column(enum_type(ClearingStatus), default=ClearingStatus.ACTIVE)
    fx_entry_id: Mapped[int | None] = ref("fi_journal_entry.id")

    items: Mapped[list[ClearingItem]] = relationship(
        back_populates="clearing",
        foreign_keys="ClearingItem.clearing_id",
        cascade="all, delete-orphan",
        order_by="ClearingItem.id",
    )


class ClearingItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "fi_clearing_item"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("amount_local >= 0", name="amount_local_non_negative"),
    )

    clearing_id: Mapped[int] = ref("fi_clearing.id", ondelete="CASCADE", index=True)
    journal_line_id: Mapped[int] = ref("fi_journal_line.id", index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    amount_local: Mapped[Decimal] = mapped_column(Money)

    clearing: Mapped[Clearing] = relationship(back_populates="items", foreign_keys=[clearing_id])
    journal_line: Mapped[JournalLine] = relationship(foreign_keys=[journal_line_id])


class ReflectionRule(IdMixin, TimestampMixin, CompanyMixin, Base):
    """Period-end reflection: Dr target / Cr reflection account for the movement on `expense_prefix`."""

    __tablename__ = "fi_reflection_rule"
    __table_args__ = (UniqueConstraint("company_id", "expense_prefix"),)

    expense_prefix: Mapped[str] = mapped_column(String(8))
    reflection_account_id: Mapped[int] = ref("fi_gl_account.id")
    target_account_id: Mapped[int] = ref("fi_gl_account.id")

    reflection_account: Mapped[GLAccount] = relationship(foreign_keys=[reflection_account_id])
    target_account: Mapped[GLAccount] = relationship(foreign_keys=[target_account_id])

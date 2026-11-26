"""Business partners: payment terms, vendors, customers."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, currency_ref, ref
from app.core.types import Money

if TYPE_CHECKING:
    from app.modules.fi.models.gl import GLAccount


class PaymentTerm(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "fi_payment_term"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("days >= 0", name="days_non_negative"),
    )

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    days: Mapped[int] = mapped_column(Integer, default=0)


class PartnerMixin:
    """Columns shared by vendors and customers."""

    code: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(255))
    tax_number: Mapped[str | None] = mapped_column(String(16))
    tax_office: Mapped[str | None] = mapped_column(String(64))
    is_person: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2), default="TR")
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    contact_name: Mapped[str | None] = mapped_column(String(128))
    iban: Mapped[str | None] = mapped_column(String(34))
    bank_name: Mapped[str | None] = mapped_column(String(128))
    currency_code: Mapped[str] = currency_ref(default="TRY")
    payment_term_id: Mapped[int | None] = ref("fi_payment_term.id")
    recon_account_id: Mapped[int] = ref("fi_gl_account.id")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    einvoice_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    einvoice_alias: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    @declared_attr
    def payment_term(cls) -> Mapped[PaymentTerm | None]:
        return relationship(foreign_keys=lambda: [cls.payment_term_id])

    @declared_attr
    def recon_account(cls) -> Mapped[GLAccount]:
        return relationship(foreign_keys=lambda: [cls.recon_account_id])


class Vendor(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, PartnerMixin, Base):
    __tablename__ = "fi_vendor"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        Index("ix_fi_vendor_company_id_tax_number", "company_id", "tax_number"),
    )

    purchasing_block: Mapped[bool] = mapped_column(Boolean, default=False)


class Customer(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, PartnerMixin, Base):
    __tablename__ = "fi_customer"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        Index("ix_fi_customer_company_id_tax_number", "company_id", "tax_number"),
        CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="credit_limit_non_negative"),
    )

    credit_limit: Mapped[Decimal | None] = mapped_column(Money)

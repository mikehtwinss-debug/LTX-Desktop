"""Organisation structure and the shared infrastructure tables."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import (
    Base,
    CompanyMixin,
    IdMixin,
    TimestampMixin,
    VersionMixin,
    currency_ref,
    ref,
    utcnow,
)
from app.core.types import Money, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.auth.models import Role, User


class RateType(enum.StrEnum):
    ALIS = "ALIS"
    SATIS = "SATIS"


class ApprovalStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalStepStatus(enum.StrEnum):
    WAITING = "WAITING"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class Company(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "org_company"
    __audit__ = True

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    legal_name: Mapped[str] = mapped_column(String(255))
    tax_office: Mapped[str | None] = mapped_column(String(64))
    tax_number: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2), default="TR")
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(255))
    currency_code: Mapped[str] = currency_ref(default="TRY")
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    logo_mime: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def has_logo(self) -> bool:
        # Answered from the mime type so that listing companies never loads the deferred image.
        return self.logo_mime is not None


class Plant(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    """A site of the company; also the valuation area for stock."""

    __tablename__ = "org_plant"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "org_warehouse"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    plant_id: Mapped[int] = ref("org_plant.id", index=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])


class PurchasingGroup(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "org_purchasing_group"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Currency(IdMixin, TimestampMixin, Base):
    __tablename__ = "org_currency"

    code: Mapped[str] = mapped_column(String(3), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExchangeRate(IdMixin, TimestampMixin, Base):
    """Local currency per one unit of `currency_code`; the latest row on or before a date applies."""

    __tablename__ = "org_exchange_rate"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("currency_code", "rate_date", "rate_type"),
        CheckConstraint("rate > 0", name="rate_positive"),
    )

    currency_code: Mapped[str] = currency_ref()
    rate_date: Mapped[date] = mapped_column(Date)
    rate_type: Mapped[RateType] = mapped_column(enum_type(RateType), default=RateType.ALIS)
    rate: Mapped[Decimal] = mapped_column(Rate)


class Uom(IdMixin, TimestampMixin, Base):
    __tablename__ = "org_uom"
    __audit__ = True
    __table_args__ = (CheckConstraint("decimals BETWEEN 0 AND 6", name="decimals_range"),)

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    decimals: Mapped[int] = mapped_column(Integer, default=0)
    unece_code: Mapped[str | None] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NumberRange(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "org_number_range"
    __table_args__ = (
        UniqueConstraint("company_id", "key", "year"),
        CheckConstraint("year >= 0", name="year_non_negative"),
        CheckConstraint("padding BETWEEN 1 AND 12", name="padding_range"),
        CheckConstraint("next_value >= 1", name="next_value_positive"),
    )

    key: Mapped[str] = mapped_column(String(32))
    year: Mapped[int] = mapped_column(Integer, default=0)
    prefix: Mapped[str] = mapped_column(String(16), default="")
    padding: Mapped[int] = mapped_column(Integer)
    next_value: Mapped[int] = mapped_column(BigInteger, default=1)


class CompanySetting(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "org_company_setting"
    __table_args__ = (UniqueConstraint("company_id", "key"),)

    key: Mapped[str] = mapped_column(String(96))
    value: Mapped[Any] = mapped_column(JSONB)


class AuditLog(IdMixin, Base):
    """Append-only change log; a database trigger rejects UPDATE and DELETE."""

    __tablename__ = "org_audit_log"
    __table_args__ = (
        Index("ix_org_audit_log_company_id_at", "company_id", "at"),
        Index("ix_org_audit_log_entity_entity_id", "entity", "entity_id"),
    )

    company_id: Mapped[int | None] = ref("org_company.id")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = ref("auth_user.id", index=True)
    action: Mapped[str] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    summary: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])


class Attachment(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "org_attachment"
    __table_args__ = (
        Index("ix_org_attachment_object", "company_id", "object_type", "object_id"),
        CheckConstraint("size >= 0", name="size_non_negative"),
    )

    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[int] = mapped_column(BigInteger)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    uploaded_by_id: Mapped[int] = ref("auth_user.id")

    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])


class ApprovalRule(IdMixin, TimestampMixin, CompanyMixin, Base):
    """A document of amount A needs every active level whose `min_amount <= A`, in level order."""

    __tablename__ = "org_approval_rule"
    __audit__ = True
    __table_args__ = (
        Index("ix_org_approval_rule_lookup", "company_id", "object_type", "level"),
        CheckConstraint("level >= 1", name="level_positive"),
        CheckConstraint("min_amount >= 0", name="min_amount_non_negative"),
        CheckConstraint("num_nonnulls(approver_role_id, approver_user_id) >= 1", name="has_approver"),
    )

    object_type: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer)
    min_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    approver_role_id: Mapped[int | None] = ref("auth_role.id")
    approver_user_id: Mapped[int | None] = ref("auth_user.id")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    approver_role: Mapped[Role | None] = relationship(foreign_keys=[approver_role_id])
    approver_user: Mapped[User | None] = relationship(foreign_keys=[approver_user_id])


class ApprovalRequest(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "org_approval_request"
    __table_args__ = (
        Index("ix_org_approval_request_object", "company_id", "object_type", "object_id"),
        Index("ix_org_approval_request_company_id_status", "company_id", "status"),
        # At most one open request per document, also when two submissions race.
        Index(
            "uq_org_approval_request_pending",
            "company_id",
            "object_type",
            "object_id",
            unique=True,
            postgresql_where="status = 'PENDING'",
        ),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[ApprovalStatus] = mapped_column(enum_type(ApprovalStatus), default=ApprovalStatus.PENDING)
    requested_by_id: Mapped[int] = ref("auth_user.id", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_level: Mapped[int | None] = mapped_column(Integer)

    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="request",
        foreign_keys="ApprovalStep.request_id",
        cascade="all, delete-orphan",
        order_by="ApprovalStep.level, ApprovalStep.id",
    )


class ApprovalStep(IdMixin, TimestampMixin, Base):
    __tablename__ = "org_approval_step"
    __table_args__ = (CheckConstraint("level >= 1", name="level_positive"),)

    request_id: Mapped[int] = ref("org_approval_request.id", ondelete="CASCADE", index=True)
    level: Mapped[int] = mapped_column(Integer)
    approver_role_id: Mapped[int | None] = ref("auth_role.id", index=True)
    approver_user_id: Mapped[int | None] = ref("auth_user.id", index=True)
    status: Mapped[ApprovalStepStatus] = mapped_column(
        enum_type(ApprovalStepStatus), default=ApprovalStepStatus.WAITING
    )
    acted_by_id: Mapped[int | None] = ref("auth_user.id")
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)

    request: Mapped[ApprovalRequest] = relationship(back_populates="steps", foreign_keys=[request_id])
    approver_role: Mapped[Role | None] = relationship(foreign_keys=[approver_role_id])
    approver_user: Mapped[User | None] = relationship(foreign_keys=[approver_user_id])
    acted_by: Mapped[User | None] = relationship(foreign_keys=[acted_by_id])

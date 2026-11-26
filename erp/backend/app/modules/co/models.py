"""Cost objects. Only cost centers are functional in Phase 1."""

from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin
from app.core.types import enum_type


class CostCenterFunction(enum.StrEnum):
    """Functional area; decides the TDHP expense account class (730/740/750/760/770/780)."""

    URETIM = "URETIM"
    HIZMET = "HIZMET"
    ARGE = "ARGE"
    PAZARLAMA = "PAZARLAMA"
    YONETIM = "YONETIM"
    FINANSMAN = "FINANSMAN"


class CostCenter(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "co_cost_center"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from", name="validity_range"
        ),
    )

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    function: Mapped[CostCenterFunction] = mapped_column(enum_type(CostCenterFunction))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class InternalOrder(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "co_internal_order"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProfitCenter(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "co_profit_center"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

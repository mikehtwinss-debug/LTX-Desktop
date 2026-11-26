"""Bank and cash accounts."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, currency_ref, ref
from app.core.types import enum_type

if TYPE_CHECKING:
    from app.modules.fi.models.gl import GLAccount


class TreasuryKind(enum.StrEnum):
    BANK = "BANK"
    CASH = "CASH"


class TreasuryAccount(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "fi_treasury_account"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    kind: Mapped[TreasuryKind] = mapped_column(enum_type(TreasuryKind))
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    bank_name: Mapped[str | None] = mapped_column(String(128))
    branch: Mapped[str | None] = mapped_column(String(128))
    iban: Mapped[str | None] = mapped_column(String(34))
    currency_code: Mapped[str] = currency_ref(default="TRY")
    gl_account_id: Mapped[int] = ref("fi_gl_account.id")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    gl_account: Mapped[GLAccount] = relationship(foreign_keys=[gl_account_id])

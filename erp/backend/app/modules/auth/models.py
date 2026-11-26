"""Users, roles and permissions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, TimestampMixin, VersionMixin, ref

if TYPE_CHECKING:
    from app.modules.org.models import Company


class User(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "auth_user"
    __audit__ = True
    __audit_mask__ = ("password_hash",)

    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    default_company_id: Mapped[int | None] = ref("org_company.id", ondelete="SET NULL")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        foreign_keys="UserRole.user_id",
        cascade="all, delete-orphan",
        order_by="UserRole.id",
    )


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "auth_role"
    __audit__ = True

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permission_links: Mapped[list[RolePermission]] = relationship(
        back_populates="role", foreign_keys="RolePermission.role_id", cascade="all, delete-orphan"
    )


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "auth_permission"

    key: Mapped[str] = mapped_column(String(96), unique=True)
    description: Mapped[str] = mapped_column(String(255))


class RolePermission(IdMixin, TimestampMixin, Base):
    __tablename__ = "auth_role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    role_id: Mapped[int] = ref("auth_role.id", ondelete="CASCADE")
    permission_id: Mapped[int] = ref("auth_permission.id", ondelete="CASCADE", index=True)

    role: Mapped[Role] = relationship(back_populates="permission_links", foreign_keys=[role_id])
    permission: Mapped[Permission] = relationship(foreign_keys=[permission_id])


class UserRole(IdMixin, TimestampMixin, Base):
    """A role held by a user in one company, or in every company when `company_id` is NULL."""

    __tablename__ = "auth_user_role"
    __audit__ = True

    user_id: Mapped[int] = ref("auth_user.id", ondelete="CASCADE", index=True)
    role_id: Mapped[int] = ref("auth_role.id", index=True)
    company_id: Mapped[int | None] = ref("org_company.id", index=True)

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(foreign_keys=[role_id])
    company: Mapped[Company | None] = relationship(foreign_keys=[company_id])

    __table_args__ = (
        Index(
            "uq_auth_user_role_global",
            "user_id",
            "role_id",
            unique=True,
            postgresql_where=company_id.is_(None),
        ),
        Index(
            "uq_auth_user_role_company",
            "user_id",
            "role_id",
            "company_id",
            unique=True,
            postgresql_where=company_id.isnot(None),
        ),
    )

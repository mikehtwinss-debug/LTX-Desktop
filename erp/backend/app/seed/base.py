"""Base seed: permissions, system roles, the administrator, currencies and units. Idempotent."""

from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.auth.schemas import PASSWORD_MIN_LENGTH
from app.modules.auth.service import sync_permissions
from app.modules.org.models import Currency, Uom
from app.seed.tdhp import load_json

ADMIN_USERNAME = "admin"
ADMIN_ROLE = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


def role_templates() -> list[dict[str, Any]]:
    """The system roles with their `grant` / `deny` permission patterns (fnmatch syntax)."""
    return load_json("base.json")["roles"]


def template_permissions(template: Mapping[str, Any], keys: Iterable[str]) -> set[str]:
    """Permission keys a role template selects: matched by a `grant` pattern and by no `deny` pattern."""
    return {
        key
        for key in keys
        if any(fnmatchcase(key, pattern) for pattern in template["grant"])
        and not any(fnmatchcase(key, pattern) for pattern in template["deny"])
    }


def _seed_currencies(db: Session) -> None:
    existing = set(db.scalars(select(Currency.code)))
    for row in load_json("base.json")["currencies"]:
        if row["code"] not in existing:
            db.add(Currency(code=row["code"], name=row["name"], symbol=row["symbol"]))


def _seed_units(db: Session) -> None:
    existing = set(db.scalars(select(Uom.code)))
    for row in load_json("base.json")["units"]:
        if row["code"] not in existing:
            db.add(
                Uom(
                    code=row["code"], name=row["name"], decimals=row["decimals"], unece_code=row["unece_code"]
                )
            )


def _seed_roles(db: Session) -> None:
    """Create missing system roles and grant them every permission their template selects.

    Only ever adds permissions: grants made by hand in the role administration survive a re-run,
    and permissions introduced by newer features are picked up.
    """
    permissions = {permission.key: permission for permission in db.scalars(select(Permission))}
    for template in role_templates():
        role = db.scalar(select(Role).where(Role.code == template["code"]))
        if role is None:
            role = Role(
                code=template["code"],
                name=template["name"],
                description=template["description"],
                is_system=True,
            )
            db.add(role)
            db.flush()
        granted = set(
            db.scalars(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        )
        for key in sorted(template_permissions(template, permissions) - granted):
            db.add(RolePermission(role_id=role.id, permission_id=permissions[key].id))


def _seed_admin(db: Session, admin_password: str | None) -> bool:
    """Create the administrator once; an existing account (and its password) is never touched.

    Returns whether the account was created with the well-known default password.
    """
    admin = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
    created_with_default = False
    if admin is None:
        if admin_password is not None and len(admin_password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"ERP_ADMIN_PASSWORD en az {PASSWORD_MIN_LENGTH} karakter olmalıdır")
        admin = User(
            username=ADMIN_USERNAME,
            full_name="Sistem Yöneticisi",
            password_hash=security.hash_password(admin_password or DEFAULT_ADMIN_PASSWORD),
            is_superuser=True,
            # Without a configured password the well-known default must be replaced at first login.
            must_change_password=admin_password is None,
        )
        db.add(admin)
        db.flush()
        created_with_default = admin_password is None
    role_id = db.scalar(select(Role.id).where(Role.code == ADMIN_ROLE))
    has_role = db.scalar(
        select(UserRole.id).where(
            UserRole.user_id == admin.id, UserRole.role_id == role_id, UserRole.company_id.is_(None)
        )
    )
    if has_role is None:
        db.add(UserRole(user_id=admin.id, role_id=role_id, company_id=None))
    return created_with_default


def seed_base(db: Session, permissions: Mapping[str, str], *, admin_password: str | None) -> bool:
    """Seed the company-independent data.

    Returns True when the administrator was just created with the default password (`admin`),
    which the account is then forced to change at first login.
    """
    sync_permissions(db, permissions)
    db.flush()
    _seed_currencies(db)
    _seed_units(db)
    _seed_roles(db)
    default_admin_created = _seed_admin(db, admin_password)
    db.flush()
    return default_admin_created

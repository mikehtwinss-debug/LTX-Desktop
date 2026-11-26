"""Test data factories. Every factory flushes, so ids are available and API requests see the rows."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.modules.auth.models import Role, User, UserRole
from app.modules.co.models import CostCenter, CostCenterFunction
from app.modules.fi.models.gl import GLAccount
from app.modules.fi.models.partners import Customer, Vendor
from app.modules.mm.models.master import Material, MaterialType, ValuationClass
from app.modules.org.models import Company, Uom

DEFAULT_COMPANY_CODE = "1000"
DEFAULT_PASSWORD = "Parola-Test-1"

_sequence = itertools.count(1)


def unique(prefix: str) -> str:
    """A code that no other factory call of this test run produced."""
    return f"{prefix}{next(_sequence):05d}"


@lru_cache
def _password_hash(password: str) -> str:
    # Argon2 is deliberately slow; tests hash each distinct password once.
    return security.hash_password(password)


def default_company(db: Session) -> Company:
    """The fully seeded company 1000."""
    return db.scalars(select(Company).where(Company.code == DEFAULT_COMPANY_CODE)).one()


def make_company(
    db: Session, *, code: str | None = None, name: str | None = None, **overrides: Any
) -> Company:
    """A bare company (no chart of accounts); use `app.seed.seed_company` for a complete one."""
    code = code or unique("T")
    company = Company(
        code=code, name=name or f"Deneme Şirketi {code}", legal_name=name or f"Deneme Şirketi {code}"
    )
    for key, value in overrides.items():
        setattr(company, key, value)
    db.add(company)
    db.flush()
    return company


def assign_role(db: Session, user: User, role_code: str, company: Company | None = None) -> UserRole:
    """Give `user` a role in `company`, or in every company when `company` is None."""
    role = db.scalars(select(Role).where(Role.code == role_code)).one()
    link = UserRole(user_id=user.id, role_id=role.id, company_id=company.id if company else None)
    db.add(link)
    db.flush()
    db.expire(user, ["roles"])
    return link


def make_user(
    db: Session,
    *,
    username: str | None = None,
    password: str = DEFAULT_PASSWORD,
    full_name: str | None = None,
    roles: Sequence[str] = (),
    company: Company | None = None,
    **overrides: Any,
) -> User:
    """A user holding `roles` in `company` (default: company 1000, which also becomes the default)."""
    username = username or unique("kullanici")
    user = User(
        username=username,
        full_name=full_name or f"Deneme Kullanıcı {username}",
        password_hash=_password_hash(password),
    )
    for key, value in overrides.items():
        setattr(user, key, value)
    db.add(user)
    db.flush()
    if roles:
        company = company or default_company(db)
        if user.default_company_id is None:
            user.default_company_id = company.id
        for role_code in roles:
            assign_role(db, user, role_code, company)
    db.flush()
    return user


def gl_account(db: Session, code: str, company: Company | None = None) -> GLAccount:
    """Look up a seeded GL account by code (`gl_account(db, "320.01")`)."""
    company = company or default_company(db)
    return db.scalars(
        select(GLAccount).where(GLAccount.company_id == company.id, GLAccount.code == code)
    ).one()


def make_cost_center(
    db: Session,
    *,
    company: Company | None = None,
    code: str | None = None,
    function: CostCenterFunction = CostCenterFunction.YONETIM,
    **overrides: Any,
) -> CostCenter:
    company = company or default_company(db)
    code = code or unique("MY")
    cost_center = CostCenter(company_id=company.id, code=code, name=f"Masraf Yeri {code}", function=function)
    for key, value in overrides.items():
        setattr(cost_center, key, value)
    db.add(cost_center)
    db.flush()
    return cost_center


def make_vendor(
    db: Session,
    *,
    company: Company | None = None,
    code: str | None = None,
    recon_account: str = "320.01",
    **overrides: Any,
) -> Vendor:
    company = company or default_company(db)
    code = code or unique("S")
    vendor = Vendor(
        company_id=company.id,
        code=code,
        name=f"Deneme Tedarikçi {code} Ltd. Şti.",
        currency_code=company.currency_code,
        recon_account_id=gl_account(db, recon_account, company).id,
    )
    for key, value in overrides.items():
        setattr(vendor, key, value)
    db.add(vendor)
    db.flush()
    return vendor


def make_customer(
    db: Session,
    *,
    company: Company | None = None,
    code: str | None = None,
    recon_account: str = "120.01",
    **overrides: Any,
) -> Customer:
    company = company or default_company(db)
    code = code or unique("M")
    customer = Customer(
        company_id=company.id,
        code=code,
        name=f"Deneme Müşteri {code} A.Ş.",
        currency_code=company.currency_code,
        recon_account_id=gl_account(db, recon_account, company).id,
    )
    for key, value in overrides.items():
        setattr(customer, key, value)
    db.add(customer)
    db.flush()
    return customer


def make_material(
    db: Session,
    *,
    company: Company | None = None,
    code: str | None = None,
    material_type: MaterialType = MaterialType.HAMMADDE,
    base_uom: str = "ADET",
    valuation_class: str | None = "HAMMADDE",
    **overrides: Any,
) -> Material:
    """A material without plant data; `valuation_class=None` leaves it unvalued."""
    company = company or default_company(db)
    code = code or unique("MLZ")
    valuation_class_id = None
    if valuation_class is not None:
        valuation_class_id = db.scalars(
            select(ValuationClass.id).where(
                ValuationClass.company_id == company.id, ValuationClass.code == valuation_class
            )
        ).one()
    material = Material(
        company_id=company.id,
        code=code,
        name=f"Deneme Malzeme {code}",
        material_type=material_type,
        base_uom_id=db.scalars(select(Uom.id).where(Uom.code == base_uom)).one(),
        valuation_class_id=valuation_class_id,
    )
    for key, value in overrides.items():
        setattr(material, key, value)
    db.add(material)
    db.flush()
    return material

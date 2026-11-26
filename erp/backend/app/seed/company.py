"""Company seed: organisation, TDHP chart of accounts and the accounting defaults. Idempotent.

Everything created here is ordinary data the accountant may change afterwards, so a re-run only
adds what is missing and never overwrites existing rows.
"""

import calendar
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import registered_settings
from app.modules.auth.models import User
from app.modules.fi.models.gl import (
    AccountType,
    GLAccount,
    Period,
    PeriodStatus,
    ReconType,
    ReflectionRule,
    Side,
    TaxCode,
    TaxType,
)
from app.modules.fi.models.partners import PaymentTerm
from app.modules.mm.models.master import AccountDetermination, AccountKey, ValuationClass
from app.modules.org.models import Company, CompanySetting, Currency, Plant, Warehouse
from app.seed.base import ADMIN_USERNAME
from app.seed.tdhp import load_json, main_accounts

LOCAL_CURRENCY = "TRY"


def _parent_code(code: str) -> str:
    return code.rsplit(".", 1)[0]


def _seed_company(db: Session, code: str, name: str) -> Company:
    company = db.scalar(select(Company).where(Company.code == code))
    if company is None:
        if db.scalar(select(Currency.code).where(Currency.code == LOCAL_CURRENCY)) is None:
            raise RuntimeError("Temel veriler eksik: önce `python -m app.seed base` çalıştırılmalıdır")
        company = Company(code=code, name=name, legal_name=name, currency_code=LOCAL_CURRENCY)
        db.add(company)
        db.flush()
    return company


def _seed_organisation(db: Session, company: Company, data: dict[str, Any]) -> None:
    plant = db.scalar(
        select(Plant).where(Plant.company_id == company.id, Plant.code == data["plant"]["code"])
    )
    if plant is None:
        plant = Plant(company_id=company.id, code=data["plant"]["code"], name=data["plant"]["name"])
        db.add(plant)
        db.flush()
    warehouse_exists = db.scalar(
        select(Warehouse.id).where(
            Warehouse.company_id == company.id, Warehouse.code == data["warehouse"]["code"]
        )
    )
    if warehouse_exists is None:
        db.add(
            Warehouse(
                company_id=company.id,
                plant_id=plant.id,
                code=data["warehouse"]["code"],
                name=data["warehouse"]["name"],
            )
        )


def _seed_chart(db: Session, company: Company, data: dict[str, Any]) -> dict[str, GLAccount]:
    accounts = {
        account.code: account
        for account in db.scalars(select(GLAccount).where(GLAccount.company_id == company.id))
    }
    parents_with_children = {_parent_code(row["code"]) for row in data["sub_accounts"]}

    mains = [
        (account.code, account.name, account.account_type, account.normal_side) for account in main_accounts()
    ]
    mains.extend(
        (row["code"], row["name"], AccountType(row["type"]), Side(row["side"]))
        for row in data["technical_accounts"]
    )
    for code, name, account_type, side in mains:
        if code not in accounts:
            accounts[code] = GLAccount(
                company_id=company.id,
                code=code,
                name=name,
                level=1,
                account_type=account_type,
                normal_side=side,
                # A main account collects its sub-accounts; it is posted to directly only without any.
                is_postable=code not in parents_with_children,
            )
            db.add(accounts[code])
    db.flush()

    for row in data["sub_accounts"]:
        if row["code"] in accounts:
            continue
        parent = accounts[_parent_code(row["code"])]
        accounts[row["code"]] = GLAccount(
            company_id=company.id,
            code=row["code"],
            name=row["name"],
            parent_id=parent.id,
            level=row["code"].count(".") + 1,
            account_type=parent.account_type,
            normal_side=parent.normal_side,
            is_postable=True,
            recon_type=ReconType(row.get("recon", ReconType.NONE)),
            requires_cost_center=row.get("requires_cost_center", False),
        )
        db.add(accounts[row["code"]])
    db.flush()
    return accounts


def _seed_tax_codes(
    db: Session, company: Company, data: dict[str, Any], accounts: dict[str, GLAccount]
) -> None:
    existing = set(db.scalars(select(TaxCode.code).where(TaxCode.company_id == company.id)))
    for row in data["tax_codes"]:
        if row["code"] not in existing:
            db.add(
                TaxCode(
                    company_id=company.id,
                    code=row["code"],
                    name=row["name"],
                    tax_type=TaxType(row["type"]),
                    rate=Decimal(row["rate"]),
                    gl_account_id=accounts[row["account"]].id,
                )
            )


def _seed_account_determination(
    db: Session, company: Company, data: dict[str, Any], accounts: dict[str, GLAccount]
) -> None:
    classes = {
        valuation_class.code: valuation_class
        for valuation_class in db.scalars(
            select(ValuationClass).where(ValuationClass.company_id == company.id)
        )
    }
    for row in data["valuation_classes"]:
        if row["code"] not in classes:
            classes[row["code"]] = ValuationClass(company_id=company.id, code=row["code"], name=row["name"])
            db.add(classes[row["code"]])
    db.flush()

    existing = {
        (rule.key, rule.valuation_class_id, rule.modifier)
        for rule in db.scalars(
            select(AccountDetermination).where(AccountDetermination.company_id == company.id)
        )
    }
    for row in data["account_determination"]:
        key = AccountKey(row["key"])
        class_id = classes[row["valuation_class"]].id if "valuation_class" in row else None
        modifier = row.get("modifier")
        if (key, class_id, modifier) not in existing:
            db.add(
                AccountDetermination(
                    company_id=company.id,
                    key=key,
                    valuation_class_id=class_id,
                    modifier=modifier,
                    gl_account_id=accounts[row["account"]].id,
                )
            )


def _seed_reflection_rules(
    db: Session, company: Company, data: dict[str, Any], accounts: dict[str, GLAccount]
) -> None:
    existing = set(
        db.scalars(select(ReflectionRule.expense_prefix).where(ReflectionRule.company_id == company.id))
    )
    for row in data["reflection_rules"]:
        if row["expense_prefix"] not in existing:
            db.add(
                ReflectionRule(
                    company_id=company.id,
                    expense_prefix=row["expense_prefix"],
                    reflection_account_id=accounts[row["reflection_account"]].id,
                    target_account_id=accounts[row["target_account"]].id,
                )
            )


def _seed_payment_terms(db: Session, company: Company, data: dict[str, Any]) -> None:
    existing = set(db.scalars(select(PaymentTerm.code).where(PaymentTerm.company_id == company.id)))
    for row in data["payment_terms"]:
        if row["code"] not in existing:
            db.add(PaymentTerm(company_id=company.id, code=row["code"], name=row["name"], days=row["days"]))


def _seed_periods(db: Session, company: Company, first_year: int) -> None:
    """Open posting periods for `first_year` and the year after (fiscal year = calendar year)."""
    existing = {
        (year, period)
        for year, period in db.execute(
            select(Period.year, Period.period).where(Period.company_id == company.id)
        )
    }
    for year in (first_year, first_year + 1):
        for month in range(1, 13):
            if (year, month) not in existing:
                db.add(
                    Period(
                        company_id=company.id,
                        year=year,
                        period=month,
                        start_date=date(year, month, 1),
                        end_date=date(year, month, calendar.monthrange(year, month)[1]),
                        status=PeriodStatus.OPEN,
                    )
                )


def _seed_settings(db: Session, company: Company) -> None:
    """Materialise the default of every registered setting so the admin UI lists them all."""
    existing = set(db.scalars(select(CompanySetting.key).where(CompanySetting.company_id == company.id)))
    for key, spec in sorted(registered_settings().items()):
        if key not in existing:
            db.add(CompanySetting(company_id=company.id, key=key, value=spec.default))


def _default_admin_company(db: Session, company: Company) -> None:
    admin = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
    if admin is not None and admin.default_company_id is None:
        admin.default_company_id = company.id


def seed_company(db: Session, *, code: str, name: str, today: date | None = None) -> Company:
    data = load_json("company.json")
    company = _seed_company(db, code, name)
    _seed_organisation(db, company, data)
    accounts = _seed_chart(db, company, data)
    _seed_tax_codes(db, company, data, accounts)
    _seed_account_determination(db, company, data, accounts)
    _seed_reflection_rules(db, company, data, accounts)
    _seed_payment_terms(db, company, data)
    _seed_periods(db, company, (today or date.today()).year)
    _seed_settings(db, company)
    _default_admin_company(db, company)
    db.flush()
    return company

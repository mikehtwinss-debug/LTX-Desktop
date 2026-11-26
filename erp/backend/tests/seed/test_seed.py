"""Seed data: base data, the TDHP chart and the accounting defaults of company 1000."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.settings import register_setting
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.co.models import CostCenterFunction
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
from app.modules.org.models import Company, CompanySetting, Currency, Plant, Uom, Warehouse
from app.seed import company as company_seed
from app.seed import seed_base, seed_company
from app.seed.base import role_templates, template_permissions
from app.seed.tdhp import load_json, load_tdhp, main_accounts
from tests import factories
from tests.conftest import ADMIN_PASSWORD

D, C = Side.DEBIT, Side.CREDIT


def _accounts(db: Session, company: Company) -> dict[str, GLAccount]:
    return {a.code: a for a in db.scalars(select(GLAccount).where(GLAccount.company_id == company.id))}


def _table_counts(db: Session) -> dict[str, int]:
    models = (
        Permission, Role, RolePermission, User, UserRole, Currency, Uom, Company, Plant, Warehouse, GLAccount,
        TaxCode, ValuationClass, AccountDetermination, ReflectionRule, PaymentTerm, Period, CompanySetting,
    )  # fmt: skip
    return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in models}


# --- base seed ---------------------------------------------------------------------------------------


def test_currencies_and_units(db: Session) -> None:
    currencies = {c.code: (c.name, c.symbol) for c in db.scalars(select(Currency))}
    units = {u.code: (u.decimals, u.unece_code) for u in db.scalars(select(Uom))}

    assert currencies == {
        "TRY": ("Türk Lirası", "₺"),
        "USD": ("ABD Doları", "$"),
        "EUR": ("Euro", "€"),
        "GBP": ("İngiliz Sterlini", "£"),
    }
    assert {"ADET", "KG", "LT", "M", "M2", "M3", "TON", "PAKET", "KOLI", "SET", "SAAT"} <= units.keys()
    assert units["ADET"] == (0, "C62")
    assert units["KG"] == (3, "KGM")
    assert units["SAAT"] == (2, "HUR")


def test_administrator(db: Session, admin: User, company: Company) -> None:
    assert admin.is_superuser and admin.is_active
    assert admin.must_change_password is False  # a password was supplied through ERP_ADMIN_PASSWORD
    assert security.verify_password(ADMIN_PASSWORD, admin.password_hash)
    assert admin.default_company_id == company.id
    assert [(link.role.code, link.company_id) for link in admin.roles] == [("admin", None)]


def test_administrator_without_configured_password_must_change_the_default(db: Session, app: FastAPI) -> None:
    db.delete(db.scalars(select(User).where(User.username == "admin")).one())
    db.flush()

    created_with_default = seed_base(db, app.state.permissions, admin_password=None)

    fresh = db.scalars(select(User).where(User.username == "admin")).one()
    assert created_with_default is True
    assert security.verify_password("admin", fresh.password_hash)
    assert fresh.must_change_password is True
    assert fresh.is_superuser


def test_too_short_administrator_password_is_refused(db: Session, app: FastAPI) -> None:
    db.delete(db.scalars(select(User).where(User.username == "admin")).one())
    db.flush()

    with pytest.raises(ValueError, match="en az 8 karakter"):
        seed_base(db, app.state.permissions, admin_password="kisa")


def test_existing_administrator_password_is_never_reset(db: Session, app: FastAPI, admin: User) -> None:
    created_with_default = seed_base(db, app.state.permissions, admin_password="Baska-Bir-Parola-1")

    db.refresh(admin)
    assert created_with_default is False
    assert security.verify_password(ADMIN_PASSWORD, admin.password_hash)


def test_six_system_roles_with_template_permissions(db: Session) -> None:
    roles = {role.code: role for role in db.scalars(select(Role))}
    all_keys = set(db.scalars(select(Permission.key)))

    assert set(roles) == {"admin", "muhasebe", "satinalma", "depo", "yonetici", "izleyici"}
    assert all(role.is_system for role in roles.values())
    granted = {code: {link.permission.key for link in role.permission_links} for code, role in roles.items()}
    assert granted["admin"] == all_keys
    assert granted["izleyici"] == {key for key in all_keys if key.endswith(".view")}
    for template in role_templates():
        assert granted[template["code"]] == template_permissions(template, all_keys)


def test_role_templates_select_by_prefix_and_action() -> None:
    keys = {
        "auth.user.view", "auth.user.manage", "org.company.view", "org.company.manage", "co.cost_center.view",
        "fi.journal.view", "fi.journal.post", "fi.vendor.view", "fi.vendor.manage", "fi.payment_term.view",
        "mm.material.view", "mm.material.manage", "mm.po.view", "mm.po.create", "mm.po.approve",
        "mm.pr.create", "mm.pr.approve", "mm.comparison.approve", "mm.matdoc.view", "mm.matdoc.create",
        "mm.stock.view", "mm.sinv.view", "mm.sinv.release",
    }  # fmt: skip
    selected = {template["code"]: template_permissions(template, keys) for template in role_templates()}

    assert selected["admin"] == keys
    assert selected["izleyici"] == {key for key in keys if key.endswith(".view")}
    assert selected["yonetici"] == {key for key in keys if key.endswith((".view", ".approve", ".release"))}
    assert {"fi.journal.post", "fi.vendor.manage", "mm.po.view", "mm.stock.view"} <= selected["muhasebe"]
    assert not {"mm.po.create", "mm.matdoc.create", "auth.user.manage"} & selected["muhasebe"]
    assert {"mm.po.create", "mm.pr.create", "mm.po.view", "fi.vendor.view", "mm.stock.view"} <= selected[
        "satinalma"
    ]
    assert not {key for key in selected["satinalma"] if key.endswith((".approve", ".release"))}
    assert not {"fi.journal.post", "mm.matdoc.create", "fi.vendor.manage"} & selected["satinalma"]
    assert {
        "mm.matdoc.create",
        "mm.matdoc.view",
        "mm.stock.view",
        "mm.material.view",
        "mm.po.view",
    } <= selected["depo"]
    assert not {"mm.po.create", "fi.journal.post", "mm.material.manage"} & selected["depo"]


def test_new_permissions_reach_the_roles_when_the_seed_is_run_again(db: Session, app: FastAPI) -> None:
    extended = {
        **app.state.permissions,
        "fi.journal.view": "Yevmiye kayıtlarını görüntüleme",
        "fi.journal.post": "Yevmiye kaydı oluşturma",
        "mm.po.approve": "Satınalma siparişi onaylama",
    }
    viewer = db.scalars(select(Role).where(Role.code == "izleyici")).one()
    manual = db.scalars(select(Permission).where(Permission.key == "auth.user.manage")).one()
    db.add(RolePermission(role_id=viewer.id, permission_id=manual.id))
    db.flush()

    seed_base(db, extended, admin_password=ADMIN_PASSWORD)
    db.expire_all()

    def granted(code: str) -> set[str]:
        role = db.scalars(select(Role).where(Role.code == code)).one()
        return {link.permission.key for link in role.permission_links}

    assert {"fi.journal.view", "fi.journal.post", "mm.po.approve"} <= granted("admin")
    assert {"fi.journal.view", "fi.journal.post"} <= granted("muhasebe")
    assert "mm.po.approve" not in granted("muhasebe")
    assert {"fi.journal.view", "mm.po.approve"} <= granted("yonetici")
    assert "fi.journal.post" not in granted("yonetici")
    # Additive only: the grant made by hand survives, the new view permission is added.
    assert granted("izleyici") == {"auth.user.view", "auth.role.view", "auth.user.manage", "fi.journal.view"}


# --- company seed: organisation --------------------------------------------------------------------


def test_company_plant_and_warehouse(db: Session, company: Company) -> None:
    plant = db.scalars(select(Plant).where(Plant.company_id == company.id)).one()
    warehouse = db.scalars(select(Warehouse).where(Warehouse.company_id == company.id)).one()

    assert (company.code, company.name, company.currency_code, company.country) == (
        "1000",
        "Örnek Sanayi A.Ş.",
        "TRY",
        "TR",
    )
    assert (plant.code, plant.name) == ("1000", "Merkez")
    assert (warehouse.code, warehouse.name, warehouse.plant_id) == ("1000", "Ana Depo", plant.id)


def test_payment_terms_and_periods(db: Session, company: Company) -> None:
    terms = {
        t.code: t.days for t in db.scalars(select(PaymentTerm).where(PaymentTerm.company_id == company.id))
    }
    periods = db.scalars(
        select(Period).where(Period.company_id == company.id).order_by(Period.year, Period.period)
    ).all()
    year = date.today().year

    assert terms == {"PESIN": 0, "V30": 30, "V45": 45, "V60": 60, "V90": 90}
    assert [(p.year, p.period) for p in periods] == [(y, m) for y in (year, year + 1) for m in range(1, 13)]
    assert all(p.status is PeriodStatus.OPEN for p in periods)
    assert (periods[0].start_date, periods[0].end_date) == (date(year, 1, 1), date(year, 1, 31))
    assert periods[11].end_date == date(year, 12, 31)
    for earlier, later in zip(periods, periods[1:], strict=False):
        assert (later.start_date - earlier.end_date).days == 1


def test_february_follows_the_calendar(db: Session) -> None:
    company = factories.make_company(db)

    seed_company(db, code=company.code, name=company.name, today=date(2028, 6, 1))

    february = db.scalars(
        select(Period).where(Period.company_id == company.id, Period.year == 2028, Period.period == 2)
    ).one()
    assert february.end_date == date(2028, 2, 29)


# --- company seed: chart of accounts -------------------------------------------------------------


def test_tdhp_data_file_structure() -> None:
    classes = load_tdhp()

    assert [(c.code, c.name) for c in classes] == [
        ("1", "DÖNEN VARLIKLAR"),
        ("2", "DURAN VARLIKLAR"),
        ("3", "KISA VADELİ YABANCI KAYNAKLAR"),
        ("4", "UZUN VADELİ YABANCI KAYNAKLAR"),
        ("5", "ÖZKAYNAKLAR"),
        ("6", "GELİR TABLOSU HESAPLARI"),
        ("7", "MALİYET HESAPLARI"),
        ("9", "NAZIM HESAPLAR"),
    ]
    groups = {group.code: group.name for chart_class in classes for group in chart_class.groups}
    assert groups["10"] == "Hazır Değerler"
    assert groups["15"] == "Stoklar"
    assert groups["32"] == "Ticari Borçlar"
    assert groups["50"] == "Ödenmiş Sermaye"
    assert groups["60"] == "Brüt Satışlar"
    assert groups["62"] == "Satışların Maliyeti (-)"
    assert groups["79"] == "Gider Çeşitleri"
    codes = [account.code for account in main_accounts()]
    assert len(codes) == len(set(codes))
    assert codes == sorted(codes)
    for chart_class in classes:
        for group in chart_class.groups:
            assert group.code.startswith(chart_class.code)
            assert group.accounts
            assert all(len(a.code) == 3 and a.code.startswith(group.code) for a in group.accounts)


@pytest.mark.parametrize(
    ("code", "name", "account_type", "side"),
    [
        ("100", "Kasa", AccountType.ASSET, D),
        ("102", "Bankalar", AccountType.ASSET, D),
        ("103", "Verilen Çekler ve Ödeme Emirleri (-)", AccountType.ASSET, C),
        ("120", "Alıcılar", AccountType.ASSET, D),
        ("122", "Alacak Senetleri Reeskontu (-)", AccountType.ASSET, C),
        ("129", "Şüpheli Ticari Alacaklar Karşılığı (-)", AccountType.ASSET, C),
        ("150", "İlk Madde ve Malzeme", AccountType.ASSET, D),
        ("153", "Ticari Mallar", AccountType.ASSET, D),
        ("158", "Stok Değer Düşüklüğü Karşılığı (-)", AccountType.ASSET, C),
        ("191", "İndirilecek KDV", AccountType.ASSET, D),
        ("253", "Tesis, Makine ve Cihazlar", AccountType.ASSET, D),
        ("257", "Birikmiş Amortismanlar (-)", AccountType.ASSET, C),
        ("268", "Birikmiş Amortismanlar (-)", AccountType.ASSET, C),
        ("300", "Banka Kredileri", AccountType.LIABILITY, C),
        ("320", "Satıcılar", AccountType.LIABILITY, C),
        ("322", "Borç Senetleri Reeskontu (-)", AccountType.LIABILITY, D),
        ("360", "Ödenecek Vergi ve Fonlar", AccountType.LIABILITY, C),
        ("391", "Hesaplanan KDV", AccountType.LIABILITY, C),
        ("400", "Banka Kredileri", AccountType.LIABILITY, C),
        ("500", "Sermaye", AccountType.EQUITY, C),
        ("501", "Ödenmemiş Sermaye (-)", AccountType.EQUITY, D),
        ("570", "Geçmiş Yıllar Kârları", AccountType.EQUITY, C),
        ("580", "Geçmiş Yıllar Zararları (-)", AccountType.EQUITY, D),
        ("590", "Dönem Net Kârı", AccountType.EQUITY, C),
        ("591", "Dönem Net Zararı (-)", AccountType.EQUITY, D),
        ("600", "Yurtiçi Satışlar", AccountType.REVENUE, C),
        ("610", "Satıştan İadeler (-)", AccountType.REVENUE, D),
        ("611", "Satış İskontoları (-)", AccountType.REVENUE, D),
        ("612", "Diğer İndirimler (-)", AccountType.REVENUE, D),
        ("620", "Satılan Mamuller Maliyeti (-)", AccountType.EXPENSE, D),
        ("621", "Satılan Ticari Mallar Maliyeti (-)", AccountType.EXPENSE, D),
        ("622", "Satılan Hizmet Maliyeti (-)", AccountType.EXPENSE, D),
        ("623", "Diğer Satışların Maliyeti (-)", AccountType.EXPENSE, D),
        ("632", "Genel Yönetim Giderleri (-)", AccountType.EXPENSE, D),
        ("646", "Kambiyo Kârları", AccountType.REVENUE, C),
        ("656", "Kambiyo Zararları (-)", AccountType.EXPENSE, D),
        ("660", "Kısa Vadeli Borçlanma Giderleri (-)", AccountType.EXPENSE, D),
        ("679", "Diğer Olağandışı Gelir ve Kârlar", AccountType.REVENUE, C),
        ("689", "Diğer Olağandışı Gider ve Zararlar (-)", AccountType.EXPENSE, D),
        ("690", "Dönem Kârı veya Zararı", AccountType.TECHNICAL, C),
        ("692", "Dönem Net Kârı veya Zararı", AccountType.TECHNICAL, C),
        ("710", "Direkt İlk Madde ve Malzeme Giderleri", AccountType.COST, D),
        ("711", "Direkt İlk Madde ve Malzeme Yansıtma Hesabı", AccountType.COST, C),
        ("730", "Genel Üretim Giderleri", AccountType.COST, D),
        ("770", "Genel Yönetim Giderleri", AccountType.COST, D),
        ("771", "Genel Yönetim Giderleri Yansıtma Hesabı", AccountType.COST, C),
        ("780", "Finansman Giderleri", AccountType.COST, D),
        ("900", "Teminat Mektuplarından Borçlular", AccountType.OFFBALANCE, D),
        ("901", "Teminat Mektuplarından Alacaklılar", AccountType.OFFBALANCE, C),
    ],
)
def test_representative_main_accounts(
    db: Session, company: Company, code: str, name: str, account_type: AccountType, side: Side
) -> None:
    account = factories.gl_account(db, code, company)

    assert (account.name, account.account_type, account.normal_side) == (name, account_type, side)
    assert (account.level, account.parent_id) == (1, None)


def test_every_main_account_of_the_data_file_is_seeded(db: Session, company: Company) -> None:
    accounts = _accounts(db, company)
    chart = main_accounts()

    assert len(chart) > 270
    for entry in chart:
        account = accounts[entry.code]
        assert (account.name, account.account_type, account.normal_side) == (
            entry.name,
            entry.account_type,
            entry.normal_side,
        ), entry.code
    assert {code[0] for code in accounts} == {"0", "1", "2", "3", "4", "5", "6", "7", "9"}


def test_contra_accounts_carry_the_opposite_side_of_their_class(db: Session, company: Company) -> None:
    class_side = {"1": D, "2": D, "3": C, "4": C, "5": C, "6": C}
    contra = [a for a in _accounts(db, company).values() if a.level == 1 and a.name.endswith("(-)")]

    assert len(contra) > 50
    for account in contra:
        assert account.normal_side is not class_side[account.code[0]], account.code


def test_sub_accounts_hang_under_their_main_account(db: Session, company: Company) -> None:
    accounts = _accounts(db, company)
    by_id = {account.id: account for account in accounts.values()}
    subs = [account for account in accounts.values() if "." in account.code]

    assert {s["code"] for s in load_json("company.json")["sub_accounts"]} == {
        account.code for account in subs
    }
    for account in subs:
        parent = by_id[account.parent_id]
        assert parent.code == account.code.split(".")[0], account.code
        assert (account.level, account.is_postable) == (2, True), account.code
        assert (account.account_type, account.normal_side) == (parent.account_type, parent.normal_side)
        assert parent.is_postable is False, parent.code
    with_children = {by_id[account.parent_id].code for account in subs}
    for account in accounts.values():
        if account.level == 1 and account.code not in with_children:
            assert account.is_postable, account.code


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("000.01", "Açılış Devir Ara Hesabı"),
        ("100.01", "Merkez Kasa"),
        ("102.01", "Banka (örnek)"),
        ("150.01", "Hammaddeler"),
        ("151.01", "Yarı Mamuller"),
        ("152.01", "Mamuller"),
        ("153.01", "Ticari Mallar"),
        ("157.01", "Diğer Stoklar"),
        ("191.01", "İndirilecek KDV %1"),
        ("191.10", "İndirilecek KDV %10"),
        ("191.20", "İndirilecek KDV %20"),
        ("197.01", "Sayım ve Tesellüm Noksanları"),
        ("329.90", "Mal Girişi / Fatura Ara Hesabı"),
        ("391.01", "Hesaplanan KDV %1"),
        ("391.10", "Hesaplanan KDV %10"),
        ("391.20", "Hesaplanan KDV %20"),
        ("397.01", "Sayım ve Tesellüm Fazlaları"),
        ("600.01", "Yurtiçi Satışlar"),
        ("621.90", "Satınalma Fiyat Farkları"),
        ("646.01", "Kambiyo Kârları"),
        ("649.01", "Diğer Olağan Gelir ve Kârlar"),
        ("656.01", "Kambiyo Zararları"),
        ("689.01", "Diğer Olağandışı Gider ve Zararlar"),
        ("710.01", "Direkt İlk Madde ve Malzeme Giderleri"),
    ],
)
def test_documented_sub_accounts(db: Session, company: Company, code: str, name: str) -> None:
    account = factories.gl_account(db, code, company)

    assert account.name == name
    assert (account.recon_type, account.requires_cost_center) == (ReconType.NONE, False)


def test_reconciliation_and_cost_center_flags(db: Session, company: Company) -> None:
    accounts = _accounts(db, company)

    assert {c: accounts[c].recon_type for c in ("120.01", "120.02", "320.01", "320.02")} == {
        "120.01": ReconType.CUSTOMER,
        "120.02": ReconType.CUSTOMER,
        "320.01": ReconType.VENDOR,
        "320.02": ReconType.VENDOR,
    }
    assert accounts["120.01"].name == "Yurtiçi Alıcılar"
    assert accounts["320.02"].name == "Yurtdışı Satıcılar"
    requiring = {account.code for account in accounts.values() if account.requires_cost_center}
    assert requiring == {"730.01", "740.01", "750.01", "760.01", "770.01", "780.01"}
    assert {a.code for a in accounts.values() if a.recon_type is not ReconType.NONE} == {
        "120.01",
        "120.02",
        "320.01",
        "320.02",
    }
    opening = accounts["000.01"]
    assert (opening.account_type, opening.is_postable) == (AccountType.TECHNICAL, True)


# --- company seed: accounting defaults -------------------------------------------------------------


def test_tax_codes_point_to_postable_vat_accounts(db: Session, company: Company) -> None:
    codes = {t.code: t for t in db.scalars(select(TaxCode).where(TaxCode.company_id == company.id))}

    assert {code: (tax.tax_type, int(tax.rate), tax.gl_account.code) for code, tax in codes.items()} == {
        "IND0": (TaxType.INPUT, 0, "191.01"),
        "IND1": (TaxType.INPUT, 1, "191.01"),
        "IND10": (TaxType.INPUT, 10, "191.10"),
        "IND20": (TaxType.INPUT, 20, "191.20"),
        "HES0": (TaxType.OUTPUT, 0, "391.01"),
        "HES1": (TaxType.OUTPUT, 1, "391.01"),
        "HES10": (TaxType.OUTPUT, 10, "391.10"),
        "HES20": (TaxType.OUTPUT, 20, "391.20"),
    }
    for tax in codes.values():
        assert tax.is_active
        assert tax.gl_account.is_postable and not tax.gl_account.is_blocked
        assert tax.gl_account.company_id == company.id


def test_account_determination_defaults(db: Session, company: Company) -> None:
    classes = {
        v.id: v.code
        for v in db.scalars(select(ValuationClass).where(ValuationClass.company_id == company.id))
    }
    rules = db.scalars(
        select(AccountDetermination).where(AccountDetermination.company_id == company.id)
    ).all()
    resolved = {
        (rule.key, classes.get(rule.valuation_class_id), rule.modifier): rule.gl_account.code
        for rule in rules
    }

    assert set(classes.values()) == {"HAMMADDE", "YARI_MAMUL", "MAMUL", "TICARI_MAL", "DIGER_STOK"}
    assert resolved == {
        (AccountKey.STOCK, "HAMMADDE", None): "150.01",
        (AccountKey.STOCK, "YARI_MAMUL", None): "151.01",
        (AccountKey.STOCK, "MAMUL", None): "152.01",
        (AccountKey.STOCK, "TICARI_MAL", None): "153.01",
        (AccountKey.STOCK, "DIGER_STOK", None): "157.01",
        (AccountKey.GR_IR, None, None): "329.90",
        (AccountKey.PRICE_DIFF, None, None): "621.90",
        (AccountKey.CONSUMPTION, None, "URETIM"): "730.01",
        (AccountKey.CONSUMPTION, None, "HIZMET"): "740.01",
        (AccountKey.CONSUMPTION, None, "ARGE"): "750.01",
        (AccountKey.CONSUMPTION, None, "PAZARLAMA"): "760.01",
        (AccountKey.CONSUMPTION, None, "YONETIM"): "770.01",
        (AccountKey.CONSUMPTION, None, "FINANSMAN"): "780.01",
        (AccountKey.SCRAP, None, None): "689.01",
        (AccountKey.INVENTORY_GAIN, None, None): "397.01",
        (AccountKey.INVENTORY_LOSS, None, None): "197.01",
        (AccountKey.INITIAL_STOCK, None, None): "000.01",
        (AccountKey.RECEIPT_OTHER, None, None): "649.01",
    }
    assert {key for key, _, _ in resolved} == set(AccountKey)
    assert {modifier for _, _, modifier in resolved if modifier} == {f.value for f in CostCenterFunction}
    for rule in rules:
        assert rule.gl_account.is_postable and rule.gl_account.company_id == company.id


def test_reflection_rules(db: Session, company: Company) -> None:
    rules = db.scalars(select(ReflectionRule).where(ReflectionRule.company_id == company.id)).all()

    assert {
        rule.expense_prefix: (rule.reflection_account.code, rule.target_account.code) for rule in rules
    } == {
        "740": ("741", "622"),
        "750": ("751", "630"),
        "760": ("761", "631"),
        "770": ("771", "632"),
        "780": ("781", "660"),
    }
    for rule in rules:
        assert rule.reflection_account.is_postable and rule.target_account.is_postable
        assert rule.reflection_account.normal_side is C
        assert rule.target_account.normal_side is D


def test_registered_settings_are_materialised_with_their_defaults(db: Session) -> None:
    register_setting("test.seed.flag", {"enabled": True, "limit": 5}, "Tohum verisi deneme ayarı")
    company = factories.make_company(db)

    seed_company(db, code=company.code, name=company.name)

    stored = db.scalars(
        select(CompanySetting).where(
            CompanySetting.company_id == company.id, CompanySetting.key == "test.seed.flag"
        )
    ).one()
    assert stored.value == {"enabled": True, "limit": 5}


# --- idempotency and isolation ---------------------------------------------------------------------


def test_running_both_seeds_again_changes_nothing(db: Session, app: FastAPI, company: Company) -> None:
    # Settings registered by other tests since the session seed are materialised by this first re-run.
    seed_company(db, code="1000", name="Örnek Sanayi A.Ş.")
    before = _table_counts(db)
    account = factories.gl_account(db, "770.01", company)
    account.name = "Muhasebecinin Verdiği Ad"
    account.requires_cost_center = False
    db.flush()

    seed_base(db, app.state.permissions, admin_password=ADMIN_PASSWORD)
    seed_company(db, code="1000", name="Başka Bir Ad")
    db.flush()
    db.expire_all()

    assert _table_counts(db) == before
    account = factories.gl_account(db, "770.01", company)
    assert (account.name, account.requires_cost_center) == ("Muhasebecinin Verdiği Ad", False)
    assert db.get_one(Company, company.id).name == "Örnek Sanayi A.Ş."


def test_second_company_gets_its_own_complete_chart(db: Session, company: Company) -> None:
    second = seed_company(db, code="2000", name="İkinci Örnek Ticaret Ltd. Şti.")

    first_accounts, second_accounts = _accounts(db, company), _accounts(db, second)
    assert second.id != company.id
    assert set(second_accounts) == set(first_accounts)
    assert not {a.id for a in first_accounts.values()} & {a.id for a in second_accounts.values()}
    assert second_accounts["320.01"].parent_id == second_accounts["320"].id
    tax_accounts = db.scalars(
        select(GLAccount.company_id)
        .join(TaxCode, TaxCode.gl_account_id == GLAccount.id)
        .where(TaxCode.company_id == second.id)
    ).all()
    assert set(tax_accounts) == {second.id}
    assert db.scalar(select(func.count()).select_from(Period).where(Period.company_id == second.id)) == 24


def test_company_seed_requires_the_base_seed(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    # The local currency is seeded by the base seed; simulate a database where it is missing.
    monkeypatch.setattr(company_seed, "LOCAL_CURRENCY", "XXX")

    with pytest.raises(RuntimeError, match="python -m app.seed base"):
        seed_company(db, code="9000", name="Temel Verisi Olmayan Şirket")

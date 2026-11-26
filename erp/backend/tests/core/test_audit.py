"""Audit trail: automatic rows for `__audit__` models and explicit entries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import RequestContext
from app.modules.auth.models import User
from app.modules.fi.models.partners import PaymentTerm
from app.modules.org.models import AuditLog, Company, Currency, ExchangeRate, RateType, Uom
from tests import factories


def _entries(db: Session, entity: str, entity_id: int | None = None) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.entity == entity).order_by(AuditLog.id)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(db.scalars(stmt))


def test_insert_writes_a_snapshot_of_the_new_row(ctx: RequestContext, db: Session) -> None:
    term = PaymentTerm(company_id=ctx.company_id, code="V15", name="15 Gün Vadeli", days=15)
    db.add(term)
    db.flush()

    [entry] = _entries(db, "fi_payment_term", term.id)
    assert entry.action == "INSERT"
    assert entry.user_id == ctx.user.id
    assert entry.company_id == ctx.company_id
    assert entry.at is not None
    assert entry.changes == {
        "company_id": {"new": ctx.company_id},
        "code": {"new": "V15"},
        "name": {"new": "15 Gün Vadeli"},
        "days": {"new": 15},
    }


def test_update_records_only_the_changed_columns_with_old_and_new(ctx: RequestContext, db: Session) -> None:
    rate = ExchangeRate(currency_code="USD", rate_date=date(2026, 3, 1), rate=Decimal("41.250000"))
    db.add(rate)
    db.flush()

    rate.rate = Decimal("41.75")
    rate.rate_type = RateType.SATIS
    rate.rate_date = date(2026, 3, 2)
    db.flush()

    insert_entry, update_entry = _entries(db, "org_exchange_rate", rate.id)
    assert insert_entry.action == "INSERT"
    assert insert_entry.company_id is None  # exchange rates are not company data
    assert insert_entry.changes["rate"] == {"new": "41.250000"}
    assert insert_entry.changes["rate_type"] == {"new": "ALIS"}
    assert update_entry.action == "UPDATE"
    assert update_entry.changes == {
        "rate": {"old": "41.250000", "new": "41.75"},
        "rate_type": {"old": "ALIS", "new": "SATIS"},
        "rate_date": {"old": "2026-03-01", "new": "2026-03-02"},
    }


def test_update_without_a_real_change_writes_nothing(ctx: RequestContext, db: Session) -> None:
    uom = Uom(code="RULO", name="Rulo", decimals=0)
    db.add(uom)
    db.flush()

    uom.name = "Rulo"
    uom.decimals = 0
    db.flush()

    assert [entry.action for entry in _entries(db, "org_uom", uom.id)] == ["INSERT"]


def test_delete_records_the_old_values(ctx: RequestContext, db: Session) -> None:
    uom = Uom(code="TOP", name="Top", decimals=0, unece_code="RO")
    db.add(uom)
    db.flush()
    uom_id = uom.id

    db.delete(uom)
    db.flush()

    delete_entry = _entries(db, "org_uom", uom_id)[-1]
    assert delete_entry.action == "DELETE"
    assert delete_entry.changes == {
        "code": {"old": "TOP"},
        "name": {"old": "Top"},
        "decimals": {"old": 0},
        "unece_code": {"old": "RO"},
        "is_active": {"old": True},
    }


def test_orphaned_and_cascaded_rows_are_logged_as_deleted(ctx: RequestContext, db: Session) -> None:
    orphaned_from = factories.make_user(db, roles=["depo"])
    cascaded_from = factories.make_user(db, roles=["depo", "izleyici"])
    orphan_id = orphaned_from.roles[0].id
    cascaded_ids = {link.id for link in cascaded_from.roles}

    orphaned_from.roles.clear()
    db.delete(cascaded_from)
    db.flush()

    deleted = {
        entry.entity_id: entry.changes for entry in _entries(db, "auth_user_role") if entry.action == "DELETE"
    }
    assert deleted.keys() == {orphan_id} | cascaded_ids
    assert deleted[orphan_id]["user_id"] == {"old": orphaned_from.id}
    assert _entries(db, "auth_user", cascaded_from.id)[-1].action == "DELETE"


def test_secret_columns_are_masked_and_binary_columns_summarised(ctx: RequestContext, db: Session) -> None:
    user = factories.make_user(db)
    user.password_hash = "another-hash"
    company = factories.make_company(db)
    company.logo = b"\x89PNG binary data"
    db.flush()

    user_insert, user_update = _entries(db, "auth_user", user.id)
    assert user_insert.changes["password_hash"] == {"new": "***"}
    assert user_update.changes == {"password_hash": {"old": "***", "new": "***"}}
    company_update = _entries(db, "org_company", company.id)[-1]
    assert company_update.changes == {"logo": {"old": None, "new": "<binary>"}}
    logged = str(user_insert.changes) + str(user_update.changes)
    assert "argon2" not in logged
    assert "another-hash" not in logged


def test_bookkeeping_columns_and_unflagged_models_are_not_audited(ctx: RequestContext, db: Session) -> None:
    db.add(Currency(code="CHF", name="İsviçre Frangı", symbol="CHF"))
    uom = Uom(code="DUZINE", name="Düzine")
    db.add(uom)
    db.flush()

    assert _entries(db, "org_currency") == []
    [entry] = _entries(db, "org_uom", uom.id)
    assert (
        not {"id", "created_at", "updated_at", "created_by_id", "updated_by_id", "version"}
        & entry.changes.keys()
    )


def test_failed_flush_does_not_leave_duplicate_entries(ctx: RequestContext, db: Session) -> None:
    duplicate = Uom(code="ADET", name="Kopya")
    try:
        with db.begin_nested():
            db.add(duplicate)
            db.flush()
    except IntegrityError:
        pass
    uom = Uom(code="BIDON", name="Bidon")
    db.add(uom)
    db.flush()

    assert [entry.action for entry in _entries(db, "org_uom", uom.id)] == ["INSERT"]
    assert all(entry.changes.get("name") != {"new": "Kopya"} for entry in _entries(db, "org_uom"))


def test_explicit_log_entry(ctx: RequestContext, db: Session) -> None:
    entry = audit.log(ctx, "APPROVE", "mm_purchase_order", 42, "Sipariş onaylandı")
    db.flush()

    stored = db.get_one(AuditLog, entry.id)
    assert (stored.action, stored.entity, stored.entity_id, stored.summary) == (
        "APPROVE",
        "mm_purchase_order",
        42,
        "Sipariş onaylandı",
    )
    assert (stored.user_id, stored.company_id, stored.changes) == (ctx.user.id, ctx.company_id, None)


def test_requests_are_audited_with_the_acting_user(client: TestClient, db: Session, admin: User) -> None:
    response = client.post(
        "/api/users",
        json={"username": "denetim.izi", "full_name": "Denetim İzi", "password": "Parola-Test-1"},
    )
    assert response.status_code == 201

    [entry] = _entries(db, "auth_user", response.json()["id"])
    assert (entry.action, entry.user_id) == ("INSERT", admin.id)
    assert entry.changes["username"] == {"new": "denetim.izi"}
    created = db.get_one(User, response.json()["id"])
    assert (created.created_by_id, created.updated_by_id) == (admin.id, admin.id)


def test_company_rows_are_not_tied_to_a_company_scope(ctx: RequestContext, db: Session) -> None:
    company = factories.make_company(db)

    [entry] = _entries(db, Company.__tablename__, company.id)
    assert entry.company_id is None

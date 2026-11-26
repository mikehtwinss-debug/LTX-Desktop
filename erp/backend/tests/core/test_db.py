"""Mixins: optimistic locking, timestamps and user stamps."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.core.context import Db, RequestContext
from app.core.db import assert_version
from app.core.errors import Conflict, register_exception_handlers
from app.core.routing import make_router
from app.modules.auth.models import User
from app.modules.co.models import CostCenter
from app.modules.org.models import Currency
from tests import factories


def test_version_starts_at_one_and_increments_on_every_update(ctx: RequestContext, db: Session) -> None:
    cost_center = factories.make_cost_center(db)
    assert cost_center.version == 1

    cost_center.name = "Genel Müdürlük"
    db.flush()
    cost_center.name = "Genel Müdürlük Ofisi"
    db.flush()

    assert cost_center.version == 3


def test_assert_version_rejects_an_outdated_payload(ctx: RequestContext, db: Session) -> None:
    cost_center = factories.make_cost_center(db)
    cost_center.name = "Yeni Ad"
    db.flush()

    assert_version(cost_center, 2)
    with pytest.raises(Conflict) as error:
        assert_version(cost_center, 1)

    assert error.value.code == "STALE_DATA"
    assert error.value.status == 409
    assert error.value.details == {"current_version": 2}


def test_stale_update_payload_returns_409(client: TestClient, db: Session) -> None:
    user = factories.make_user(db, full_name="İlk Ad")
    payload = {"full_name": "Yeni Ad", "email": None, "is_active": True, "is_superuser": False}

    first = client.put(f"/api/users/{user.id}", json={**payload, "version": 1})
    stale = client.put(f"/api/users/{user.id}", json={**payload, "full_name": "Eski Form", "version": 1})

    assert first.status_code == 200
    assert first.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_DATA"
    assert stale.json()["details"] == {"current_version": 2}
    db.expire_all()
    assert db.get_one(User, user.id).full_name == "Yeni Ad"


def test_orm_detects_a_row_changed_behind_its_back(ctx: RequestContext, db: Session) -> None:
    cost_center = factories.make_cost_center(db)
    db.execute(
        update(CostCenter)
        .where(CostCenter.id == cost_center.id)
        .values(version=CostCenter.version + 1)
        .execution_options(synchronize_session=False)
    )

    cost_center.name = "Çakışan Değişiklik"
    with pytest.raises(StaleDataError):
        db.flush()


@pytest.fixture
def racing_client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """An endpoint that loses an update race: the row changes between its read and its write."""
    router = make_router("/race", ["probe"])

    @router.put("/cost-centers/{cost_center_id}")
    def rename(cost_center_id: int, db: Db) -> dict[str, bool]:
        cost_center = db.get_one(CostCenter, cost_center_id)
        db.execute(
            update(CostCenter)
            .where(CostCenter.id == cost_center_id)
            .values(version=CostCenter.version + 1)
            .execution_options(synchronize_session=False)
        )
        cost_center.name = "Yarışı Kaybeden"
        return {"ok": True}

    application = FastAPI()
    application.state.session_factory = session_factory
    register_exception_handlers(application)
    application.include_router(router)
    yield TestClient(application, raise_server_exceptions=False)


def test_concurrent_update_detected_at_commit_returns_409(racing_client: TestClient, db: Session) -> None:
    cost_center = factories.make_cost_center(db, name="Özgün Ad")

    response = racing_client.put(f"/race/cost-centers/{cost_center.id}")

    assert response.status_code == 409
    assert response.json()["code"] == "STALE_DATA"
    db.expire_all()
    assert db.get_one(CostCenter, cost_center.id).name == "Özgün Ad"


def test_user_stamps_come_from_the_session(ctx: RequestContext, db: Session) -> None:
    other = factories.make_user(db)
    cost_center = factories.make_cost_center(db)
    assert (cost_center.created_by_id, cost_center.updated_by_id) == (ctx.user.id, ctx.user.id)
    created_at, first_update = cost_center.created_at, cost_center.updated_at

    db.info["user_id"] = other.id
    cost_center.name = "Başka Kullanıcı Değiştirdi"
    db.flush()

    assert (cost_center.created_by_id, cost_center.updated_by_id) == (ctx.user.id, other.id)
    assert cost_center.created_at == created_at
    assert cost_center.updated_at > first_update
    assert cost_center.created_at.tzinfo is not None


def test_rows_written_without_a_user_have_no_stamp(db: Session) -> None:
    currency = Currency(code="JPY", name="Japon Yeni", symbol="¥")
    db.add(currency)
    db.flush()

    assert (currency.created_by_id, currency.updated_by_id) == (None, None)
    assert db.scalar(select(Currency.created_at).where(Currency.code == "JPY")) is not None

"""Permission checks, company isolation and company-scoped roles."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.context import COMPANY_HEADER, Ctx, require
from app.core.errors import register_exception_handlers
from app.core.routing import make_router
from app.modules.auth.models import User
from app.modules.org.models import Company
from tests import factories


@pytest.fixture
def scoped_app(app: FastAPI, session_factory: sessionmaker[Session]) -> Iterator[FastAPI]:
    """A small application with company-scoped endpoints, as feature modules will define them."""
    router = make_router("/scoped", ["probe"])

    @router.get("/context")
    def context(ctx: Ctx) -> dict[str, object]:
        return {
            "user_id": ctx.user.id,
            "company_id": ctx.company_id,
            "session_user_id": ctx.db.info["user_id"],
            "session_company_id": ctx.db.info["company_id"],
        }

    @router.get("/guarded", dependencies=[require("auth.user.manage")])
    def guarded(ctx: Ctx) -> dict[str, int]:
        return {"company_id": ctx.company_id}

    @router.get("/unknown-permission", dependencies=[require("no.such.permission")])
    def unknown_permission() -> dict[str, bool]:
        return {"ok": True}

    application = FastAPI()
    application.state.session_factory = session_factory
    register_exception_handlers(application)
    application.include_router(router)
    yield application


@pytest.fixture
def scoped_client_for(
    scoped_app: FastAPI, client_for: Callable[..., TestClient]
) -> Callable[..., TestClient]:
    def build(user: User, active_company: Company | None = None) -> TestClient:
        headers = dict(client_for(user, active_company).headers)
        return TestClient(scoped_app, headers=headers)

    return build


def test_read_only_role_may_view_but_not_change(client_as: Callable[[str], TestClient]) -> None:
    viewer = client_as("izleyici")

    assert viewer.get("/api/users").status_code == 200
    assert viewer.get("/api/roles").status_code == 200
    assert viewer.get("/api/permissions").status_code == 200
    denied = viewer.post(
        "/api/users", json={"username": "yeni.kisi", "full_name": "Yeni", "password": "12345678"}
    )
    assert denied.status_code == 403
    assert denied.json() == {
        "code": "PERMISSION_DENIED",
        "message": "Bu işlem için yetkiniz yok",
        "details": {"permission": "auth.user.manage"},
    }
    assert viewer.delete("/api/roles/1").json()["details"] == {"permission": "auth.role.manage"}


def test_role_without_the_permission_is_denied(client_as: Callable[[str], TestClient]) -> None:
    warehouse = client_as("depo")

    for path in ("/api/users", "/api/roles", "/api/permissions"):
        response = warehouse.get(path)
        assert (response.status_code, response.json()["code"]) == (403, "PERMISSION_DENIED"), path
    assert warehouse.get("/api/auth/me").status_code == 200


def test_user_without_any_role_is_denied(client_for: Callable[..., TestClient], db: Session) -> None:
    user = factories.make_user(db)

    response = client_for(user, None).get("/api/users")

    assert (response.status_code, response.json()["code"]) == (403, "PERMISSION_DENIED")


def test_superuser_passes_every_check(scoped_client_for: Callable[..., TestClient], admin: User) -> None:
    assert scoped_client_for(admin).get("/scoped/unknown-permission").status_code == 200


def test_company_isolation(client_for: Callable[..., TestClient], db: Session, company: Company) -> None:
    other_company = factories.make_company(db)
    user = factories.make_user(db, roles=["izleyici"], company=company)

    own = client_for(user, company).get("/api/users")
    foreign = client_for(user, other_company).get("/api/users")
    foreign_me = client_for(user, other_company).get("/api/auth/me")
    me = client_for(user, company).get("/api/auth/me")

    assert own.status_code == 200
    assert foreign.status_code == 403
    assert foreign.json() == {
        "code": "COMPANY_ACCESS_DENIED",
        "message": "Bu şirkette işlem yapma yetkiniz yok",
        "details": {},
    }
    assert foreign_me.json()["code"] == "COMPANY_ACCESS_DENIED"
    assert me.json()["companies"] == [{"id": company.id, "code": "1000", "name": company.name}]


def test_company_header_must_name_an_existing_active_company(
    client_for: Callable[..., TestClient], app: FastAPI, db: Session, admin: User
) -> None:
    inactive = factories.make_company(db, is_active=False)
    token_headers = {"Authorization": client_for(admin).headers["Authorization"]}

    def call(company_header: str):
        response = TestClient(app, headers={**token_headers, COMPANY_HEADER: company_header}).get(
            "/api/users"
        )
        return response.status_code, response.json()["code"]

    assert call("abc") == (400, "INVALID_COMPANY")
    assert call("999999") == (403, "COMPANY_ACCESS_DENIED")
    assert call(str(inactive.id)) == (403, "COMPANY_ACCESS_DENIED")


def test_role_is_scoped_to_its_company(
    client_for: Callable[..., TestClient], db: Session, company: Company
) -> None:
    """Viewer in company 1000, warehouse clerk in a second company: the permissions follow the header."""
    second = factories.make_company(db)
    user = factories.make_user(db, roles=["izleyici"], company=company)
    factories.assign_role(db, user, "depo", second)

    in_first = client_for(user, company)
    in_second = client_for(user, second)

    assert in_first.get("/api/users").status_code == 200
    denied = in_second.get("/api/users")
    assert (denied.status_code, denied.json()["code"]) == (403, "PERMISSION_DENIED")
    assert in_first.get("/api/auth/me").json()["permissions"] == ["auth.role.view", "auth.user.view"]
    second_me = in_second.get("/api/auth/me").json()
    assert second_me["permissions"] == []
    assert second_me["company_id"] == second.id
    assert {item["code"] for item in second_me["companies"]} == {"1000", second.code}


def test_global_role_applies_in_every_company(client_for: Callable[..., TestClient], db: Session) -> None:
    second = factories.make_company(db)
    user = factories.make_user(db)
    factories.assign_role(db, user, "izleyici", None)

    assert client_for(user, second).get("/api/users").status_code == 200
    me = client_for(user, second).get("/api/auth/me").json()
    assert {item["code"] for item in me["companies"]} >= {"1000", second.code}
    assert me["permissions"] == ["auth.role.view", "auth.user.view"]


def test_active_company_falls_back_to_the_default_then_the_first_accessible(
    client_for: Callable[..., TestClient], db: Session, company: Company
) -> None:
    second = factories.make_company(db, code="2000")
    unrelated = factories.make_company(db, code="3000")
    user = factories.make_user(db, roles=["izleyici"], company=second)
    factories.assign_role(db, user, "izleyici", company)
    user.default_company_id = second.id
    db.flush()

    assert client_for(user, None).get("/api/auth/me").json()["company_id"] == second.id

    user.default_company_id = unrelated.id  # a default the user has no role in is ignored
    db.flush()
    assert client_for(user, None).get("/api/auth/me").json()["company_id"] == company.id


def test_context_carries_user_and_company(
    scoped_client_for: Callable[..., TestClient], db: Session, company: Company
) -> None:
    user = factories.make_user(db, roles=["depo"], company=company)

    response = scoped_client_for(user, company).get("/scoped/context")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": user.id,
        "company_id": company.id,
        "session_user_id": user.id,
        "session_company_id": company.id,
    }


def test_company_scoped_endpoint_needs_a_company(
    scoped_client_for: Callable[..., TestClient], db: Session
) -> None:
    user = factories.make_user(db)

    me = scoped_client_for(user).get("/scoped/context")

    assert me.status_code == 403
    assert me.json()["code"] == "COMPANY_REQUIRED"


def test_user_without_a_company_still_sees_the_own_profile(
    client_for: Callable[..., TestClient], db: Session
) -> None:
    user = factories.make_user(db)

    me = client_for(user, None).get("/api/auth/me")

    assert me.status_code == 200
    assert (me.json()["company_id"], me.json()["companies"], me.json()["permissions"]) == (None, [], [])


def test_guard_and_context_use_the_same_company(
    scoped_client_for: Callable[..., TestClient], db: Session, company: Company
) -> None:
    second = factories.make_company(db)
    user = factories.make_user(db, roles=["admin"], company=second)
    factories.assign_role(db, user, "izleyici", company)

    allowed = scoped_client_for(user, second).get("/scoped/guarded")
    denied = scoped_client_for(user, company).get("/scoped/guarded")

    assert allowed.status_code == 200
    assert allowed.json() == {"company_id": second.id}
    assert (denied.status_code, denied.json()["code"]) == (403, "PERMISSION_DENIED")

"""Changing the own password and the forced password change."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import security
from app.modules.auth.models import User
from tests import factories

OLD = factories.DEFAULT_PASSWORD
NEW = "Yeni-Parola-2"


def _change(client: TestClient, current: str, new: str):
    return client.post("/api/auth/change-password", json={"current_password": current, "new_password": new})


def test_change_password(
    client_for: Callable[..., TestClient], anonymous_client: TestClient, db: Session
) -> None:
    user = factories.make_user(db, username="parola.degisimi", roles=["izleyici"])

    response = _change(client_for(user), OLD, NEW)

    assert response.status_code == 204
    assert response.content == b""
    db.expire_all()
    stored = db.get_one(User, user.id)
    assert security.verify_password(NEW, stored.password_hash)
    assert not security.verify_password(OLD, stored.password_hash)
    login = "/api/auth/login"
    assert (
        anonymous_client.post(login, json={"username": "parola.degisimi", "password": OLD}).status_code == 401
    )
    assert (
        anonymous_client.post(login, json={"username": "parola.degisimi", "password": NEW}).status_code == 200
    )


def test_wrong_current_password_is_rejected(client_for: Callable[..., TestClient], db: Session) -> None:
    user = factories.make_user(db)

    response = _change(client_for(user), "yanlis-parola", NEW)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CURRENT_PASSWORD"
    assert response.json()["details"] == {"fields": {"current_password": "Mevcut parola hatalı"}}
    db.expire_all()
    assert security.verify_password(OLD, db.get_one(User, user.id).password_hash)


def test_password_policy_requires_eight_characters(
    client_for: Callable[..., TestClient], db: Session
) -> None:
    user = factories.make_user(db)
    user_client = client_for(user)

    too_short = _change(user_client, OLD, "1234567")
    just_enough = _change(user_client, OLD, "12345678")

    assert too_short.status_code == 422
    assert too_short.json()["code"] == "VALIDATION_ERROR"
    assert too_short.json()["details"] == {"fields": {"new_password": "En az 8 karakter olmalıdır"}}
    assert just_enough.status_code == 204


def test_new_password_must_differ(client_for: Callable[..., TestClient], db: Session) -> None:
    user = factories.make_user(db)

    response = _change(client_for(user), OLD, OLD)

    assert (response.status_code, response.json()["code"]) == (422, "PASSWORD_UNCHANGED")


def test_user_who_must_change_the_password_can_only_do_that(
    client_for: Callable[..., TestClient], db: Session
) -> None:
    user = factories.make_user(db, roles=["admin"], must_change_password=True)
    user_client = client_for(user)

    me = user_client.get("/api/auth/me")
    blocked = [
        user_client.get("/api/users"),
        user_client.get("/api/roles"),
        user_client.get("/api/permissions"),
        user_client.post("/api/users", json={"username": "x.y", "full_name": "X", "password": "12345678"}),
        user_client.get(f"/api/users/{user.id}"),
    ]

    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    for response in blocked:
        assert response.status_code == 403
        assert response.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    assert _change(user_client, OLD, NEW).status_code == 204
    assert user_client.get("/api/auth/me").json()["must_change_password"] is False
    assert user_client.get("/api/users").status_code == 200

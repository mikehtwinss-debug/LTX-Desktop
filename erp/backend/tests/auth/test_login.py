"""Login, lockout, tokens and the current-user endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.db import utcnow
from app.modules.auth.models import User
from app.modules.auth.service import LOCKOUT, MAX_FAILED_LOGINS
from app.modules.org.models import AuditLog, Company
from tests import factories
from tests.conftest import ADMIN_PASSWORD

PASSWORD = factories.DEFAULT_PASSWORD


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _reload(db: Session, user: User) -> User:
    db.expire_all()
    return db.get_one(User, user.id)


def test_login_returns_a_token_and_the_current_user(
    anonymous_client: TestClient, db: Session, company: Company
) -> None:
    user = factories.make_user(db, username="ayse.yilmaz", full_name="Ayşe Yılmaz", roles=["izleyici"])

    response = _login(anonymous_client, "ayse.yilmaz")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": user.id,
        "username": "ayse.yilmaz",
        "full_name": "Ayşe Yılmaz",
        "email": None,
        "is_superuser": False,
        "must_change_password": False,
        "default_company_id": company.id,
        "company_id": company.id,
        "companies": [{"id": company.id, "code": "1000", "name": "Örnek Sanayi A.Ş."}],
        "permissions": ["auth.role.view", "auth.user.view"],
    }
    me = anonymous_client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_token_lifetime_is_twelve_hours(anonymous_client: TestClient, db: Session) -> None:
    factories.make_user(db, username="sure.kontrol")

    token = _login(anonymous_client, "sure.kontrol").json()["access_token"]

    claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 12 * 60 * 60


def test_login_records_the_time_without_touching_the_version(
    anonymous_client: TestClient, db: Session
) -> None:
    user = factories.make_user(db, username="surum.kontrol")
    version, updated_at = user.version, user.updated_at

    assert _login(anonymous_client, "surum.kontrol").status_code == 200

    user = _reload(db, user)
    assert user.last_login_at is not None
    assert (user.version, user.updated_at) == (version, updated_at)
    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity == "auth_user", AuditLog.entity_id == user.id, AuditLog.action == "LOGIN"
        )
    ).one()
    assert entry.user_id == user.id


def test_username_is_matched_case_insensitively_and_trimmed(
    anonymous_client: TestClient, db: Session
) -> None:
    factories.make_user(db, username="mehmet.demir")

    assert _login(anonymous_client, "  Mehmet.Demir ").status_code == 200


@pytest.mark.parametrize("username", ["var.olan", "olmayan.kullanici"])
def test_wrong_credentials_are_rejected_without_revealing_the_account(
    anonymous_client: TestClient, db: Session, username: str
) -> None:
    factories.make_user(db, username="var.olan")

    response = _login(anonymous_client, username, "yanlis-parola")

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "Kullanıcı adı veya parola hatalı",
        "details": {},
    }


def test_failed_attempts_are_counted_even_though_the_request_fails(
    anonymous_client: TestClient, db: Session
) -> None:
    user = factories.make_user(db, username="sayac.kontrol")

    for _ in range(3):
        assert _login(anonymous_client, "sayac.kontrol", "yanlis").status_code == 401

    user = _reload(db, user)
    assert (user.failed_login_count, user.locked_until) == (3, None)


def test_account_locks_after_five_consecutive_failures(anonymous_client: TestClient, db: Session) -> None:
    user = factories.make_user(db, username="kilit.kontrol")

    statuses = [
        _login(anonymous_client, "kilit.kontrol", "yanlis").status_code for _ in range(MAX_FAILED_LOGINS)
    ]
    locked = _login(anonymous_client, "kilit.kontrol")

    assert statuses == [401, 401, 401, 401, 423]
    assert locked.status_code == 423
    body = locked.json()
    assert body["code"] == "ACCOUNT_LOCKED"
    user = _reload(db, user)
    assert body["details"] == {"locked_until": user.locked_until.isoformat()}
    remaining = user.locked_until - utcnow()
    assert LOCKOUT - timedelta(minutes=1) < remaining <= LOCKOUT
    assert LOCKOUT.total_seconds() == 15 * 60
    assert (
        db.scalar(
            select(AuditLog.summary).where(
                AuditLog.entity == "auth_user",
                AuditLog.entity_id == user.id,
                AuditLog.action == "ACCOUNT_LOCKED",
            )
        )
        is not None
    )


def test_lock_expires_and_the_counter_starts_over(anonymous_client: TestClient, db: Session) -> None:
    user = factories.make_user(db, username="kilit.suresi")
    for _ in range(MAX_FAILED_LOGINS):
        _login(anonymous_client, "kilit.suresi", "yanlis")
    user = _reload(db, user)
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.flush()

    wrong_again = _login(anonymous_client, "kilit.suresi", "yanlis")
    success = _login(anonymous_client, "kilit.suresi")

    assert wrong_again.status_code == 401  # a fresh first failure, not an immediate new lock
    assert success.status_code == 200
    user = _reload(db, user)
    assert (user.failed_login_count, user.locked_until) == (0, None)


def test_successful_login_resets_the_failure_counter(anonymous_client: TestClient, db: Session) -> None:
    factories.make_user(db, username="sifirlama.kontrol")

    for _ in range(MAX_FAILED_LOGINS - 1):
        _login(anonymous_client, "sifirlama.kontrol", "yanlis")
    assert _login(anonymous_client, "sifirlama.kontrol").status_code == 200
    statuses = [_login(anonymous_client, "sifirlama.kontrol", "yanlis").status_code for _ in range(4)]

    assert statuses == [401, 401, 401, 401]
    assert _login(anonymous_client, "sifirlama.kontrol").status_code == 200


def test_inactive_user_cannot_log_in(anonymous_client: TestClient, db: Session) -> None:
    factories.make_user(db, username="pasif.kullanici", is_active=False)

    response = _login(anonymous_client, "pasif.kullanici")

    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"


def test_login_payload_is_validated(anonymous_client: TestClient) -> None:
    response = anonymous_client.post("/api/auth/login", json={"username": "", "password": ""})

    assert response.status_code == 422
    assert set(response.json()["details"]["fields"]) == {"username", "password"}


def test_seeded_administrator_can_log_in(anonymous_client: TestClient) -> None:
    response = _login(anonymous_client, "admin", ADMIN_PASSWORD)

    assert response.status_code == 200
    assert response.json()["user"]["is_superuser"] is True
    assert response.json()["user"]["must_change_password"] is False


def test_requests_without_a_valid_token_are_rejected(anonymous_client: TestClient, db: Session) -> None:
    user = factories.make_user(db)
    settings = get_settings()
    expired = jwt.encode(
        {"sub": str(user.id), "exp": utcnow() - timedelta(minutes=1)}, settings.secret_key, algorithm="HS256"
    )
    forged = jwt.encode(
        {"sub": str(user.id), "exp": utcnow() + timedelta(hours=1)}, "x" * 40, algorithm="HS256"
    )
    no_subject = jwt.encode({"exp": utcnow() + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")

    def call(token: str | None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = anonymous_client.get("/api/auth/me", headers=headers)
        return response.status_code, response.json()["code"], response.headers.get("www-authenticate")

    assert call(None) == (401, "NOT_AUTHENTICATED", "Bearer")
    assert call("not-a-token") == (401, "INVALID_TOKEN", "Bearer")
    assert call(expired) == (401, "TOKEN_EXPIRED", "Bearer")
    assert call(forged) == (401, "INVALID_TOKEN", "Bearer")
    assert call(no_subject) == (401, "INVALID_TOKEN", "Bearer")
    assert call(security.create_access_token(999_999_999)) == (401, "INVALID_TOKEN", "Bearer")


def test_token_of_a_deactivated_user_stops_working(
    client_for: Callable[..., TestClient], db: Session
) -> None:
    user = factories.make_user(db, roles=["izleyici"])
    user_client = client_for(user)
    assert user_client.get("/api/auth/me").status_code == 200

    user.is_active = False
    db.flush()

    response = user_client.get("/api/auth/me")
    assert (response.status_code, response.json()["code"]) == (401, "INVALID_TOKEN")

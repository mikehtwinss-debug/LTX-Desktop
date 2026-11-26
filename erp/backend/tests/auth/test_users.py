"""User administration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.db import utcnow
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.org.models import AuditLog, Company
from tests import factories

NEW_USER = {"username": "zeynep.kaya", "full_name": "Zeynep Kaya", "password": "Parola-Test-9"}


def _role(db: Session, code: str) -> Role:
    return db.scalars(select(Role).where(Role.code == code)).one()


def _user_admin_role(db: Session) -> Role:
    """A custom role holding only the user administration permissions."""
    role = Role(code="kullanici_yoneticisi", name="Kullanıcı Yöneticisi")
    db.add(role)
    db.flush()
    for permission in db.scalars(select(Permission).where(Permission.key.like("auth.user.%"))):
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    return role


def _update_payload(user: User, **changes: object) -> dict[str, object]:
    payload = {
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "default_company_id": user.default_company_id,
        "version": user.version,
    }
    return {**payload, **changes}


def test_create_user(client: TestClient, db: Session, company: Company) -> None:
    role = _role(db, "muhasebe")

    response = client.post(
        "/api/users",
        json={
            **NEW_USER,
            "username": " Zeynep.Kaya ",
            "email": "zeynep@ornek.example",
            "default_company_id": company.id,
            "roles": [{"role_id": role.id, "company_id": company.id}],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "zeynep.kaya"
    assert body["email"] == "zeynep@ornek.example"
    assert (body["is_active"], body["is_superuser"], body["must_change_password"]) == (True, False, True)
    assert body["version"] == 1
    assert body["roles"] == [
        {
            "id": body["roles"][0]["id"],
            "role": {"id": role.id, "code": "muhasebe", "name": "Muhasebe"},
            "company": {"id": company.id, "code": "1000", "name": "Örnek Sanayi A.Ş."},
        }
    ]
    stored = db.get_one(User, body["id"])
    assert stored.password_hash.startswith("$argon2id$")
    assert security.verify_password(NEW_USER["password"], stored.password_hash)


def test_responses_never_contain_password_material(client: TestClient, db: Session) -> None:
    created = client.post("/api/users", json=NEW_USER)
    listing = client.get("/api/users", params={"page_size": 500})
    single = client.get(f"/api/users/{created.json()['id']}")

    for response in (created, listing, single):
        assert response.status_code in (200, 201)
        assert "password_hash" not in response.text
        assert "argon2" not in response.text


def test_create_user_validation(client: TestClient) -> None:
    response = client.post(
        "/api/users",
        json={"username": "geçersiz ad", "full_name": " ", "password": "kisa", "email": "eposta-degil"},
    )

    assert response.status_code == 422
    assert response.json()["details"]["fields"] == {
        "username": "Geçersiz biçim",
        "full_name": "En az 1 karakter olmalıdır",
        "email": "Geçersiz biçim",
        "password": "En az 8 karakter olmalıdır",
    }


def test_username_must_be_unique(client: TestClient) -> None:
    assert client.post("/api/users", json=NEW_USER).status_code == 201

    response = client.post("/api/users", json={**NEW_USER, "username": "ZEYNEP.KAYA"})

    assert response.status_code == 409
    assert response.json()["code"] == "USERNAME_TAKEN"
    assert response.json()["details"] == {"fields": {"username": "Bu kullanıcı adı zaten kullanılıyor"}}


def test_create_user_checks_references(client: TestClient, db: Session) -> None:
    unknown_company = client.post("/api/users", json={**NEW_USER, "default_company_id": 999_999})
    unknown_role = client.post("/api/users", json={**NEW_USER, "roles": [{"role_id": 999_999}]})

    assert (unknown_company.status_code, unknown_company.json()["code"]) == (422, "COMPANY_NOT_FOUND")
    assert (unknown_role.status_code, unknown_role.json()["code"]) == (422, "ROLE_NOT_FOUND")
    assert db.scalar(select(User.id).where(User.username == NEW_USER["username"])) is None


def test_get_user(client: TestClient, db: Session) -> None:
    user = factories.make_user(db, username="tekil.kullanici", roles=["depo"])

    found = client.get(f"/api/users/{user.id}")
    missing = client.get("/api/users/999999")

    assert found.status_code == 200
    assert found.json()["username"] == "tekil.kullanici"
    assert [link["role"]["code"] for link in found.json()["roles"]] == ["depo"]
    assert (missing.status_code, missing.json()["code"]) == (404, "USER_NOT_FOUND")


def test_list_users_filters_and_searches(client: TestClient, db: Session) -> None:
    factories.make_user(db, username="filtre.aktif", full_name="Çiğdem Öztürk")
    factories.make_user(db, username="filtre.pasif", full_name="Işıl Şahin", is_active=False)

    inactive = client.get("/api/users", params={"is_active": "false", "q": "filtre."})
    by_name = client.get("/api/users", params={"q": "ÖZTÜRK"})
    superusers = client.get("/api/users", params={"is_superuser": "true"})

    assert [item["username"] for item in inactive.json()["items"]] == ["filtre.pasif"]
    assert [item["username"] for item in by_name.json()["items"]] == ["filtre.aktif"]
    assert [item["username"] for item in superusers.json()["items"]] == ["admin"]


def test_update_user(client: TestClient, db: Session, company: Company) -> None:
    user = factories.make_user(db, full_name="Eski Ad", email="eski@ornek.example")

    response = client.put(
        f"/api/users/{user.id}",
        json=_update_payload(user, full_name="Yeni Ad", email="  ", default_company_id=company.id),
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["full_name"], body["email"], body["default_company_id"]) == ("Yeni Ad", None, company.id)
    assert body["version"] == user.version + 1


def test_reset_password_also_clears_a_lock(
    client: TestClient, anonymous_client: TestClient, db: Session
) -> None:
    user = factories.make_user(
        db, username="sifre.sifirlama", failed_login_count=5, locked_until=utcnow() + timedelta(minutes=10)
    )

    response = client.post(f"/api/users/{user.id}/reset-password", json={"new_password": "Gecici-Parola-1"})

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert response.json()["locked_until"] is None
    login = anonymous_client.post(
        "/api/auth/login", json={"username": "sifre.sifirlama", "password": "Gecici-Parola-1"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity == "auth_user", AuditLog.entity_id == user.id)
    ).all()
    assert "PASSWORD_RESET" in actions


def test_unlock_user(client: TestClient, anonymous_client: TestClient, db: Session) -> None:
    user = factories.make_user(
        db, username="kilit.acma", failed_login_count=5, locked_until=utcnow() + timedelta(minutes=10)
    )
    credentials = {"username": "kilit.acma", "password": factories.DEFAULT_PASSWORD}
    assert anonymous_client.post("/api/auth/login", json=credentials).status_code == 423

    response = client.post(f"/api/users/{user.id}/unlock")

    assert response.status_code == 200
    assert response.json()["locked_until"] is None
    assert anonymous_client.post("/api/auth/login", json=credentials).status_code == 200


def test_delete_unreferenced_user(client: TestClient, db: Session) -> None:
    user = factories.make_user(db, roles=["depo"])

    response = client.delete(f"/api/users/{user.id}")

    assert response.status_code == 200
    assert response.json() == {"result": "DELETED"}
    assert db.scalar(select(User.id).where(User.id == user.id)) is None
    assert db.scalar(select(UserRole.id).where(UserRole.user_id == user.id)) is None


def test_delete_referenced_user_deactivates_instead(
    client: TestClient, anonymous_client: TestClient, db: Session
) -> None:
    user = factories.make_user(db, username="iz.birakan", roles=["depo"])
    # Logging in leaves an audit entry that refers to the user.
    credentials = {"username": "iz.birakan", "password": factories.DEFAULT_PASSWORD}
    assert anonymous_client.post("/api/auth/login", json=credentials).status_code == 200

    response = client.delete(f"/api/users/{user.id}")

    assert response.status_code == 200
    assert response.json() == {"result": "DEACTIVATED"}
    db.expire_all()
    stored = db.get_one(User, user.id)
    assert stored.is_active is False
    assert [link.role.code for link in stored.roles] == ["depo"]
    assert anonymous_client.post("/api/auth/login", json=credentials).status_code == 403


def test_own_account_is_protected(client: TestClient, admin: User) -> None:
    delete = client.delete(f"/api/users/{admin.id}")
    deactivate = client.put(f"/api/users/{admin.id}", json=_update_payload(admin, is_active=False))

    assert (delete.status_code, delete.json()["code"]) == (409, "CANNOT_DELETE_SELF")
    assert (deactivate.status_code, deactivate.json()["code"]) == (409, "CANNOT_DEACTIVATE_SELF")


def test_last_active_superuser_cannot_be_demoted(client: TestClient, admin: User) -> None:
    response = client.put(f"/api/users/{admin.id}", json=_update_payload(admin, is_superuser=False))

    assert (response.status_code, response.json()["code"]) == (409, "LAST_SUPERUSER")


def test_second_superuser_can_be_demoted_and_deleted(client: TestClient, db: Session) -> None:
    second = factories.make_user(db, is_superuser=True)

    demoted = client.put(f"/api/users/{second.id}", json=_update_payload(second, is_superuser=False))
    deleted = client.delete(f"/api/users/{second.id}")

    assert demoted.status_code == 200
    assert demoted.json()["is_superuser"] is False
    assert deleted.json() == {"result": "DELETED"}


def test_only_superusers_manage_superuser_accounts(
    client_for: Callable[..., TestClient], db: Session, admin: User, company: Company
) -> None:
    role = _user_admin_role(db)
    manager = factories.make_user(db, default_company_id=company.id)
    db.add(UserRole(user_id=manager.id, role_id=role.id, company_id=None))
    db.flush()
    manager_client = client_for(manager)
    regular = factories.make_user(db)

    attempts = [
        manager_client.post("/api/users", json={**NEW_USER, "is_superuser": True}),
        manager_client.put(f"/api/users/{regular.id}", json=_update_payload(regular, is_superuser=True)),
        manager_client.put(f"/api/users/{admin.id}", json=_update_payload(admin, full_name="Ele Geçirildi")),
        manager_client.post(f"/api/users/{admin.id}/reset-password", json={"new_password": "Ele-Gecirme-1"}),
        manager_client.put(f"/api/users/{admin.id}/roles", json={"roles": []}),
        manager_client.delete(f"/api/users/{admin.id}"),
    ]

    for response in attempts:
        assert (response.status_code, response.json()["code"]) == (403, "SUPERUSER_REQUIRED")
    assert manager_client.post("/api/users", json=NEW_USER).status_code == 201


def test_set_user_roles_replaces_the_assignments(client: TestClient, db: Session, company: Company) -> None:
    user = factories.make_user(db, roles=["depo"])
    other_company = factories.make_company(db)
    purchasing, viewer = _role(db, "satinalma"), _role(db, "izleyici")

    response = client.put(
        f"/api/users/{user.id}/roles",
        json={
            "roles": [
                {"role_id": purchasing.id, "company_id": company.id},
                {"role_id": purchasing.id, "company_id": company.id},
                {"role_id": purchasing.id, "company_id": other_company.id},
                {"role_id": viewer.id},
            ]
        },
    )

    assert response.status_code == 200
    assigned = {
        (link["role"]["code"], link["company"]["code"] if link["company"] else None)
        for link in response.json()["roles"]
    }
    assert assigned == {("satinalma", "1000"), ("satinalma", other_company.code), ("izleyici", None)}
    assert len(response.json()["roles"]) == 3
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity == "auth_user_role")).all()
    assert actions.count("DELETE") >= 1
    assert actions.count("INSERT") >= 3

    cleared = client.put(f"/api/users/{user.id}/roles", json={"roles": []})
    assert cleared.json()["roles"] == []


def test_company_scoped_administrator_only_manages_that_company(
    client_for: Callable[..., TestClient], db: Session, company: Company
) -> None:
    """A user administrator of company 1000 may not hand out roles elsewhere or globally, and may
    not take over accounts that hold roles outside that company."""
    role = _user_admin_role(db)
    other_company = factories.make_company(db)
    manager = factories.make_user(db, default_company_id=company.id)
    db.add(UserRole(user_id=manager.id, role_id=role.id, company_id=company.id))
    db.flush()
    manager_client = client_for(manager)
    depot = _role(db, "depo")
    local_user = factories.make_user(db, roles=["depo"], company=company)
    foreign_user = factories.make_user(db, roles=["depo"], company=other_company)

    own_company = manager_client.put(
        f"/api/users/{local_user.id}/roles", json={"roles": [{"role_id": depot.id, "company_id": company.id}]}
    )
    elsewhere = manager_client.put(
        f"/api/users/{local_user.id}/roles",
        json={
            "roles": [
                {"role_id": depot.id, "company_id": company.id},
                {"role_id": depot.id, "company_id": other_company.id},
            ]
        },
    )
    global_grant = manager_client.put(
        f"/api/users/{local_user.id}/roles",
        json={"roles": [{"role_id": depot.id, "company_id": company.id}, {"role_id": depot.id}]},
    )
    takeover = manager_client.post(
        f"/api/users/{foreign_user.id}/reset-password", json={"new_password": "Ele-Gecirme-1"}
    )
    removal = manager_client.delete(f"/api/users/{foreign_user.id}")

    assert own_company.status_code == 200
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (403, "ROLE_SCOPE_DENIED")
    assert elsewhere.json()["details"] == {"company_id": other_company.id}
    assert (global_grant.status_code, global_grant.json()["code"]) == (403, "ROLE_SCOPE_DENIED")
    assert (takeover.status_code, takeover.json()["code"]) == (403, "ROLE_SCOPE_DENIED")
    assert (removal.status_code, removal.json()["code"]) == (403, "ROLE_SCOPE_DENIED")
    assert (
        manager_client.post(
            f"/api/users/{local_user.id}/reset-password", json={"new_password": "Yeni-Parola-3"}
        ).status_code
        == 200
    )

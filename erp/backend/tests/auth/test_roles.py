"""Role administration and the permission catalogue."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import Role, RolePermission
from app.modules.auth.permissions import PERMISSIONS
from app.modules.org.models import AuditLog
from tests import factories

SYSTEM_ROLES = ["admin", "depo", "izleyici", "muhasebe", "satinalma", "yonetici"]


def test_permission_catalogue(client: TestClient) -> None:
    response = client.get("/api/permissions")

    assert response.status_code == 200
    items = response.json()
    keys = [item["key"] for item in items]
    assert keys == sorted(keys)
    assert set(PERMISSIONS) <= set(keys)
    assert {"key": "auth.user.view", "description": "Kullanıcıları görüntüleme"} in items
    assert set(PERMISSIONS) == {"auth.user.view", "auth.user.manage", "auth.role.view", "auth.role.manage"}


def test_list_roles(client: TestClient) -> None:
    response = client.get("/api/roles", params={"is_system": "true"})

    assert response.status_code == 200
    body = response.json()
    assert [item["code"] for item in body["items"]] == SYSTEM_ROLES
    assert body["total"] == 6
    by_code = {item["code"]: item for item in body["items"]}
    assert set(PERMISSIONS) <= set(by_code["admin"]["permissions"])
    assert {"auth.role.view", "auth.user.view"} <= set(by_code["izleyici"]["permissions"])
    assert not any(key.endswith(".manage") for key in by_code["izleyici"]["permissions"])


def test_create_get_and_update_role(client: TestClient, db: Session) -> None:
    created = client.post(
        "/api/roles",
        json={
            "code": "insan_kaynaklari",
            "name": "İnsan Kaynakları",
            "description": "Kullanıcı yönetimi",
            "permissions": ["auth.user.view", "auth.user.manage"],
        },
    )
    assert created.status_code == 201
    role_id = created.json()["id"]
    assert created.json()["is_system"] is False
    assert created.json()["permissions"] == ["auth.user.manage", "auth.user.view"]

    fetched = client.get(f"/api/roles/{role_id}")
    updated = client.put(
        f"/api/roles/{role_id}",
        json={"name": "İK Uzmanı", "description": None, "permissions": ["auth.user.view", "auth.role.view"]},
    )

    assert fetched.json() == created.json()
    assert updated.status_code == 200
    assert (updated.json()["name"], updated.json()["description"]) == ("İK Uzmanı", None)
    assert updated.json()["permissions"] == ["auth.role.view", "auth.user.view"]
    assert updated.json()["code"] == "insan_kaynaklari"
    stored = db.scalars(select(RolePermission).where(RolePermission.role_id == role_id)).all()
    assert len(stored) == 2
    assert db.scalar(
        select(AuditLog.summary).where(
            AuditLog.entity == "auth_role",
            AuditLog.entity_id == role_id,
            AuditLog.action == "PERMISSIONS_CHANGED",
        )
    )


def test_role_validation(client: TestClient) -> None:
    bad_code = client.post("/api/roles", json={"code": "Büyük Harf", "name": "Geçersiz"})
    unknown_permission = client.post(
        "/api/roles",
        json={
            "code": "gecersiz_yetki",
            "name": "Geçersiz",
            "permissions": ["auth.user.view", "yok.boyle.yetki"],
        },
    )
    duplicate = client.post("/api/roles", json={"code": "admin", "name": "Kopya"})
    missing = client.get("/api/roles/999999")

    assert bad_code.status_code == 422
    assert bad_code.json()["details"]["fields"] == {"code": "Geçersiz biçim"}
    assert (unknown_permission.status_code, unknown_permission.json()["code"]) == (422, "UNKNOWN_PERMISSION")
    assert unknown_permission.json()["details"] == {"keys": ["yok.boyle.yetki"]}
    assert (duplicate.status_code, duplicate.json()["code"]) == (409, "ROLE_CODE_TAKEN")
    assert (missing.status_code, missing.json()["code"]) == (404, "ROLE_NOT_FOUND")


def test_delete_custom_role(client: TestClient, db: Session) -> None:
    role_id = client.post(
        "/api/roles", json={"code": "gecici", "name": "Geçici", "permissions": ["auth.user.view"]}
    ).json()["id"]

    response = client.delete(f"/api/roles/{role_id}")

    assert response.status_code == 204
    assert db.get(Role, role_id) is None
    assert db.scalar(select(RolePermission.id).where(RolePermission.role_id == role_id)) is None


def test_system_roles_cannot_be_deleted_but_can_be_extended(client: TestClient, db: Session) -> None:
    depot = db.scalars(select(Role).where(Role.code == "depo")).one()

    delete = client.delete(f"/api/roles/{depot.id}")
    extend = client.put(
        f"/api/roles/{depot.id}",
        json={"name": depot.name, "description": depot.description, "permissions": ["auth.user.view"]},
    )

    assert (delete.status_code, delete.json()["code"]) == (409, "SYSTEM_ROLE")
    assert extend.status_code == 200
    assert extend.json()["permissions"] == ["auth.user.view"]
    assert extend.json()["is_system"] is True


def test_assigned_role_cannot_be_deleted(client: TestClient, db: Session) -> None:
    role_id = client.post("/api/roles", json={"code": "kullanimda", "name": "Kullanımda"}).json()["id"]
    user = factories.make_user(db)
    assert (
        client.put(f"/api/users/{user.id}/roles", json={"roles": [{"role_id": role_id}]}).status_code == 200
    )

    response = client.delete(f"/api/roles/{role_id}")

    assert response.status_code == 409
    assert response.json() == {
        "code": "IN_USE",
        "message": "Kayıt kullanımda olduğu için silinemez",
        "details": {},
    }

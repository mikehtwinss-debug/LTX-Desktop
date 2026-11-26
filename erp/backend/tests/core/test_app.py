"""Application factory: feature discovery, permission sync, health check, CORS."""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.modules
from app.core.config import Settings, get_settings
from app.core.features import ALWAYS_LOADED, discover_features
from app.main import create_app
from app.modules.auth.models import Permission, Role, RolePermission
from app.modules.auth.permissions import PERMISSIONS as AUTH_PERMISSIONS
from app.modules.auth.service import sync_permissions

SAMPLE_FEATURE = {
    "__init__.py": """
        LOADED = True
    """,
    "permissions.py": """
        PERMISSIONS = {"sample.thing.view": "Örnek kayıtları görüntüleme"}
    """,
    "api.py": """
        from app.core.routing import make_router

        router = make_router("/api/sample", ["sample"])


        @router.get("/ping")
        def ping() -> dict[str, bool]:
            return {"pong": True}
    """,
    "child/__init__.py": "",
    "child/permissions.py": """
        PERMISSIONS = {"sample.child.view": "Alt özellik kayıtlarını görüntüleme"}
    """,
    "child/api.py": """
        from app.core.routing import make_router

        router = make_router("/api/sample-child", ["sample"])
    """,
    "models/__init__.py": "",
}


def _write_package(root: Path, name: str, files: dict[str, str]) -> None:
    for relative, source in files.items():
        target = root / name / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")


@pytest.fixture
def extra_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A directory whose packages appear under `app.modules` for the duration of one test."""
    monkeypatch.setattr(app.modules, "__path__", [*app.modules.__path__, str(tmp_path)])
    yield tmp_path
    for name in [name for name in sys.modules if name.startswith("app.modules.sample")]:
        del sys.modules[name]


def test_real_features_are_discovered(app: FastAPI) -> None:
    features = app.state.features
    paths = app.openapi()["paths"].keys()

    assert set(ALWAYS_LOADED) <= set(features)
    assert features == sorted(features)
    if get_settings().feature_list is None:
        assert {
            "fi",
            "fi.gl",
            "fi.partners",
            "fi.ap_ar",
            "fi.models",
            "mm",
            "mm.master",
            "mm.inventory",
        } <= set(features)
        assert {"mm.purchasing", "mm.invoice", "mm.models"} <= set(features)
    assert AUTH_PERMISSIONS.items() <= app.state.permissions.items()
    assert {
        "/api/health",
        "/api/auth/login",
        "/api/auth/me",
        "/api/users",
        "/api/roles",
        "/api/permissions",
    } <= paths


def test_discovery_collects_routers_and_permissions_of_new_packages(extra_modules: Path) -> None:
    _write_package(extra_modules, "sample", SAMPLE_FEATURE)

    discovery = discover_features(None)

    assert {"sample", "sample.child", "sample.models"} <= set(discovery.features)
    assert discovery.permissions["sample.thing.view"] == "Örnek kayıtları görüntüleme"
    assert discovery.permissions["sample.child.view"] == "Alt özellik kayıtlarını görüntüleme"
    assert {"/api/sample", "/api/sample-child"} <= {router.prefix for router in discovery.routers}
    assert sys.modules["app.modules.sample"].LOADED is True


def test_feature_restriction_keeps_the_foundation_and_the_named_features(extra_modules: Path) -> None:
    _write_package(extra_modules, "sample", SAMPLE_FEATURE)
    _write_package(
        extra_modules, "sample2", {"__init__.py": "", "api.py": "raise RuntimeError('work in progress')"}
    )

    only_child = discover_features(["sample.child"])
    whole_tree = discover_features(["sample"])
    foundation_only = discover_features([])

    assert only_child.features == ["auth", "co", "org", "sample.child"]
    assert "sample.child.view" in only_child.permissions
    assert "sample.thing.view" not in only_child.permissions
    assert "/api/sample" not in {router.prefix for router in only_child.routers}
    assert "app.modules.sample" in sys.modules  # the parent package is still imported for its side effects
    assert whole_tree.features == ["auth", "co", "org", "sample", "sample.child", "sample.models"]
    assert foundation_only.features == ["auth", "co", "org"]
    assert AUTH_PERMISSIONS.keys() <= foundation_only.permissions.keys()
    # The broken sibling only fails when it is part of the selection.
    with pytest.raises(RuntimeError, match="work in progress"):
        discover_features(["sample2"])


def test_discovery_rejects_unknown_features_and_duplicate_permissions(extra_modules: Path) -> None:
    _write_package(
        extra_modules,
        "sampledup",
        {"__init__.py": "", "permissions.py": "PERMISSIONS = {'auth.user.view': 'Çakışan anahtar'}"},
    )

    with pytest.raises(ValueError, match="Unknown feature.*fi.typo"):
        discover_features(["fi.typo"])
    with pytest.raises(ValueError, match="declared twice: auth.user.view"):
        discover_features(["sampledup"])


def test_app_honours_erp_features(extra_modules: Path) -> None:
    _write_package(extra_modules, "sample", SAMPLE_FEATURE)
    settings = Settings(_env_file=None, features="sample")

    application = create_app(settings)
    client = TestClient(application)

    assert application.state.features == ["auth", "co", "org", "sample", "sample.child", "sample.models"]
    assert client.get("/api/sample/ping").json() == {"pong": True}
    assert "sample.thing.view" in application.state.permissions
    application.state.engine.dispose()


def test_startup_syncs_permissions(db: Session, session_factory: sessionmaker[Session]) -> None:
    application = create_app()
    application.state.session_factory = session_factory
    application.state.permissions = {
        **application.state.permissions,
        "test.startup.view": "Başlangıçta eklenen yetki",
        "auth.user.view": "Güncellenen açıklama",
    }

    with TestClient(application) as client:
        assert client.get("/api/health").status_code == 200

    stored = dict(db.execute(select(Permission.key, Permission.description)).all())
    assert stored["test.startup.view"] == "Başlangıçta eklenen yetki"
    assert stored["auth.user.view"] == "Güncellenen açıklama"


def test_permission_sync_is_idempotent_and_never_deletes(db: Session) -> None:
    sync_permissions(db, {"test.sync.a": "Bir", "test.sync.b": "İki"})
    db.flush()
    first = {p.key: (p.id, p.description, p.updated_at) for p in db.scalars(select(Permission))}
    role = db.scalars(select(Role).where(Role.code == "depo")).one()
    db.add(RolePermission(role_id=role.id, permission_id=first["test.sync.a"][0]))
    db.flush()

    sync_permissions(db, {"test.sync.a": "Bir", "test.sync.b": "İki (yeni açıklama)"})
    sync_permissions(db, {})
    db.expire_all()
    second = {p.key: (p.id, p.description, p.updated_at) for p in db.scalars(select(Permission))}

    assert second.keys() == first.keys()  # test.sync.* kept although absent from the last call
    assert second["test.sync.a"] == first["test.sync.a"]  # untouched row: same id, same timestamp
    assert second["test.sync.b"][:2] == (first["test.sync.b"][0], "İki (yeni açıklama)")
    assert second["auth.user.view"] == first["auth.user.view"]
    assert db.scalar(select(RolePermission.id).where(RolePermission.permission_id == first["test.sync.a"][0]))


def test_health(client: TestClient, anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_an_unreachable_database() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://erp:erp@127.0.0.1:1/unreachable")
    application = create_app(settings)

    response = TestClient(application).get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "down"}


def test_cors_is_off_by_default_and_configurable(
    app: FastAPI, session_factory: sessionmaker[Session]
) -> None:
    origin = "http://localhost:5173"
    preflight = {"Origin": origin, "Access-Control-Request-Method": "POST"}
    configured = create_app(Settings(_env_file=None, cors_origins=f"{origin}, https://erp.ornek.example"))
    configured.state.session_factory = session_factory

    default_response = TestClient(app).get("/api/health", headers={"Origin": origin})
    allowed = TestClient(configured).options("/api/auth/login", headers=preflight)
    simple = TestClient(configured).get("/api/health", headers={"Origin": origin})
    foreign = TestClient(configured).get("/api/health", headers={"Origin": "https://baska.example"})

    assert "access-control-allow-origin" not in default_response.headers
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == origin
    assert simple.headers["access-control-allow-origin"] == origin
    assert "Content-Disposition" in simple.headers["access-control-expose-headers"]
    assert "access-control-allow-origin" not in foreign.headers
    configured.state.engine.dispose()


def test_openapi_schema_is_served(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/api/auth/login", "/api/users/{user_id}", "/api/roles/{role_id}", "/api/health"} <= paths.keys()


def test_api_documentation_is_not_served_in_production() -> None:
    settings = Settings(_env_file=None, env="production", secret_key="k" * 40)
    application = create_app(settings)
    client = TestClient(application)

    assert client.get("/api/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/health").status_code == 200
    application.state.engine.dispose()

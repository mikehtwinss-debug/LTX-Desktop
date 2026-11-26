"""Every failure is reported as `{"code", "message", "details"}`."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from app.core.context import Db
from app.core.errors import (
    AppError,
    Conflict,
    Forbidden,
    NotFound,
    ValidationFailed,
    register_exception_handlers,
)
from app.core.routing import make_router
from app.modules.auth.models import Role, User, UserRole
from app.modules.org.models import Currency, ExchangeRate
from tests import factories


class _LineIn(BaseModel):
    quantity: Decimal = Field(gt=0)


class _OrderIn(BaseModel):
    name: str = Field(min_length=3)
    count: int
    lines: list[_LineIn]

    @field_validator("name")
    @classmethod
    def _no_digits(cls, value: str) -> str:
        if any(char.isdigit() for char in value):
            raise ValueError("Ad rakam içeremez")
        return value


@pytest.fixture
def probe(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A throw-away application exposing one endpoint per failure kind."""
    router = make_router("/probe", ["probe"])

    @router.get("/app-error/{kind}")
    def app_error(kind: str) -> None:
        errors = {
            "base": AppError("PERIOD_CLOSED", "Dönem kapalı", details={"period": 3}),
            "not-found": NotFound("ORDER_NOT_FOUND", "Sipariş bulunamadı"),
            "forbidden": Forbidden("NOT_ALLOWED", "İzin yok"),
            "conflict": Conflict("ALREADY_POSTED", "Belge zaten kaydedilmiş"),
            "validation": ValidationFailed("BAD_QUANTITY", "Miktar hatalı"),
            "teapot": AppError("CUSTOM_STATUS", "Özel durum", 418),
        }
        raise errors[kind]

    @router.post("/validate")
    def validate(data: _OrderIn) -> dict[str, bool]:
        return {"ok": True}

    @router.post("/duplicate-currency")
    def duplicate_currency(db: Db) -> None:
        db.add(Currency(code="TRY", name="Kopya", symbol="?"))
        db.flush()

    @router.post("/unknown-reference")
    def unknown_reference(db: Db) -> None:
        db.add(UserRole(user_id=-1, role_id=-1))
        db.flush()

    @router.post("/negative-rate")
    def negative_rate(db: Db) -> None:
        db.add(ExchangeRate(currency_code="USD", rate_date="2026-01-01", rate=Decimal("-1")))
        db.flush()

    @router.delete("/roles/{role_id}")
    def delete_role_unchecked(role_id: int, db: Db) -> None:
        db.delete(db.get_one(Role, role_id))
        db.flush()

    @router.get("/crash")
    def crash() -> None:
        raise RuntimeError("boom")

    application = FastAPI()
    application.state.session_factory = session_factory
    register_exception_handlers(application)
    application.include_router(router)
    yield TestClient(application, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("kind", "status", "code", "message", "details"),
    [
        ("base", 400, "PERIOD_CLOSED", "Dönem kapalı", {"period": 3}),
        ("not-found", 404, "ORDER_NOT_FOUND", "Sipariş bulunamadı", {}),
        ("forbidden", 403, "NOT_ALLOWED", "İzin yok", {}),
        ("conflict", 409, "ALREADY_POSTED", "Belge zaten kaydedilmiş", {}),
        ("validation", 422, "BAD_QUANTITY", "Miktar hatalı", {}),
        ("teapot", 418, "CUSTOM_STATUS", "Özel durum", {}),
    ],
)
def test_app_errors_use_the_documented_shape(
    probe: TestClient, kind: str, status: int, code: str, message: str, details: dict
) -> None:
    response = probe.get(f"/probe/app-error/{kind}")

    assert response.status_code == status
    assert response.json() == {"code": code, "message": message, "details": details}


def test_request_validation_errors_are_mapped_to_fields(probe: TestClient) -> None:
    response = probe.post(
        "/probe/validate", json={"name": "ab", "count": "x", "lines": [{"quantity": "1"}, {"quantity": 0}]}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"] == "Gönderilen veriler geçersiz"
    assert body["details"]["fields"] == {
        "name": "En az 3 karakter olmalıdır",
        "count": "Geçerli bir tam sayı giriniz",
        "lines.1.quantity": "0 değerinden büyük olmalıdır",
    }


def test_missing_fields_and_custom_validator_messages(probe: TestClient) -> None:
    response = probe.post("/probe/validate", json={"name": "abc1", "lines": []})

    assert response.status_code == 422
    assert response.json()["details"]["fields"] == {
        "name": "Ad rakam içeremez",
        "count": "Bu alan zorunludur",
    }


def test_malformed_json_body_is_a_validation_error(probe: TestClient) -> None:
    response = probe.post(
        "/probe/validate", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_unique_violation_becomes_duplicate(probe: TestClient) -> None:
    response = probe.post("/probe/duplicate-currency")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "DUPLICATE"
    assert body["details"]["constraint"] == "uq_org_currency_code"


def test_foreign_key_violation_on_insert_is_an_invalid_reference(probe: TestClient) -> None:
    response = probe.post("/probe/unknown-reference")

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REFERENCE"


def test_check_violation_is_a_constraint_violation(probe: TestClient) -> None:
    response = probe.post("/probe/negative-rate")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "CONSTRAINT_VIOLATION"
    assert body["details"]["constraint"] == "ck_org_exchange_rate_rate_positive"


def test_deleting_a_referenced_row_becomes_in_use(probe: TestClient, db: Session) -> None:
    role = Role(code="gecici_rol", name="Geçici Rol")
    db.add(role)
    db.flush()
    user = factories.make_user(db)
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()

    response = probe.delete(f"/probe/roles/{role.id}")

    assert response.status_code == 409
    assert response.json() == {
        "code": "IN_USE",
        "message": "Kayıt kullanımda olduğu için silinemez",
        "details": {"constraint": "fk_auth_user_role_role_id_auth_role", "table": "auth_user_role"},
    }
    # The failed request was rolled back as a whole and left the connection usable.
    assert db.get(User, user.id) is not None
    assert db.get(Role, role.id) is not None


def test_unknown_route_and_wrong_method_use_the_shape(probe: TestClient) -> None:
    missing = probe.get("/probe/does-not-exist")
    wrong_method = probe.put("/probe/crash")

    assert missing.status_code == 404
    assert missing.json() == {"code": "NOT_FOUND", "message": "Kaynak bulunamadı", "details": {}}
    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_exception_is_a_generic_500_without_internals(probe: TestClient) -> None:
    response = probe.get("/probe/crash")

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "Beklenmeyen bir hata oluştu",
        "details": {},
    }
    assert "boom" not in response.text

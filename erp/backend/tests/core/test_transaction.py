"""`TransactionalRoute`: one transaction per request, committed before the response leaves.

These tests need to observe real commits from a second connection, so they bypass the per-test
outer transaction: they run a small application on the session engine and delete what they wrote.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import Db
from app.core.errors import AppError, register_exception_handlers
from app.core.routing import make_router
from app.core.transaction import TransactionalRoute
from app.modules.org.models import Currency

CODES = ("ZT1", "ZT2", "ZT3", "ZT4", "ZT5", "ZT6")


def _count(engine: Engine, code: str) -> int:
    """Rows visible to an independent connection, i.e. committed ones."""
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(Currency).where(Currency.code == code)) or 0


@dataclass
class _Observation:
    status: int
    committed_rows: int


@dataclass
class _Harness:
    client: TestClient
    engine: Engine
    at_response_start: list[_Observation] = field(default_factory=list)


class _ResponseStartProbe:
    """ASGI middleware recording, at the moment the response starts, what is already committed."""

    def __init__(self, app: ASGIApp, harness: _Harness) -> None:
        self.app = app
        self.harness = harness

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def probing_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                code = scope["path"].split("/")[2]
                self.harness.at_response_start.append(
                    _Observation(message["status"], _count(self.harness.engine, code))
                )
            await send(message)

        await self.app(scope, receive, probing_send)


@pytest.fixture
def harness(engine: Engine) -> Iterator[_Harness]:
    router = make_router("/currencies", ["probe"])

    def add_currency(db: Session, code: str) -> None:
        db.add(Currency(code=code, name="Deneme Para Birimi", symbol="¤"))
        db.flush()

    @router.post("/{code}")
    def create(code: str, db: Db) -> dict[str, str]:
        add_currency(db, code)
        return {"code": code}

    @router.post("/{code}/async")
    async def create_async(code: str, db: Db) -> dict[str, str]:
        await run_in_threadpool(add_currency, db, code)
        return {"code": code}

    @router.post("/{code}/app-error")
    def create_then_fail(code: str, db: Db) -> None:
        add_currency(db, code)
        raise AppError("PROBE_FAILED", "İşlem geri alındı")

    @router.post("/{code}/crash")
    def create_then_crash(code: str, db: Db) -> None:
        add_currency(db, code)
        raise RuntimeError("unexpected")

    @router.post("/{code}/commit-failure")
    def fail_at_commit(code: str, db: Db) -> dict[str, str]:
        # Two rows with the same key and no flush: the violation only surfaces in the commit.
        db.add(Currency(code=code, name="Bir", symbol="1"))
        db.add(Currency(code=code, name="İki", symbol="2"))
        return {"code": code}

    application = FastAPI()
    application.state.session_factory = sessionmaker(bind=engine)
    register_exception_handlers(application)
    application.include_router(router)
    harness = _Harness(client=TestClient(application, raise_server_exceptions=False), engine=engine)
    application.add_middleware(_ResponseStartProbe, harness=harness)
    try:
        yield harness
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Currency).where(Currency.code.in_(CODES)))


def test_router_factory_uses_the_transactional_route() -> None:
    router = make_router("/x", ["x"])

    assert router.route_class is TransactionalRoute
    assert router.prefix == "/x"
    assert router.tags == ["x"]


def test_commit_is_visible_before_the_response_starts(harness: _Harness) -> None:
    response = harness.client.post("/currencies/ZT1")

    assert response.status_code == 200
    assert harness.at_response_start == [_Observation(status=200, committed_rows=1)]
    assert _count(harness.engine, "ZT1") == 1


def test_async_endpoints_commit_the_same_way(harness: _Harness) -> None:
    response = harness.client.post("/currencies/ZT2/async")

    assert response.status_code == 200
    assert harness.at_response_start == [_Observation(status=200, committed_rows=1)]


def test_app_error_rolls_the_request_back(harness: _Harness) -> None:
    response = harness.client.post("/currencies/ZT3/app-error")

    assert response.status_code == 400
    assert response.json()["code"] == "PROBE_FAILED"
    assert harness.at_response_start == [_Observation(status=400, committed_rows=0)]
    assert _count(harness.engine, "ZT3") == 0


def test_unexpected_exception_rolls_the_request_back(harness: _Harness) -> None:
    response = harness.client.post("/currencies/ZT4/crash")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert _count(harness.engine, "ZT4") == 0


def test_failure_during_commit_is_reported_and_nothing_is_stored(harness: _Harness) -> None:
    response = harness.client.post("/currencies/ZT5/commit-failure")

    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE"
    assert harness.at_response_start == [_Observation(status=409, committed_rows=0)]
    assert _count(harness.engine, "ZT5") == 0


def test_the_session_is_always_closed(harness: _Harness) -> None:
    harness.client.post("/currencies/ZT6")
    harness.client.post("/currencies/ZT6/app-error")
    harness.client.post("/currencies/ZT6/crash")
    harness.client.post("/currencies/ZT6/commit-failure")

    # Every request returned its connection to the pool, whatever its outcome.
    assert harness.engine.pool.checkedout() == 0

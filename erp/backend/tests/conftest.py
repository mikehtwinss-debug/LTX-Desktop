"""Test harness.

One uniquely named database per test session: schema from `Base.metadata.create_all` (which also
installs the triggers), base seed and company 1000. Each test runs inside an outer transaction on
one connection that is rolled back afterwards; sessions join it with savepoints, so the `commit()`
of the request transaction is real to the application and still invisible to the next test.

Fixtures: `db` (session), `ctx` (admin in company 1000), `client` (admin `TestClient`),
`client_as(role)`, `client_for(user)`, `anonymous_client`, `engine` (for the few tests that need
really committed data and clean up after themselves).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection, Engine, make_url

DEFAULT_SERVER_URL = "postgresql+psycopg://erp:erp@127.0.0.1:5432/erp_dev"
TEST_DATABASE = f"erp_test_{uuid.uuid4().hex[:12]}"
ADMIN_PASSWORD = "Yonetici-Test-1"
COMPANY_CODE = "1000"
COMPANY_NAME = "Örnek Sanayi A.Ş."

_server_url = make_url(
    os.environ.get("ERP_TEST_DATABASE_URL") or os.environ.get("ERP_DATABASE_URL") or DEFAULT_SERVER_URL
).set(drivername="postgresql+psycopg")
_storage_dir = tempfile.mkdtemp(prefix="erp-test-storage-")

# The application reads its settings from the environment, so these must be in place before the
# first application import below: nothing in a test run may touch the development database.
os.environ["ERP_ENV"] = "test"
os.environ["ERP_DATABASE_URL"] = _server_url.set(database=TEST_DATABASE).render_as_string(hide_password=False)
os.environ["ERP_STORAGE_DIR"] = _storage_dir

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core import security  # noqa: E402
from app.core.context import COMPANY_HEADER, RequestContext  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.auth.models import User  # noqa: E402
from app.modules.org.models import Company  # noqa: E402
from app.seed import seed_base, seed_company  # noqa: E402
from app.seed.base import ADMIN_USERNAME  # noqa: E402
from tests import factories  # noqa: E402


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
def engine(app: FastAPI) -> Iterator[Engine]:
    """Engine of the session's throw-away database, created and seeded here and dropped at the end."""
    server = create_engine(_server_url, isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    engine: Engine = app.state.engine
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            seed_base(session, app.state.permissions, admin_password=ADMIN_PASSWORD)
            seed_company(session, code=COMPANY_CODE, name=COMPANY_NAME)
        yield engine
    finally:
        engine.dispose()
        with server.connect() as connection:
            # Close whatever a test left connected under our role. DROP ... WITH (FORCE) is not an
            # option: it also tries to terminate autovacuum workers, which an ordinary role may not do,
            # whereas a plain DROP DATABASE waits for them by itself.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND usename = current_user AND pid <> pg_backend_pid()"
                ),
                {"name": TEST_DATABASE},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}"'))
        server.dispose()
        shutil.rmtree(_storage_dir, ignore_errors=True)


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """The single connection of a test, inside a transaction that is always rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def session_factory(app: FastAPI, connection: Connection) -> Iterator[sessionmaker[Session]]:
    """Sessions bound to the test connection; installed as the application's session factory."""
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    original = app.state.session_factory
    app.state.session_factory = factory
    try:
        yield factory
    finally:
        app.state.session_factory = original


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Session for arranging and asserting. Requests use their own sessions on the same connection:
    flush before calling the API and `db.expire_all()` before re-reading what a request changed."""
    with session_factory() as session:
        yield session


@pytest.fixture
def company(db: Session) -> Company:
    return factories.default_company(db)


@pytest.fixture
def admin(db: Session) -> User:
    return db.scalars(select(User).where(User.username == ADMIN_USERNAME)).one()


@pytest.fixture
def ctx(db: Session, admin: User, company: Company) -> RequestContext:
    """Service context of the administrator in company 1000."""
    db.info["user_id"] = admin.id
    db.info["company_id"] = company.id
    return RequestContext(db=db, user=admin, company_id=company.id)


@pytest.fixture
def client_for(
    app: FastAPI, session_factory: sessionmaker[Session], company: Company
) -> Callable[..., TestClient]:
    """`client_for(user)` / `client_for(user, other_company)`: a client authenticated as that user."""

    def build(user: User, active_company: Company | None = company) -> TestClient:
        headers = {"Authorization": f"Bearer {security.create_access_token(user.id)}"}
        if active_company is not None:
            headers[COMPANY_HEADER] = str(active_company.id)
        return TestClient(app, headers=headers)

    return build


@pytest.fixture
def client(client_for: Callable[..., TestClient], admin: User) -> TestClient:
    """Client authenticated as the administrator in company 1000."""
    return client_for(admin)


@pytest.fixture
def client_as(
    db: Session, company: Company, client_for: Callable[..., TestClient]
) -> Callable[[str], TestClient]:
    """`client_as("muhasebe")`: a client for a fresh user holding that role in company 1000."""

    def build(role: str) -> TestClient:
        return client_for(factories.make_user(db, roles=[role], company=company))

    return build


@pytest.fixture
def anonymous_client(app: FastAPI, session_factory: sessionmaker[Session]) -> TestClient:
    return TestClient(app)

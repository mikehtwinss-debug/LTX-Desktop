"""Number ranges: format, yearly ranges, lazy creation, gap-free behaviour, concurrency."""

from __future__ import annotations

import threading
import uuid
from datetime import date

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import Conflict
from app.core.numbering import next_number, register_number_range, registered_number_ranges
from app.modules.auth.models import User
from app.modules.org.models import Company, NumberRange
from tests import factories


def _key() -> str:
    return f"T{uuid.uuid4().hex[:10].upper()}"


def _range(db: Session, company_id: int, key: str, year: int = 0) -> NumberRange | None:
    db.expire_all()
    return db.scalar(
        select(NumberRange).where(
            NumberRange.company_id == company_id, NumberRange.key == key, NumberRange.year == year
        )
    )


def test_sequence_and_format(ctx: RequestContext) -> None:
    key = _key()
    register_number_range(key, "SIP", 7, False)

    assert [next_number(ctx, key) for _ in range(3)] == ["SIP0000001", "SIP0000002", "SIP0000003"]


def test_range_row_is_created_lazily(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "TLP", 7, False)
    assert _range(db, ctx.company_id, key) is None

    next_number(ctx, key)

    row = _range(db, ctx.company_id, key)
    assert row is not None
    assert (row.prefix, row.padding, row.next_value, row.year) == ("TLP", 7, 2, 0)
    assert row.created_by_id == ctx.user.id


def test_yearly_ranges_count_per_year(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "MB", 6, True)

    assert next_number(ctx, key, year=2026) == "MB26000001"
    assert next_number(ctx, key, year=2026) == "MB26000002"
    assert next_number(ctx, key, year=2027) == "MB27000001"
    assert next_number(ctx, key, year=2026) == "MB26000003"
    assert _range(db, ctx.company_id, key, 2026).next_value == 4
    assert _range(db, ctx.company_id, key, 2027).next_value == 2


def test_yearly_range_defaults_to_the_current_year_and_allows_an_empty_prefix(ctx: RequestContext) -> None:
    key = _key()
    register_number_range(key, "", 8, True)

    assert next_number(ctx, key) == f"{date.today().year % 100:02d}00000001"


def test_year_is_ignored_for_ranges_that_are_not_yearly(ctx: RequestContext) -> None:
    key = _key()
    register_number_range(key, "TKT", 5, False)

    assert next_number(ctx, key, year=2026) == "TKT00001"
    assert next_number(ctx, key, year=2031) == "TKT00002"


def test_edited_range_is_respected(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "FK", 6, False)
    next_number(ctx, key)
    row = _range(db, ctx.company_id, key)
    row.prefix, row.padding, row.next_value = "FT-", 4, 250
    db.flush()

    assert next_number(ctx, key) == "FT-0250"
    assert next_number(ctx, key) == "FT-0251"


def test_rolled_back_number_is_issued_again(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "OD", 5, False)
    assert next_number(ctx, key) == "OD00001"

    savepoint = db.begin_nested()
    assert next_number(ctx, key) == "OD00002"
    savepoint.rollback()

    assert next_number(ctx, key) == "OD00002"


def test_each_company_has_its_own_sequence(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "SYM", 5, False)
    other = factories.make_company(db)
    other_ctx = RequestContext(db=db, user=ctx.user, company_id=other.id)

    assert next_number(ctx, key) == "SYM00001"
    assert next_number(ctx, key) == "SYM00002"
    assert next_number(other_ctx, key) == "SYM00001"


def test_exhausted_range_is_refused(ctx: RequestContext, db: Session) -> None:
    key = _key()
    register_number_range(key, "X", 2, False)
    next_number(ctx, key)
    _range(db, ctx.company_id, key).next_value = 100
    db.flush()

    with pytest.raises(Conflict) as error:
        next_number(ctx, key)

    assert error.value.code == "NUMBER_RANGE_EXHAUSTED"


def test_registration_rules(ctx: RequestContext) -> None:
    key = _key()
    register_number_range(key, "A", 5, False)
    register_number_range(key, "A", 5, False)  # identical re-registration (module re-import) is fine

    assert registered_number_ranges()[key].prefix == "A"
    with pytest.raises(ValueError, match="already registered"):
        register_number_range(key, "B", 5, False)
    with pytest.raises(LookupError):
        next_number(ctx, "NOT_REGISTERED")


def test_concurrent_transactions_get_no_duplicates_and_no_gaps(engine: Engine) -> None:
    """Eight threads, each with its own connection and committed transactions, race on a range that
    does not exist yet; every fifth transaction rolls back. The committed numbers must be exactly
    1..n: no duplicates, and no gaps left behind by the rollbacks."""
    key = _key()
    register_number_range(key, "CC", 6, False)
    threads, per_thread = 8, 20
    with Session(engine) as session:
        company_id = session.scalars(select(Company.id).where(Company.code == "1000")).one()
        admin_id = session.scalars(select(User.id).where(User.username == "admin")).one()

    committed: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    start = threading.Barrier(threads)

    def worker(index: int) -> None:
        try:
            start.wait(timeout=30)
            for iteration in range(per_thread):
                with Session(engine) as session:
                    ctx = RequestContext(
                        db=session, user=session.get_one(User, admin_id), company_id=company_id
                    )
                    number = next_number(ctx, key)
                    if (index + iteration) % 5 == 0:
                        session.rollback()
                    else:
                        session.commit()
                        with lock:
                            committed.append(number)
        except BaseException as exc:  # noqa: BLE001 (reported to the main thread below)
            errors.append(exc)

    try:
        workers = [threading.Thread(target=worker, args=(index,)) for index in range(threads)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=120)

        assert not errors
        assert not any(thread.is_alive() for thread in workers)
        assert len(committed) == len(set(committed))
        sequence = sorted(int(number.removeprefix("CC")) for number in committed)
        assert sequence == list(range(1, len(committed) + 1))
        assert len(committed) == threads * per_thread - sum(
            1 for index in range(threads) for iteration in range(per_thread) if (index + iteration) % 5 == 0
        )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(NumberRange).where(NumberRange.key == key))

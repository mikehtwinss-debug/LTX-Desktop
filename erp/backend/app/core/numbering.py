"""Document number ranges.

Features declare their ranges at import time with `register_number_range`; the per-company row is
created lazily on first use and can then be edited (prefix, padding, next value) in the admin UI.
Numbers are gap-free: the range row stays locked until the surrounding transaction ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import Conflict
from app.modules.org.models import NumberRange

if TYPE_CHECKING:
    from app.core.context import RequestContext


@dataclass(frozen=True, slots=True)
class NumberRangeSpec:
    key: str
    prefix: str
    padding: int
    yearly: bool


_registry: dict[str, NumberRangeSpec] = {}


def register_number_range(key: str, prefix: str, padding: int, yearly: bool) -> None:
    spec = NumberRangeSpec(key=key, prefix=prefix, padding=padding, yearly=yearly)
    existing = _registry.get(key)
    if existing is not None and existing != spec:
        raise ValueError(f"Number range {key!r} is already registered with a different definition")
    _registry[key] = spec


def registered_number_ranges() -> dict[str, NumberRangeSpec]:
    return dict(_registry)


def _locked_range(ctx: RequestContext, spec: NumberRangeSpec, year: int) -> NumberRange:
    stmt = (
        select(NumberRange)
        .where(
            NumberRange.company_id == ctx.company_id,
            NumberRange.key == spec.key,
            NumberRange.year == year,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = ctx.db.scalar(stmt)
    if row is None:
        # Concurrent first users race on the unique key: the loser waits for the winner's commit,
        # inserts nothing, and then locks the winner's row below.
        ctx.db.execute(
            insert(NumberRange)
            .values(
                company_id=ctx.company_id,
                key=spec.key,
                year=year,
                prefix=spec.prefix,
                padding=spec.padding,
                next_value=1,
                created_by_id=ctx.user.id,
                updated_by_id=ctx.user.id,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "key", "year"])
        )
        row = ctx.db.scalars(stmt).one()
    return row


def next_number(ctx: RequestContext, key: str, *, year: int | None = None) -> str:
    """Take the next number of a range: `prefix + (YY if yearly) + zero-padded sequence`.

    `year` selects the range of a yearly key (default: the current calendar year) and is ignored for
    ranges that are not yearly.
    """
    spec = _registry.get(key)
    if spec is None:
        raise LookupError(f"Number range {key!r} is not registered")
    range_year = (year or date.today().year) if spec.yearly else 0
    row = _locked_range(ctx, spec, range_year)

    value = row.next_value
    if len(str(value)) > row.padding:
        raise Conflict(
            "NUMBER_RANGE_EXHAUSTED",
            f"Numara aralığı doldu: {key}",
            details={"key": key, "year": range_year},
        )
    row.next_value = value + 1
    ctx.db.flush()

    year_part = f"{range_year % 100:02d}" if spec.yearly else ""
    return f"{row.prefix}{year_part}{value:0{row.padding}d}"

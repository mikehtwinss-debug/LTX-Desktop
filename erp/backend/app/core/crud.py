"""Lookups shared by the master-data services: company-scoped fetch and unique business keys."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import Conflict, NotFound

if TYPE_CHECKING:
    from app.core.context import RequestContext, UserContext

_CODE_TAKEN = "Bu kod zaten kullanılıyor"


def get_owned[T](
    ctx: RequestContext, model: type[T], row_id: int, not_found: NotFound, *, lock: bool = False
) -> T:
    """The row of `model` with this id in the active company.

    Rows of other companies do not exist for the caller: they raise the same `not_found` error as
    an unknown id. `lock=True` takes the row lock that every update and status change needs.
    """
    stmt = select(model).where(model.id == row_id, model.company_id == ctx.company_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = ctx.db.scalar(stmt)
    if row is None:
        raise not_found
    return row


def assert_unique(
    ctx: UserContext,
    column: InstrumentedAttribute[Any],
    value: Any,
    *,
    company_id: int | None = None,
    exclude_id: int | None = None,
) -> None:
    """Raise 409 `CODE_TAKEN` when another row already uses `value` in `column`.

    `company_id` limits the check to one company (business keys are unique per company);
    `exclude_id` is the row being updated. The unique constraint still decides a race.
    """
    model = column.class_
    stmt = select(model.id).where(column == value)
    if company_id is not None:
        stmt = stmt.where(model.company_id == company_id)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if ctx.db.scalar(stmt.limit(1)) is not None:
        raise Conflict("CODE_TAKEN", _CODE_TAKEN, details={"fields": {column.key: _CODE_TAKEN}})

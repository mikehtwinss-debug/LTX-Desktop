"""List contract: `?page=&page_size=&sort=&q=&<field>=<value>` -> `{items, total, page, page_size}`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from fastapi import Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, Numeric, Select, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ValidationFailed

if TYPE_CHECKING:
    from app.core.context import UserContext

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 50
_RESERVED_PARAMS = frozenset({"page", "page_size", "sort", "q"})
_RANGE_SUFFIXES = (("_from", "ge"), ("_to", "le"))
_ISO_DATE_LENGTH = len("2026-01-31")
_FOLD_FROM = "İIıŞĞÜÖÇ"
_FOLD_TO = "iiişğüöç"
_FOLD_TABLE = str.maketrans(_FOLD_FROM, _FOLD_TO)
_TRUE = {"true", "1", "evet"}
_FALSE = {"false", "0", "hayir", "hayır"}


class Page[T](BaseModel):
    """Response model of every list endpoint: `response_model=Page[UserOut]`."""

    items: list[T]
    total: int
    page: int
    page_size: int


class PageData(TypedDict):
    items: list[Any]
    total: int
    page: int
    page_size: int


class ListParams:
    """Paging, sorting, search and the raw `<field>=<value>` filters of a list request."""

    def __init__(
        self,
        request: Request,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        sort: Annotated[str | None, Query(max_length=200)] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
    ) -> None:
        self.page = page
        self.page_size = page_size
        self.sort = sort
        self.q = q
        self.filters: dict[str, list[str]] = {}
        for name, value in request.query_params.multi_items():
            if name not in _RESERVED_PARAMS:
                self.filters.setdefault(name, []).append(value)


ListQuery = Annotated[ListParams, Depends(ListParams)]


def _invalid_filter(name: str) -> ValidationFailed:
    return ValidationFailed(
        "INVALID_FILTER", f"Geçersiz filtre değeri: {name}", details={"fields": {name: "Geçersiz değer"}}
    )


def _coerce(name: str, column: ColumnElement[Any], raw: str) -> Any:
    column_type = column.type
    try:
        if isinstance(column_type, Boolean):
            lowered = raw.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise ValueError(raw)
        if isinstance(column_type, Enum) and column_type.enum_class is not None:
            return column_type.enum_class(raw)
        if isinstance(column_type, Integer):
            return int(raw)
        if isinstance(column_type, Numeric):
            return Decimal(raw)
        if isinstance(column_type, DateTime):
            moment = datetime.fromisoformat(raw)
            return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        if isinstance(column_type, Date):
            return date.fromisoformat(raw)
    except (ValueError, InvalidOperation) as exc:
        raise _invalid_filter(name) from exc
    return raw


def _filter_values(raw_values: Sequence[str]) -> list[str]:
    """Repeated parameters and comma-separated lists both mean "any of"; blanks are ignored."""
    return [part for raw in raw_values for part in raw.split(",") if part.strip()]


def _is_range_type(column: ColumnElement[Any]) -> bool:
    return isinstance(column.type, (Date, DateTime, Numeric, Integer)) and not isinstance(
        column.type, Boolean
    )


def _apply_filters(
    stmt: Select[Any], params: ListParams, filters: Mapping[str, ColumnElement[Any]]
) -> Select[Any]:
    for name, raw_values in params.filters.items():
        values = _filter_values(raw_values)
        if not values:
            continue
        if name in filters:
            column = filters[name]
            coerced = [_coerce(name, column, value) for value in values]
            stmt = stmt.where(column == coerced[0] if len(coerced) == 1 else column.in_(coerced))
            continue
        for suffix, operator in _RANGE_SUFFIXES:
            base = name.removesuffix(suffix)
            if name.endswith(suffix) and base in filters and _is_range_type(filters[base]):
                column = filters[base]
                bound = _coerce(name, column, values[0])
                if operator == "ge":
                    stmt = stmt.where(column >= bound)
                elif isinstance(column.type, DateTime) and len(values[0].strip()) == _ISO_DATE_LENGTH:
                    # A bare date as upper bound of a timestamp means "until the end of that day".
                    stmt = stmt.where(column < bound + timedelta(days=1))
                else:
                    stmt = stmt.where(column <= bound)
                break
    return stmt


def fold_search_text(value: str) -> str:
    """Case-fold for searching. Dotted and dotless i (İ, I, ı, i) count as one letter, so that
    "SATICILAR" finds "Satıcılar" whatever the database locale is."""
    return value.translate(_FOLD_TABLE).lower()


def _apply_search(stmt: Select[Any], q: str | None, search: Sequence[ColumnElement[Any]]) -> Select[Any]:
    term = fold_search_text((q or "").strip())
    if not term or not search:
        return stmt
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return stmt.where(
        or_(
            *(
                func.lower(func.translate(column, _FOLD_FROM, _FOLD_TO)).like(pattern, escape="\\")
                for column in search
            )
        )
    )


def _order_columns(spec: str, sort: Mapping[str, ColumnElement[Any]]) -> list[ColumnElement[Any]]:
    columns = []
    for part in spec.split(","):
        name = part.strip()
        if not name:
            continue
        descending = name.startswith("-")
        key = name.lstrip("+-")
        if key not in sort:
            raise ValidationFailed(
                "INVALID_SORT",
                f"Bu alana göre sıralama yapılamaz: {key}",
                details={"allowed": sorted(sort)},
            )
        columns.append(sort[key].desc() if descending else sort[key].asc())
    return columns


def paginate(
    ctx: UserContext,
    stmt: Select[Any],
    params: ListParams,
    *,
    search: Sequence[ColumnElement[Any]] = (),
    sort: Mapping[str, ColumnElement[Any]] | None = None,
    filters: Mapping[str, ColumnElement[Any]] | None = None,
    default_sort: str | None = None,
) -> PageData:
    """Apply the list contract to `stmt` and return one page.

    `sort` maps public names to columns (`?sort=-created_at,code`), `filters` maps query parameter names
    to columns: `?status=A,B` matches any value, and date/number columns also accept `<name>_from` /
    `<name>_to` bounds. `default_sort` uses the same syntax; it also breaks ties of a requested sort so
    that paging is stable. Statements selecting one entity return ORM objects, others return rows.
    """
    sort = sort or {}
    stmt = _apply_filters(stmt, params, filters or {})
    stmt = _apply_search(stmt, params.q, search)

    total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0

    order = _order_columns(params.sort, sort) if params.sort else []
    if default_sort:
        order.extend(_order_columns(default_sort, sort))
    if order:
        stmt = stmt.order_by(None).order_by(*order)
    stmt = stmt.limit(params.page_size).offset((params.page - 1) * params.page_size)

    result = ctx.db.execute(stmt)
    items = list(result.scalars().unique()) if len(stmt.column_descriptions) == 1 else list(result)
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}

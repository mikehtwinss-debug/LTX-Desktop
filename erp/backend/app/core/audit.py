"""Audit trail.

Models flagged `__audit__ = True` get one `org_audit_log` row per insert, update and delete with the
changed columns. Inserts and updates are captured in `before_flush` (while attribute history is still
available); deletes are captured as the flush performs them, because orphaned and cascaded rows are
only determined inside the flush. Everything is written in `after_flush`, once generated primary keys
are known. Services add explicit entries for business events (status changes, logins) with `log()`.

A model may list secret columns in `__audit_mask__`; their values are logged as `***`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, event, insert
from sqlalchemy import inspect as orm_inspect
from sqlalchemy.orm import Mapper, Session, UOWTransaction, object_session

from app.core.db import Base, utcnow
from app.modules.org.models import AuditLog

if TYPE_CHECKING:
    from app.core.context import UserContext

INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"

_PENDING_KEY = "audit_pending"
_BOOKKEEPING_COLUMNS = frozenset(
    {"id", "created_at", "updated_at", "created_by_id", "updated_by_id", "version"}
)
_MASK = "***"
_BINARY = "<binary>"


@dataclass(slots=True)
class _Pending:
    action: str
    obj: Any
    changes: dict[str, Any] | None  # None for inserts: snapshotted after the flush applied defaults


def _is_audited(obj: Any) -> bool:
    return getattr(type(obj), "__audit__", False) is True


def _render(obj: Any, key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in getattr(type(obj), "__audit_mask__", ()):
        return _MASK
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _BINARY
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _audited_keys(obj: Any) -> list[str]:
    mapper = orm_inspect(obj).mapper
    return [attr.key for attr in mapper.column_attrs if attr.key not in _BOOKKEEPING_COLUMNS]


def _snapshot(obj: Any, side: str) -> dict[str, Any]:
    loaded = orm_inspect(obj).dict
    return {
        key: {side: _render(obj, key, loaded[key])}
        for key in _audited_keys(obj)
        if loaded.get(key) is not None
    }


def _diff(obj: Any) -> dict[str, Any]:
    state = orm_inspect(obj)
    changes: dict[str, Any] = {}
    for key in _audited_keys(obj):
        history = state.attrs[key].history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if old != new:
            changes[key] = {"old": _render(obj, key, old), "new": _render(obj, key, new)}
    return changes


@event.listens_for(Session, "before_flush")
def _collect_changes(session: Session, flush_context: UOWTransaction, instances: Any) -> None:
    pending: list[_Pending] = []
    for obj in session.new:
        if _is_audited(obj):
            pending.append(_Pending(INSERT, obj, None))
    for obj in session.dirty:
        if _is_audited(obj) and session.is_modified(obj):
            changes = _diff(obj)
            if changes:
                pending.append(_Pending(UPDATE, obj, changes))
    # Replaced rather than extended: a failed flush leaves its objects pending and they are collected again.
    session.info[_PENDING_KEY] = pending


@event.listens_for(Base, "after_delete", propagate=True)
def _collect_delete(mapper: Mapper[Any], connection: Connection, target: Any) -> None:
    session = object_session(target)
    if session is not None and _is_audited(target):
        session.info.setdefault(_PENDING_KEY, []).append(_Pending(DELETE, target, _snapshot(target, "old")))


@event.listens_for(Session, "after_flush")
def _write_changes(session: Session, flush_context: UOWTransaction) -> None:
    pending: list[_Pending] = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    now = utcnow()
    user_id = session.info.get("user_id")
    rows = [
        {
            "company_id": getattr(entry.obj, "company_id", None),
            "at": now,
            "user_id": user_id,
            "action": entry.action,
            "entity": entry.obj.__tablename__,
            "entity_id": entry.obj.id,
            "summary": None,
            "changes": entry.changes if entry.changes is not None else _snapshot(entry.obj, "new"),
        }
        for entry in pending
    ]
    session.connection().execute(insert(AuditLog.__table__), rows)


def log(
    ctx: UserContext, action: str, entity: str, entity_id: int | None, summary: str | None = None
) -> AuditLog:
    """Record a business event (status change, login, ...) on behalf of the acting user."""
    entry = AuditLog(
        company_id=getattr(ctx, "company_id", None),
        user_id=ctx.user.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        summary=summary,
    )
    ctx.db.add(entry)
    return entry

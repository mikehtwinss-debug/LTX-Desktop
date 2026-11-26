"""Approval engine.

A feature registers a handler per object type (`PR`, `QCMP`, `PO`, ...) at import time. Submitting a
document creates an `ApprovalRequest` with one step per matching `ApprovalRule`; approvers work
through the levels in order, and when the request reaches `APPROVED` or `REJECTED` the handler runs
in the same transaction and moves the document status.

Rules of one level are alternatives: the first approver who decides completes the level and the
other steps of that level are skipped. Every transition locks the request row first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.interfaces import ORMOption

from app.core import audit
from app.core.db import utcnow
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.settings import get_setting, register_setting
from app.core.types import q_money
from app.modules.auth.models import UserRole
from app.modules.org.models import (
    ApprovalRequest,
    ApprovalRule,
    ApprovalStatus,
    ApprovalStep,
    ApprovalStepStatus,
)

if TYPE_CHECKING:
    from app.core.context import RequestContext

SELF_APPROVAL_SETTING = "approval.allow_self_approval"
register_setting(
    SELF_APPROVAL_SETTING, False, "Onaya gönderen kullanıcı kendi belgesini onaylayabilir veya reddedebilir"
)

Decision = Literal["approve", "reject"]

_ENTITY = ApprovalRequest.__tablename__
_OPEN_STEPS = (ApprovalStepStatus.PENDING, ApprovalStepStatus.WAITING)


@dataclass(frozen=True, slots=True)
class ApprovalDocument:
    """How the document of a request is shown in the approval inbox."""

    number: str
    title: str
    currency: str
    path: str  # frontend route of the document


ApprovalHandler = Callable[["RequestContext", int, bool, ApprovalRequest], None]
DescribeDocument = Callable[["RequestContext", int], ApprovalDocument | None]


@dataclass(frozen=True, slots=True)
class _Registration:
    handler: ApprovalHandler
    describe: DescribeDocument | None


_registry: dict[str, _Registration] = {}


def _identity(function: Callable[..., object] | None) -> tuple[str, str] | None:
    if function is None:
        return None
    return (function.__module__, function.__qualname__)


def register_approval_handler(
    object_type: str, handler: ApprovalHandler, describe: DescribeDocument | None = None
) -> None:
    """Declare the owner of an approval object type.

    `handler(ctx, object_id, approved, request)` runs when a request of this type is decided;
    `describe(ctx, object_id)` supplies number, title, currency and frontend path for the inbox.
    """
    existing = _registry.get(object_type)
    # Re-importing the owning module registers the same functions again; anything else is a clash.
    if existing is not None and (
        _identity(existing.handler) != _identity(handler)
        or _identity(existing.describe) != _identity(describe)
    ):
        raise ValueError(f"Approval object type {object_type!r} is already registered by another handler")
    _registry[object_type] = _Registration(handler=handler, describe=describe)


def _registration(object_type: str) -> _Registration:
    registration = _registry.get(object_type)
    if registration is None:
        raise LookupError(f"No approval handler is registered for object type {object_type!r}")
    return registration


def request_options() -> tuple[ORMOption, ...]:
    """Loader options for everything the API shows of a request."""
    return (
        joinedload(ApprovalRequest.requested_by),
        selectinload(ApprovalRequest.steps).options(
            joinedload(ApprovalStep.approver_role),
            joinedload(ApprovalStep.approver_user),
            joinedload(ApprovalStep.acted_by),
        ),
    )


def _role_ids(ctx: RequestContext) -> set[int]:
    """Roles the user holds in the active company, including assignments valid for every company."""
    return set(
        ctx.db.scalars(
            select(UserRole.role_id).where(
                UserRole.user_id == ctx.user.id,
                or_(UserRole.company_id == ctx.company_id, UserRole.company_id.is_(None)),
            )
        )
    )


def _is_approver(step: ApprovalStep, user_id: int, role_ids: set[int]) -> bool:
    return step.approver_user_id == user_id or step.approver_role_id in role_ids


def _current_steps(request: ApprovalRequest) -> list[ApprovalStep]:
    return [
        step
        for step in request.steps
        if step.level == request.current_level and step.status is ApprovalStepStatus.PENDING
    ]


def _self_approval_blocked(ctx: RequestContext, request: ApprovalRequest) -> bool:
    return request.requested_by_id == ctx.user.id and not get_setting(ctx, SELF_APPROVAL_SETTING)


def actionable_ids(ctx: RequestContext, requests: Iterable[ApprovalRequest]) -> set[int]:
    """Ids of those requests whose current step the user may decide right now."""
    role_ids = _role_ids(ctx)
    may_decide_own = bool(get_setting(ctx, SELF_APPROVAL_SETTING))
    return {
        request.id
        for request in requests
        if request.status is ApprovalStatus.PENDING
        and request.company_id == ctx.company_id
        and (may_decide_own or request.requested_by_id != ctx.user.id)
        and any(_is_approver(step, ctx.user.id, role_ids) for step in _current_steps(request))
    }


def can_act(ctx: RequestContext, request: ApprovalRequest) -> bool:
    return request.id in actionable_ids(ctx, [request])


def describe_document(ctx: RequestContext, request: ApprovalRequest) -> ApprovalDocument | None:
    """Number, title, currency and frontend path of the request's document, when its owner tells."""
    registration = _registry.get(request.object_type)
    if registration is None or registration.describe is None:
        return None
    return registration.describe(ctx, request.object_id)


def _close_open_steps(request: ApprovalRequest) -> None:
    for step in request.steps:
        if step.status in _OPEN_STEPS:
            step.status = ApprovalStepStatus.SKIPPED


def _complete(request: ApprovalRequest, status: ApprovalStatus, now: datetime) -> None:
    request.status = status
    request.completed_at = now
    request.current_level = None


def submit(ctx: RequestContext, object_type: str, object_id: int, amount_local: Decimal) -> ApprovalRequest:
    """Start the approval of a document worth `amount_local` (local currency).

    Every active rule of the object type with `min_amount <= amount_local` becomes a step. Without a
    matching rule the request is approved at once and the handler runs before this returns.
    """
    registration = _registration(object_type)
    amount = q_money(amount_local)
    if amount < 0:
        raise ValueError("Approval amount must not be negative")
    already_pending = ctx.db.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.company_id == ctx.company_id,
            ApprovalRequest.object_type == object_type,
            ApprovalRequest.object_id == object_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )
    if already_pending is not None:
        raise Conflict("APPROVAL_ALREADY_PENDING", "Bu belge için bekleyen bir onay talebi zaten var")

    rules = ctx.db.scalars(
        select(ApprovalRule)
        .where(
            ApprovalRule.company_id == ctx.company_id,
            ApprovalRule.object_type == object_type,
            ApprovalRule.is_active,
            ApprovalRule.min_amount <= amount,
        )
        .order_by(ApprovalRule.level, ApprovalRule.id)
    ).all()

    now = utcnow()
    request = ApprovalRequest(
        company_id=ctx.company_id,
        object_type=object_type,
        object_id=object_id,
        amount=amount,
        status=ApprovalStatus.PENDING,
        requested_by_id=ctx.user.id,
        requested_at=now,
    )
    if rules:
        first_level = rules[0].level
        request.current_level = first_level
        request.steps = [
            ApprovalStep(
                level=rule.level,
                approver_role_id=rule.approver_role_id,
                approver_user_id=rule.approver_user_id,
                status=ApprovalStepStatus.PENDING if rule.level == first_level else ApprovalStepStatus.WAITING,
            )
            for rule in rules
        ]
    else:
        _complete(request, ApprovalStatus.APPROVED, now)
    ctx.db.add(request)
    ctx.db.flush()

    if rules:
        audit.log(ctx, "APPROVAL_SUBMITTED", _ENTITY, request.id, f"{object_type} belgesi onaya gönderildi")
    else:
        audit.log(
            ctx,
            "APPROVAL_AUTO_APPROVED",
            _ENTITY,
            request.id,
            f"{object_type} belgesi için onay kuralı bulunmadığından doğrudan onaylandı",
        )
        registration.handler(ctx, object_id, True, request)
    return request


def _locked_request(ctx: RequestContext, request_id: int) -> ApprovalRequest:
    request = ctx.db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id, ApprovalRequest.company_id == ctx.company_id)
        .options(selectinload(ApprovalRequest.steps))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise NotFound("APPROVAL_NOT_FOUND", "Onay talebi bulunamadı")
    return request


def act(ctx: RequestContext, request_id: int, decision: Decision, comment: str | None) -> ApprovalRequest:
    """Approve or reject the current level of a request on behalf of the acting user.

    An approval moves on to the next level or completes the request; a rejection ends it. A
    rejection needs a comment. The requester may not decide their own request unless the company
    setting `approval.allow_self_approval` allows it.
    """
    if decision not in ("approve", "reject"):
        raise ValueError(f"Unknown approval decision: {decision!r}")
    request = _locked_request(ctx, request_id)
    if request.status is not ApprovalStatus.PENDING:
        raise Conflict(
            "APPROVAL_NOT_PENDING",
            "Onay talebi artık beklemede değil",
            details={"status": request.status.value},
        )
    role_ids = _role_ids(ctx)
    own_steps = [step for step in _current_steps(request) if _is_approver(step, ctx.user.id, role_ids)]
    if not own_steps:
        raise Forbidden("APPROVAL_NOT_ALLOWED", "Bu onay adımında işlem yapma yetkiniz yok")
    if _self_approval_blocked(ctx, request):
        raise Forbidden("SELF_APPROVAL_NOT_ALLOWED", "Kendi onaya gönderdiğiniz belgede karar veremezsiniz")
    note = (comment or "").strip() or None
    approved = decision == "approve"
    if not approved and note is None:
        message = "Reddetmek için bir açıklama yazılmalıdır"
        raise ValidationFailed("COMMENT_REQUIRED", message, details={"fields": {"comment": message}})

    now = utcnow()
    level = request.current_level
    # A step naming the user personally is preferred over one they only cover through a role.
    step = next((item for item in own_steps if item.approver_user_id == ctx.user.id), own_steps[0])
    step.status = ApprovalStepStatus.APPROVED if approved else ApprovalStepStatus.REJECTED
    step.acted_by_id = ctx.user.id
    step.acted_at = now
    step.comment = note

    if approved:
        for sibling in _current_steps(request):
            sibling.status = ApprovalStepStatus.SKIPPED
        waiting_levels = [item.level for item in request.steps if item.status is ApprovalStepStatus.WAITING]
        if waiting_levels:
            request.current_level = min(waiting_levels)
            for item in request.steps:
                if item.level == request.current_level and item.status is ApprovalStepStatus.WAITING:
                    item.status = ApprovalStepStatus.PENDING
        else:
            _complete(request, ApprovalStatus.APPROVED, now)
    else:
        _close_open_steps(request)
        _complete(request, ApprovalStatus.REJECTED, now)
    ctx.db.flush()

    summary = f"{request.object_type} belgesi {level}. seviyede {'onaylandı' if approved else 'reddedildi'}"
    audit.log(ctx, "APPROVAL_APPROVED" if approved else "APPROVAL_REJECTED", _ENTITY, request.id, summary)
    if request.status is not ApprovalStatus.PENDING:
        _registration(request.object_type).handler(ctx, request.object_id, approved, request)
    return request


def cancel(ctx: RequestContext, object_type: str, object_id: int) -> None:
    """Withdraw the pending request of a document, if there is one. The handler is not called: the
    owning module cancels as part of its own status change."""
    requests = ctx.db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.company_id == ctx.company_id,
            ApprovalRequest.object_type == object_type,
            ApprovalRequest.object_id == object_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
        .options(selectinload(ApprovalRequest.steps))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    now = utcnow()
    for request in requests:
        _close_open_steps(request)
        _complete(request, ApprovalStatus.CANCELLED, now)
        audit.log(ctx, "APPROVAL_CANCELLED", _ENTITY, request.id, f"{object_type} belgesinin onay talebi iptal edildi")
    ctx.db.flush()


def history(ctx: RequestContext, object_type: str, object_id: int) -> list[ApprovalRequest]:
    """Every approval request of a document, oldest first."""
    return list(
        ctx.db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.company_id == ctx.company_id,
                ApprovalRequest.object_type == object_type,
                ApprovalRequest.object_id == object_id,
            )
            .options(*request_options())
            .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
        )
    )


def inbox(ctx: RequestContext) -> list[ApprovalRequest]:
    """Pending requests of the active company whose current step the user may decide, oldest first."""
    role_ids = _role_ids(ctx)
    approver = ApprovalStep.approver_user_id == ctx.user.id
    if role_ids:
        approver = or_(approver, ApprovalStep.approver_role_id.in_(role_ids))
    stmt = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.company_id == ctx.company_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.steps.any(
                and_(
                    ApprovalStep.level == ApprovalRequest.current_level,
                    ApprovalStep.status == ApprovalStepStatus.PENDING,
                    approver,
                )
            ),
        )
        .options(*request_options())
        .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
    )
    if not get_setting(ctx, SELF_APPROVAL_SETTING):
        stmt = stmt.where(ApprovalRequest.requested_by_id != ctx.user.id)
    return list(ctx.db.scalars(stmt))

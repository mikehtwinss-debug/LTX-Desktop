"""Posting period lookup shared by every module that posts by date."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.errors import AppError
from app.modules.fi.models.gl import Period, PeriodStatus

if TYPE_CHECKING:
    from app.core.context import RequestContext


def _format(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def get_period(ctx: RequestContext, day: date, *, lock: bool = False) -> Period:
    """The posting period containing `day`; raises `PERIOD_MISSING` when none is defined.

    `lock=True` takes a shared row lock: postings may run side by side, but closing the period (which
    needs the exclusive lock) waits for them and they see the new status afterwards.
    """
    stmt = select(Period).where(
        Period.company_id == ctx.company_id, Period.start_date <= day, Period.end_date >= day
    )
    if lock:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    period = ctx.db.scalar(stmt)
    if period is None:
        raise AppError(
            "PERIOD_MISSING",
            f"{_format(day)} tarihi için tanımlı bir muhasebe dönemi yok",
            details={"date": day.isoformat()},
        )
    return period


def assert_period_open(ctx: RequestContext, day: date) -> Period:
    """The open posting period of `day`, share-locked until the transaction ends; raises
    `PERIOD_MISSING` or `PERIOD_CLOSED`."""
    period = get_period(ctx, day, lock=True)
    if period.status is not PeriodStatus.OPEN:
        raise AppError(
            "PERIOD_CLOSED",
            f"{period.year}/{period.period:02d} muhasebe dönemi kapalı",
            details={"year": period.year, "period": period.period, "date": day.isoformat()},
        )
    return period

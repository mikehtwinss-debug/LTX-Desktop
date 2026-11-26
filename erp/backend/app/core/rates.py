"""Exchange rates: local currency per one unit of a foreign currency."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.errors import AppError
from app.modules.org.models import Company, ExchangeRate, RateType

if TYPE_CHECKING:
    from app.core.context import RequestContext

_RATE_TYPE_LABELS = {RateType.ALIS: "alış", RateType.SATIS: "satış"}


def local_currency(ctx: RequestContext) -> str:
    """Currency in which the active company keeps its books."""
    return ctx.db.scalars(select(Company.currency_code).where(Company.id == ctx.company_id)).one()


def get_rate(
    ctx: RequestContext, currency_code: str, on_date: date, rate_type: RateType | str = RateType.ALIS
) -> Decimal:
    """Rate of `currency_code` valid on `on_date`: the latest entry on or before that date.

    The company's own currency always converts at 1. Raises `RATE_MISSING` when no rate was entered
    up to that date.
    """
    if currency_code == local_currency(ctx):
        return Decimal(1)
    kind = RateType(rate_type)
    rate = ctx.db.scalar(
        select(ExchangeRate.rate)
        .where(
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.rate_type == kind,
            ExchangeRate.rate_date <= on_date,
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    )
    if rate is None:
        raise AppError(
            "RATE_MISSING",
            f"{on_date:%d.%m.%Y} tarihi için {currency_code} {_RATE_TYPE_LABELS[kind]} kuru tanımlı değil",
            details={"currency_code": currency_code, "date": on_date.isoformat(), "rate_type": kind.value},
        )
    return rate

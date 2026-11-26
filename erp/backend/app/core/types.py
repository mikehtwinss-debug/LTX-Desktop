"""Shared column types and decimal helpers. Amounts are never floats."""

import enum
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Enum, Numeric

Money = Numeric(18, 2)
Qty = Numeric(18, 3)
Price = Numeric(18, 6)
Rate = Numeric(18, 6)
Pct = Numeric(9, 4)

_MONEY_QUANTUM = Decimal("0.01")
_QTY_QUANTUM = Decimal("0.001")
_PRICE_QUANTUM = Decimal("0.000001")


def q_money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def q_qty(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(_QTY_QUANTUM, rounding=ROUND_HALF_UP)


def q_price(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def enum_type(py_enum: type[enum.Enum]) -> Enum:
    """Column type for an enum stored as its upper-case value in a VARCHAR(32)."""
    return Enum(
        py_enum,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )

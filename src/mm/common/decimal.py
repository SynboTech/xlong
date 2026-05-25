from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 38


ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


def D(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        raise ValueError("cannot convert None to Decimal")
    return Decimal(str(value))


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        raise ValueError("increment must be positive")
    return (value / increment).to_integral_value(rounding=ROUND_FLOOR) * increment


def ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        raise ValueError("increment must be positive")
    return (value / increment).to_integral_value(rounding=ROUND_CEILING) * increment


def round_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        raise ValueError("increment must be positive")
    return (value / increment).to_integral_value(rounding=ROUND_HALF_UP) * increment


def bps_mul(price: Decimal, bps: Decimal) -> Decimal:
    return price * bps / BPS


def decimal_to_str(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f")


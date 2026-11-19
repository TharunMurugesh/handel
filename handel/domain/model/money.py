"""Money in integer paise (architecture §8: no floating-point money anywhere).

``Decimal`` is accepted only at the edges (parsing, scaling by a rate). Every result is
rounded back to whole paise with ROUND_HALF_UP (ties away from zero), so displayed
components always add up to displayed totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISE_PER_RUPEE = 100


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool | float):
        raise TypeError("money never uses float or bool; pass Decimal, int or str")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def round_paise(paise: Decimal) -> int:
    """Round a (possibly fractional) paise amount to whole paise, ties away from zero."""
    return int(paise.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True, order=True)
class Money:
    paise: int

    def __post_init__(self) -> None:
        if isinstance(self.paise, bool) or not isinstance(self.paise, int):
            raise TypeError("Money.paise must be an int")

    # ---- construction ----
    @classmethod
    def zero(cls) -> Money:
        return cls(0)

    @classmethod
    def rupees(cls, value: Decimal | int | str) -> Money:
        """``Money.rupees("62.45")`` → 6245 paise. Sub-paisa input is rounded."""
        return cls(round_paise(_to_decimal(value) * PAISE_PER_RUPEE))

    @classmethod
    def from_exact_paise(cls, paise: Decimal) -> Money:
        return cls(round_paise(paise))

    # ---- arithmetic ----
    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.paise + other.paise)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.paise - other.paise)

    def __neg__(self) -> Money:
        return Money(-self.paise)

    def exact(self) -> Decimal:
        """Paise as a Decimal, for multi-step formulas that round only once at the end."""
        return Decimal(self.paise)

    def scale(self, factor: Decimal | int | str) -> Money:
        """Multiply by a factor (a rate, a share), rounding once to whole paise."""
        return Money(round_paise(self.exact() * _to_decimal(factor)))

    def divide(self, divisor: Decimal | int | str) -> Money:
        d = _to_decimal(divisor)
        if d == 0:
            raise ZeroDivisionError("divide money by zero")
        return Money(round_paise(self.exact() / d))

    @staticmethod
    def total(items: list[Money] | tuple[Money, ...]) -> Money:
        return Money(sum((m.paise for m in items), 0))

    # ---- views ----
    def to_rupees(self) -> Decimal:
        return Decimal(self.paise) / PAISE_PER_RUPEE

    def is_negative(self) -> bool:
        return self.paise < 0

    def __str__(self) -> str:
        return format_inr(self)


def format_inr(money: Money) -> str:
    """Indian digit grouping: ₹12,34,567.89; negative as -₹0.92."""
    sign = "-" if money.paise < 0 else ""
    rupees, paise = divmod(abs(money.paise), PAISE_PER_RUPEE)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join([head, *groups, tail])  # head is 1–2 digits here, never empty
    return f"{sign}₹{digits}.{paise:02d}"

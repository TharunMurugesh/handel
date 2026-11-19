"""Money, weights, rate conversion and business hours."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from handel.domain.model.calendar import BusinessHours
from handel.domain.model.entities import (
    Charge,
    ChargeBasis,
    FreightEstimate,
    FreightQuote,
    PaymentKind,
    PaymentTerms,
)
from handel.domain.model.money import Money, format_inr
from handel.domain.model.quantity import MassUnit, RateUnit, Weight
from handel.domain.rules.weights import (
    flat_weight,
    rate_per_kg,
    round_bar_weight,
    sheet_weight,
)
from tests.unit.domain.builders import quote

IST = ZoneInfo("Asia/Kolkata")


# ---- Money ----
def test_rupees_parsing_and_rounding() -> None:
    assert Money.rupees("62.45").paise == 6245
    assert Money.rupees(62).paise == 6200
    assert Money.rupees("0.005").paise == 1  # half away from zero
    assert Money.rupees("-0.005").paise == -1
    assert Money.from_exact_paise(Decimal("92.25")).paise == 92


@pytest.mark.parametrize("bad", [62.5, True])
def test_money_rejects_float_and_bool(bad: Any) -> None:
    with pytest.raises(TypeError):
        Money.rupees(bad)


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity"])
def test_money_rejects_non_numbers(bad: str) -> None:
    with pytest.raises(ValueError):
        Money.rupees(bad)


def test_money_paise_must_be_int() -> None:
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(True)


def test_money_arithmetic() -> None:
    a, b = Money.rupees("10.10"), Money.rupees("0.95")
    assert a + b == Money.rupees("11.05")
    assert a - b == Money.rupees("9.15")
    assert -a == Money.rupees("-10.10")
    assert a.scale(Decimal("0.18")) == Money.rupees("1.82")  # 181.8 paise → 182
    assert a.divide(3) == Money(337)  # 336.67 → 337
    assert Money.total([a, b, b]) == Money.rupees("12.00")
    assert Money.total([]) == Money.zero()
    assert a.to_rupees() == Decimal("10.10")
    with pytest.raises(ZeroDivisionError):
        a.divide(0)


def test_money_does_not_mix_with_numbers() -> None:
    m = Money(1)
    with pytest.raises(TypeError):
        m + 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        m - 1  # type: ignore[operator]


@pytest.mark.parametrize(
    ("paise", "text"),
    [
        (0, "₹0.00"),
        (6245, "₹62.45"),
        (123456, "₹1,234.56"),
        (1234567, "₹12,345.67"),
        (123456789, "₹12,34,567.89"),
        (12345678901, "₹12,34,56,789.01"),
        (-92, "-₹0.92"),
    ],
)
def test_indian_number_format(paise: int, text: str) -> None:
    assert format_inr(Money(paise)) == text
    assert str(Money(paise)) == text


# ---- Weight and conversions ----
def test_weight_units() -> None:
    assert Weight.of("2", MassUnit.TONNE).kg == Decimal(2000)
    assert Weight.of(3, MassUnit.QUINTAL).kg == Decimal(300)
    assert str(Weight.of("46.6740")) == "46.674 kg"


@pytest.mark.parametrize("bad", ["0", "-1", "NaN"])
def test_weight_must_be_positive(bad: str) -> None:
    with pytest.raises(ValueError):
        Weight.of(bad)


def test_weight_rejects_float_and_non_decimal() -> None:
    with pytest.raises(TypeError):
        Weight.of(2.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Weight(2)  # type: ignore[arg-type]


def test_sheet_weight_8x4_2mm() -> None:
    assert sheet_weight(Decimal("2438.4"), Decimal("1219.2"), Decimal(2)).kg == Decimal("46.674")


def test_round_bar_and_flat_weights() -> None:
    # 16 mm bar, 1 m: π/4 × 16² × 1000 mm³ × 7.85 g/cm³ = 1.578 kg (tables: 1.58 kg/m)
    assert round_bar_weight(Decimal(16), Decimal(1000)).kg == Decimal("1.578")
    # 50 × 6 flat, 1 m: 50 × 6 × 1000 × 7.85 / 10^6 = 2.355 kg
    assert flat_weight(Decimal(50), Decimal(6), Decimal(1000)).kg == Decimal("2.355")


def test_weight_inputs_validated() -> None:
    with pytest.raises(ValueError):
        sheet_weight(Decimal(0), Decimal(1), Decimal(1))
    with pytest.raises(TypeError):
        sheet_weight(1, Decimal(1), Decimal(1))  # type: ignore[arg-type]


def test_rate_per_kg() -> None:
    assert rate_per_kg(Money.rupees("61500"), RateUnit.PER_TONNE) == Money.rupees("61.50")
    assert rate_per_kg(Money.rupees("6150"), RateUnit.PER_QUINTAL) == Money.rupees("61.50")
    assert rate_per_kg(Money.rupees("62"), RateUnit.PER_KG) == Money.rupees("62")
    piece = Weight.of("46.674")
    assert rate_per_kg(Money.rupees("2900"), RateUnit.PER_PIECE, piece) == Money.rupees("62.13")
    with pytest.raises(ValueError):
        rate_per_kg(Money.rupees("2900"), RateUnit.PER_PIECE)
    with pytest.raises(ValueError):
        rate_per_kg(Money.zero(), RateUnit.PER_KG)


# ---- entities ----
def test_payment_terms_d_pay() -> None:
    assert PaymentTerms(kind=PaymentKind.ADVANCE, days=15).d_pay == 15
    assert PaymentTerms(kind=PaymentKind.CREDIT, days=30).d_pay == -30
    assert PaymentTerms(kind=PaymentKind.CREDIT, days=30).credit_days == 30
    assert PaymentTerms(kind=PaymentKind.ON_DELIVERY).d_pay == 0
    assert PaymentTerms(kind=PaymentKind.ADVANCE, days=5).credit_days == 0
    with pytest.raises(ValidationError):
        PaymentTerms(kind=PaymentKind.ON_DELIVERY, days=3)


def test_entities_reject_negative_or_zero_money() -> None:
    with pytest.raises(ValidationError):
        Charge(name="loading", amount=Money(-1), basis=ChargeBasis.LUMP_SUM)
    with pytest.raises(ValidationError):
        FreightQuote(id="F", transporter_id="T", amount=Money.zero())
    with pytest.raises(ValidationError):
        FreightEstimate(per_kg=Money(-1), source="book")
    with pytest.raises(ValidationError):
        quote(rate=Money.zero())


# ---- business hours ----
HOURS = BusinessHours()  # Mon–Sat 09:30–18:30 IST


def _ist(*args: int) -> datetime:
    return datetime(*args, tzinfo=IST)  # type: ignore[misc]


def test_business_hours_same_day() -> None:
    assert HOURS.add(_ist(2026, 12, 1, 10, 0), timedelta(hours=2)) == _ist(2026, 12, 1, 12, 0)


def test_business_hours_roll_over_evening_and_sunday() -> None:
    # Sat 5 Dec 17:30 + 2h → 1h left Saturday, Sunday closed, Monday 7 Dec 10:30
    assert HOURS.add(_ist(2026, 12, 5, 17, 30), timedelta(hours=2)) == _ist(2026, 12, 7, 10, 30)


def test_business_hours_start_after_closing_moves_to_next_day() -> None:
    # Tue 1 Dec 19:00, after closing → Wed 2 Dec 09:30 + 2h
    assert HOURS.add(_ist(2026, 12, 1, 19, 0), timedelta(hours=2)) == _ist(2026, 12, 2, 11, 30)


def test_business_hours_before_opening_and_utc_input() -> None:
    start = datetime(2026, 12, 1, 1, 0, tzinfo=UTC)  # 06:30 IST, before opening
    assert HOURS.add(start, timedelta(hours=2)) == _ist(2026, 12, 1, 11, 30)


def test_business_hours_validation() -> None:
    with pytest.raises(ValueError):
        BusinessHours(opens=time(18), closes=time(9))
    with pytest.raises(ValueError):
        BusinessHours(weekdays=frozenset())
    with pytest.raises(ValueError):
        BusinessHours(weekdays=frozenset({7}))
    with pytest.raises(ValueError):
        HOURS.add(datetime(2026, 12, 1, 10), timedelta(hours=1))
    with pytest.raises(ValueError):
        HOURS.add(_ist(2026, 12, 1, 10), timedelta(hours=-1))

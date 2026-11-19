"""Steel weights and rate conversion (spec M-02, RULE-L1).

Weights use standard formulas rather than a lookup table, so every figure can be
re-derived by hand. ``WEIGHT_RULES_VERSION`` is recorded in traces; bump it whenever a
formula or density changes.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from handel.domain.model.money import Money, round_paise
from handel.domain.model.quantity import KG_PER, RateUnit, Weight

WEIGHT_RULES_VERSION = "SW-2026.1"
STEEL_DENSITY_G_PER_CM3 = Decimal("7.85")  # mild steel
_GRAM = Decimal("0.001")
_MM3_PER_CM3 = Decimal(1000)
_G_PER_KG = Decimal(1000)


def _pos(name: str, value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _weight_from_mm3(volume_mm3: Decimal, density: Decimal) -> Weight:
    kg = volume_mm3 / _MM3_PER_CM3 * density / _G_PER_KG
    return Weight(kg.quantize(_GRAM, rounding=ROUND_HALF_UP))


def sheet_weight(
    length_mm: Decimal,
    width_mm: Decimal,
    thickness_mm: Decimal,
    density: Decimal = STEEL_DENSITY_G_PER_CM3,
) -> Weight:
    """Plate/sheet: L × W × t × 7.85 (mm, g/cm³) → kg, to the gram.

    8 ft × 4 ft × 2 mm (2438.4 × 1219.2 × 2) → 46.674 kg.
    """
    volume = _pos("length", length_mm) * _pos("width", width_mm) * _pos("thickness", thickness_mm)
    return _weight_from_mm3(volume, _pos("density", density))


def round_bar_weight(diameter_mm: Decimal, length_mm: Decimal) -> Weight:
    """Round bar: π/4 × d² × L × density."""
    d = _pos("diameter", diameter_mm)
    pi = Decimal("3.14159265358979")
    volume = pi / 4 * d * d * _pos("length", length_mm)
    return _weight_from_mm3(volume, STEEL_DENSITY_G_PER_CM3)


def flat_weight(width_mm: Decimal, thickness_mm: Decimal, length_mm: Decimal) -> Weight:
    return sheet_weight(length_mm, width_mm, thickness_mm)


def rate_per_kg(rate: Money, unit: RateUnit, piece_weight: Weight | None = None) -> Money:
    """RULE-L1: convert a quoted rate to ₹/kg, rounded once to the paisa."""
    if rate.paise <= 0:
        raise ValueError("rate must be positive")
    mass_unit = unit.mass_unit
    if mass_unit is not None:
        return Money(round_paise(rate.exact() / KG_PER[mass_unit]))
    if piece_weight is None:
        raise ValueError("a per-piece rate needs the piece weight")
    return Money(round_paise(rate.exact() / piece_weight.kg))

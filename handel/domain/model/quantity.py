"""Weights and quantity units (spec M-02 conversions)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class MassUnit(StrEnum):
    KG = "kg"
    QUINTAL = "quintal"
    TONNE = "tonne"


KG_PER: dict[MassUnit, Decimal] = {
    MassUnit.KG: Decimal(1),
    MassUnit.QUINTAL: Decimal(100),
    MassUnit.TONNE: Decimal(1000),
}


@dataclass(frozen=True, slots=True, order=True)
class Weight:
    """A strictly positive weight in kilograms (exact Decimal)."""

    kg: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.kg, Decimal):
            raise TypeError("Weight.kg must be a Decimal")
        if not self.kg.is_finite() or self.kg <= 0:
            raise ValueError(f"weight must be positive, got {self.kg}")

    @classmethod
    def of(cls, value: Decimal | int | str, unit: MassUnit = MassUnit.KG) -> Weight:
        if isinstance(value, float | bool):
            raise TypeError("weights never use float")
        return cls(Decimal(value) * KG_PER[unit])

    def __str__(self) -> str:
        return f"{self.kg.normalize():f} kg"


class RateUnit(StrEnum):
    """What a quoted rate is per. Piece-type units need the piece weight to compare."""

    PER_KG = "per_kg"
    PER_QUINTAL = "per_quintal"
    PER_TONNE = "per_tonne"
    PER_PIECE = "per_piece"  # sheet, plate, bar, length, ...

    @property
    def mass_unit(self) -> MassUnit | None:
        return {
            RateUnit.PER_KG: MassUnit.KG,
            RateUnit.PER_QUINTAL: MassUnit.QUINTAL,
            RateUnit.PER_TONNE: MassUnit.TONNE,
        }.get(self)

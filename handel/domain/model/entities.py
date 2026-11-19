"""Entities and value objects from spec §9 needed by the buy-side rules.

Fields a supplier didn't state are ``None`` (missing), never guessed (spec M-04).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from handel.domain.model.calendar import BusinessHours
from handel.domain.model.money import Money
from handel.domain.model.quantity import RateUnit, Weight

_FROZEN = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class SupplierMode(StrEnum):
    COMPETE = "compete"
    RELATIONSHIP = "relationship"  # FR-BUY-14: no rank feedback, no rounds


class Role(StrEnum):
    OWNER = "owner"
    DELEGATE = "delegate"
    OPERATOR = "operator"


class Unit(BaseModel):
    """The owner's factory, with the settings landed cost and bidding depend on."""

    model_config = _FROZEN

    id: str
    name: str
    itc_eligible: bool  # claims GST input tax credit (RULE-L4)
    # r in RULE-L5: owner's cost of money per month, e.g. 0.015 for 1.5%/month.
    cost_of_money_monthly: Decimal = Field(ge=0, le=Decimal("0.10"))
    business_hours: BusinessHours = BusinessHours()
    min_margin: Decimal = Field(default=Decimal("0.05"), ge=0)
    target_margin: Decimal = Field(default=Decimal("0.12"), ge=0)


class Supplier(BaseModel):
    model_config = _FROZEN

    id: str
    name: str
    mode: SupplierMode = SupplierMode.COMPETE
    reliability: Decimal | None = Field(default=None, ge=0, le=1)  # from memory; None = unknown


class Material(BaseModel):
    model_config = _FROZEN

    id: str
    category: str  # e.g. "MS sheet"
    standard_gst_pct: Decimal = Field(default=Decimal(18), ge=0, le=100)  # used when GST missing


class Need(BaseModel):
    model_config = _FROZEN

    id: str
    unit_id: str
    material_id: str
    spec: str
    quantity: Weight
    needed_by: date
    location: str
    ceiling_per_kg: Money | None = None  # BD-01: never disclosed to suppliers
    target_per_kg: Money | None = None  # bidding stops early when met


class FreightTerms(StrEnum):
    DELIVERED = "delivered"
    EX_YARD = "ex_yard"


class PaymentKind(StrEnum):
    ADVANCE = "advance"
    ON_DELIVERY = "on_delivery"
    CREDIT = "credit"


class PaymentTerms(BaseModel):
    model_config = _FROZEN

    kind: PaymentKind
    days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def _days_match_kind(self) -> PaymentTerms:
        if self.kind is PaymentKind.ON_DELIVERY and self.days != 0:
            raise ValueError("on-delivery payment has no days")
        return self

    @property
    def d_pay(self) -> int:
        """RULE-L5: days paid before delivery. Advance positive, credit negative."""
        if self.kind is PaymentKind.ADVANCE:
            return self.days
        if self.kind is PaymentKind.CREDIT:
            return -self.days
        return 0

    @property
    def credit_days(self) -> int:
        return self.days if self.kind is PaymentKind.CREDIT else 0


class ChargeBasis(StrEnum):
    PER_KG = "per_kg"
    LUMP_SUM = "lump_sum"


class Charge(BaseModel):
    model_config = _FROZEN

    name: str  # loading, unloading, cutting, ...
    amount: Money
    basis: ChargeBasis

    @model_validator(mode="after")
    def _non_negative(self) -> Charge:
        if self.amount.is_negative():
            raise ValueError("charges cannot be negative")
        return self


class Via(StrEnum):
    DIRECT = "direct"
    RELAY = "relay"


class Quote(BaseModel):
    """A structured supplier quote (spec M-04 output)."""

    model_config = _FROZEN

    id: str
    case_id: str
    supplier_id: str
    round: int = Field(default=0, ge=0, le=2)
    via: Via = Via.DIRECT
    received_at: datetime

    rate: Money | None = None
    rate_unit: RateUnit | None = None
    piece_weight: Weight | None = None  # needed when rate_unit is PER_PIECE
    quantity: Weight | None = None  # None → the need's quantity, labelled assumed
    gst_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tax_invoice: bool | None = None
    freight_terms: FreightTerms | None = None
    charges: tuple[Charge, ...] = ()
    payment: PaymentTerms | None = None
    delivery_date: date | None = None
    valid_until: date | None = None

    deviations: tuple[str, ...] = ()  # spec mismatches flagged by M-04
    deviations_resolved: bool = False
    from_history: frozenset[str] = frozenset()  # field names filled from supplier history

    @model_validator(mode="after")
    def _positive_rate(self) -> Quote:
        if self.rate is not None and self.rate.paise <= 0:
            raise ValueError("a quoted rate must be positive")
        return self

    @property
    def has_unresolved_deviation(self) -> bool:
        return bool(self.deviations) and not self.deviations_resolved


class FreightQuote(BaseModel):
    """A transporter's lump-sum price for moving this load (M-03, RULE-L2)."""

    model_config = _FROZEN

    id: str
    transporter_id: str
    amount: Money
    valid_until: date | None = None

    @model_validator(mode="after")
    def _positive(self) -> FreightQuote:
        if self.amount.paise <= 0:
            raise ValueError("freight amount must be positive")
        return self


class FreightEstimate(BaseModel):
    """Transporter-book rate used until a real freight quote exists (labelled *estimate*)."""

    model_config = _FROZEN

    per_kg: Money
    source: str

    @model_validator(mode="after")
    def _non_negative(self) -> FreightEstimate:
        if self.per_kg.is_negative():
            raise ValueError("freight estimate cannot be negative")
        return self

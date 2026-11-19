"""Landed-cost engine: RULE-L1 to RULE-L6 (spec §8.1, M-05).

``effective_landed = base + freight + charges + tax + money``, all per kg.

Rounding: each component is rounded once to the paisa; ``effective`` is the sum of the
rounded components, so the parts shown to the owner always add up to the total.

Handel assumptions (not stated in the spec; revisit with real quotes):
- GST is applied to ``base + charges``. Delivered freight is already inside ``base``.
  GST on separately-hired transport (GTA) is not modelled yet.
- A quote without a stated quantity is costed for the need's quantity (labelled *assumed*).
- Missing payment terms are costed as payment on delivery (labelled *assumed*).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from handel.domain.model.entities import (
    ChargeBasis,
    FreightEstimate,
    FreightQuote,
    FreightTerms,
    Material,
    Need,
    PaymentKind,
    PaymentTerms,
    Quote,
    Unit,
)
from handel.domain.model.money import Money, round_paise
from handel.domain.model.quantity import Weight
from handel.domain.model.trace import Trace, TraceStep
from handel.domain.rules.weights import WEIGHT_RULES_VERSION, rate_per_kg

DAYS_PER_MONTH = Decimal(30)  # RULE-L5


class Label(StrEnum):
    """How a component's value was obtained (spec M-05)."""

    QUOTED = "quoted"
    ESTIMATED = "estimated"
    ASSUMED = "assumed"
    FROM_HISTORY = "from history"
    ITC_CLAIMED = "input tax credit claimed"


class Flag(StrEnum):
    """Warnings on the quote as a whole."""

    LATE = "late"  # delivers after the need date (RULE-L6)
    STALE = "stale"  # validity has passed; refresh before award (RULE-L6, FR-BUY-07)
    ITC_NOT_ELIGIBLE = "not eligible for input tax credit"  # no tax invoice (RULE-L4)
    DELIVERY_UNKNOWN = "delivery date missing"
    VALIDITY_UNKNOWN = "validity missing"
    DEVIATION = "does not match the specification"


class QuoteNotCostableError(ValueError):
    """The quote lacks a field landed cost can't do without. Ask the sender (MSG-04)."""

    def __init__(self, quote_id: str, missing: tuple[str, ...]) -> None:
        super().__init__(f"quote {quote_id} cannot be costed; missing: {', '.join(missing)}")
        self.quote_id = quote_id
        self.missing = missing


@dataclass(frozen=True, slots=True)
class Component:
    per_kg: Money
    labels: frozenset[Label]
    note: str = ""


@dataclass(frozen=True, slots=True)
class LandedCost:
    quote_id: str
    supplier_id: str
    base: Component
    freight: Component
    charges: Component
    tax: Component
    money: Component
    flags: frozenset[Flag]
    quantity: Weight
    trace: Trace = field(compare=False)

    @property
    def effective(self) -> Money:
        return Money.total([c.per_kg for c in self.components.values()])

    @property
    def components(self) -> dict[str, Component]:
        return {
            "base": self.base,
            "freight": self.freight,
            "charges": self.charges,
            "tax": self.tax,
            "money": self.money,
        }

    def total_for_quantity(self) -> Money:
        return self.effective.scale(self.quantity.kg)


def _fmt_pct(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def _provenance(quote: Quote, field_name: str) -> Label:
    return Label.FROM_HISTORY if field_name in quote.from_history else Label.QUOTED


def landed_cost(
    quote: Quote,
    need: Need,
    unit: Unit,
    material: Material,
    today: date,
    freight_quotes: tuple[FreightQuote, ...] = (),
    freight_estimate: FreightEstimate | None = None,
) -> LandedCost:
    """Apply RULE-L1..L6 to one quote.

    Raises ``QuoteNotCostableError`` if a field it cannot do without is missing.
    """
    missing: list[str] = []
    if quote.rate is None:
        missing.append("rate")
    if quote.rate_unit is None:
        missing.append("rate_unit")
    if quote.freight_terms is None:
        missing.append("freight_terms")
    if (
        quote.rate_unit is not None
        and quote.rate_unit.mass_unit is None
        and quote.piece_weight is None
    ):
        missing.append("piece_weight")
    usable_freight = tuple(
        f for f in freight_quotes if f.valid_until is None or f.valid_until >= today
    )
    if (
        quote.freight_terms is FreightTerms.EX_YARD
        and not usable_freight
        and freight_estimate is None
    ):
        missing.append("freight")
    if missing:
        raise QuoteNotCostableError(quote.id, tuple(missing))
    assert (
        quote.rate is not None and quote.rate_unit is not None
    )  # narrowed above, for the type checker

    steps: list[TraceStep] = []

    # Quantity used for lump sums.
    if quote.quantity is not None:
        qty, qty_label = quote.quantity, _provenance(quote, "quantity")
    else:
        qty, qty_label = need.quantity, Label.ASSUMED
    qty_kg = qty.kg

    # RULE-L1: base
    base = rate_per_kg(quote.rate, quote.rate_unit, quote.piece_weight)
    base_inputs: list[tuple[str, str]] = [("rate", f"{quote.rate} {quote.rate_unit.value}")]
    if quote.piece_weight is not None and quote.rate_unit.mass_unit is None:
        base_inputs.append(("piece weight", f"{quote.piece_weight} ({WEIGHT_RULES_VERSION})"))
    steps.append(
        TraceStep(
            "RULE-L1", "base rate", "quoted rate converted to ₹/kg", tuple(base_inputs), str(base)
        )
    )
    base_c = Component(base, frozenset({_provenance(quote, "rate")}))

    # RULE-L2: freight
    if quote.freight_terms is FreightTerms.DELIVERED:
        freight_c = Component(
            Money.zero(), frozenset({_provenance(quote, "freight_terms")}), "delivered"
        )
        steps.append(TraceStep("RULE-L2", "freight", "delivered → 0", (), str(Money.zero())))
    elif usable_freight:
        best = min(usable_freight, key=lambda f: (f.amount, f.id))
        per_kg = Money(round_paise(best.amount.exact() / qty_kg))
        freight_c = Component(
            per_kg, frozenset({Label.QUOTED}), f"best of {len(usable_freight)} freight quote(s)"
        )
        steps.append(
            TraceStep(
                "RULE-L2",
                "freight",
                "best quoted freight ÷ quantity",
                (
                    ("freight quote", f"{best.amount} ({best.transporter_id})"),
                    ("quantity", str(qty)),
                ),
                str(per_kg),
            )
        )
    else:
        assert freight_estimate is not None  # checked above
        freight_c = Component(
            freight_estimate.per_kg,
            frozenset({Label.ESTIMATED}),
            f"estimate: {freight_estimate.source}",
        )
        steps.append(
            TraceStep(
                "RULE-L2",
                "freight",
                "transporter-book estimate until a freight quote exists",
                (("estimate", f"{freight_estimate.per_kg}/kg ({freight_estimate.source})"),),
                str(freight_estimate.per_kg),
            )
        )

    # RULE-L3: charges, rounded once
    exact_charges = Decimal(0)
    for charge in quote.charges:
        exact_charges += (
            charge.amount.exact()
            if charge.basis is ChargeBasis.PER_KG
            else charge.amount.exact() / qty_kg
        )
    charges = Money(round_paise(exact_charges))
    charge_labels = frozenset({_provenance(quote, "charges")})
    if any(c.basis is ChargeBasis.LUMP_SUM for c in quote.charges) and qty_label is Label.ASSUMED:
        charge_labels |= {Label.ASSUMED}
    charges_c = Component(charges, charge_labels, ", ".join(c.name for c in quote.charges))
    steps.append(
        TraceStep(
            "RULE-L3",
            "charges",
            "per-kg charges + lump sums ÷ quantity",
            (
                *((c.name, f"{c.amount} {c.basis.value}") for c in quote.charges),
                ("quantity", f"{qty} ({qty_label.value})"),
            ),
            str(charges),
        )
    )

    # RULE-L4: tax
    flags: set[Flag] = set()
    invoice = quote.tax_invoice is True
    if not invoice:
        flags.add(Flag.ITC_NOT_ELIGIBLE)
    if unit.itc_eligible and invoice:
        tax_c = Component(Money.zero(), frozenset({Label.ITC_CLAIMED}))
        steps.append(
            TraceStep("RULE-L4", "tax", "input tax credit claimed → 0", (), str(Money.zero()))
        )
    else:
        if quote.gst_pct is not None:
            gst, gst_label = quote.gst_pct, _provenance(quote, "gst_pct")
        else:
            gst, gst_label = material.standard_gst_pct, Label.ASSUMED
        taxable = base + charges
        tax = taxable.scale(gst / 100)
        tax_c = Component(tax, frozenset({gst_label}), f"GST {_fmt_pct(gst)}")
        steps.append(
            TraceStep(
                "RULE-L4",
                "tax",
                "(base + charges) × GST%",
                (("taxable", str(taxable)), ("GST", f"{_fmt_pct(gst)} ({gst_label.value})")),
                str(tax),
            )
        )

    # RULE-L5: cost of money
    if quote.payment is not None:
        payment, pay_label = quote.payment, _provenance(quote, "payment")
    else:
        payment, pay_label = PaymentTerms(kind=PaymentKind.ON_DELIVERY), Label.ASSUMED
    r = unit.cost_of_money_monthly
    financed = base + freight_c.per_kg + charges
    money = Money(round_paise(financed.exact() * r * Decimal(payment.d_pay) / DAYS_PER_MONTH))
    money_c = Component(money, frozenset({pay_label}), f"{payment.kind.value} {payment.days}d")
    steps.append(
        TraceStep(
            "RULE-L5",
            "cost of money",
            "(base + freight + charges) × r × d_pay/30",
            (
                ("base + freight + charges", str(financed)),
                ("r (per month)", _fmt_pct(r * 100)),
                ("d_pay", f"{payment.d_pay} days ({pay_label.value})"),
            ),
            str(money),
        )
    )

    # RULE-L6: flags
    if quote.delivery_date is None:
        flags.add(Flag.DELIVERY_UNKNOWN)
    elif quote.delivery_date > need.needed_by:
        flags.add(Flag.LATE)
    if quote.valid_until is None:
        flags.add(Flag.VALIDITY_UNKNOWN)
    elif quote.valid_until < today:
        flags.add(Flag.STALE)
    if quote.has_unresolved_deviation:
        flags.add(Flag.DEVIATION)

    result = LandedCost(
        quote_id=quote.id,
        supplier_id=quote.supplier_id,
        base=base_c,
        freight=freight_c,
        charges=charges_c,
        tax=tax_c,
        money=money_c,
        flags=frozenset(flags),
        quantity=qty,
        trace=Trace(()),
    )
    steps.append(
        TraceStep(
            "RULE-L6",
            "effective landed",
            "base + freight + charges + tax + money",
            tuple((name, str(c.per_kg)) for name, c in result.components.items()),
            str(result.effective),
        )
    )
    return replace(result, trace=Trace(tuple(steps)))

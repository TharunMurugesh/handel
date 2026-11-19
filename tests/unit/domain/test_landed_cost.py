"""Landed cost: Q-03 hand-worked cases, AT-04, and edge cases for RULE-L1..L6."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from handel.domain.model.entities import (
    Charge,
    ChargeBasis,
    FreightEstimate,
    FreightQuote,
    FreightTerms,
    PaymentKind,
    PaymentTerms,
    Quote,
)
from handel.domain.model.money import Money
from handel.domain.model.quantity import RateUnit, Weight
from handel.domain.rules.explain import explain_landed_cost, explain_step
from handel.domain.rules.landed_cost import Flag, Label, QuoteNotCostableError, landed_cost
from tests.unit.domain.builders import TODAY, material, need, quote, unit

CASES_FILE = Path(__file__).parents[2] / "data" / "q03_landed_cost_cases.json"
DATA = json.loads(CASES_FILE.read_text(encoding="utf-8"))
DEFAULTS = DATA["defaults"]


def _rupees(v: str | None) -> Money | None:
    return None if v is None else Money.rupees(v)


def _build(case: dict[str, Any]) -> dict[str, Any]:
    u = DEFAULTS["unit"] | case.get("unit", {})
    q = DEFAULTS["quote"] | case["quote"]
    pay = q["payment"]
    quote_obj = Quote(
        id=case["id"],
        case_id="C",
        supplier_id="S",
        received_at="2026-12-01T10:00:00+00:00",
        rate=_rupees(q["rate"]),
        rate_unit=RateUnit(q["rate_unit"]),
        piece_weight=Weight.of(q["piece_weight_kg"]) if q.get("piece_weight_kg") else None,
        quantity=Weight.of(q["quantity_kg"]) if q["quantity_kg"] else None,
        gst_pct=None if q["gst_pct"] is None else Decimal(q["gst_pct"]),
        tax_invoice=q["tax_invoice"],
        freight_terms=FreightTerms(q["freight_terms"]),
        charges=tuple(
            Charge(name=c["name"], amount=Money.rupees(c["amount"]), basis=ChargeBasis(c["basis"]))
            for c in q.get("charges", [])
        ),
        payment=None
        if pay is None
        else PaymentTerms(kind=PaymentKind(pay["kind"]), days=pay["days"]),
        delivery_date=date.fromisoformat(q["delivery_date"]),
        valid_until=date.fromisoformat(q["valid_until"]),
    )
    est = case.get("freight_estimate_per_kg")
    return {
        "quote": quote_obj,
        "need": need(
            quantity=Weight.of(case.get("need_qty_kg", DEFAULTS["need_qty_kg"])),
            needed_by=date.fromisoformat(DEFAULTS["needed_by"]),
        ),
        "unit": unit(itc_eligible=u["itc_eligible"], cost_of_money_monthly=Decimal(u["r"])),
        "material": material(standard_gst_pct=Decimal(DEFAULTS["material_standard_gst_pct"])),
        "today": date.fromisoformat(DEFAULTS["today"]),
        "freight_quotes": tuple(
            FreightQuote(id=f["id"], transporter_id="T", amount=Money.rupees(f["amount"]))
            for f in case.get("freight_quotes", [])
        ),
        "freight_estimate": None
        if est is None
        else FreightEstimate(per_kg=Money.rupees(est), source="transporter book"),
    }


def test_q03_has_twenty_cases() -> None:
    assert len(DATA["cases"]) == 20
    assert len({c["id"] for c in DATA["cases"]}) == 20


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_q03_matches_hand_calculation_to_the_paisa(case: dict[str, Any]) -> None:
    lc = landed_cost(**_build(case))
    exp = case["expected"]
    for name in ("base", "freight", "charges", "tax", "money"):
        assert lc.components[name].per_kg == Money.rupees(exp[name]), name
    assert lc.effective == Money.rupees(exp["effective"])
    shown = {f.value for f in lc.flags} - {Flag.DELIVERY_UNKNOWN.value, Flag.VALIDITY_UNKNOWN.value}
    assert shown == set(exp["flags"])
    for key, component in (
        ("freight_label", "freight"),
        ("tax_label", "tax"),
        ("money_label", "money"),
    ):
        if key in exp:
            assert Label(exp[key]) in lc.components[component].labels


def test_at04_ex_yard_advance_vs_delivered_credit() -> None:
    """AT-04: effective landed costs follow RULE-L1..L6 with every component labelled."""
    u, m, n = unit(), material(), need()
    ex_yard_advance = quote(
        "QA",
        rate=Money.rupees("60.50"),
        freight_terms=FreightTerms.EX_YARD,
        payment=PaymentTerms(kind=PaymentKind.ADVANCE, days=7),
    )
    delivered_credit = quote(
        "QB",
        rate=Money.rupees("63.00"),
        payment=PaymentTerms(kind=PaymentKind.CREDIT, days=30),
    )
    a = landed_cost(
        ex_yard_advance,
        n,
        u,
        m,
        TODAY,
        freight_estimate=FreightEstimate(per_kg=Money.rupees("1.60"), source="book"),
    )
    b = landed_cost(delivered_credit, n, u, m, TODAY)
    # a: 60.50 + 1.60 + 0 + 0 + (62.10 × 0.015 × 7/30 = 0.217 → 0.22) = 62.32
    assert a.effective == Money.rupees("62.32")
    # b: 63.00 + 0 + 0 + 0 + (63.00 × 0.015 × -1 = -0.945 → -0.95) = 62.05
    assert b.effective == Money.rupees("62.05")
    # The lower quoted rate is not the lower landed cost.
    assert ex_yard_advance.rate is not None and delivered_credit.rate is not None
    assert ex_yard_advance.rate < delivered_credit.rate and b.effective < a.effective
    for lc in (a, b):
        assert all(c.labels for c in lc.components.values())
    assert Label.ESTIMATED in a.freight.labels
    assert [s.rule for s in a.trace.steps] == [f"RULE-L{i}" for i in range(1, 7)]


# ---- missing fields: never guessed ----
@pytest.mark.parametrize(
    ("override", "missing"),
    [
        ({"rate": None}, "rate"),
        ({"rate_unit": None}, "rate_unit"),
        ({"freight_terms": None}, "freight_terms"),
        ({"rate_unit": RateUnit.PER_PIECE}, "piece_weight"),
        ({"freight_terms": FreightTerms.EX_YARD}, "freight"),
    ],
)
def test_missing_key_field_is_not_costable(override: dict[str, Any], missing: str) -> None:
    with pytest.raises(QuoteNotCostableError) as err:
        landed_cost(quote(**override), need(), unit(), material(), TODAY)
    assert missing in err.value.missing
    assert err.value.quote_id == "Q1"


def test_expired_freight_quote_is_ignored() -> None:
    old = FreightQuote(
        id="F1", transporter_id="T", amount=Money.rupees("1000"), valid_until=date(2026, 11, 30)
    )
    q = quote(freight_terms=FreightTerms.EX_YARD)
    with pytest.raises(QuoteNotCostableError):
        landed_cost(q, need(), unit(), material(), TODAY, freight_quotes=(old,))
    est = FreightEstimate(per_kg=Money.rupees("2.00"), source="book")
    lc = landed_cost(
        q, need(), unit(), material(), TODAY, freight_quotes=(old,), freight_estimate=est
    )
    assert lc.freight.per_kg == Money.rupees("2.00")


def test_unknown_delivery_and_validity_are_flagged_not_guessed() -> None:
    lc = landed_cost(quote(delivery_date=None, valid_until=None), need(), unit(), material(), TODAY)
    assert {Flag.DELIVERY_UNKNOWN, Flag.VALIDITY_UNKNOWN} <= lc.flags
    assert Flag.LATE not in lc.flags and Flag.STALE not in lc.flags


def test_fields_from_supplier_history_are_labelled() -> None:
    q = quote(from_history=frozenset({"rate", "payment"}))
    lc = landed_cost(q, need(), unit(), material(), TODAY)
    assert Label.FROM_HISTORY in lc.base.labels
    assert Label.FROM_HISTORY in lc.money.labels


def test_unresolved_deviation_is_flagged_and_resolution_clears_it() -> None:
    q = quote(deviations=("1.8 mm instead of 2 mm",))
    assert Flag.DEVIATION in landed_cost(q, need(), unit(), material(), TODAY).flags
    resolved = q.model_copy(update={"deviations_resolved": True})
    assert Flag.DEVIATION not in landed_cost(resolved, need(), unit(), material(), TODAY).flags


def test_lump_charges_on_assumed_quantity_are_labelled_assumed() -> None:
    q = quote(
        quantity=None,
        charges=(Charge(name="loading", amount=Money.rupees("500"), basis=ChargeBasis.LUMP_SUM),),
    )
    lc = landed_cost(q, need(), unit(), material(), TODAY)
    assert Label.ASSUMED in lc.charges.labels
    assert lc.total_for_quantity() == lc.effective.scale(2000)


def test_explanations_come_from_the_trace() -> None:
    q = quote(
        payment=PaymentTerms(kind=PaymentKind.CREDIT, days=30), delivery_date=date(2026, 12, 12)
    )
    lc = landed_cost(q, need(), unit(), material(), TODAY)
    text = explain_landed_cost(lc)
    assert "Effective landed cost: ₹61.07/kg" in text
    assert "Warnings: late" in text
    why = explain_step(lc, "RULE-L5")
    assert "d_pay = -30 days (quoted)" in why and "Result: -₹0.93" in why
    assert "Inputs: none" in explain_step(lc, "RULE-L2")
    with pytest.raises(KeyError):
        lc.trace.step("RULE-X9")


def test_per_piece_trace_records_the_weight_rule_version() -> None:
    q = quote(
        rate=Money.rupees("2900"), rate_unit=RateUnit.PER_PIECE, piece_weight=Weight.of("46.674")
    )
    lc = landed_cost(q, need(), unit(), material(), TODAY)
    assert "SW-2026.1" in dict(lc.trace.step("RULE-L1").inputs)["piece weight"]


def test_explanation_without_warnings_has_no_warning_line() -> None:
    lc = landed_cost(quote(), need(), unit(), material(), TODAY)
    assert not lc.flags
    assert "Warnings" not in explain_landed_cost(lc)

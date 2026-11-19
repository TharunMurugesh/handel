"""Property-based tests (Hypothesis) for the money-handling rules (architecture §12.1)."""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from handel.domain.model.calendar import BusinessHours
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
from handel.domain.policy.bidding_guard import check_feedback
from handel.domain.rules.bidding import (
    BiddingPolicy,
    feedback_for,
    render_feedback,
    round_participants,
)
from handel.domain.rules.landed_cost import landed_cost
from handel.domain.rules.ranking import candidate, rank
from tests.unit.domain.builders import (
    NOW,
    TODAY,
    compete,
    material,
    need,
    quote,
    relationship,
    unit,
)

HOURS = BusinessHours()

paise = st.integers(min_value=1, max_value=50_000_000)  # up to ₹5 lakh
rates = paise.map(Money)
qty_kg = st.integers(min_value=1, max_value=100_000).map(lambda n: Weight(Decimal(n)))
r_monthly = st.integers(min_value=0, max_value=100).map(lambda n: Decimal(n) / 1000)  # 0–10%
payments = st.one_of(
    st.just(None),
    st.just(PaymentTerms(kind=PaymentKind.ON_DELIVERY)),
    st.builds(PaymentTerms, kind=st.just(PaymentKind.ADVANCE), days=st.integers(0, 365)),
    st.builds(PaymentTerms, kind=st.just(PaymentKind.CREDIT), days=st.integers(0, 180)),
)
charges = st.lists(
    st.builds(
        Charge,
        name=st.sampled_from(["loading", "unloading", "cutting"]),
        amount=st.integers(0, 1_000_000).map(Money),
        basis=st.sampled_from(list(ChargeBasis)),
    ),
    max_size=3,
).map(tuple)
units = st.sampled_from(
    [RateUnit.PER_KG, RateUnit.PER_QUINTAL, RateUnit.PER_TONNE, RateUnit.PER_PIECE]
)


@st.composite
def quotes(draw: st.DrawFn, qid: str = "Q1", sid: str = "S1") -> Quote:
    unit_ = draw(units)
    return quote(
        qid,
        sid,
        rate=draw(rates),
        rate_unit=unit_,
        piece_weight=draw(qty_kg) if unit_ is RateUnit.PER_PIECE else None,
        quantity=draw(st.one_of(st.none(), qty_kg)),
        gst_pct=draw(st.one_of(st.none(), st.sampled_from([Decimal(0), Decimal(5), Decimal(18)]))),
        tax_invoice=draw(st.one_of(st.none(), st.booleans())),
        freight_terms=draw(st.sampled_from(list(FreightTerms))),
        charges=draw(charges),
        payment=draw(payments),
        delivery_date=draw(st.one_of(st.none(), st.dates(date(2026, 12, 1), date(2027, 1, 31)))),
        valid_until=draw(st.one_of(st.none(), st.dates(date(2026, 11, 1), date(2027, 1, 31)))),
    )


FREIGHT = (FreightQuote(id="F1", transporter_id="T", amount=Money.rupees("2500")),)
ESTIMATE = FreightEstimate(per_kg=Money.rupees("1.50"), source="book")


@settings(max_examples=400)
@given(q=quotes(), r=r_monthly, itc=st.booleans())
def test_landed_cost_never_negative_and_parts_add_up(q: Quote, r: Decimal, itc: bool) -> None:
    lc = landed_cost(
        q,
        need(),
        unit(itc_eligible=itc, cost_of_money_monthly=r),
        material(),
        TODAY,
        freight_quotes=FREIGHT,
        freight_estimate=ESTIMATE,
    )
    assert lc.effective.paise >= 0
    assert lc.effective == Money.total([c.per_kg for c in lc.components.values()])
    for name in ("base", "freight", "charges", "tax"):
        assert lc.components[name].per_kg.paise >= 0
    assert all(c.labels for c in lc.components.values())


@given(
    q=quotes(),
    delivery=st.dates(date(2026, 12, 1), date(2027, 1, 31)),
    valid=st.dates(date(2026, 11, 1), date(2027, 1, 31)),
    deviation=st.text(min_size=1, max_size=20),
    via=st.sampled_from(["direct", "relay"]),
)
def test_non_price_fields_never_change_price_components(
    q: Quote, delivery: date, valid: date, deviation: str, via: str
) -> None:
    def price(x: Quote) -> list[Money]:
        lc = landed_cost(x, need(), unit(), material(), TODAY, FREIGHT, ESTIMATE)
        return [c.per_kg for c in lc.components.values()]

    changed = q.model_copy(
        update={
            "delivery_date": delivery,
            "valid_until": valid,
            "deviations": (deviation,),
            "via": via,
            "received_at": NOW + timedelta(hours=3),
        }
    )
    assert price(changed) == price(q)


@given(r=r_monthly, extra_credit=st.integers(1, 180), q=quotes())
def test_longer_credit_never_costs_more(r: Decimal, extra_credit: int, q: Quote) -> None:
    def eff(days: int) -> Money:
        x = q.model_copy(update={"payment": PaymentTerms(kind=PaymentKind.CREDIT, days=days)})
        return landed_cost(
            x, need(), unit(cost_of_money_monthly=r), material(), TODAY, FREIGHT, ESTIMATE
        ).effective

    assert eff(min(180, extra_credit)) <= eff(0)


@st.composite
def quote_sets(draw: st.DrawFn) -> list[Quote]:
    n = draw(st.integers(1, 8))
    return [draw(quotes(f"Q{i}", f"S{i}")) for i in range(n)]


@settings(max_examples=200)
@given(qs=quote_sets(), seed=st.integers(0, 2**32 - 1), penalise=st.booleans())
def test_ranking_is_total_and_independent_of_input_order(
    qs: list[Quote], seed: int, penalise: bool
) -> None:
    cands = [
        candidate(
            landed_cost(q, need(), unit(), material(), TODAY, FREIGHT, ESTIMATE),
            q,
            compete(q.supplier_id),
        )
        for q in qs
    ]
    shuffled = cands[:]
    random.Random(seed).shuffle(shuffled)
    a, b = rank(cands, penalise), rank(shuffled, penalise)
    assert a == b
    ids = [e.quote_id for e in a.entries] + [x.quote_id for x in a.excluded]
    assert sorted(ids) == sorted(q.id for q in qs)  # every quote exactly once
    assert [e.position for e in a.entries] == list(range(1, len(a.entries) + 1))
    if penalise:
        lates = [e.position for e in a.entries if "late" in {f.value for f in e.flags}]
        on_time = [e.position for e in a.entries if "late" not in {f.value for f in e.flags}]
        assert not lates or not on_time or max(on_time) < min(lates)


names = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz", min_size=4, max_size=20
).filter(lambda s: s.strip() == s and len(s.strip()) >= 4)


@settings(max_examples=200)
@given(
    qs=quote_sets().filter(lambda qs: len(qs) >= 2),
    supplier_names=st.lists(names, min_size=8, max_size=8, unique_by=str.casefold),
    modes=st.lists(st.booleans(), min_size=8, max_size=8),
    ceiling=rates,
    show=st.booleans(),
)
def test_rendered_feedback_never_leaks_and_always_passes_guard(
    qs: list[Quote], supplier_names: list[str], modes: list[bool], ceiling: Money, show: bool
) -> None:
    suppliers = [
        (compete if modes[i] else relationship)(q.supplier_id, supplier_names[i])
        for i, q in enumerate(qs)
    ]
    by_id = {s.id: s for s in suppliers}
    ranking = rank(
        candidate(
            landed_cost(q, need(), unit(), material(), TODAY, FREIGHT, ESTIMATE),
            q,
            by_id[q.supplier_id],
        )
        for q in qs
    )
    policy = BiddingPolicy(rounds=1, show_price_to_beat=show)
    for sid in round_participants(suppliers, ranking):
        fb = feedback_for(sid, ranking, 1, NOW, policy)
        text = render_feedback(fb, HOURS)
        assert by_id[sid].mode.value == "compete"
        for other in suppliers:
            if other.id != sid:
                assert other.name.casefold() not in text.casefold()
        violations = check_feedback(fb, text, ranking, suppliers, qs, policy, ceiling)
        # Only a coincidental number clash may block a message (failing safe), never a name.
        assert all("quoted rate" in v or "ceiling" in v for v in violations)

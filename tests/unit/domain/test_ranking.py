"""Ranking (spec §8.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from handel.domain.model.entities import PaymentKind, PaymentTerms, Quote, Supplier
from handel.domain.model.money import Money
from handel.domain.rules.explain import explain_entry
from handel.domain.rules.landed_cost import landed_cost
from handel.domain.rules.ranking import Candidate, candidate, rank
from tests.unit.domain.builders import TODAY, compete, material, need, quote, unit


def _cand(q: Quote, s: Supplier | None = None) -> Candidate:
    s = s or compete(q.supplier_id)
    return candidate(landed_cost(q, need(), unit(), material(), TODAY), q, s)


def test_sorted_by_effective_landed_not_quoted_rate() -> None:
    cheap_rate_on_advance = quote(
        "QA",
        "SA",
        rate=Money.rupees("61.90"),
        payment=PaymentTerms(kind=PaymentKind.ADVANCE, days=60),
    )  # 61.90 + 61.90×0.015×2 = 63.76
    dearer_rate_on_credit = quote(
        "QB",
        "SB",
        rate=Money.rupees("62.50"),
        payment=PaymentTerms(kind=PaymentKind.CREDIT, days=30),
    )  # 62.50 − 0.94 = 61.56
    r = rank([_cand(cheap_rate_on_advance), _cand(dearer_rate_on_credit)])
    assert [e.supplier_id for e in r.entries] == ["SB", "SA"]
    assert r.entries[0].reason.startswith("lowest effective landed cost, ₹61.56/kg")
    assert "₹2.20/kg more than the best" in r.entries[1].reason
    assert r.position_of("SA") == 2 and r.position_of("nobody") is None


def test_deviation_excluded_and_shown_separately() -> None:
    bad = quote("QX", "SX", rate=Money.rupees("50"), deviations=("1.6 mm",))
    r = rank([_cand(bad), _cand(quote("Q1", "S1"))])
    assert [e.quote_id for e in r.entries] == ["Q1"]
    assert [x.quote_id for x in r.excluded] == ["QX"]


def test_late_ranked_below_on_time_unless_owner_overrides() -> None:
    late_cheap = quote("QL", "SL", rate=Money.rupees("60"), delivery_date=date(2026, 12, 15))
    on_time = quote("QO", "SO", rate=Money.rupees("62"))
    cands = [_cand(late_cheap), _cand(on_time)]
    penalised = rank(cands)
    assert [e.quote_id for e in penalised.entries] == ["QO", "QL"]
    assert "ranked below on-time quotes" in penalised.entries[1].reason
    assert [e.quote_id for e in rank(cands, penalise_late=False).entries] == ["QL", "QO"]


def test_tie_band_breaks_by_delivery_then_reliability_then_credit() -> None:
    # All within 0.5% of ₹62.00 (≤ ₹62.31)
    a = quote("QA", "SA", rate=Money.rupees("62.00"), delivery_date=date(2026, 12, 9))
    b = quote("QB", "SB", rate=Money.rupees("62.20"), delivery_date=date(2026, 12, 4))
    c = quote("QC", "SC", rate=Money.rupees("62.25"), delivery_date=date(2026, 12, 9))
    r = rank(
        [
            _cand(a, compete("SA", reliability=Decimal("0.5"))),
            _cand(b),
            _cand(c, compete("SC", reliability=Decimal("0.9"))),
        ]
    )
    assert [e.quote_id for e in r.entries] == ["QB", "QC", "QA"]  # earliest; then more reliable
    assert all("within 0.5%" in e.reason for e in r.entries)


def test_tie_band_credit_breaks_last() -> None:
    base = {"rate": Money.rupees("62.00"), "delivery_date": date(2026, 12, 8)}
    short = quote("Q1", "S1", **base)
    long = quote(
        "Q2",
        "S2",
        rate=Money.rupees("62.90"),
        delivery_date=date(2026, 12, 8),
        payment=PaymentTerms(kind=PaymentKind.CREDIT, days=1),
    )  # 62.90 − 0.03 = 62.87 > band
    longer = quote(
        "Q3",
        "S3",
        rate=Money.rupees("62.25"),
        delivery_date=date(2026, 12, 8),
        payment=PaymentTerms(kind=PaymentKind.CREDIT, days=7),
    )  # 62.25 − 0.22 = 62.03
    r = rank([_cand(short), _cand(long), _cand(longer)])
    assert [e.quote_id for e in r.entries] == ["Q3", "Q1", "Q2"]


def test_band_is_anchored_so_chains_do_not_merge() -> None:
    # 100.00, 100.40, 100.80: B is within 0.5% of A, C is not within 0.5% of A.
    qa = quote("QA", "SA", rate=Money.rupees("100.00"), delivery_date=date(2026, 12, 9))
    qb = quote("QB", "SB", rate=Money.rupees("100.40"), delivery_date=date(2026, 12, 9))
    qc = quote("QC", "SC", rate=Money.rupees("100.80"), delivery_date=date(2026, 12, 2))
    r = rank([_cand(qa), _cand(qb), _cand(qc)])
    assert [e.quote_id for e in r.entries] == ["QA", "QB", "QC"]  # C's early delivery can't jump A
    assert "within 0.5%" not in r.entries[2].reason


def test_stale_is_ranked_with_warning() -> None:
    r = rank([_cand(quote(valid_until=date(2026, 11, 30)))])
    assert "refresh before award" in r.entries[0].reason


def test_unknown_delivery_and_reliability_sort_last_in_band() -> None:
    known = quote("Q1", "S1", rate=Money.rupees("62.10"))
    unknown = quote("Q2", "S2", rate=Money.rupees("62.00"), delivery_date=None)
    r = rank([_cand(unknown), _cand(known)])
    assert [e.quote_id for e in r.entries] == ["Q1", "Q2"]


def test_empty_and_invalid_inputs() -> None:
    empty = rank([])
    assert empty.entries == () and empty.best is None
    c = _cand(quote())
    with pytest.raises(ValueError):
        rank([c, c])
    with pytest.raises(ValueError):
        candidate(c.landed, quote("OTHER"), compete("S1"))
    with pytest.raises(ValueError):
        candidate(c.landed, quote(), compete("S9"))


def test_explain_entry() -> None:
    e = rank([_cand(quote())]).entries[0]
    assert (
        explain_entry(e, "Demo Steels")
        == "#1 Demo Steels: lowest effective landed cost, ₹62.00/kg."
    )

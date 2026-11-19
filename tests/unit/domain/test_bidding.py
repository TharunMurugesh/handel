"""Bidding rules (RULE-B1..B6) and the bidding-message guard, including AT-05."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from handel.domain.model.calendar import BusinessHours
from handel.domain.model.entities import Quote, Supplier, SupplierMode
from handel.domain.model.money import Money
from handel.domain.model.quantity import RateUnit, Weight
from handel.domain.policy.bidding_guard import check_feedback
from handel.domain.rules.bidding import (
    BiddingPolicy,
    BidRejectedError,
    can_start_round,
    check_improvement,
    feedback_for,
    render_feedback,
    round_deadline,
    round_participants,
    rules_text,
    target_met,
)
from handel.domain.rules.landed_cost import landed_cost
from handel.domain.rules.ranking import Ranking, candidate, rank
from tests.unit.domain.builders import TODAY, compete, material, need, quote, relationship, unit

IST = ZoneInfo("Asia/Kolkata")
HOURS = BusinessHours()
OPENS = datetime(2026, 12, 2, 11, 0, tzinfo=IST)
CEILING = Money.rupees("64.00")

MURUGAN = compete("S1", "Murugan Steels")
LAKSHMI = compete("S2", "Lakshmi Traders")
RAVI = relationship("S3", "Ravi Steels")
SUPPLIERS = (MURUGAN, LAKSHMI, RAVI)
QUOTES = (
    quote("Q1", "S1", rate=Money.rupees("61.20")),
    quote("Q2", "S2", rate=Money.rupees("62.40")),
    quote("Q3", "S3", rate=Money.rupees("62.80")),
)


def _ranking(
    quotes: tuple[Quote, ...] = QUOTES, suppliers: tuple[Supplier, ...] = SUPPLIERS
) -> Ranking:
    by_id = {s.id: s for s in suppliers}
    return rank(
        candidate(landed_cost(q, need(), unit(), material(), TODAY), q, by_id[q.supplier_id])
        for q in quotes
    )


def _check(
    text: str, fb: object, policy: BiddingPolicy, ranking: Ranking | None = None
) -> tuple[str, ...]:
    return check_feedback(fb, text, ranking or _ranking(), SUPPLIERS, QUOTES, policy, CEILING)  # type: ignore[arg-type]


# ---- RULE-B1 ----
def test_rules_text_by_mode() -> None:
    policy = BiddingPolicy(rounds=2)
    compete_text = rules_text(policy, "Demo Fabricators", SupplierMode.COMPETE)
    assert "up to 2 improvement round(s)" in compete_text
    assert "not automatically" in compete_text  # RULE-B6
    assert rules_text(policy, "Demo Fabricators", SupplierMode.RELATIONSHIP) == (
        "Demo Fabricators is comparing quotes."
    )


def test_policy_round_limits() -> None:
    BiddingPolicy(rounds=0)
    with pytest.raises(ValueError):
        BiddingPolicy(rounds=3)
    with pytest.raises(ValueError):
        BiddingPolicy(rounds=-1)


# ---- RULE-B5 ----
def test_relationship_and_leader_sit_out_rounds() -> None:
    assert round_participants(SUPPLIERS, _ranking()) == ("S2",)


def test_participants_without_any_ranking() -> None:
    assert round_participants(SUPPLIERS, Ranking((), ())) == ()


def test_round_deadline_is_at_least_two_business_hours() -> None:
    assert round_deadline(OPENS, HOURS) == OPENS + timedelta(hours=2)
    late = datetime(2026, 12, 2, 18, 0, tzinfo=IST)
    assert round_deadline(late, HOURS) == datetime(2026, 12, 3, 11, 0, tzinfo=IST)
    with pytest.raises(ValueError):
        round_deadline(OPENS, HOURS, timedelta(hours=1))


def test_bids_may_only_improve() -> None:
    q2 = QUOTES[1]
    before = landed_cost(q2, need(), unit(), material(), TODAY)
    better = landed_cost(
        q2.model_copy(update={"rate": Money.rupees("61.00"), "round": 1}),
        need(),
        unit(),
        material(),
        TODAY,
    )
    check_improvement(before, better)
    with pytest.raises(BidRejectedError):
        check_improvement(before, before)
    with pytest.raises(BidRejectedError):
        check_improvement(better, before)
    with pytest.raises(BidRejectedError):
        check_improvement(before, replace(better, supplier_id="S9"))


def test_round_start_rules() -> None:
    r = _ranking()
    policy = BiddingPolicy(rounds=1)
    assert can_start_round(0, policy, r, target=None)
    assert not can_start_round(1, policy, r, target=None)  # limit reached
    assert not can_start_round(0, policy, r, target=Money.rupees("61.50"))  # target met
    assert target_met(r, Money.rupees("61.20"))
    assert not target_met(r, None)
    assert not target_met(Ranking((), ()), Money.rupees("99"))
    assert not can_start_round(
        0, policy, _ranking(QUOTES[:1]), target=None
    )  # nobody to compete with


# ---- feedback facts ----
def test_feedback_facts() -> None:
    policy = BiddingPolicy(rounds=1, show_price_to_beat=True)
    fb = feedback_for("S2", _ranking(), 1, OPENS, policy)
    assert not fb.is_lowest and fb.price_to_beat == Money.rupees("61.20")
    leader = feedback_for("S1", _ranking(), 1, OPENS, policy)
    assert leader.is_lowest and leader.price_to_beat is None
    hidden = feedback_for("S2", _ranking(), 1, OPENS, BiddingPolicy(rounds=1))
    assert hidden.price_to_beat is None
    with pytest.raises(ValueError):
        feedback_for("S9", _ranking(), 1, OPENS, policy)
    with pytest.raises(ValueError):
        feedback_for("S2", _ranking(), 2, OPENS, policy)


def test_render_feedback() -> None:
    policy = BiddingPolicy(rounds=1, show_price_to_beat=True)
    deadline = round_deadline(OPENS, HOURS)
    text = render_feedback(feedback_for("S2", _ranking(), 1, deadline, policy), HOURS)
    assert text == (
        "Your offer is currently not the lowest. You may improve it by 02 Dec, 13:00. "
        "Price to beat: ₹61.20/kg landed."
    )
    leader = render_feedback(feedback_for("S1", _ranking(), 1, deadline, policy), HOURS)
    assert leader == "Your offer is currently the lowest. The round closes 02 Dec, 13:00."


# ---- AT-05 ----
def test_at05_only_compete_supplier_gets_feedback_and_nothing_leaks() -> None:
    """One compete and one relationship supplier behind the leader: only the compete one gets
    feedback, and no message reveals another supplier or the ceiling."""
    policy = BiddingPolicy(rounds=1, show_price_to_beat=True)
    ranking = _ranking()
    deadline = round_deadline(OPENS, HOURS)
    recipients = round_participants(SUPPLIERS, ranking)
    assert recipients == ("S2",)  # Ravi (relationship) gets nothing

    for sid in recipients:
        fb = feedback_for(sid, ranking, 1, deadline, policy)
        text = render_feedback(fb, HOURS)
        assert _check(text, fb, policy, ranking) == ()
        for other in SUPPLIERS:
            if other.id != sid:
                assert other.name not in text and other.id not in text
        assert "64" not in text  # the ceiling

    # And the guard refuses to send feedback to the relationship supplier.
    fb_ravi = feedback_for("S3", ranking, 1, deadline, policy)
    assert any(
        "relationship" in v
        for v in _check(render_feedback(fb_ravi, HOURS), fb_ravi, policy, ranking)
    )


# ---- guard: each violation is caught ----
POLICY = BiddingPolicy(rounds=1, show_price_to_beat=True)
FB = feedback_for("S2", _ranking(), 1, OPENS, POLICY)
OK_TEXT = render_feedback(FB, HOURS)


def test_guard_accepts_the_rendered_template() -> None:
    assert _check(OK_TEXT, FB, POLICY) == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (OK_TEXT + " Murugan Steels is lower.", "reveals another supplier"),
        (OK_TEXT + " (ref s1)", "reveals another supplier"),
        ("Another supplier quoted 61.20 per kg.", None),  # equals price to beat: allowed figure
        ("The best quote is ₹62.80/kg.", "another supplier's quoted rate"),
        ("The best quote is 6280 paise.", "another supplier's quoted rate"),
        ("Please stay under ₹64.00.", "owner's ceiling"),
        ("Please stay under 64.", "owner's ceiling"),
    ],
)
def test_guard_text_checks(text: str, expected: str | None) -> None:
    violations = _check(text, FB, POLICY)
    if expected is None:
        assert violations == ()
    else:
        assert any(expected in v for v in violations), violations


def test_guard_truthfulness_and_limits() -> None:
    lie = replace(FB, is_lowest=True)
    assert any("misstates" in v for v in _check(OK_TEXT, lie, POLICY))
    wrong_ptb = replace(FB, price_to_beat=Money.rupees("60.00"))
    assert any("not the true current best" in v for v in _check(OK_TEXT, wrong_ptb, POLICY))
    not_allowed = _check(OK_TEXT, FB, BiddingPolicy(rounds=1, show_price_to_beat=False))
    assert any("did not allow" in v for v in not_allowed)
    assert any("round outside" in v for v in _check(OK_TEXT, replace(FB, round_no=2), POLICY))
    stranger = replace(FB, supplier_id="S9")
    out = _check(OK_TEXT, stranger, POLICY)
    assert any("not a supplier" in v for v in out) and any("no ranked quote" in v for v in out)


def test_guard_checks_per_kg_form_of_per_tonne_quotes() -> None:
    tonne_quotes = (
        QUOTES[0].model_copy(
            update={"rate": Money.rupees("61200"), "rate_unit": RateUnit.PER_TONNE}
        ),
        QUOTES[1],
        QUOTES[2].model_copy(
            update={
                "rate": Money.rupees("3000"),
                "rate_unit": RateUnit.PER_PIECE,
                "piece_weight": Weight.of("46.674"),
            }
        ),
    )
    fb = feedback_for("S2", _ranking(tonne_quotes), 1, OPENS, BiddingPolicy(rounds=1))
    out = check_feedback(
        fb,
        "Someone is at 64.28 per kg",
        _ranking(tonne_quotes),
        SUPPLIERS,
        tonne_quotes,
        BiddingPolicy(rounds=1),
        None,
    )
    assert any("quoted rate" in v for v in out)  # 3000 / 46.674 = 64.28
    clean = check_feedback(
        fb,
        render_feedback(fb, HOURS),
        _ranking(tonne_quotes),
        SUPPLIERS,
        tonne_quotes,
        BiddingPolicy(rounds=1),
        None,
    )
    assert clean == ()


def test_guard_skips_uncostable_quotes_rate_forms_safely() -> None:
    """A quote with no rate unit still contributes its raw rate to the forbidden figures."""
    unread = QUOTES[2].model_copy(update={"rate": Money.rupees("63.30"), "rate_unit": None})
    quotes = (QUOTES[0], QUOTES[1], unread)
    fb = feedback_for("S2", _ranking(), 1, OPENS, POLICY)
    out = check_feedback(fb, "Someone offered 63.30", _ranking(), SUPPLIERS, quotes, POLICY, None)
    assert any("quoted rate" in v for v in out)

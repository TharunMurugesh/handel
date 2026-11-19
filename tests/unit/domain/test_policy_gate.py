"""Approval and policy gate (M-13, BD-01, BD-02, AG-06)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from handel.domain.cases.purchase import Action, State
from handel.domain.model.entities import Role
from handel.domain.model.money import Money
from handel.domain.policy.gate import (
    Approval,
    ApprovalKind,
    AwardFacts,
    Proposal,
    award_terms_digest,
    evaluate,
)
from handel.domain.rules.landed_cost import Flag, landed_cost
from tests.unit.domain.builders import NOW, TODAY, material, need, quote, unit

Q = quote()
LC = landed_cost(Q, need(), unit(), material(), TODAY)
DIGEST = award_terms_digest(Q, LC)


def approval(**kw: Any) -> Approval:
    base: dict[str, Any] = {
        "id": "A1",
        "case_id": "C1",
        "kind": ApprovalKind.AWARD,
        "approver_id": "P-owner",
        "approver_role": Role.OWNER,
        "granted_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=24),
        "terms_digest": DIGEST,
    }
    return Approval(**(base | kw))


def award(**kw: Any) -> Proposal:
    facts: dict[str, Any] = {
        "quote_id": Q.id,
        "terms_digest": DIGEST,
        "flags": LC.flags,
        "effective": LC.effective,
        "ceiling": Money.rupees("64.00"),
    }
    return Proposal(
        case_id="C1",
        state=State.AWAITING_SUPPLIER_CONFIRM,
        action=Action.SEND_AWARD,
        award=AwardFacts(**(facts | kw)),
    )


def test_award_with_owner_approval_for_these_terms_passes() -> None:
    d = evaluate(award(), [approval()], NOW)
    assert d.allowed and d.violations == () and d.consume == ("A1",)


def test_award_without_approval_is_refused() -> None:
    d = evaluate(award(), [], NOW)
    assert not d.allowed
    assert any("no valid owner approval" in v for v in d.violations)


@pytest.mark.parametrize(
    "bad",
    [
        {"used": True},
        {"case_id": "OTHER"},
        {"kind": ApprovalKind.SEND_QUOTE},
        {"approver_role": Role.OPERATOR},
        {"approver_role": Role.DELEGATE},
        {"terms_digest": "different-terms"},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"granted_at": NOW + timedelta(minutes=1)},  # not yet granted
    ],
    ids=[
        "used",
        "other-case",
        "wrong-kind",
        "operator",
        "delegate",
        "other-terms",
        "expired",
        "future",
    ],
)
def test_approval_must_be_valid_unused_owner_and_for_these_terms(bad: dict[str, Any]) -> None:
    assert not evaluate(award(), [approval(**bad)], NOW).allowed


def test_award_refused_outside_its_state() -> None:
    p = award()
    wrong = Proposal(case_id=p.case_id, state=State.SHORTLISTED, action=p.action, award=p.award)
    d = evaluate(wrong, [approval()], NOW)
    assert not d.allowed and any("not allowed in state" in v for v in d.violations)


def test_stale_or_deviating_quote_cannot_be_awarded() -> None:
    assert not evaluate(award(flags=frozenset({Flag.STALE})), [approval()], NOW).allowed
    assert not evaluate(award(flags=frozenset({Flag.DEVIATION})), [approval()], NOW).allowed


def test_above_ceiling_needs_a_separate_exceed_limit_approval() -> None:
    over = award(effective=Money.rupees("64.01"))
    d = evaluate(over, [approval()], NOW)
    assert not d.allowed and any("ceiling" in v for v in d.violations)
    exceed = approval(id="A2", kind=ApprovalKind.EXCEED_LIMIT, terms_digest=None)
    d2 = evaluate(over, [approval(), exceed], NOW)
    assert d2.allowed and set(d2.consume) == {"A1", "A2"}


def test_no_ceiling_means_no_limit_check() -> None:
    assert evaluate(award(ceiling=None, effective=Money.rupees("99")), [approval()], NOW).allowed


def test_award_without_facts_is_refused() -> None:
    p = Proposal(case_id="C1", state=State.AWAITING_SUPPLIER_CONFIRM, action=Action.SEND_AWARD)
    assert not evaluate(p, [approval()], NOW).allowed


def test_non_approval_action_allowed_in_state() -> None:
    p = Proposal(case_id="C1", state=State.COLLECTING, action=Action.SEND_REMINDER)
    assert evaluate(p, [], NOW).allowed
    p2 = Proposal(case_id="C1", state=State.CLOSED, action=Action.SEND_REMINDER)
    assert not evaluate(p2, [], NOW).allowed


def test_gate_needs_aware_time() -> None:
    with pytest.raises(ValueError):
        evaluate(award(), [approval()], datetime(2026, 12, 1, 10))


def test_digest_changes_when_any_term_changes() -> None:
    other_rate = quote(rate=Money.rupees("62.01"))
    other_delivery = quote(delivery_date=TODAY + timedelta(days=9))
    d1 = award_terms_digest(other_rate, landed_cost(other_rate, need(), unit(), material(), TODAY))
    d2 = award_terms_digest(
        other_delivery, landed_cost(other_delivery, need(), unit(), material(), TODAY)
    )
    assert len({DIGEST, d1, d2}) == 3
    assert award_terms_digest(Q, LC) == DIGEST  # stable


def test_digest_handles_missing_fields() -> None:
    q = quote(gst_pct=None, payment=None, delivery_date=None)
    assert len(award_terms_digest(q, landed_cost(q, need(), unit(), material(), TODAY))) == 64


def test_oldest_matching_approval_is_consumed_first() -> None:
    newer = approval(id="A9", granted_at=NOW - timedelta(minutes=1))
    assert evaluate(award(), [newer, approval()], NOW).consume == ("A1",)


def test_now_is_utc_or_any_aware_zone() -> None:
    ist_now = NOW.astimezone(UTC)
    assert evaluate(award(), [approval()], ist_now).allowed

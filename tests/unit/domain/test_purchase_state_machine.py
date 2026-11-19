"""Purchase state machine (spec §7.1): every legal transition, every illegal one, every guard."""

from __future__ import annotations

import itertools

import pytest

from handel.domain.cases.purchase import (
    ALLOWED_ACTIONS,
    CANCELLABLE,
    TERMINAL,
    TRANSITIONS,
    Action,
    CaseFacts,
    Event,
    IllegalTransitionError,
    State,
    allowed_events,
    next_state,
)

S, E = State, Event
OPEN = CaseFacts(need_complete=True, suppliers_selected=4, valid_quotes=3, rounds_allowed=1)

HAPPY_PATH = [
    (S.DRAFT, E.OWNER_CONFIRMED_NEED, S.CONFIRMED),
    (S.CONFIRMED, E.SUPPLIERS_SELECTED, S.SOURCING),
    (S.SOURCING, E.RFQS_SENT, S.COLLECTING),
    (S.COLLECTING, E.DEADLINE_REACHED, S.BIDDING),
    (S.BIDDING, E.BIDDING_DONE, S.SHORTLISTED),
    (S.SHORTLISTED, E.APPROVAL_REQUESTED, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, E.OWNER_APPROVED, S.AWAITING_SUPPLIER_CONFIRM),
    (S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_CONFIRMED, S.AWARDED),
    (S.AWARDED, E.DELIVERY_CONFIRMED, S.DELIVERED),
    (S.DELIVERED, E.OUTCOME_RECORDED, S.CLOSED),
]


def test_happy_path_to_closed() -> None:
    facts = CaseFacts(
        need_complete=True, suppliers_selected=4, valid_quotes=3, rounds_done=1, rounds_allowed=1
    )
    state = S.DRAFT
    for start, event, end in HAPPY_PATH:
        assert state is start
        state = next_state(state, event, facts)
        assert state is end


# (state, event, facts that pass, facts that fail)
GUARDED = [
    (
        S.DRAFT,
        E.OWNER_CONFIRMED_NEED,
        CaseFacts(need_complete=True),
        CaseFacts(need_complete=False),
    ),
    (
        S.CONFIRMED,
        E.SUPPLIERS_SELECTED,
        CaseFacts(suppliers_selected=1),
        CaseFacts(suppliers_selected=0),
    ),
    (S.COLLECTING, E.DEADLINE_REACHED, CaseFacts(valid_quotes=2), CaseFacts(valid_quotes=1)),
    (S.COLLECTING, E.WIDEN_APPROVED, CaseFacts(valid_quotes=1), CaseFacts(valid_quotes=2)),
    (
        S.COLLECTING,
        E.DEADLINE_EXTENDED,
        CaseFacts(valid_quotes=1),
        CaseFacts(valid_quotes=1, extensions_used=1),
    ),
    (S.COLLECTING, E.DEADLINE_EXTENDED, CaseFacts(valid_quotes=0), CaseFacts(valid_quotes=2)),
    (
        S.BIDDING,
        E.BIDDING_DONE,
        CaseFacts(rounds_done=1, rounds_allowed=1),
        CaseFacts(rounds_done=0, rounds_allowed=1),
    ),
    (
        S.BIDDING,
        E.BIDDING_DONE,
        CaseFacts(target_met=True, rounds_allowed=2),
        CaseFacts(rounds_done=1, rounds_allowed=2),
    ),
    (
        S.AWAITING_APPROVAL,
        E.OWNER_NEGOTIATE_AGAIN,
        CaseFacts(rounds_done=0, rounds_allowed=1),
        CaseFacts(rounds_done=1, rounds_allowed=1),
    ),
]


@pytest.mark.parametrize(("state", "event", "ok", "bad"), GUARDED)
def test_guards(state: State, event: Event, ok: CaseFacts, bad: CaseFacts) -> None:
    next_state(state, event, ok)
    with pytest.raises(IllegalTransitionError, match="guard"):
        next_state(state, event, bad)


def test_every_unlisted_state_event_pair_is_rejected() -> None:
    for state, event in itertools.product(State, Event):
        if (state, event) in TRANSITIONS:
            continue
        with pytest.raises(IllegalTransitionError, match="not allowed"):
            next_state(state, event, OPEN)


def test_recovery_transitions() -> None:
    f = CaseFacts(valid_quotes=1)
    assert next_state(S.COLLECTING, E.WIDEN_APPROVED, f) is S.SOURCING
    assert next_state(S.COLLECTING, E.DEADLINE_EXTENDED, f) is S.COLLECTING
    assert (
        next_state(S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_TERMS_DIFFER, f) is S.AWAITING_APPROVAL
    )
    assert next_state(S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_WITHDREW, f) is S.AWAITING_APPROVAL
    assert next_state(S.AWAITING_APPROVAL, E.OWNER_REJECTED_ALL, f) is S.CANCELLED
    assert next_state(S.DRAFT, E.MISSING_FIELDS, f) is S.CLARIFYING
    assert next_state(S.CLARIFYING, E.OWNER_ANSWERED, f) is S.DRAFT


def test_cancel_only_before_award() -> None:
    for state in State:
        if state in CANCELLABLE:
            assert next_state(state, E.OWNER_CANCELLED, OPEN) is S.CANCELLED
        else:
            with pytest.raises(IllegalTransitionError):
                next_state(state, E.OWNER_CANCELLED, OPEN)
    assert S.AWARDED not in CANCELLABLE


def test_terminal_states_have_no_way_out() -> None:
    for state in TERMINAL:
        assert allowed_events(state) == frozenset()


def test_every_state_is_reachable_and_has_an_action_table() -> None:
    reachable = {S.DRAFT}
    frontier = [S.DRAFT]
    while frontier:
        s = frontier.pop()
        for (src, _), (dst, _) in TRANSITIONS.items():
            if src is s and dst not in reachable:
                reachable.add(dst)
                frontier.append(dst)
    assert reachable == set(State)
    assert set(ALLOWED_ACTIONS) == set(State)


def test_award_only_while_awaiting_supplier_confirm() -> None:
    """RULE-B6 / BD-02: the award message exists only after the owner approved."""
    assert [s for s, acts in ALLOWED_ACTIONS.items() if Action.SEND_AWARD in acts] == [
        S.AWAITING_SUPPLIER_CONFIRM
    ]


def test_no_payment_action_exists() -> None:
    """BD-02: Handel never pays anyone."""
    for action in Action:
        assert "pay" not in action.value
        assert "transfer" not in action.value


def test_rank_feedback_only_while_bidding() -> None:
    assert [s for s, acts in ALLOWED_ACTIONS.items() if Action.SEND_RANK_FEEDBACK in acts] == [
        S.BIDDING
    ]


def test_closed_allows_nothing() -> None:
    assert ALLOWED_ACTIONS[S.CLOSED] == frozenset()

"""Purchase case state machine (spec §7.1), as declarative tables.

- ``TRANSITIONS``: (state, event) → (next state, guard).
- ``ALLOWED_ACTIONS``: what the agent may do in each state (architecture §4.3).

The planner may only pick from ``ALLOWED_ACTIONS[state]``; the policy gate checks the
pick. There is deliberately no payment action anywhere (BD-02).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    DRAFT = "Draft"
    CLARIFYING = "Clarifying"
    CONFIRMED = "Confirmed"
    SOURCING = "Sourcing"
    COLLECTING = "Collecting"
    BIDDING = "Bidding"
    SHORTLISTED = "Shortlisted"
    AWAITING_APPROVAL = "AwaitingApproval"
    AWAITING_SUPPLIER_CONFIRM = "AwaitingSupplierConfirm"
    AWARDED = "Awarded"
    DELIVERED = "Delivered"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


TERMINAL = frozenset({State.CLOSED, State.CANCELLED})


class Event(StrEnum):
    MISSING_FIELDS = "missing_fields"
    OWNER_ANSWERED = "owner_answered"
    OWNER_CONFIRMED_NEED = "owner_confirmed_need"
    SUPPLIERS_SELECTED = "suppliers_selected"
    RFQS_SENT = "rfqs_sent"
    DEADLINE_REACHED = "deadline_reached"
    DEADLINE_EXTENDED = "deadline_extended"
    WIDEN_APPROVED = "widen_approved"
    BIDDING_DONE = "bidding_done"
    APPROVAL_REQUESTED = "approval_requested"
    OWNER_APPROVED = "owner_approved"
    OWNER_NEGOTIATE_AGAIN = "owner_negotiate_again"
    OWNER_REJECTED_ALL = "owner_rejected_all"
    SUPPLIER_CONFIRMED = "supplier_confirmed"
    SUPPLIER_TERMS_DIFFER = "supplier_terms_differ"
    SUPPLIER_WITHDREW = "supplier_withdrew"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    OUTCOME_RECORDED = "outcome_recorded"
    OWNER_CANCELLED = "owner_cancelled"


class Action(StrEnum):
    """The tool registry for purchase cases. No action pays anyone (BD-02)."""

    ASK_CLARIFICATION = "ask_clarification"
    CONFIRM_NEED = "confirm_need"  # MSG-08
    SELECT_SUPPLIERS = "select_suppliers"
    INVITE_SUPPLIER = "invite_supplier"  # MSG-00 draft for the owner
    SEND_RFQ = "send_rfq"  # MSG-02
    SEND_RELAY_DRAFT = "send_relay_draft"  # MSG-02R
    SEND_REMINDER = "send_reminder"  # MSG-03
    RECORD_QUOTE = "record_quote"
    ASK_QUOTE_CLARIFICATION = "ask_quote_clarification"  # MSG-04
    MARK_NO_RESPONSE = "mark_no_response"
    SUGGEST_MORE_SUPPLIERS = "suggest_more_suppliers"
    EXTEND_DEADLINE = "extend_deadline"
    RUN_ROUND = "run_round"
    SEND_RANK_FEEDBACK = "send_rank_feedback"  # MSG-05
    SHORTLIST = "shortlist"
    REQUEST_APPROVAL = "request_approval"  # MSG-09
    REMIND_OWNER = "remind_owner"
    REQUEST_VALIDITY_EXTENSION = "request_validity_extension"
    RERANK = "rerank"
    SEND_AWARD = "send_award"  # MSG-06, needs a recorded owner approval
    SEND_REGRET = "send_regret"  # MSG-07
    RECORD_DELIVERY = "record_delivery"
    RECORD_OUTCOME = "record_outcome"


@dataclass(frozen=True, slots=True)
class CaseFacts:
    """What guards look at. Built by the application from the case and its quotes."""

    need_complete: bool = False
    suppliers_selected: int = 0
    valid_quotes: int = 0
    extensions_used: int = 0
    rounds_done: int = 0
    rounds_allowed: int = 1
    target_met: bool = False


Guard = Callable[[CaseFacts], bool]
MIN_VALID_QUOTES = 2  # spec §7.1 / M-12
MAX_EXTENSIONS = 1  # M-12: "extend once"


def _always(_: CaseFacts) -> bool:
    return True


def _need_complete(f: CaseFacts) -> bool:
    return f.need_complete


def _has_suppliers(f: CaseFacts) -> bool:
    return f.suppliers_selected >= 1


def _enough_quotes(f: CaseFacts) -> bool:
    return f.valid_quotes >= MIN_VALID_QUOTES


def _too_few_quotes(f: CaseFacts) -> bool:
    return f.valid_quotes < MIN_VALID_QUOTES


def _can_extend(f: CaseFacts) -> bool:
    return f.valid_quotes < MIN_VALID_QUOTES and f.extensions_used < MAX_EXTENSIONS


def _bidding_finished(f: CaseFacts) -> bool:
    return f.target_met or f.rounds_done >= f.rounds_allowed


def _rounds_left(f: CaseFacts) -> bool:
    return f.rounds_done < f.rounds_allowed


S, E = State, Event
TRANSITIONS: dict[tuple[State, Event], tuple[State, Guard]] = {
    (S.DRAFT, E.MISSING_FIELDS): (S.CLARIFYING, _always),
    (S.CLARIFYING, E.OWNER_ANSWERED): (S.DRAFT, _always),
    (S.DRAFT, E.OWNER_CONFIRMED_NEED): (S.CONFIRMED, _need_complete),
    (S.CONFIRMED, E.SUPPLIERS_SELECTED): (S.SOURCING, _has_suppliers),
    (S.SOURCING, E.RFQS_SENT): (S.COLLECTING, _always),
    (S.COLLECTING, E.DEADLINE_REACHED): (S.BIDDING, _enough_quotes),
    (S.COLLECTING, E.DEADLINE_EXTENDED): (S.COLLECTING, _can_extend),
    (S.COLLECTING, E.WIDEN_APPROVED): (S.SOURCING, _too_few_quotes),
    (S.BIDDING, E.BIDDING_DONE): (S.SHORTLISTED, _bidding_finished),
    (S.SHORTLISTED, E.APPROVAL_REQUESTED): (S.AWAITING_APPROVAL, _always),
    (S.AWAITING_APPROVAL, E.OWNER_APPROVED): (S.AWAITING_SUPPLIER_CONFIRM, _always),
    (S.AWAITING_APPROVAL, E.OWNER_NEGOTIATE_AGAIN): (S.BIDDING, _rounds_left),
    (S.AWAITING_APPROVAL, E.OWNER_REJECTED_ALL): (S.CANCELLED, _always),
    (S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_CONFIRMED): (S.AWARDED, _always),
    (S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_TERMS_DIFFER): (S.AWAITING_APPROVAL, _always),
    (S.AWAITING_SUPPLIER_CONFIRM, E.SUPPLIER_WITHDREW): (S.AWAITING_APPROVAL, _always),
    (S.AWARDED, E.DELIVERY_CONFIRMED): (S.DELIVERED, _always),
    (S.DELIVERED, E.OUTCOME_RECORDED): (S.CLOSED, _always),
}
# "Stop the sheet order": the owner may cancel any time before the award is confirmed.
CANCELLABLE = (
    S.DRAFT,
    S.CLARIFYING,
    S.CONFIRMED,
    S.SOURCING,
    S.COLLECTING,
    S.BIDDING,
    S.SHORTLISTED,
    S.AWAITING_APPROVAL,
    S.AWAITING_SUPPLIER_CONFIRM,
)
for _state in CANCELLABLE:
    TRANSITIONS[(_state, E.OWNER_CANCELLED)] = (S.CANCELLED, _always)

A = Action
ALLOWED_ACTIONS: dict[State, frozenset[Action]] = {
    S.DRAFT: frozenset({A.ASK_CLARIFICATION, A.CONFIRM_NEED}),
    S.CLARIFYING: frozenset({A.ASK_CLARIFICATION}),
    S.CONFIRMED: frozenset({A.SELECT_SUPPLIERS, A.INVITE_SUPPLIER}),
    S.SOURCING: frozenset({A.SEND_RFQ, A.SEND_RELAY_DRAFT, A.INVITE_SUPPLIER}),
    S.COLLECTING: frozenset(
        {
            A.RECORD_QUOTE,
            A.ASK_QUOTE_CLARIFICATION,
            A.SEND_REMINDER,
            A.SEND_RELAY_DRAFT,
            A.MARK_NO_RESPONSE,
            A.SUGGEST_MORE_SUPPLIERS,
            A.EXTEND_DEADLINE,
        }
    ),
    S.BIDDING: frozenset(
        {
            A.RUN_ROUND,
            A.SEND_RANK_FEEDBACK,
            A.RECORD_QUOTE,
            A.ASK_QUOTE_CLARIFICATION,
            A.SEND_REMINDER,
        }
    ),
    S.SHORTLISTED: frozenset({A.SHORTLIST, A.REQUEST_APPROVAL, A.RERANK}),
    S.AWAITING_APPROVAL: frozenset(
        {A.REQUEST_APPROVAL, A.REMIND_OWNER, A.REQUEST_VALIDITY_EXTENSION, A.RERANK}
    ),
    S.AWAITING_SUPPLIER_CONFIRM: frozenset({A.SEND_AWARD, A.SEND_REMINDER}),
    S.AWARDED: frozenset({A.SEND_REGRET, A.RECORD_DELIVERY}),
    S.DELIVERED: frozenset({A.RECORD_OUTCOME}),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset({A.SEND_REGRET}),
}


class IllegalTransitionError(ValueError):
    pass


def next_state(state: State, event: Event, facts: CaseFacts) -> State:
    try:
        target, guard = TRANSITIONS[(state, event)]
    except KeyError:
        raise IllegalTransitionError(f"{event.value} is not allowed in {state.value}") from None
    if not guard(facts):
        raise IllegalTransitionError(
            f"{event.value} in {state.value}: guard {guard.__name__} failed"
        )
    return target


def allowed_events(state: State) -> frozenset[Event]:
    return frozenset(e for (s, e) in TRANSITIONS if s is state)

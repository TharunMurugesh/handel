"""Competitive bidding: RULE-B1 to RULE-B6 (spec §8.3, M-06).

This module computes *facts* (who may bid, round deadlines, whether a bid improves, what
feedback is true). It never writes free text on its own: ``render_feedback`` fills the
fixed MSG-05 template, and ``handel.domain.policy.bidding_guard`` checks every message
before it can be sent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from handel.domain.model.calendar import BusinessHours
from handel.domain.model.entities import Supplier, SupplierMode
from handel.domain.model.money import Money
from handel.domain.rules.landed_cost import LandedCost
from handel.domain.rules.ranking import Ranking

MAX_ROUNDS = 2  # RULE-B5
MIN_ROUND = timedelta(hours=2)  # RULE-B5, business hours [A-9]

# RULE-B1: stated in every compete-mode request for quotes, before any bid.
RULES_SHORT_TEXT = (
    "Bidding rules: up to {rounds} improvement round(s) after the first quotes. "
    "Each round is open at least 2 business hours. You may only lower your own offer. "
    "We never share your name or prices with other suppliers. "
    "The final choice is made by {unit}, not automatically."
)
RELATIONSHIP_TEXT = "{unit} is comparing quotes."  # M-06: honest note for relationship suppliers


@dataclass(frozen=True, slots=True)
class BiddingPolicy:
    """Owner's settings for one purchase."""

    rounds: int = 1  # improvement rounds, 0..2 (default 1)
    show_price_to_beat: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.rounds <= MAX_ROUNDS:
            raise ValueError(f"improvement rounds must be 0..{MAX_ROUNDS}")


class BidRejectedError(ValueError):
    pass


def rules_text(policy: BiddingPolicy, unit_name: str, mode: SupplierMode) -> str:
    """RULE-B1 text for the request for quotes, by supplier mode."""
    if mode is SupplierMode.RELATIONSHIP:
        return RELATIONSHIP_TEXT.format(unit=unit_name)
    return RULES_SHORT_TEXT.format(rounds=policy.rounds, unit=unit_name)


def round_participants(suppliers: Iterable[Supplier], ranking: Ranking) -> tuple[str, ...]:
    """RULE-B5 + M-06: compete-mode suppliers with a ranked quote, except the current best."""
    best = ranking.best
    ranked = {e.supplier_id for e in ranking.entries}
    return tuple(
        sorted(
            s.id
            for s in suppliers
            if s.mode is SupplierMode.COMPETE
            and s.id in ranked
            and (best is None or s.id != best.supplier_id)
        )
    )


def target_met(ranking: Ranking, target_per_kg: Money | None) -> bool:
    best = ranking.best
    return target_per_kg is not None and best is not None and best.effective <= target_per_kg


def can_start_round(
    rounds_done: int, policy: BiddingPolicy, ranking: Ranking, target: Money | None
) -> bool:
    """Another improvement round is allowed and useful."""
    if rounds_done >= policy.rounds or target_met(ranking, target):
        return False
    return ranking.best is not None and len(ranking.entries) >= 2


def round_deadline(
    opens_at: datetime, hours: BusinessHours, duration: timedelta = MIN_ROUND
) -> datetime:
    if duration < MIN_ROUND:
        raise ValueError("a round must last at least 2 business hours (RULE-B5)")
    return hours.add(opens_at, duration)


def check_improvement(previous: LandedCost, new: LandedCost) -> None:
    """RULE-B5: a bid may only improve on the same supplier's own previous offer."""
    if previous.supplier_id != new.supplier_id:
        raise BidRejectedError("a bid is compared only with the same supplier's own offer")
    if new.effective >= previous.effective:
        raise BidRejectedError(
            f"bid {new.effective}/kg does not improve on the previous {previous.effective}/kg"
        )


@dataclass(frozen=True, slots=True)
class RankFeedback:
    """The only facts MSG-05 may carry (RULE-B2, RULE-B3)."""

    supplier_id: str
    round_no: int
    is_lowest: bool
    round_deadline: datetime
    price_to_beat: Money | None  # current best *effective landed* figure, never a raw quote


def feedback_for(
    supplier_id: str, ranking: Ranking, round_no: int, deadline: datetime, policy: BiddingPolicy
) -> RankFeedback:
    position = ranking.position_of(supplier_id)
    best = ranking.best
    if position is None or best is None:
        raise ValueError("feedback only for a supplier with a ranked quote")
    if not 1 <= round_no <= policy.rounds:
        raise ValueError("round number outside the owner's limit")
    return RankFeedback(
        supplier_id=supplier_id,
        round_no=round_no,
        is_lowest=position == 1,
        round_deadline=deadline,
        price_to_beat=best.effective if policy.show_price_to_beat and position != 1 else None,
    )


def render_feedback(feedback: RankFeedback, hours: BusinessHours) -> str:
    """MSG-05 in English (translation happens later, from the same facts)."""
    when = feedback.round_deadline.astimezone(hours.zone).strftime("%d %b, %H:%M")
    if feedback.is_lowest:
        text = f"Your offer is currently the lowest. The round closes {when}."
    else:
        text = f"Your offer is currently not the lowest. You may improve it by {when}."
    if feedback.price_to_beat is not None:
        text += f" Price to beat: {feedback.price_to_beat}/kg landed."
    return text

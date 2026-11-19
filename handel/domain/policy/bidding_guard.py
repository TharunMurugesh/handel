"""Checks every bidding message before it can be sent (RULE-B2 to RULE-B5, BD-01).

Two layers, both must pass:
- **Facts:** the feedback's claims are true against the current ranking, the recipient
  may take part in this round, and the round is within the owner's limit.
- **Text:** the rendered message contains no other supplier's name or id, no other
  supplier's quoted rate, and not the owner's ceiling. Any number in the text that equals
  a forbidden figure blocks the message (failing safe), unless it is the true
  price to beat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from handel.domain.model.entities import Quote, Supplier, SupplierMode
from handel.domain.model.money import Money
from handel.domain.rules.bidding import BiddingPolicy, RankFeedback
from handel.domain.rules.ranking import Ranking
from handel.domain.rules.weights import rate_per_kg

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(Decimal(token.replace(",", "")))
        except InvalidOperation:  # pragma: no cover - the regex only matches digits
            continue
    return found


def _money_forms(m: Money) -> set[Decimal]:
    """How a figure might appear in text: rupees (62.5, 62.50), and whole paise."""
    return {m.to_rupees(), Decimal(m.paise)}


def check_feedback(
    feedback: RankFeedback,
    text: str,
    ranking: Ranking,
    suppliers: Iterable[Supplier],
    quotes: Iterable[Quote],
    policy: BiddingPolicy,
    ceiling: Money | None,
) -> tuple[str, ...]:
    """Return the violations; an empty tuple means the message may be sent."""
    violations: list[str] = []
    by_id = {s.id: s for s in suppliers}
    recipient = by_id.get(feedback.supplier_id)

    # RULE-B5: who and when
    if recipient is None:
        violations.append("recipient is not a supplier on this case")
    elif recipient.mode is not SupplierMode.COMPETE:
        violations.append("relationship-mode suppliers get no rank feedback (FR-BUY-14)")
    if not 1 <= feedback.round_no <= policy.rounds:
        violations.append("round outside the owner's limit (RULE-B5)")

    # RULE-B2: truthfulness
    position = ranking.position_of(feedback.supplier_id)
    best = ranking.best
    if position is None or best is None:
        violations.append("recipient has no ranked quote, so no feedback can be true")
    else:
        if feedback.is_lowest != (position == 1):
            violations.append("feedback misstates whether the offer is the lowest (RULE-B2)")
        if feedback.price_to_beat is not None:
            if not policy.show_price_to_beat:
                violations.append("price to beat shown but the owner did not allow it")
            if feedback.price_to_beat != best.effective:
                violations.append(
                    "price to beat is not the true current best landed figure (RULE-B2)"
                )

    # RULE-B3 / BD-01: text must not leak
    lowered = text.casefold()
    for s in by_id.values():
        if s.id == feedback.supplier_id:
            continue
        if s.name.casefold() in lowered or s.id.casefold() in lowered:
            violations.append(f"message reveals another supplier ({s.id}) (RULE-B3)")

    forbidden: set[Decimal] = set()
    for q in quotes:
        if q.supplier_id == feedback.supplier_id or q.rate is None:
            continue
        forbidden |= _money_forms(q.rate)
        if q.rate_unit is not None and (q.rate_unit.mass_unit is not None or q.piece_weight):
            forbidden |= _money_forms(rate_per_kg(q.rate, q.rate_unit, q.piece_weight))
    ceiling_forms = _money_forms(ceiling) if ceiling is not None else set()
    allowed = _money_forms(feedback.price_to_beat) if feedback.price_to_beat is not None else set()
    present = _numbers(text)
    if (present & forbidden) - allowed:
        violations.append("message contains another supplier's quoted rate (RULE-B3)")
    if (present & ceiling_forms) - allowed:
        violations.append("message contains the owner's ceiling (RULE-B4)")

    return tuple(violations)

"""Ranking (spec §8.2).

1. Quotes with an unresolved specification deviation are excluded and shown separately.
2. Late quotes rank below on-time quotes, unless the owner says otherwise (RULE-L6).
3. Sort by effective landed cost, ascending.
4. Tie-break within 0.5%: earlier delivery, then higher supplier reliability, then longer credit.

Grouping for the 0.5% tie-break is anchored: the cheapest remaining quote starts a group,
and every quote within 0.5% *of that anchor* joins it. This keeps the ordering
deterministic (a chain A≈B≈C never merges quotes more than 0.5% apart). The final
tie-break is the quote id, so the result never depends on input order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from handel.domain.model.entities import Quote, Supplier
from handel.domain.model.money import Money
from handel.domain.rules.landed_cost import Flag, LandedCost

TIE_BAND = Decimal("0.005")  # 0.5%


@dataclass(frozen=True, slots=True)
class Candidate:
    landed: LandedCost
    delivery_date: date | None
    reliability: Decimal | None
    credit_days: int
    deviation_unresolved: bool

    @property
    def quote_id(self) -> str:
        return self.landed.quote_id

    @property
    def late(self) -> bool:
        return Flag.LATE in self.landed.flags


def candidate(landed: LandedCost, quote: Quote, supplier: Supplier) -> Candidate:
    if landed.quote_id != quote.id or quote.supplier_id != supplier.id:
        raise ValueError("landed cost, quote and supplier don't belong together")
    return Candidate(
        landed=landed,
        delivery_date=quote.delivery_date,
        reliability=supplier.reliability,
        credit_days=quote.payment.credit_days if quote.payment else 0,
        deviation_unresolved=quote.has_unresolved_deviation,
    )


@dataclass(frozen=True, slots=True)
class RankedEntry:
    position: int
    quote_id: str
    supplier_id: str
    effective: Money
    flags: frozenset[Flag]
    reason: str


@dataclass(frozen=True, slots=True)
class Excluded:
    quote_id: str
    supplier_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Ranking:
    entries: tuple[RankedEntry, ...]
    excluded: tuple[Excluded, ...]

    @property
    def best(self) -> RankedEntry | None:
        return self.entries[0] if self.entries else None

    def position_of(self, supplier_id: str) -> int | None:
        for e in self.entries:
            if e.supplier_id == supplier_id:
                return e.position
        return None


def _within_band(anchor: Money, other: Money) -> bool:
    return (other.exact() - anchor.exact()) <= anchor.exact() * TIE_BAND


def _tiebreak_key(c: Candidate) -> tuple[date, Decimal, int, int, str]:
    return (
        c.delivery_date or date.max,  # earlier delivery first; unknown last
        -(
            c.reliability if c.reliability is not None else Decimal(-1)
        ),  # higher first; unknown last
        -c.credit_days,  # longer credit first
        c.landed.effective.paise,
        c.quote_id,
    )


def _order(group: list[Candidate]) -> list[tuple[Candidate, bool]]:
    """Order one tier (on-time or late). Returns (candidate, decided_by_tiebreak)."""
    remaining = sorted(group, key=lambda c: (c.landed.effective.paise, c.quote_id))
    out: list[tuple[Candidate, bool]] = []
    while remaining:
        anchor = remaining[0].landed.effective
        band = [c for c in remaining if _within_band(anchor, c.landed.effective)]
        in_band = {c.quote_id for c in band}
        remaining = [c for c in remaining if c.quote_id not in in_band]
        band.sort(key=_tiebreak_key)
        out.extend((c, len(band) > 1) for c in band)
    return out


def rank(candidates: Iterable[Candidate], penalise_late: bool = True) -> Ranking:
    all_c = list(candidates)
    ids = [c.quote_id for c in all_c]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate quote ids")

    excluded = tuple(
        Excluded(
            c.quote_id, c.landed.supplier_id, "does not match the specification; shown separately"
        )
        for c in sorted(all_c, key=lambda c: c.quote_id)
        if c.deviation_unresolved
    )
    eligible = [c for c in all_c if not c.deviation_unresolved]
    if penalise_late:
        tiers = [[c for c in eligible if not c.late], [c for c in eligible if c.late]]
    else:
        tiers = [eligible]
    ordered = [item for tier in tiers for item in _order(tier)]

    entries: list[RankedEntry] = []
    best = ordered[0][0].landed.effective if ordered else Money.zero()
    for position, (c, tied) in enumerate(ordered, start=1):
        entries.append(
            RankedEntry(
                position=position,
                quote_id=c.quote_id,
                supplier_id=c.landed.supplier_id,
                effective=c.landed.effective,
                flags=c.landed.flags,
                reason=_reason(position, c, best, tied, penalise_late),
            )
        )
    return Ranking(tuple(entries), excluded)


def _reason(position: int, c: Candidate, best: Money, tied: bool, penalise_late: bool) -> str:
    eff = c.landed.effective
    parts: list[str] = []
    if position == 1:
        parts.append(f"lowest effective landed cost, {eff}/kg")
    else:
        parts.append(f"{eff}/kg landed, {eff - best}/kg more than the best")
    if tied:
        parts.append(
            "within 0.5% of another quote, so ordered by delivery date, reliability and credit"
        )
    if c.late and penalise_late:
        parts.append("delivers after the date needed, so ranked below on-time quotes")
    if Flag.STALE in c.landed.flags:
        parts.append("quote has expired: refresh before award")
    return "; ".join(parts)

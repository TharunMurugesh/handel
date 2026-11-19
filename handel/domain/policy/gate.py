"""Approval and policy gate (spec M-13, BD-01..BD-04, AG-06; architecture §4.3).

Every action the agent proposes passes ``evaluate`` before anything happens. The gate:
1. allows only actions the state machine lists for the current state;
2. requires a recorded, unused, unexpired approval **from the owner** for actions that
   move money, commit the owner or share personal data;
3. for awards: requires a fresh, specification-matching quote within the owner's ceiling
   (or a separate approval to exceed it), and the approval must be for these exact terms.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from handel.domain.cases.purchase import ALLOWED_ACTIONS, Action, State
from handel.domain.model.entities import Quote, Role
from handel.domain.model.money import Money
from handel.domain.rules.landed_cost import Flag, LandedCost


class ApprovalKind(StrEnum):
    """M-13: things Handel can never do without a person's recorded approval."""

    AWARD = "award"
    SEND_QUOTE = "send_quote"
    JOIN_POOL = "join_pool"
    REFER_JOB = "refer_job"
    SHARE_PERSONAL_DATA = "share_personal_data"
    EXCEED_LIMIT = "exceed_limit"
    COMMIT_STATEMENT = "commit_statement"


REQUIRES_APPROVAL: dict[Action, ApprovalKind] = {Action.SEND_AWARD: ApprovalKind.AWARD}
AUTHORISED_ROLES = frozenset({Role.OWNER})


class Approval(BaseModel):
    """A recorded human approval (spec §9 Approval). One-time use."""

    model_config = ConfigDict(frozen=True)

    id: str
    case_id: str
    kind: ApprovalKind
    approver_id: str
    approver_role: Role
    granted_at: datetime
    expires_at: datetime
    terms_digest: str | None = None  # for awards: the exact terms approved
    used: bool = False


def award_terms_digest(quote: Quote, landed: LandedCost) -> str:
    """Fingerprint of the exact terms in the award message (MSG-06), for two-sided confirmation."""
    terms = {
        "quote_id": quote.id,
        "supplier_id": quote.supplier_id,
        "rate_paise": quote.rate.paise if quote.rate else None,
        "rate_unit": quote.rate_unit.value if quote.rate_unit else None,
        "quantity_kg": str(landed.quantity.kg),
        "freight_terms": quote.freight_terms.value if quote.freight_terms else None,
        "gst_pct": str(quote.gst_pct) if quote.gst_pct is not None else None,
        "tax_invoice": quote.tax_invoice,
        "payment": [quote.payment.kind.value, quote.payment.days] if quote.payment else None,
        "delivery_date": quote.delivery_date.isoformat() if quote.delivery_date else None,
        "charges": [[c.name, c.amount.paise, c.basis.value] for c in quote.charges],
        "effective_paise": landed.effective.paise,
    }
    canonical = json.dumps(terms, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AwardFacts:
    quote_id: str
    terms_digest: str
    flags: frozenset[Flag]
    effective: Money
    ceiling: Money | None


@dataclass(frozen=True, slots=True)
class Proposal:
    case_id: str
    state: State
    action: Action
    award: AwardFacts | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    violations: tuple[str, ...]
    consume: tuple[str, ...] = ()  # approval ids to mark used if the action goes ahead


def _find(
    approvals: list[Approval], case_id: str, kind: ApprovalKind, now: datetime, digest: str | None
) -> Approval | None:
    for a in approvals:
        if (
            a.case_id == case_id
            and a.kind is kind
            and not a.used
            and a.granted_at <= now < a.expires_at
            and a.approver_role in AUTHORISED_ROLES
            and (digest is None or a.terms_digest == digest)
        ):
            return a
    return None


def evaluate(proposal: Proposal, approvals: Iterable[Approval], now: datetime) -> Decision:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    pool = sorted(approvals, key=lambda a: (a.granted_at, a.id))
    violations: list[str] = []
    consume: list[str] = []

    if proposal.action not in ALLOWED_ACTIONS[proposal.state]:
        violations.append(f"{proposal.action.value} is not allowed in state {proposal.state.value}")

    kind = REQUIRES_APPROVAL.get(proposal.action)
    if kind is ApprovalKind.AWARD:
        facts = proposal.award
        if facts is None:
            violations.append("award proposed without award facts")
        else:
            if Flag.STALE in facts.flags:
                violations.append("quote has expired; refresh it before award (RULE-L6)")
            if Flag.DEVIATION in facts.flags:
                violations.append("quote does not match the specification")
            approval = _find(pool, proposal.case_id, kind, now, facts.terms_digest)
            if approval is None:
                violations.append("no valid owner approval for these exact award terms")
            else:
                consume.append(approval.id)
            if facts.ceiling is not None and facts.effective > facts.ceiling:
                over = _find(pool, proposal.case_id, ApprovalKind.EXCEED_LIMIT, now, None)
                if over is None:
                    violations.append(
                        "above the owner's ceiling without approval to exceed it (BD-01)"
                    )
                else:
                    consume.append(over.id)

    if violations:
        return Decision(False, tuple(violations))
    return Decision(True, (), tuple(consume))

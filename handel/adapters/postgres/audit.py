"""Append-only, hash-chained audit log (DT-04, ADR-010).

Each row stores ``hash = sha256(prev_hash + canonical(row))``. Changing, deleting or
re-ordering any row breaks every hash after it, which ``verify`` reports. Appends take a
transaction-scoped advisory lock so the chain has a single order.

Payloads hold ids and facts only, never personal data, so erasure requests (DT-05) never
need to edit the log.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres.util import canonical_json, utc

GENESIS = "0" * 64
_CHAIN_LOCK = 4_242_001  # pg_advisory_xact_lock key for the audit chain


@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor_type: str  # person / agent / system
    actor_id: str
    action: str
    unit_id: str | None = None
    case_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def _digest(prev_hash: str, entry: AuditEntry, created_at: datetime) -> str:
    body = canonical_json(
        {
            "unit_id": entry.unit_id,
            "case_ref": entry.case_ref,
            "actor_type": entry.actor_type,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "payload": entry.payload,
            "created_at": utc(created_at).isoformat(),
        }
    )
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


async def append(conn: AsyncConnection, entry: AuditEntry, now: datetime) -> str:
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK})
    prev = (
        await conn.execute(text("SELECT hash FROM ops.audit_event ORDER BY id DESC LIMIT 1"))
    ).scalar()
    prev_hash = str(prev) if prev is not None else GENESIS
    digest = _digest(prev_hash, entry, now)
    await conn.execute(
        text(
            """
            INSERT INTO ops.audit_event (unit_id, case_ref, actor_type, actor_id, action, payload,
                                         created_at, prev_hash, hash)
            VALUES (:unit_id, :case_ref, :actor_type, :actor_id, :action, CAST(:payload AS jsonb),
                    :created_at, :prev_hash, :hash)
            """
        ),
        {
            "unit_id": entry.unit_id,
            "case_ref": entry.case_ref,
            "actor_type": entry.actor_type,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "payload": canonical_json(entry.payload),
            "created_at": utc(now),
            "prev_hash": prev_hash,
            "hash": digest,
        },
    )
    return digest


@dataclass(frozen=True, slots=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_id: int | None = None
    reason: str | None = None


async def verify(conn: AsyncConnection) -> VerifyResult:
    rows = (
        await conn.execute(
            text(
                "SELECT id, unit_id, case_ref, actor_type, actor_id, action, payload, created_at, "
                "prev_hash, hash FROM ops.audit_event ORDER BY id"
            )
        )
    ).all()
    expected_prev = GENESIS
    for n, r in enumerate(rows, start=1):
        if r.prev_hash != expected_prev:
            return VerifyResult(
                False, n, r.id, "chain broken: prev_hash does not match the row before"
            )
        entry = AuditEntry(
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            action=r.action,
            unit_id=r.unit_id,
            case_ref=r.case_ref,
            payload=dict(r.payload),
        )
        if _digest(r.prev_hash, entry, r.created_at) != r.hash:
            return VerifyResult(False, n, r.id, "row content does not match its hash")
        expected_prev = r.hash
    return VerifyResult(True, len(rows))

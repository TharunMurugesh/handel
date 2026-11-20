"""Case persistence: one agent step = one transaction (architecture §4.1 step 3).

``commit_step`` writes, atomically and in the caller's transaction:
- the new case state, guarded by optimistic locking on ``version``;
- one ``case_event`` (the case timeline, ``seq`` = new version);
- the step's outbox messages, timers and timer cancellations;
- an audit entry.
Either all of it commits or none of it does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres import audit, outbox, timers
from handel.adapters.postgres.util import utc


class StaleCaseError(RuntimeError):
    """The case changed since it was loaded; reload and re-plan."""


@dataclass(frozen=True, slots=True)
class CaseRow:
    id: str
    unit_id: str
    need_id: str
    state: str
    version: int
    plan: list[Any]


@dataclass(frozen=True, slots=True)
class CaseStep:
    case_id: str
    unit_id: str
    expected_version: int
    new_state: str
    event_kind: str
    event_payload: dict[str, Any] = field(default_factory=dict)
    plan: list[Any] | None = None
    messages: tuple[outbox.OutboxMessage, ...] = ()
    timers: tuple[timers.Timer, ...] = ()
    cancel_timers: tuple[str, ...] = ()  # timer kinds to cancel for this case
    audit: audit.AuditEntry | None = None


async def create_need(
    conn: AsyncConnection, need_id: str, unit_id: str, payload: dict[str, Any]
) -> None:
    await conn.execute(
        text(
            "INSERT INTO cases.need (id, unit_id, payload) "
            "VALUES (:id, :unit_id, CAST(:payload AS jsonb))"
        ),
        {"id": need_id, "unit_id": unit_id, "payload": json.dumps(payload)},
    )


async def create_case(
    conn: AsyncConnection, case_id: str, unit_id: str, need_id: str, state: str, now: datetime
) -> CaseRow:
    await conn.execute(
        text(
            """
            INSERT INTO cases.purchase_case (id, unit_id, need_id, state, created_at, updated_at)
            VALUES (:id, :unit_id, :need_id, :state, :now, :now)
            """
        ),
        {"id": case_id, "unit_id": unit_id, "need_id": need_id, "state": state, "now": utc(now)},
    )
    return CaseRow(case_id, unit_id, need_id, state, 0, [])


async def load_case(conn: AsyncConnection, case_id: str) -> CaseRow | None:
    r = (
        await conn.execute(
            text(
                "SELECT id, unit_id, need_id, state, version, plan "
                "FROM cases.purchase_case WHERE id = :id"
            ),
            {"id": case_id},
        )
    ).first()
    if r is None:
        return None
    return CaseRow(r.id, r.unit_id, r.need_id, r.state, r.version, list(r.plan))


async def commit_step(conn: AsyncConnection, step: CaseStep, now: datetime) -> int:
    """Apply one step. Returns the new version. Raises ``StaleCaseError`` on a lost race."""
    result = await conn.execute(
        text(
            """
            UPDATE cases.purchase_case
            SET state = :state, version = version + 1, updated_at = :now,
                plan = COALESCE(CAST(:plan AS jsonb), plan)
            WHERE id = :id AND version = :expected
            """
        ),
        {
            "state": step.new_state,
            "now": utc(now),
            "plan": None if step.plan is None else json.dumps(step.plan),
            "id": step.case_id,
            "expected": step.expected_version,
        },
    )
    if result.rowcount != 1:
        raise StaleCaseError(f"case {step.case_id} is not at version {step.expected_version}")
    version = step.expected_version + 1
    await conn.execute(
        text(
            """
            INSERT INTO cases.case_event (unit_id, case_id, seq, kind, payload, created_at)
            VALUES (:unit_id, :case_id, :seq, :kind, CAST(:payload AS jsonb), :now)
            """
        ),
        {
            "unit_id": step.unit_id,
            "case_id": step.case_id,
            "seq": version,
            "kind": step.event_kind,
            "payload": json.dumps(step.event_payload),
            "now": utc(now),
        },
    )
    for kind in step.cancel_timers:
        await timers.cancel(conn, step.case_id, kind, now)
    for timer in step.timers:
        await timers.schedule(conn, timer)
    for message in step.messages:
        await outbox.put(conn, message, now)
    if step.audit is not None:
        await audit.append(conn, step.audit, now)
    return version


async def timeline(conn: AsyncConnection, case_id: str) -> list[tuple[int, str]]:
    rows = (
        await conn.execute(
            text("SELECT seq, kind FROM cases.case_event WHERE case_id = :id ORDER BY seq"),
            {"id": case_id},
        )
    ).all()
    return [(r.seq, r.kind) for r in rows]

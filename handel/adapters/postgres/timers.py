"""Durable timers (architecture §4.1 step 5): T1/T2 reminders, deadlines, round closes.

A due timer is fired exactly once: the scheduler marks it fired and enqueues a
``case.timer`` job in one transaction, skipping rows another scheduler has locked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres import jobs
from handel.adapters.postgres.util import utc

TIMER_JOB = "case.timer"


@dataclass(frozen=True, slots=True)
class Timer:
    unit_id: str
    case_id: str
    kind: str  # e.g. "T1_REMINDER_DUE", "DEADLINE_REACHED"
    due_at: datetime


async def schedule(conn: AsyncConnection, timer: Timer) -> bool:
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO ops.timer (unit_id, case_id, kind, due_at)
                VALUES (:unit_id, :case_id, :kind, :due_at)
                ON CONFLICT (case_id, kind, due_at) DO NOTHING
                RETURNING id
                """
            ),
            {
                "unit_id": timer.unit_id,
                "case_id": timer.case_id,
                "kind": timer.kind,
                "due_at": utc(timer.due_at),
            },
        )
    ).first()
    return row is not None


async def cancel(conn: AsyncConnection, case_id: str, kind: str, now: datetime) -> int:
    result = await conn.execute(
        text(
            """
            UPDATE ops.timer SET cancelled_at = :now
            WHERE case_id = :case_id AND kind = :kind AND fired_at IS NULL AND cancelled_at IS NULL
            """
        ),
        {"case_id": case_id, "kind": kind, "now": utc(now)},
    )
    return int(result.rowcount)


async def fire_due(conn: AsyncConnection, now: datetime, limit: int = 100) -> list[int]:
    """Fire due timers in the caller's transaction; returns the fired timer ids."""
    rows = (
        await conn.execute(
            text(
                """
                UPDATE ops.timer SET fired_at = :now
                WHERE id IN (
                    SELECT id FROM ops.timer
                    WHERE fired_at IS NULL AND cancelled_at IS NULL AND due_at <= :now
                    ORDER BY due_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                )
                RETURNING id, unit_id, case_id, kind, due_at
                """
            ),
            {"now": utc(now), "limit": limit},
        )
    ).all()
    for r in rows:
        await jobs.enqueue(
            conn,
            TIMER_JOB,
            {
                "timer_id": r.id,
                "case_id": r.case_id,
                "kind": r.kind,
                "due_at": r.due_at.isoformat(),
            },
            now,
            unit_id=r.unit_id,
            idempotency_key=f"timer:{r.id}",
        )
    return sorted(r.id for r in rows)

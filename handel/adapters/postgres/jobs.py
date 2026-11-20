"""Job queue on Postgres (architecture §4.1, ADR-003).

At-least-once delivery with exactly-once *effects*: a handler's writes and the job's
``done`` mark commit in one transaction, guarded by the claim (``locked_by``). If a
worker dies, its lease expires and another worker re-runs the job; the dead worker's
uncommitted writes were rolled back by Postgres.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres.util import backoff, utc


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    unit_id: str | None
    attempts: int
    max_attempts: int
    locked_by: str


class LeaseLostError(RuntimeError):
    """Another worker took this job over after our lease expired; our writes must roll back."""


async def enqueue(
    conn: AsyncConnection,
    kind: str,
    payload: dict[str, Any],
    now: datetime,
    *,
    unit_id: str | None = None,
    run_after: datetime | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
) -> int | None:
    """Add a job in the caller's transaction. Returns its id, or None if the key already exists."""
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO ops.job (kind, payload, unit_id, run_after, idempotency_key,
                                     max_attempts, created_at)
                VALUES (:kind, CAST(:payload AS jsonb), :unit_id, :run_after, :key, :max, :now)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "kind": kind,
                "payload": json.dumps(payload),
                "unit_id": unit_id,
                "run_after": utc(run_after or now),
                "key": idempotency_key,
                "max": max_attempts,
                "now": utc(now),
            },
        )
    ).first()
    return None if row is None else int(row[0])


async def claim(
    conn: AsyncConnection, worker_id: str, now: datetime, lease: timedelta, kinds: tuple[str, ...]
) -> Job | None:
    """Claim one runnable job (queued and due, or running with an expired lease)."""
    row = (
        await conn.execute(
            text(
                """
                UPDATE ops.job SET status = 'running', attempts = attempts + 1,
                       locked_by = :worker, locked_until = :until
                WHERE id = (
                    SELECT id FROM ops.job
                    WHERE kind = ANY(:kinds)
                      AND ((status = 'queued' AND run_after <= :now)
                           OR (status = 'running' AND locked_until < :now))
                    ORDER BY run_after, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, kind, payload, unit_id, attempts, max_attempts, locked_by
                """
            ),
            {"worker": worker_id, "until": utc(now + lease), "now": utc(now), "kinds": list(kinds)},
        )
    ).first()
    if row is None:
        return None
    return Job(
        id=row.id,
        kind=row.kind,
        payload=dict(row.payload),
        unit_id=row.unit_id,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        locked_by=row.locked_by,
    )


async def complete(conn: AsyncConnection, job: Job, now: datetime) -> None:
    """Mark done in the handler's transaction. Raises if our claim was lost."""
    result = await conn.execute(
        text(
            """
            UPDATE ops.job SET status = 'done', done_at = :now, locked_until = NULL
            WHERE id = :id AND status = 'running' AND locked_by = :worker AND attempts = :attempts
            """
        ),
        {"id": job.id, "now": utc(now), "worker": job.locked_by, "attempts": job.attempts},
    )
    if result.rowcount != 1:
        raise LeaseLostError(f"job {job.id} was reclaimed by another worker")


async def fail(conn: AsyncConnection, job: Job, error: str, now: datetime) -> str:
    """Record a failed attempt: retry with backoff, or give up after max_attempts."""
    give_up = job.attempts >= job.max_attempts
    status = "failed" if give_up else "queued"
    await conn.execute(
        text(
            """
            UPDATE ops.job SET status = :status, last_error = :error, locked_until = NULL,
                   run_after = :run_after
            WHERE id = :id AND locked_by = :worker AND attempts = :attempts
            """
        ),
        {
            "status": status,
            "error": error[:2000],
            "run_after": utc(now if give_up else now + backoff(job.attempts)),
            "id": job.id,
            "worker": job.locked_by,
            "attempts": job.attempts,
        },
    )
    return status

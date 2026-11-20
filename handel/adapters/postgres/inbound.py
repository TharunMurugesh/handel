"""Inbound events (architecture §4.1 step 1): store fast, de-duplicate, hand to the worker."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres import jobs
from handel.adapters.postgres.util import utc
from handel.ports.channel import InboundMessage

PERCEIVE_JOB = "inbound.perceive"


async def record(conn: AsyncConnection, message: InboundMessage, now: datetime) -> int | None:
    """Store an inbound update once per ``(channel, update_id)`` and queue its perception job.

    Returns the new event id, or None for a duplicate delivery (webhooks retry).
    """
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO ops.inbound_event (channel, update_id, payload, received_at)
                VALUES (:channel, :update_id, CAST(:payload AS jsonb), :now)
                ON CONFLICT (channel, update_id) DO NOTHING
                RETURNING id
                """
            ),
            {
                "channel": message.channel.value,
                "update_id": message.update_id,
                "payload": message.model_dump_json(),
                "now": utc(now),
            },
        )
    ).first()
    if row is None:
        return None
    event_id = int(row[0])
    await jobs.enqueue(
        conn,
        PERCEIVE_JOB,
        {"inbound_event_id": event_id},
        now,
        idempotency_key=f"inbound:{event_id}",
    )
    return event_id

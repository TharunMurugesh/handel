"""Transactional outbox (architecture §4.1 step 4).

Messages are written in the same transaction as the case change that caused them, then
sent by the dispatcher. Each row has an idempotency key; inserting the same key twice is a
no-op, so a retried case step never queues a message twice.

Delivery is at-least-once: if a worker dies after the provider accepted a message but
before ``mark_sent`` commits, the row is retried with the same idempotency key. Channels
that support idempotency keys drop the repeat; Telegram does not, so that narrow window
can produce a duplicate chat message (never a lost one).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres.util import backoff, utc
from handel.ports.channel import Address, Button, ChannelKind, ContentKind, OutboundMessage

# Sent without prior consent: the invite the owner forwards, and the notice itself (spec §10).
CONSENT_EXEMPT = frozenset({"MSG-00", "MSG-01"})


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    unit_id: str
    idempotency_key: str
    message_id: str  # spec §10 catalogue id, e.g. "MSG-02"
    purpose: str  # consent purpose, e.g. "procurement"
    party_type: str  # person / supplier / transporter / buyer
    party_id: str
    to: Address
    body: dict[str, Any]  # kind, text, media_key, buttons
    case_id: str | None = None

    @classmethod
    def from_outbound(
        cls,
        message: OutboundMessage,
        *,
        unit_id: str,
        message_id: str,
        purpose: str,
        party_type: str,
        party_id: str,
        case_id: str | None = None,
    ) -> OutboxMessage:
        body = {
            "kind": message.kind.value,
            "text": message.text,
            "media_key": message.media_key,
            "buttons": [b.model_dump() for b in message.buttons],
        }
        return cls(
            unit_id=unit_id,
            idempotency_key=message.idempotency_key,
            message_id=message_id,
            purpose=purpose,
            party_type=party_type,
            party_id=party_id,
            to=message.to,
            body=body,
            case_id=case_id,
        )


@dataclass(frozen=True, slots=True)
class ClaimedMessage:
    id: int
    unit_id: str
    message_id: str
    purpose: str
    party_type: str
    party_id: str
    attempts: int
    max_attempts: int
    claim_token: str
    outbound: OutboundMessage


async def put(conn: AsyncConnection, message: OutboxMessage, now: datetime) -> bool:
    """Queue a message in the caller's transaction. False if its key was already queued."""
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO ops.outbox (unit_id, case_id, idempotency_key, message_id, purpose,
                    channel, chat_id, party_type, party_id, body, next_attempt_at, created_at)
                VALUES (:unit_id, :case_id, :key, :message_id, :purpose, :channel, :chat_id,
                    :party_type, :party_id, CAST(:body AS jsonb), :now, :now)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "unit_id": message.unit_id,
                "case_id": message.case_id,
                "key": message.idempotency_key,
                "message_id": message.message_id,
                "purpose": message.purpose,
                "channel": message.to.channel.value,
                "chat_id": message.to.chat_id,
                "party_type": message.party_type,
                "party_id": message.party_id,
                "body": json.dumps(message.body),
                "now": utc(now),
            },
        )
    ).first()
    return row is not None


async def claim(
    conn: AsyncConnection,
    channels: tuple[ChannelKind, ...],
    now: datetime,
    lease: timedelta,
    limit: int,
) -> list[ClaimedMessage]:
    rows = (
        await conn.execute(
            text(
                """
                UPDATE ops.outbox SET status = 'sending', attempts = attempts + 1,
                       locked_until = :until, claim_token = :token
                WHERE id IN (
                    SELECT id FROM ops.outbox
                    WHERE channel = ANY(:channels)
                      AND ((status = 'queued' AND next_attempt_at <= :now)
                           OR (status = 'sending' AND locked_until < :now))
                    ORDER BY next_attempt_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                )
                RETURNING id, unit_id, message_id, purpose, party_type, party_id, attempts,
                          max_attempts, channel, chat_id, idempotency_key, body, claim_token
                """
            ),
            {
                "token": uuid.uuid4().hex,
                "until": utc(now + lease),
                "now": utc(now),
                "channels": [c.value for c in channels],
                "limit": limit,
            },
        )
    ).all()
    out = []
    for r in sorted(rows, key=lambda r: r.id):
        body = dict(r.body)
        out.append(
            ClaimedMessage(
                id=r.id,
                unit_id=r.unit_id,
                message_id=r.message_id,
                purpose=r.purpose,
                party_type=r.party_type,
                party_id=r.party_id,
                attempts=r.attempts,
                max_attempts=r.max_attempts,
                claim_token=r.claim_token,
                outbound=OutboundMessage(
                    to=Address(channel=ChannelKind(r.channel), chat_id=r.chat_id),
                    kind=ContentKind(body["kind"]),
                    text=body.get("text"),
                    media_key=body.get("media_key"),
                    buttons=tuple(Button(**b) for b in body.get("buttons", [])),
                    idempotency_key=r.idempotency_key,
                ),
            )
        )
    return out


async def touch(
    conn: AsyncConnection, msg: ClaimedMessage, now: datetime, lease: timedelta
) -> bool:
    """Renew our lease right before sending. False if another dispatcher has taken the row."""
    result = await conn.execute(
        text(
            "UPDATE ops.outbox SET locked_until = :until "
            "WHERE id = :id AND status = 'sending' AND claim_token = :token"
        ),
        {"until": utc(now + lease), "id": msg.id, "token": msg.claim_token},
    )
    return bool(result.rowcount == 1)


async def mark_sent(
    conn: AsyncConnection, msg: ClaimedMessage, provider_id: str, now: datetime
) -> None:
    await conn.execute(
        text(
            """
            UPDATE ops.outbox SET status = 'sent', sent_at = :now, provider_message_id = :pid,
                   locked_until = NULL
            WHERE id = :id AND status = 'sending' AND claim_token = :token
            """
        ),
        {"id": msg.id, "pid": provider_id, "now": utc(now), "token": msg.claim_token},
    )


async def mark_refused(conn: AsyncConnection, msg: ClaimedMessage, reason: str) -> None:
    await conn.execute(
        text(
            "UPDATE ops.outbox SET status = 'refused', last_error = :reason, locked_until = NULL "
            "WHERE id = :id AND claim_token = :token"
        ),
        {"id": msg.id, "reason": reason, "token": msg.claim_token},
    )


async def mark_failed_attempt(
    conn: AsyncConnection, msg: ClaimedMessage, error: str, now: datetime
) -> str:
    give_up = msg.attempts >= msg.max_attempts
    status = "failed" if give_up else "queued"
    await conn.execute(
        text(
            """
            UPDATE ops.outbox SET status = :status, last_error = :error, locked_until = NULL,
                   next_attempt_at = :next
            WHERE id = :id AND status = 'sending' AND claim_token = :token
            """
        ),
        {
            "token": msg.claim_token,
            "status": status,
            "error": error[:2000],
            "next": utc(now if give_up else now + backoff(msg.attempts)),
            "id": msg.id,
        },
    )
    return status

"""Consent records (DT-01, DT-05; architecture §10.1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres.util import utc


async def grant(
    conn: AsyncConnection,
    *,
    unit_id: str,
    party_type: str,
    party_id: str,
    purpose: str,
    notice_version: str,
    language: str,
    now: datetime,
) -> int:
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO privacy.consent (unit_id, party_type, party_id, purpose, notice_version,
                                             language, granted_at)
                VALUES (:unit_id, :party_type, :party_id, :purpose, :notice, :language, :now)
                RETURNING id
                """
            ),
            {
                "unit_id": unit_id,
                "party_type": party_type,
                "party_id": party_id,
                "purpose": purpose,
                "notice": notice_version,
                "language": language,
                "now": utc(now),
            },
        )
    ).one()
    return int(row[0])


async def withdraw(conn: AsyncConnection, *, party_type: str, party_id: str, now: datetime) -> int:
    """STOP: withdraw every purpose for this party."""
    result = await conn.execute(
        text(
            """
            UPDATE privacy.consent SET withdrawn_at = :now
            WHERE party_type = :party_type AND party_id = :party_id AND withdrawn_at IS NULL
            """
        ),
        {"party_type": party_type, "party_id": party_id, "now": utc(now)},
    )
    return int(result.rowcount)


async def is_granted(
    conn: AsyncConnection,
    *,
    unit_id: str,
    party_type: str,
    party_id: str,
    purpose: str,
    now: datetime,
) -> bool:
    row = (
        await conn.execute(
            text(
                """
                SELECT 1 FROM privacy.consent
                WHERE unit_id = :unit_id AND party_type = :party_type AND party_id = :party_id
                  AND purpose = :purpose AND granted_at <= :now
                  AND (withdrawn_at IS NULL OR withdrawn_at > :now)
                LIMIT 1
                """
            ),
            {
                "unit_id": unit_id,
                "party_type": party_type,
                "party_id": party_id,
                "purpose": purpose,
                "now": utc(now),
            },
        )
    ).first()
    return row is not None

"""Shared helpers for the Postgres adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any


def canonical_json(value: Any) -> str:
    """Stable JSON for hashing: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC)


def backoff(
    attempt: int, base: timedelta = timedelta(seconds=2), cap: timedelta = timedelta(minutes=10)
) -> timedelta:
    """Exponential backoff after the ``attempt``-th failure: 2s, 4s, 8s … capped at 10 min."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    delay: timedelta = base * (2 ** (attempt - 1))
    return min(delay, cap)

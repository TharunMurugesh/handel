"""Clock implementations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """A clock tests can move, so timers (T1, T2, deadlines) fire without waiting."""

    def __init__(self, start: datetime | None = None) -> None:
        start = start or datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start time")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("time only moves forward")
        self._now += delta
        return self._now

    def set(self, moment: datetime) -> None:
        if moment < self._now:
            raise ValueError("time only moves forward")
        self._now = moment

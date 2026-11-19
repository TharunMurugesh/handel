"""Business hours, for bidding-round deadlines (RULE-B5: each round ≥ 2 business hours).

Holidays are not modelled yet; the owner can always extend a deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


@dataclass(frozen=True, slots=True)
class BusinessHours:
    opens: time = time(9, 30)
    closes: time = time(18, 30)
    weekdays: frozenset[int] = field(
        default_factory=lambda: frozenset({MON, TUE, WED, THU, FRI, SAT})
    )
    tz: str = "Asia/Kolkata"

    def __post_init__(self) -> None:
        if self.opens >= self.closes:
            raise ValueError("business hours must open before they close")
        if not self.weekdays or not self.weekdays <= set(range(7)):
            raise ValueError("weekdays must be a non-empty subset of 0..6")
        ZoneInfo(self.tz)  # raises if unknown

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def _window(self, day: date) -> tuple[datetime, datetime] | None:
        if day.weekday() not in self.weekdays:
            return None
        return (
            datetime.combine(day, self.opens, self.zone),
            datetime.combine(day, self.closes, self.zone),
        )

    def add(self, start: datetime, duration: timedelta) -> datetime:
        """The moment ``duration`` of business time has passed after ``start``."""
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        if duration < timedelta(0):
            raise ValueError("duration must not be negative")
        cursor = start.astimezone(self.zone)
        remaining = duration
        day = cursor.date()
        for _ in range(3660):  # ten years of days: a hard stop against misconfiguration
            window = self._window(day)
            if window is not None:
                begin = max(window[0], cursor)
                if begin < window[1]:
                    available = window[1] - begin
                    if remaining <= available:
                        return begin + remaining
                    remaining -= available
            day += timedelta(days=1)
        raise ValueError("duration too long for business calendar")  # pragma: no cover

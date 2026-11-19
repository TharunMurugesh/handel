"""Clock port: all code asks this for the time, so tests can move time (timers T1/T2, deadlines)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, always timezone-aware UTC."""
        ...

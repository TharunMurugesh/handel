"""Outbound rate limits (architecture §4.1 step 4).

Telegram allows about 1 message/s per chat and about 30/s overall.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    def __init__(
        self,
        per_chat: timedelta = timedelta(seconds=1),
        global_per_second: int = 30,
    ) -> None:
        if global_per_second < 1:
            raise ValueError("global_per_second must be at least 1")
        self.per_chat = per_chat
        self.global_per_second = global_per_second
        self._last_by_chat: dict[str, datetime] = {}
        self._recent: deque[datetime] = deque()

    def delay(self, chat_id: str, now: datetime) -> timedelta:
        """How long to wait before sending to ``chat_id``. Zero means send now."""
        wait = timedelta(0)
        last = self._last_by_chat.get(chat_id)
        if last is not None:
            wait = max(wait, last + self.per_chat - now)
        window = timedelta(seconds=1)
        while self._recent and self._recent[0] <= now - window:
            self._recent.popleft()
        if len(self._recent) >= self.global_per_second:
            wait = max(wait, self._recent[0] + window - now)
        return wait

    def record(self, chat_id: str, now: datetime) -> None:
        self._last_by_chat[chat_id] = now
        self._recent.append(now)

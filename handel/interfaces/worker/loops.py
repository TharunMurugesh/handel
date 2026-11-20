"""Worker loops (architecture §4.1): job runner, outbox dispatcher, timer scheduler.

Each loop has ``run_once`` (one unit of work, used by tests with a fake clock) and
``run`` (poll until stopped). They talk to each other only through Postgres.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from handel.adapters.postgres import audit, consent, jobs, outbox, timers
from handel.interfaces.worker.ratelimit import RateLimiter
from handel.ports.channel import Channel, ChannelKind
from handel.ports.clock import Clock

log = logging.getLogger("handel.worker")

Handler = Callable[[AsyncConnection, jobs.Job], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


async def _poll(
    loop_once: Callable[[], Awaitable[int]], stop: asyncio.Event, idle_seconds: float
) -> None:
    while not stop.is_set():
        try:
            did = await loop_once()
        except Exception:
            log.exception("worker loop iteration failed")
            did = 0
        if did == 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), idle_seconds)


class JobRunner:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        handlers: Mapping[str, Handler],
        lease: timedelta,
        worker_id: str | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.handlers = dict(handlers)
        self.lease = lease
        self.worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}"

    async def run_once(self) -> int:
        if not self.handlers:
            return 0
        async with self.engine.begin() as conn:
            job = await jobs.claim(
                conn, self.worker_id, self.clock.now(), self.lease, tuple(self.handlers)
            )
        if job is None:
            return 0
        try:
            async with self.engine.begin() as conn:
                await self.handlers[job.kind](conn, job)
                await jobs.complete(conn, job, self.clock.now())
        except jobs.LeaseLostError:
            log.warning("job %s lease lost; its effects were rolled back", job.id)
        except Exception as exc:
            async with self.engine.begin() as conn:
                status = await jobs.fail(
                    conn, job, f"{type(exc).__name__}: {exc}", self.clock.now()
                )
            log.warning(
                "job %s (%s) failed attempt %d → %s", job.id, job.kind, job.attempts, status
            )
        return 1

    async def run(self, stop: asyncio.Event, idle_seconds: float) -> None:
        await _poll(self.run_once, stop, idle_seconds)


class Dispatcher:
    """Sends outbox rows through channel adapters, refusing any without consent (DT-01)."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        channels: Mapping[ChannelKind, Channel],
        lease: timedelta,
        limiter: RateLimiter | None = None,
        sleep: Sleep = asyncio.sleep,
        batch: int = 20,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.channels = dict(channels)
        self.lease = lease
        self.limiter = limiter or RateLimiter()
        self.sleep = sleep
        self.batch = batch

    async def run_once(self) -> int:
        if not self.channels:
            return 0
        async with self.engine.begin() as conn:
            claimed = await outbox.claim(
                conn, tuple(self.channels), self.clock.now(), self.lease, self.batch
            )
        for msg in claimed:
            await self._deliver(msg)
        return len(claimed)

    async def _deliver(self, msg: outbox.ClaimedMessage) -> None:
        now = self.clock.now()
        if msg.message_id not in outbox.CONSENT_EXEMPT:
            async with self.engine.begin() as conn:
                allowed = await consent.is_granted(
                    conn,
                    unit_id=msg.unit_id,
                    party_type=msg.party_type,
                    party_id=msg.party_id,
                    purpose=msg.purpose,
                    now=now,
                )
                if not allowed:
                    await outbox.mark_refused(conn, msg, f"no consent for purpose {msg.purpose!r}")
                    await audit.append(
                        conn,
                        audit.AuditEntry(
                            actor_type="system",
                            actor_id="dispatcher",
                            action="message_refused_no_consent",
                            unit_id=msg.unit_id,
                            payload={
                                "outbox_id": msg.id,
                                "message_id": msg.message_id,
                                "party_type": msg.party_type,
                                "party_id": msg.party_id,
                            },
                        ),
                        now,
                    )
                    return
        wait = self.limiter.delay(msg.outbound.to.chat_id, now)
        if wait > timedelta(0):
            await self.sleep(wait.total_seconds())
            now = self.clock.now()
        async with self.engine.begin() as conn:
            if not await outbox.touch(conn, msg, now, self.lease):
                log.info("outbox %s was reclaimed by another dispatcher; skipping", msg.id)
                return
        self.limiter.record(msg.outbound.to.chat_id, now)
        try:
            result = await self.channels[msg.outbound.to.channel].send(msg.outbound)
        except Exception as exc:
            async with self.engine.begin() as conn:
                status = await outbox.mark_failed_attempt(
                    conn, msg, f"{type(exc).__name__}: {exc}", self.clock.now()
                )
            log.warning("outbox %s attempt %d failed → %s", msg.id, msg.attempts, status)
            return
        async with self.engine.begin() as conn:
            await outbox.mark_sent(conn, msg, result.provider_message_id, self.clock.now())

    async def run(self, stop: asyncio.Event, idle_seconds: float) -> None:
        await _poll(self.run_once, stop, idle_seconds)


class Scheduler:
    def __init__(self, engine: AsyncEngine, clock: Clock, batch: int = 100) -> None:
        self.engine = engine
        self.clock = clock
        self.batch = batch

    async def run_once(self) -> int:
        async with self.engine.begin() as conn:
            fired = await timers.fire_due(conn, self.clock.now(), self.batch)
        return len(fired)

    async def run(self, stop: asyncio.Event, idle_seconds: float) -> None:
        await _poll(self.run_once, stop, idle_seconds)

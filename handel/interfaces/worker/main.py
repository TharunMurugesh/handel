"""Worker service (architecture §2.2): heartbeat, job runner, outbox dispatcher, timer scheduler.

P3 registers the case handlers and the Telegram/relay channels; until then the runner and
dispatcher have nothing registered and stay idle, while the scheduler already fires timers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Mapping
from datetime import timedelta

from handel import __version__
from handel.adapters.clock import SystemClock
from handel.adapters.postgres.db import make_engine, ping
from handel.config import Settings, get_settings
from handel.interfaces.worker.loops import Dispatcher, Handler, JobRunner, Scheduler
from handel.ports.channel import Channel, ChannelKind
from handel.ports.clock import Clock

log = logging.getLogger("handel.worker")


async def run(
    settings: Settings,
    stop: asyncio.Event,
    clock: Clock | None = None,
    max_beats: int | None = None,
) -> int:
    """Heartbeat until ``stop`` is set (or ``max_beats`` reached). Returns the number of beats."""
    clock = clock or SystemClock()
    engine = make_engine(settings.database_url)
    beats = 0
    try:
        while not stop.is_set():
            db_ok = await ping(engine)
            beats += 1
            log.info(
                "worker heartbeat beat=%d at=%s db=%s",
                beats,
                clock.now().isoformat(),
                "ok" if db_ok else "unreachable",
            )
            if max_beats is not None and beats >= max_beats:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), settings.worker_heartbeat_seconds)
    finally:
        await engine.dispose()
    log.info("worker stopped after %d beats", beats)
    return beats


async def run_worker(
    settings: Settings,
    stop: asyncio.Event,
    handlers: Mapping[str, Handler],
    channels: Mapping[ChannelKind, Channel],
    clock: Clock | None = None,
    worker_id: str | None = None,
) -> None:
    """Run heartbeat + job runner + dispatcher + scheduler until ``stop`` is set."""
    clock = clock or SystemClock()
    engine = make_engine(settings.database_url)
    idle = settings.worker_poll_seconds
    runner = JobRunner(
        engine, clock, handlers, timedelta(seconds=settings.job_lease_seconds), worker_id
    )
    dispatcher = Dispatcher(
        engine, clock, channels, timedelta(seconds=settings.outbox_lease_seconds)
    )
    scheduler = Scheduler(engine, clock)
    try:
        await asyncio.gather(
            run(settings, stop, clock),
            runner.run(stop, idle),
            dispatcher.run(stop, idle),
            scheduler.run(stop, idle),
        )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    log.info("worker starting version=%s env=%s", __version__, settings.env.value)

    async def _amain() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_worker(settings, stop, handlers={}, channels={})

    asyncio.run(_amain())


if __name__ == "__main__":
    main()

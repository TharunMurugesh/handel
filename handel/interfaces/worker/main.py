"""Worker service (architecture §2.2). P0: a heartbeat loop with clean shutdown.

P2 adds the job claimer, outbox dispatcher and timer scheduler to this loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from handel import __version__
from handel.adapters.clock import SystemClock
from handel.adapters.postgres.db import make_engine, ping
from handel.config import Settings, get_settings
from handel.ports.clock import Clock

log = logging.getLogger("handel.worker")


async def run(
    settings: Settings,
    stop: asyncio.Event,
    clock: Clock | None = None,
    max_beats: int | None = None,
) -> int:
    """Beat until ``stop`` is set (or ``max_beats`` reached). Returns the number of beats."""
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    log.info("worker starting version=%s env=%s", __version__, settings.env.value)

    async def _amain() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run(settings, stop)

    asyncio.run(_amain())


if __name__ == "__main__":
    main()

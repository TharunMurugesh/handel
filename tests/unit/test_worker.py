from __future__ import annotations

import asyncio
import logging

import pytest

from handel.adapters.clock import FakeClock
from handel.config import Settings
from handel.interfaces.worker.main import run


async def test_worker_beats_and_reports_unreachable_db(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="handel.worker")
    beats = await run(settings, asyncio.Event(), clock=FakeClock(), max_beats=3)
    assert beats == 3
    lines = [r.getMessage() for r in caplog.records if "heartbeat" in r.getMessage()]
    assert len(lines) == 3
    assert all("db=unreachable" in line for line in lines)


async def test_worker_stops_promptly_when_signalled(settings: Settings) -> None:
    slow = settings.model_copy(update={"worker_heartbeat_seconds": 60.0})
    stop = asyncio.Event()
    task = asyncio.create_task(run(slow, stop))
    await asyncio.sleep(0.2)
    stop.set()
    beats = await asyncio.wait_for(task, timeout=5)  # far less than the 60 s interval
    assert beats >= 1

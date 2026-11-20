"""P2 gate: kill workers with SIGKILL mid-job 50 times; nothing is lost or done twice.

Checks:
- every job's effect is committed exactly once (effects and ``done`` share a transaction);
- every job ends ``done`` and every queued message ends ``sent``;
- the external channel received every message.

Re-sends of the *same* message can only happen if a kill lands between the provider
accepting a message and the ``sent`` mark committing. The test counts them and reports
the number; they are bounded by the number of kills.
"""

from __future__ import annotations

import asyncio
import os
import random
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from handel.adapters.postgres import consent, jobs
from tests.integration.conftest import REPO_ROOT, add_unit

pytestmark = pytest.mark.integration

N_JOBS = 400
KILLS = 50
WORKERS = 2


def _spawn(url: str, sent_log: Path) -> subprocess.Popen[bytes]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HANDEL_DATABASE_URL": url,
        "HANDEL_ENV": "test",
        "HANDEL_WORKER_POLL_SECONDS": "0.05",
        "HANDEL_JOB_LEASE_SECONDS": "1.5",
        "HANDEL_OUTBOX_LEASE_SECONDS": "1.5",
        "HANDEL_WORKER_HEARTBEAT_SECONDS": "60",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "tests.integration.crash_worker", str(sent_log)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _counts(engine: AsyncEngine) -> tuple[int, int]:
    async with engine.connect() as conn:
        done = (
            await conn.execute(text("SELECT count(*) FROM ops.job WHERE status = 'done'"))
        ).scalar_one()
        sent = (
            await conn.execute(text("SELECT count(*) FROM ops.outbox WHERE status = 'sent'"))
        ).scalar_one()
    return int(done), int(sent)


async def test_sigkill_fifty_times_loses_nothing_and_repeats_no_effect(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    url = engine.url.render_as_string(hide_password=False)
    sent_log = tmp_path / "sent.log"
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS public.crash_effect"))
        await conn.execute(
            text("CREATE TABLE public.crash_effect (job_id bigint NOT NULL, n int NOT NULL)")
        )
        await add_unit(conn, "U1")
        await consent.grant(
            conn,
            unit_id="U1",
            party_type="supplier",
            party_id="S1",
            purpose="procurement",
            notice_version="MSG-01 v1",
            language="ta",
            now=now,
        )
        for n in range(N_JOBS):
            await jobs.enqueue(
                conn, "test.effect", {"n": n}, now, idempotency_key=f"crash:{n}", max_attempts=50
            )

    rng = random.Random(20261201)
    procs = [_spawn(url, sent_log) for _ in range(WORKERS)]
    kills_mid_work = 0
    try:
        for _ in range(KILLS):
            await asyncio.sleep(rng.uniform(0.1, 0.35))
            i = rng.randrange(WORKERS)
            done, sent = await _counts(engine)
            if done < N_JOBS or sent < N_JOBS:
                kills_mid_work += 1
            procs[i].send_signal(signal.SIGKILL)
            procs[i].wait()
            procs[i] = _spawn(url, sent_log)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            done, sent = await _counts(engine)
            if done == N_JOBS and sent == N_JOBS:
                break
            await asyncio.sleep(0.25)
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                p.kill()

    async with engine.connect() as conn:
        effects = (
            await conn.execute(text("SELECT count(*), count(DISTINCT n) FROM public.crash_effect"))
        ).one()
        statuses = dict(
            (await conn.execute(text("SELECT status, count(*) FROM ops.job GROUP BY status"))).all()
        )
        outbox_rows = (
            await conn.execute(
                text("SELECT count(*), count(*) FILTER (WHERE status = 'sent') FROM ops.outbox")
            )
        ).one()
        max_attempts = (await conn.execute(text("SELECT max(attempts) FROM ops.job"))).scalar_one()
        await conn.execute(text("DROP TABLE public.crash_effect"))
        await conn.commit()

    lines = sent_log.read_text().split()
    per_key = Counter(lines)
    resent = sum(c - 1 for c in per_key.values())
    report = (
        f"kills={KILLS} (mid-work {kills_mid_work}), jobs={statuses}, max attempts={max_attempts}, "
        f"effects={effects[0]} (distinct {effects[1]}), outbox sent={outbox_rows[1]}/{outbox_rows[0]}, "
        f"channel deliveries={len(lines)} for {len(per_key)} keys, re-sends={resent}"
    )
    (REPO_ROOT / "tests" / "integration" / ".crash_report.txt").write_text(report + "\n")
    print(report)

    assert kills_mid_work >= KILLS // 2, report  # the kills really landed while work was running
    assert statuses == {"done": N_JOBS}, report
    assert effects[0] == N_JOBS and effects[1] == N_JOBS, report  # exactly once
    assert outbox_rows[0] == N_JOBS and outbox_rows[1] == N_JOBS, (
        report
    )  # one message per job, all sent
    assert set(per_key) == {f"effect:{n}" for n in range(N_JOBS)}, report  # none lost
    assert resent <= KILLS, report

"""A real worker process for the crash test: ``python -m tests.integration.crash_worker <sent-log>``.

Its job handler writes an effect row and queues one outbox message in the same
transaction. Its channel stands in for an external provider: it appends each message's
idempotency key to a file and fsyncs before returning, like an API that has accepted
the message. The test kills these processes with SIGKILL at random moments.
"""

from __future__ import annotations

import asyncio
import os
import random
import signal
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.adapters.postgres import jobs, outbox
from handel.config import get_settings
from handel.interfaces.worker.main import run_worker
from handel.ports.channel import Address, ChannelKind, OutboundMessage, SendResult

EFFECT_JOB = "test.effect"


class FileChannel:
    kind = ChannelKind.MEMORY

    def __init__(self, path: str) -> None:
        self.path = path

    async def send(self, message: OutboundMessage) -> SendResult:
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (message.idempotency_key + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return SendResult(idempotency_key=message.idempotency_key, provider_message_id="file")


async def effect(conn: AsyncConnection, job: jobs.Job) -> None:
    n = int(job.payload["n"])
    await conn.execute(
        text("INSERT INTO public.crash_effect (job_id, n) VALUES (:j, :n)"), {"j": job.id, "n": n}
    )
    await asyncio.sleep(random.uniform(0.01, 0.05))  # widen the window a kill can land in
    from handel.adapters.clock import SystemClock

    await outbox.put(
        conn,
        outbox.OutboxMessage.from_outbound(
            OutboundMessage(
                to=Address(channel=ChannelKind.MEMORY, chat_id=f"chat-{n % 7}"),
                text=f"message {n}",
                idempotency_key=f"effect:{n}",
            ),
            unit_id="U1",
            message_id="MSG-02",
            purpose="procurement",
            party_type="supplier",
            party_id="S1",
        ),
        SystemClock().now(),
    )


async def _main(sent_log: str) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    await run_worker(
        get_settings(),
        stop,
        handlers={EFFECT_JOB: effect},
        channels={ChannelKind.MEMORY: FileChannel(sent_log)},
        worker_id=f"crash-{os.getpid()}",
    )


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1]))

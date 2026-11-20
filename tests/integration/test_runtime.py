"""P2 gate: durable runtime on a real Postgres (set HANDEL_TEST_DATABASE_URL)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from handel.adapters.clock import FakeClock
from handel.adapters.memory.channel import InMemoryChannel
from handel.adapters.postgres import audit, cases, consent, inbound, jobs, outbox, phones, timers
from handel.adapters.postgres.tenancy import unit_scope
from handel.domain.model.entities import Supplier
from handel.interfaces.worker.loops import Dispatcher, JobRunner, Scheduler
from handel.interfaces.worker.ratelimit import RateLimiter
from handel.ports.channel import (
    Address,
    ChannelKind,
    ContentKind,
    InboundMessage,
    OutboundMessage,
)
from tests.integration.conftest import PHONE_ENC_KEY, PHONE_HASH_KEY, REPO_ROOT, add_unit

pytestmark = pytest.mark.integration

T0 = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
LEASE = timedelta(seconds=30)
KEYS = phones.PhoneKeys(PHONE_ENC_KEY, PHONE_HASH_KEY)


def _msg(
    key: str, chat: str = "chat-s1", message_id: str = "MSG-02", party: str = "S1"
) -> outbox.OutboxMessage:
    return outbox.OutboxMessage.from_outbound(
        OutboundMessage(
            to=Address(channel=ChannelKind.MEMORY, chat_id=chat),
            text="Demo Fabricators needs 2 t MS sheet 2 mm…",
            idempotency_key=key,
        ),
        unit_id="U1",
        message_id=message_id,
        purpose="procurement",
        party_type="supplier",
        party_id=party,
        case_id="C1",
    )


async def _status(engine: AsyncEngine, table: str, key_col: str, key: object) -> str:
    async with engine.connect() as conn:
        return str(
            (
                await conn.execute(
                    text(f"SELECT status FROM {table} WHERE {key_col} = :k"), {"k": key}
                )
            ).scalar_one()
        )


# ---------- inbound ----------
async def test_duplicate_webhook_update_is_recorded_once(engine: AsyncEngine) -> None:
    update = InboundMessage(
        channel=ChannelKind.TELEGRAM,
        update_id="884211",
        sender=Address(channel=ChannelKind.TELEGRAM, chat_id="555"),
        kind=ContentKind.TEXT,
        received_at=T0,
        text="2 ton MS sheet 2mm by Friday",
    )
    async with engine.begin() as conn:
        first = await inbound.record(conn, update, T0)
    async with engine.begin() as conn:
        second = await inbound.record(conn, update, T0 + timedelta(seconds=5))
    assert first is not None and second is None
    async with engine.connect() as conn:
        assert (
            await conn.execute(text("SELECT count(*) FROM ops.inbound_event"))
        ).scalar_one() == 1
        assert (
            await conn.execute(text("SELECT count(*) FROM ops.job WHERE kind = 'inbound.perceive'"))
        ).scalar_one() == 1


# ---------- jobs ----------
async def test_job_runs_once_and_effect_commits_with_done(engine: AsyncEngine) -> None:
    clock = FakeClock(T0)
    calls: list[int] = []

    async def handler(conn, job):  # type: ignore[no-untyped-def]
        calls.append(job.id)
        await conn.execute(
            text(
                "INSERT INTO ops.model_call (task, provider, model, prompt_version, request_hash, created_at) VALUES ('t','p','m','v1',:h, now())"
            ),
            {"h": str(job.id)},
        )

    async with engine.begin() as conn:
        await jobs.enqueue(conn, "demo", {"x": 1}, T0, idempotency_key="k1")
        assert await jobs.enqueue(conn, "demo", {"x": 1}, T0, idempotency_key="k1") is None
    runner = JobRunner(engine, clock, {"demo": handler}, LEASE)
    assert await runner.run_once() == 1
    assert await runner.run_once() == 0
    assert len(calls) == 1
    assert await _status(engine, "ops.job", "idempotency_key", "k1") == "done"


async def test_failing_job_retries_with_backoff_then_gives_up(engine: AsyncEngine) -> None:
    clock = FakeClock(T0)

    async def boom(conn, job):  # type: ignore[no-untyped-def]
        await conn.execute(
            text(
                "INSERT INTO ops.model_call (task, provider, model, prompt_version, request_hash, created_at) VALUES ('t','p','m','v1','x', now())"
            )
        )
        raise RuntimeError("provider down")

    async with engine.begin() as conn:
        await jobs.enqueue(conn, "demo", {}, T0, idempotency_key="k", max_attempts=2)
    runner = JobRunner(engine, clock, {"demo": boom}, LEASE)
    assert await runner.run_once() == 1
    assert await runner.run_once() == 0  # backing off (2 s)
    clock.advance(timedelta(seconds=2))
    assert await runner.run_once() == 1
    assert await _status(engine, "ops.job", "idempotency_key", "k") == "failed"
    async with engine.connect() as conn:
        # the handler's writes rolled back both times
        assert (await conn.execute(text("SELECT count(*) FROM ops.model_call"))).scalar_one() == 0
        err = (await conn.execute(text("SELECT last_error FROM ops.job"))).scalar_one()
    assert "provider down" in err


async def test_expired_lease_is_reclaimed_and_old_worker_cannot_complete(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as conn:
        await jobs.enqueue(conn, "demo", {}, T0)
    async with engine.begin() as conn:
        stale = await jobs.claim(conn, "worker-a", T0, timedelta(seconds=10), ("demo",))
    assert stale is not None
    async with engine.begin() as conn:
        assert (
            await jobs.claim(conn, "worker-b", T0 + timedelta(seconds=5), LEASE, ("demo",)) is None
        )
    async with engine.begin() as conn:
        fresh = await jobs.claim(conn, "worker-b", T0 + timedelta(seconds=11), LEASE, ("demo",))
    assert fresh is not None and fresh.attempts == 2
    with pytest.raises(jobs.LeaseLostError):
        async with engine.begin() as conn:
            await jobs.complete(conn, stale, T0 + timedelta(seconds=12))
    async with engine.begin() as conn:
        await jobs.complete(conn, fresh, T0 + timedelta(seconds=12))


# ---------- timers ----------
async def test_due_timer_fires_once_even_with_two_schedulers(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for i in range(20):
            await timers.schedule(
                conn, timers.Timer("U1", f"C{i}", "T1_REMINDER_DUE", T0 + timedelta(hours=4))
            )
        await timers.schedule(
            conn, timers.Timer("U1", "C-late", "T2_NO_RESPONSE", T0 + timedelta(hours=8))
        )
    clock = FakeClock(T0)
    other = create_async_engine(engine.url)
    try:
        a, b = Scheduler(engine, clock, batch=3), Scheduler(other, clock, batch=3)
        assert await a.run_once() == 0  # nothing due yet
        clock.advance(timedelta(hours=4))
        fired = 0
        for _ in range(20):
            got = await asyncio.gather(a.run_once(), b.run_once())
            fired += sum(got)
    finally:
        await other.dispose()
    assert fired == 20
    async with engine.connect() as conn:
        n_jobs = (
            await conn.execute(text("SELECT count(*) FROM ops.job WHERE kind = 'case.timer'"))
        ).scalar_one()
        late = (
            await conn.execute(text("SELECT fired_at FROM ops.timer WHERE case_id = 'C-late'"))
        ).scalar_one()
    assert n_jobs == 20 and late is None


async def test_cancelled_timer_never_fires(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await timers.schedule(conn, timers.Timer("U1", "C1", "T1_REMINDER_DUE", T0))
        assert await timers.cancel(conn, "C1", "T1_REMINDER_DUE", T0) == 1
    assert await Scheduler(engine, FakeClock(T0 + timedelta(days=1))).run_once() == 0


# ---------- audit ----------
async def test_audit_chain_verifies_and_detects_tampering(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for i in range(5):
            await audit.append(
                conn,
                audit.AuditEntry("person", "P-owner", "approval_recorded", "U1", "C1", {"n": i}),
                T0 + timedelta(minutes=i),
            )
    async with engine.connect() as conn:
        assert (await audit.verify(conn)).ok
    # The table refuses edits outright ...
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE ops.audit_event SET action = 'x' WHERE id = 3"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM ops.audit_event WHERE id = 3"))
    # ... and someone with owner rights who disables the trigger is still caught.
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE ops.audit_event DISABLE TRIGGER audit_event_append_only")
        )
        await conn.execute(
            text("""UPDATE ops.audit_event SET payload = '{"n": 99}' WHERE id = 3""")
        )
        await conn.execute(
            text("ALTER TABLE ops.audit_event ENABLE TRIGGER audit_event_append_only")
        )
    async with engine.connect() as conn:
        result = await audit.verify(conn)
    assert (
        not result.ok
        and result.first_bad_id == 3
        and "does not match its hash" in (result.reason or "")
    )


async def test_audit_detects_deleted_row(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for i in range(3):
            await audit.append(
                conn, audit.AuditEntry("agent", "planner", "step", payload={"i": i}), T0
            )
        await conn.execute(
            text("ALTER TABLE ops.audit_event DISABLE TRIGGER audit_event_append_only")
        )
        await conn.execute(text("DELETE FROM ops.audit_event WHERE id = 2"))
        await conn.execute(
            text("ALTER TABLE ops.audit_event ENABLE TRIGGER audit_event_append_only")
        )
    async with engine.connect() as conn:
        result = await audit.verify(conn)
    assert not result.ok and result.first_bad_id == 3 and "chain broken" in (result.reason or "")


async def test_audit_verify_command(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await audit.append(conn, audit.AuditEntry("system", "test", "hello"), T0)
    env = {
        "HANDEL_DATABASE_URL": str(engine.url.render_as_string(hide_password=False)),
        "PATH": os.environ["PATH"],
    }
    ok = subprocess.run(
        [sys.executable, "-m", "handel.interfaces.cli", "audit-verify"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0 and "1 events verified" in ok.stdout
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE ops.audit_event DISABLE TRIGGER audit_event_append_only")
        )
        await conn.execute(text("UPDATE ops.audit_event SET actor_id = 'someone-else'"))
        await conn.execute(
            text("ALTER TABLE ops.audit_event ENABLE TRIGGER audit_event_append_only")
        )
    bad = subprocess.run(
        [sys.executable, "-m", "handel.interfaces.cli", "audit-verify"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1 and "BROKEN at event 1" in bad.stderr


# ---------- row-level security ----------
async def test_unit_cannot_read_or_write_another_units_rows(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "UA")
        await add_unit(conn, "UB")
        await phones.add_supplier(conn, "UA", Supplier(id="SA", name="Murugan Steels"), None, KEYS)
        await phones.add_supplier(conn, "UB", Supplier(id="SB", name="Lakshmi Traders"), None, KEYS)
    async with unit_scope(engine, "UA") as conn:
        visible = (
            (await conn.execute(text("SELECT id FROM core.supplier ORDER BY id"))).scalars().all()
        )
        assert visible == ["SA"]
        updated = await conn.execute(text("UPDATE core.supplier SET name = 'x' WHERE id = 'SB'"))
        assert updated.rowcount == 0
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with unit_scope(engine, "UA") as conn:
            await phones.add_supplier(conn, "UB", Supplier(id="SX", name="Sneaky"), None, KEYS)
    # Without a unit set, the app role sees nothing at all.
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE handel_app"))
        assert (await conn.execute(text("SELECT count(*) FROM core.supplier"))).scalar_one() == 0
    with pytest.raises(ValueError):
        async with unit_scope(engine, "") as conn:
            pass


# ---------- consent-gated dispatcher ----------
async def _grant(engine: AsyncEngine, party: str = "S1", purpose: str = "procurement") -> None:
    async with engine.begin() as conn:
        await consent.grant(
            conn,
            unit_id="U1",
            party_type="supplier",
            party_id=party,
            purpose=purpose,
            notice_version="MSG-01 v1",
            language="ta",
            now=T0 - timedelta(days=1),
        )


async def test_dispatcher_refuses_rfq_without_consent(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
        await outbox.put(conn, _msg("rfq-1"), T0)
    channel = InMemoryChannel()
    assert (
        await Dispatcher(engine, FakeClock(T0), {ChannelKind.MEMORY: channel}, LEASE).run_once()
        == 1
    )
    assert channel.sent == []
    assert await _status(engine, "ops.outbox", "idempotency_key", "rfq-1") == "refused"
    async with engine.connect() as conn:
        action = (await conn.execute(text("SELECT action FROM ops.audit_event"))).scalar_one()
    assert action == "message_refused_no_consent"


async def test_dispatcher_sends_with_consent_and_notice_is_exempt(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
    await _grant(engine, "S1")
    async with engine.begin() as conn:
        await outbox.put(conn, _msg("rfq-1"), T0)
        await outbox.put(
            conn, _msg("notice-s2", chat="chat-s2", message_id="MSG-01", party="S2"), T0
        )
        assert not await outbox.put(conn, _msg("rfq-1"), T0)  # same key: not queued twice
    channel = InMemoryChannel()
    await Dispatcher(engine, FakeClock(T0), {ChannelKind.MEMORY: channel}, LEASE).run_once()
    assert sorted(m.idempotency_key for m in channel.sent) == ["notice-s2", "rfq-1"]
    assert await _status(engine, "ops.outbox", "idempotency_key", "rfq-1") == "sent"


async def test_withdrawn_consent_stops_messages(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
    await _grant(engine, "S1")
    async with engine.begin() as conn:
        assert await consent.withdraw(conn, party_type="supplier", party_id="S1", now=T0) == 1
        await outbox.put(conn, _msg("rfq-2"), T0)
    channel = InMemoryChannel()
    await Dispatcher(
        engine, FakeClock(T0 + timedelta(seconds=1)), {ChannelKind.MEMORY: channel}, LEASE
    ).run_once()
    assert channel.sent == []


async def test_failed_send_retries_with_backoff(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
    await _grant(engine)
    async with engine.begin() as conn:
        await outbox.put(conn, _msg("rfq-3"), T0)
    clock = FakeClock(T0)
    channel = InMemoryChannel()
    channel.fail_next = 1
    d = Dispatcher(engine, clock, {ChannelKind.MEMORY: channel}, LEASE)
    await d.run_once()
    assert await _status(engine, "ops.outbox", "idempotency_key", "rfq-3") == "queued"
    assert await d.run_once() == 0  # waiting out the backoff
    clock.advance(timedelta(seconds=2))
    await d.run_once()
    assert await _status(engine, "ops.outbox", "idempotency_key", "rfq-3") == "sent"
    assert len(channel.sent) == 1


async def test_dispatcher_waits_for_per_chat_rate_limit(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
    await _grant(engine)
    async with engine.begin() as conn:
        for i in range(3):
            await outbox.put(conn, _msg(f"m{i}"), T0)
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    channel = InMemoryChannel()
    await Dispatcher(
        engine,
        FakeClock(T0),
        {ChannelKind.MEMORY: channel},
        LEASE,
        limiter=RateLimiter(),
        sleep=fake_sleep,
    ).run_once()
    assert len(channel.sent) == 3 and slept == [1.0, 1.0]


# ---------- one transaction per case step ----------
async def _new_case(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
        await cases.create_need(conn, "N1", "U1", {"spec": "MS sheet 2 mm"})
        await cases.create_case(conn, "C1", "U1", "N1", "Confirmed", T0)
    await _grant(engine)


def _step(version: int, key: str = "rfq-c1-s1") -> cases.CaseStep:
    return cases.CaseStep(
        case_id="C1",
        unit_id="U1",
        expected_version=version,
        new_state="Collecting",
        event_kind="rfqs_sent",
        event_payload={"suppliers": 1},
        plan=[{"step": "wait for quotes", "due": "2026-12-02T12:00:00+05:30"}],
        messages=(_msg(key),),
        timers=(timers.Timer("U1", "C1", "T1_REMINDER_DUE", T0 + timedelta(hours=4)),),
        audit=audit.AuditEntry("agent", "planner", "send_rfq", "U1", "C1", {"n": 1}),
    )


async def test_case_step_commits_everything_together(engine: AsyncEngine) -> None:
    await _new_case(engine)
    async with engine.begin() as conn:
        assert await cases.commit_step(conn, _step(0), T0) == 1
    async with engine.connect() as conn:
        row = await cases.load_case(conn, "C1")
        assert row is not None and row.state == "Collecting" and row.version == 1
        assert row.plan[0]["step"] == "wait for quotes"
        assert await cases.timeline(conn, "C1") == [(1, "rfqs_sent")]
        for table in ("ops.outbox", "ops.timer", "ops.audit_event"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 1
        assert await cases.load_case(conn, "nope") is None


async def test_stale_case_step_writes_nothing(engine: AsyncEngine) -> None:
    await _new_case(engine)
    async with engine.begin() as conn:
        await cases.commit_step(conn, _step(0), T0)
    with pytest.raises(cases.StaleCaseError):
        async with engine.begin() as conn:
            await cases.commit_step(conn, _step(0, key="rfq-other"), T0)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM ops.outbox"))).scalar_one() == 1
        assert (await conn.execute(text("SELECT count(*) FROM cases.case_event"))).scalar_one() == 1


async def test_case_step_failing_midway_rolls_back(engine: AsyncEngine) -> None:
    await _new_case(engine)
    with pytest.raises(RuntimeError):
        async with engine.begin() as conn:
            await cases.commit_step(conn, _step(0), T0)
            raise RuntimeError("crash after the step, before commit")
    async with engine.connect() as conn:
        row = await cases.load_case(conn, "C1")
        assert row is not None and row.version == 0 and row.state == "Confirmed"
        assert (await conn.execute(text("SELECT count(*) FROM ops.outbox"))).scalar_one() == 0


async def test_case_step_cancels_timers(engine: AsyncEngine) -> None:
    await _new_case(engine)
    async with engine.begin() as conn:
        await cases.commit_step(conn, _step(0), T0)
        await cases.commit_step(
            conn,
            cases.CaseStep(
                "C1", "U1", 1, "Bidding", "deadline_reached", cancel_timers=("T1_REMINDER_DUE",)
            ),
            T0,
        )
    assert await Scheduler(engine, FakeClock(T0 + timedelta(days=1))).run_once() == 0


# ---------- phone numbers ----------
async def test_phone_numbers_are_encrypted_and_found_by_hash(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
        await phones.add_supplier(
            conn, "U1", Supplier(id="S1", name="Murugan Steels"), "098400 12345", KEYS
        )
    async with engine.connect() as conn:
        raw = (await conn.execute(text("SELECT phone_enc, phone_hash FROM core.supplier"))).one()
        assert b"9840012345" not in bytes(raw.phone_enc) and "9840012345" not in raw.phone_hash
        assert await phones.find_supplier_by_phone(conn, "U1", "+91 98400-12345", KEYS) == "S1"
        assert await phones.find_supplier_by_phone(conn, "U1", "9840099999", KEYS) is None
        assert await phones.reveal_supplier_phone(conn, "S1", KEYS) == "+919840012345"
        other = phones.PhoneKeys(PHONE_ENC_KEY, "a-different-hash-key-123456")
        assert await phones.find_supplier_by_phone(conn, "U1", "9840012345", other) is None


async def test_dispatcher_that_lost_its_claim_does_not_send(engine: AsyncEngine) -> None:
    """A slow dispatcher whose lease expired must not send rows another dispatcher took over."""
    async with engine.begin() as conn:
        await add_unit(conn, "U1")
    await _grant(engine)
    async with engine.begin() as conn:
        await outbox.put(conn, _msg("rfq-slow"), T0)
    async with engine.begin() as conn:
        (slow,) = await outbox.claim(conn, (ChannelKind.MEMORY,), T0, timedelta(seconds=5), 10)
    async with engine.begin() as conn:
        (fast,) = await outbox.claim(
            conn, (ChannelKind.MEMORY,), T0 + timedelta(seconds=6), LEASE, 10
        )
    async with engine.begin() as conn:
        assert not await outbox.touch(conn, slow, T0 + timedelta(seconds=7), LEASE)
        assert await outbox.touch(conn, fast, T0 + timedelta(seconds=7), LEASE)
        await outbox.mark_sent(conn, slow, "ignored", T0 + timedelta(seconds=7))  # no effect
    assert await _status(engine, "ops.outbox", "idempotency_key", "rfq-slow") == "sending"

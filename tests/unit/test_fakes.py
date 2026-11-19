"""The in-memory fakes behave like the ports promise, so later use-case tests can trust them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from handel.adapters.clock import FakeClock, SystemClock
from handel.adapters.memory.channel import InMemoryChannel, SendFailedError
from handel.adapters.memory.llm import ScriptedLLM
from handel.adapters.memory.speech import ScriptedSpeech
from handel.adapters.memory.storage import InMemoryStorage
from handel.ports.channel import Address, Button, ChannelKind, OutboundMessage
from handel.ports.llm import LLMRequest, extract
from handel.ports.speech import Transcript
from handel.ports.storage import ObjectNotFoundError

OWNER = Address(channel=ChannelKind.MEMORY, chat_id="owner-1")


# ---- clock ----
def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_fake_clock_moves_forward_only() -> None:
    clock = FakeClock(datetime(2026, 12, 1, 9, tzinfo=UTC))
    assert clock.advance(timedelta(hours=4)) == datetime(2026, 12, 1, 13, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 12, 1, 9, tzinfo=UTC))


def test_fake_clock_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 12, 1, 9))


# ---- channel ----
async def test_channel_send_is_idempotent() -> None:
    ch = InMemoryChannel()
    msg = OutboundMessage(to=OWNER, text="Shall I ask 4 suppliers?", idempotency_key="case1:msg08")
    first = await ch.send(msg)
    second = await ch.send(msg)
    assert not first.duplicate
    assert second.duplicate
    assert second.provider_message_id == first.provider_message_id
    assert len(ch.sent) == 1


async def test_channel_can_simulate_failure_then_recover() -> None:
    ch = InMemoryChannel()
    ch.fail_next = 1
    msg = OutboundMessage(to=OWNER, text="hi", idempotency_key="k")
    with pytest.raises(SendFailedError):
        await ch.send(msg)
    assert (await ch.send(msg)).duplicate is False
    assert ch.sent_to("owner-1") == [msg]


def test_outbound_message_allows_at_most_four_buttons() -> None:
    buttons = tuple(Button(label=f"b{i}", payload=f"p{i}") for i in range(5))
    OutboundMessage(to=OWNER, text="ok", buttons=buttons[:4], idempotency_key="k")
    with pytest.raises(ValidationError):
        OutboundMessage(to=OWNER, text="too many", buttons=buttons, idempotency_key="k")


def test_button_payload_fits_telegram_callback_limit() -> None:
    with pytest.raises(ValidationError):
        Button(label="Approve", payload="x" * 65)


# ---- storage ----
async def test_storage_roundtrip_with_hash_and_random_key() -> None:
    store = InMemoryStorage()
    a = await store.put(b"voice-bytes", "audio/ogg")
    b = await store.put(b"voice-bytes", "audio/ogg")
    assert a.key != b.key  # keys are random UUIDs, never content- or person-derived
    assert a.sha256 == b.sha256
    assert await store.get(a.key) == b"voice-bytes"
    await store.delete(a.key)
    with pytest.raises(ObjectNotFoundError):
        await store.get(a.key)


# ---- llm ----
class NeedDraft(BaseModel):
    material: str
    quantity_kg: int


async def test_extract_validates_against_schema() -> None:
    llm = ScriptedLLM({"extract_need": '{"material": "MS sheet 2mm", "quantity_kg": 2000}'})
    req = LLMRequest(task="extract_need", prompt_version="v1", input_text="2 ton MS sheet 2mm")
    need = await extract(llm, req, NeedDraft)
    assert need == NeedDraft(material="MS sheet 2mm", quantity_kg=2000)
    assert llm.calls[0].output_schema == "NeedDraft"


async def test_extract_rejects_output_that_breaks_schema() -> None:
    llm = ScriptedLLM({"extract_need": '{"material": "MS sheet", "quantity_kg": "two ton"}'})
    req = LLMRequest(task="extract_need", prompt_version="v1", input_text="x")
    with pytest.raises(ValidationError):
        await extract(llm, req, NeedDraft)


async def test_scripted_llm_fails_loudly_for_unknown_task() -> None:
    with pytest.raises(LookupError):
        await ScriptedLLM().complete(LLMRequest(task="nope", prompt_version="v1"))


# ---- speech ----
async def test_scripted_speech() -> None:
    speech = ScriptedSpeech()
    speech.add(b"ogg", Transcript(text="rendu ton sheet", language="ta-IN", confidence=0.9))
    assert (await speech.stt(b"ogg", "audio/ogg")).text == "rendu ton sheet"
    with pytest.raises(LookupError):
        await speech.stt(b"other", "audio/ogg")
    assert await speech.tts("Sari", "ta-IN") == b"FAKE-TTS[ta-IN]:Sari"

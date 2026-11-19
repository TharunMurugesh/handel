"""Fixture mode: record once against a provider, replay forever without spending quota."""

from __future__ import annotations

from pathlib import Path

import pytest

from handel.adapters.fixtures.store import FixtureMissingError, FixtureStore
from handel.adapters.fixtures.wrappers import FixtureLLM, FixtureSpeech
from handel.adapters.memory.llm import ScriptedLLM
from handel.adapters.memory.speech import ScriptedSpeech
from handel.config import ModelMode
from handel.ports.llm import LLMRequest
from handel.ports.speech import Transcript

REQ = LLMRequest(task="extract_need", prompt_version="v1", input_text="2 ton MS sheet")


async def test_llm_record_then_replay_without_calling_provider(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    live = ScriptedLLM({"extract_need": '{"q": 1}'})

    recorded = await FixtureLLM(store, ModelMode.RECORD, live).complete(REQ)
    assert len(live.calls) == 1
    files = list((tmp_path / "llm" / "extract_need").glob("*.json"))
    assert len(files) == 1

    replayed = await FixtureLLM(store, ModelMode.REPLAY).complete(REQ)
    assert replayed == recorded
    assert len(live.calls) == 1  # replay never reaches the provider


async def test_llm_replay_missing_fixture_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FixtureMissingError):
        await FixtureLLM(FixtureStore(tmp_path), ModelMode.REPLAY).complete(REQ)


async def test_llm_fixture_key_changes_with_prompt_version_and_image(tmp_path: Path) -> None:
    k1 = FixtureLLM.key_for(REQ, None)
    k2 = FixtureLLM.key_for(REQ.model_copy(update={"prompt_version": "v2"}), None)
    k3 = FixtureLLM.key_for(REQ, b"photo")
    assert len({k1, k2, k3}) == 3


async def test_live_mode_saves_nothing(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    await FixtureLLM(store, ModelMode.LIVE, ScriptedLLM({"extract_need": "{}"})).complete(REQ)
    assert not tmp_path.joinpath("llm").exists()


def test_record_mode_requires_a_live_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        FixtureLLM(FixtureStore(tmp_path), ModelMode.RECORD)
    with pytest.raises(ValueError):
        FixtureSpeech(FixtureStore(tmp_path), ModelMode.LIVE)


async def test_speech_record_then_replay(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    live = ScriptedSpeech()
    live.add(b"ogg", Transcript(text="rendu ton", language="ta-IN"))

    rec = FixtureSpeech(store, ModelMode.RECORD, live)
    t = await rec.stt(b"ogg", "audio/ogg", "ta-IN")
    audio = await rec.tts("Sari", "ta-IN")

    rep = FixtureSpeech(store, ModelMode.REPLAY)
    assert await rep.stt(b"ogg", "audio/ogg", "ta-IN") == t
    assert await rep.tts("Sari", "ta-IN") == audio
    assert live.tts_calls == [("Sari", "ta-IN")]
    with pytest.raises(FixtureMissingError):
        await rep.tts("Illai", "ta-IN")

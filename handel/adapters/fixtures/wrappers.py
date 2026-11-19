"""Record/replay wrappers around the LLM and speech ports (architecture §7.4, §12.2, §12.4).

Wrap any real adapter. In ``replay`` mode the inner adapter is never called, so CI and
local development spend no free-tier quota or Sarvam credit.
"""

from __future__ import annotations

import base64
import hashlib

from handel.adapters.fixtures.store import FixtureStore, request_key
from handel.config import ModelMode
from handel.ports.llm import LLM, LLMRequest, LLMResponse
from handel.ports.speech import Speech, Transcript


def _require[T](inner: T | None) -> T:
    if inner is None:
        raise RuntimeError("replay-only adapter has no live provider")
    return inner


class FixtureLLM:
    def __init__(self, store: FixtureStore, mode: ModelMode, inner: LLM | None = None) -> None:
        if mode is not ModelMode.REPLAY and inner is None:
            raise ValueError(f"{mode} mode needs a live LLM adapter")
        self.store = store
        self.mode = mode
        self.inner = inner

    @staticmethod
    def key_for(request: LLMRequest, image: bytes | None) -> str:
        payload = request.model_dump(mode="json")
        if image is not None:
            payload["image_sha256"] = hashlib.sha256(image).hexdigest()
        return request_key(payload)

    async def complete(self, request: LLMRequest, image: bytes | None = None) -> LLMResponse:
        key = self.key_for(request, image)
        if self.mode is ModelMode.REPLAY:
            record = self.store.load("llm", request.task, key)
            return LLMResponse.model_validate(record["response"])
        response = await _require(self.inner).complete(request, image)
        if self.mode is ModelMode.RECORD:
            self.store.save(
                "llm",
                request.task,
                key,
                {
                    "request": request.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                },
            )
        return response


class FixtureSpeech:
    def __init__(self, store: FixtureStore, mode: ModelMode, inner: Speech | None = None) -> None:
        if mode is not ModelMode.REPLAY and inner is None:
            raise ValueError(f"{mode} mode needs a live speech adapter")
        self.store = store
        self.mode = mode
        self.inner = inner

    async def stt(self, audio: bytes, mime: str, language_hint: str | None = None) -> Transcript:
        request = {
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "mime": mime,
            "language_hint": language_hint,
        }
        key = request_key(request)
        if self.mode is ModelMode.REPLAY:
            return Transcript.model_validate(self.store.load("speech", "stt", key)["response"])
        transcript = await _require(self.inner).stt(audio, mime, language_hint)
        if self.mode is ModelMode.RECORD:
            self.store.save(
                "speech",
                "stt",
                key,
                {"request": request, "response": transcript.model_dump(mode="json")},
            )
        return transcript

    async def tts(self, text: str, language: str) -> bytes:
        request = {"text": text, "language": language}
        key = request_key(request)
        if self.mode is ModelMode.REPLAY:
            record = self.store.load("speech", "tts", key)
            return base64.b64decode(record["response"]["audio_b64"])
        audio = await _require(self.inner).tts(text, language)
        if self.mode is ModelMode.RECORD:
            self.store.save(
                "speech",
                "tts",
                key,
                {"request": request, "response": {"audio_b64": base64.b64encode(audio).decode()}},
            )
        return audio

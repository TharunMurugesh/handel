"""Speech port: speech-to-text and text-to-speech (spec AI-01, AI-02; architecture §7.3)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Transcript(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    language: str  # BCP-47, e.g. "ta-IN"; "mixed" handled by the provider
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    english_gloss: str | None = None


class SpeechToText(Protocol):
    async def stt(
        self, audio: bytes, mime: str, language_hint: str | None = None
    ) -> Transcript: ...


class TextToSpeech(Protocol):
    async def tts(self, text: str, language: str) -> bytes:
        """Return encoded audio (OGG/Opus for Telegram voice notes)."""
        ...


class Speech(SpeechToText, TextToSpeech, Protocol):
    """A provider that does both directions."""

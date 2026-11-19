"""Scripted speech for tests: transcripts keyed by the audio's SHA-256."""

from __future__ import annotations

import hashlib

from handel.ports.speech import Transcript


class ScriptedSpeech:
    def __init__(self, transcripts: dict[str, Transcript] | None = None) -> None:
        self.transcripts: dict[str, Transcript] = dict(transcripts or {})
        self.tts_calls: list[tuple[str, str]] = []

    def add(self, audio: bytes, transcript: Transcript) -> None:
        self.transcripts[hashlib.sha256(audio).hexdigest()] = transcript

    async def stt(self, audio: bytes, mime: str, language_hint: str | None = None) -> Transcript:
        key = hashlib.sha256(audio).hexdigest()
        try:
            return self.transcripts[key]
        except KeyError:
            raise LookupError(f"ScriptedSpeech has no transcript for audio {key[:12]}") from None

    async def tts(self, text: str, language: str) -> bytes:
        self.tts_calls.append((text, language))
        return f"FAKE-TTS[{language}]:{text}".encode()

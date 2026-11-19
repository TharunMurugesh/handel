"""Scripted LLM for tests: answers come from a table keyed by task."""

from __future__ import annotations

from collections.abc import Callable

from handel.ports.llm import LLMRequest, LLMResponse

Responder = Callable[[LLMRequest], str]


class ScriptedLLM:
    def __init__(self, responses: dict[str, str | Responder] | None = None) -> None:
        self.responses: dict[str, str | Responder] = dict(responses or {})
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, image: bytes | None = None) -> LLMResponse:
        self.calls.append(request)
        try:
            answer = self.responses[request.task]
        except KeyError:
            raise LookupError(f"ScriptedLLM has no response for task {request.task!r}") from None
        text = answer(request) if callable(answer) else answer
        return LLMResponse(text=text, provider="scripted", model="scripted")

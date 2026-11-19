"""LLM port (architecture §7.1).

The model is used only for perception and language. It never computes money and
never authorises actions (spec §11, ADR-002). Every extraction is validated against
a Pydantic schema.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class LLMRequest(BaseModel):
    """Everything that determines a model answer. Its hash is the fixture/cache key."""

    model_config = ConfigDict(frozen=True)

    task: str  # e.g. "extract_need", "extract_quote_text", "classify_intent"
    prompt_version: str  # e.g. "v1"; prompts live in prompts/<task>/<version>.md
    input_text: str | None = None
    image_sha256: str | None = None  # images are referenced by hash, bytes passed separately
    output_schema: str | None = None  # name of the Pydantic schema for extractions


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str  # raw model output (JSON text for extractions)
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    async def complete(self, request: LLMRequest, image: bytes | None = None) -> LLMResponse: ...


async def extract[T: BaseModel](
    llm: LLM, request: LLMRequest, schema: type[T], image: bytes | None = None
) -> T:
    """Run an extraction and validate it against ``schema``.

    P0 behaviour: one call, strict validation. Retry-with-error, provider fallback and
    "ask a person" arrive with the gateway in P4.
    """
    response = await llm.complete(
        request.model_copy(update={"output_schema": schema.__name__}), image
    )
    return schema.model_validate_json(response.text)

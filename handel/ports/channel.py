"""Channel port: channel-neutral messaging (spec §5.1, architecture §6).

Adapters (Telegram, relay, WhatsApp) translate these types to each app.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

MAX_BUTTONS = 4  # spec §5.2: decisions use at most 4 buttons (NF-04)


class ChannelKind(StrEnum):
    TELEGRAM = "telegram"
    RELAY = "relay"
    WHATSAPP = "whatsapp"
    MEMORY = "memory"  # in-memory fake used by tests


class ContentKind(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    DOCUMENT = "document"
    BUTTON = "button"  # a button press (callback) on an inbound message


class Address(BaseModel):
    """Where a person is reachable on one channel."""

    model_config = ConfigDict(frozen=True)

    channel: ChannelKind
    chat_id: str


class Button(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1, max_length=40)
    payload: str = Field(min_length=1, max_length=64)  # Telegram callback_data limit


class OutboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    to: Address
    kind: ContentKind = ContentKind.TEXT
    text: str | None = None
    media_key: str | None = None  # object-storage key for voice/image/document
    buttons: tuple[Button, ...] = Field(default=(), max_length=MAX_BUTTONS)
    idempotency_key: str = Field(min_length=1)


class InboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel: ChannelKind
    update_id: str  # de-duplication key per channel (architecture §4.1)
    sender: Address
    kind: ContentKind
    received_at: datetime
    text: str | None = None
    media_key: str | None = None
    button_payload: str | None = None
    forwarded_from: str | None = None  # relay mode: original sender as shown by the app


class SendResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    idempotency_key: str
    provider_message_id: str
    duplicate: bool = False  # True when this key was already sent; nothing went out again


class Channel(Protocol):
    kind: ChannelKind

    async def send(self, message: OutboundMessage) -> SendResult: ...

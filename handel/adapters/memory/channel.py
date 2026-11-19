"""In-memory channel: records what would be sent and honours idempotency keys."""

from __future__ import annotations

from handel.ports.channel import ChannelKind, OutboundMessage, SendResult


class SendFailedError(RuntimeError):
    pass


class InMemoryChannel:
    kind = ChannelKind.MEMORY

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []
        self._by_key: dict[str, SendResult] = {}
        self.fail_next: int = 0  # tests set this to simulate network failures

    async def send(self, message: OutboundMessage) -> SendResult:
        existing = self._by_key.get(message.idempotency_key)
        if existing is not None:
            return existing.model_copy(update={"duplicate": True})
        if self.fail_next > 0:
            self.fail_next -= 1
            raise SendFailedError("simulated send failure")
        self.sent.append(message)
        result = SendResult(
            idempotency_key=message.idempotency_key, provider_message_id=f"mem-{len(self.sent)}"
        )
        self._by_key[message.idempotency_key] = result
        return result

    def sent_to(self, chat_id: str) -> list[OutboundMessage]:
        return [m for m in self.sent if m.to.chat_id == chat_id]

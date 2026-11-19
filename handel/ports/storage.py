"""Object storage port for voice notes, photos and PDFs (architecture §5 "Media")."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class StoredObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str  # random UUID; never derived from personal data
    sha256: str
    mime: str
    size: int


class ObjectNotFoundError(KeyError):
    pass


class Storage(Protocol):
    async def put(self, data: bytes, mime: str) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

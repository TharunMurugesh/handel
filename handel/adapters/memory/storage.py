"""In-memory object storage."""

from __future__ import annotations

import hashlib
import uuid

from handel.ports.storage import ObjectNotFoundError, StoredObject


class InMemoryStorage:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, StoredObject]] = {}

    async def put(self, data: bytes, mime: str) -> StoredObject:
        meta = StoredObject(
            key=str(uuid.uuid4()),
            sha256=hashlib.sha256(data).hexdigest(),
            mime=mime,
            size=len(data),
        )
        self._objects[meta.key] = (data, meta)
        return meta

    async def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError:
            raise ObjectNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

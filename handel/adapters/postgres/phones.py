"""Phone numbers: encrypted at column level, looked up by keyed hash (architecture §5).

Encryption uses pgcrypto ``pgp_sym_encrypt``; lookups use ``hmac(phone, key, 'sha256')``
so the plain number is never stored. Keys come from the environment and are passed as
bind parameters, never written into SQL text or logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from handel.config import Settings
from handel.domain.model.entities import Supplier

_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class PhoneKeys:
    encryption: str
    hashing: str

    def __post_init__(self) -> None:
        if len(self.encryption) < 16 or len(self.hashing) < 16:
            raise ValueError("phone keys must be at least 16 characters")
        if self.encryption == self.hashing:
            raise ValueError("use different keys for encryption and hashing")

    @classmethod
    def from_settings(cls, settings: Settings) -> PhoneKeys:
        return cls(
            settings.phone_encryption_key.get_secret_value(),
            settings.phone_hash_key.get_secret_value(),
        )


def normalize_phone(raw: str) -> str:
    """To E.164. Bare 10-digit numbers are taken as Indian (+91)."""
    has_plus = raw.strip().startswith("+")
    digits = _DIGITS.sub("", raw)
    if not has_plus:
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            digits = "91" + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError("not a valid phone number")
    return "+" + digits


async def add_supplier(
    conn: AsyncConnection, unit_id: str, supplier: Supplier, phone: str | None, keys: PhoneKeys
) -> None:
    number = normalize_phone(phone) if phone else None
    await conn.execute(
        text(
            """
            INSERT INTO core.supplier (id, unit_id, name, mode, phone_enc, phone_hash)
            VALUES (:id, :unit_id, :name, :mode,
                    CASE WHEN CAST(:phone AS text) IS NULL THEN NULL
                         ELSE pgp_sym_encrypt(CAST(:phone AS text), :ekey) END,
                    CASE WHEN CAST(:phone AS text) IS NULL THEN NULL
                         ELSE encode(hmac(CAST(:phone AS text), :hkey, 'sha256'), 'hex') END)
            """
        ),
        {
            "id": supplier.id,
            "unit_id": unit_id,
            "name": supplier.name,
            "mode": supplier.mode.value,
            "phone": number,
            "ekey": keys.encryption,
            "hkey": keys.hashing,
        },
    )


async def find_supplier_by_phone(
    conn: AsyncConnection, unit_id: str, phone: str, keys: PhoneKeys
) -> str | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT id FROM core.supplier
                WHERE unit_id = :unit_id
                  AND phone_hash = encode(hmac(:phone, :hkey, 'sha256'), 'hex')
                """
            ),
            {"unit_id": unit_id, "phone": normalize_phone(phone), "hkey": keys.hashing},
        )
    ).first()
    return None if row is None else str(row[0])


async def reveal_supplier_phone(
    conn: AsyncConnection, supplier_id: str, keys: PhoneKeys
) -> str | None:
    """Decrypt for sending only (e.g. relay drafts). Never log the result."""
    row = (
        await conn.execute(
            text(
                "SELECT pgp_sym_decrypt(phone_enc, :ekey) FROM core.supplier "
                "WHERE id = :id AND phone_enc IS NOT NULL"
            ),
            {"id": supplier_id, "ekey": keys.encryption},
        )
    ).first()
    return None if row is None else str(row[0])

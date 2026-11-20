from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from handel.adapters.postgres.phones import PhoneKeys, normalize_phone
from handel.adapters.postgres.util import backoff, canonical_json, utc
from handel.interfaces.worker.ratelimit import RateLimiter

T0 = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


def test_backoff_doubles_and_caps() -> None:
    assert [backoff(n).total_seconds() for n in range(1, 6)] == [2, 4, 8, 16, 32]
    assert backoff(30) == timedelta(minutes=10)
    with pytest.raises(ValueError):
        backoff(0)


def test_canonical_json_and_utc() -> None:
    assert canonical_json({"b": 1, "a": "₹"}) == '{"a":"₹","b":1}'
    with pytest.raises(ValueError):
        utc(datetime(2026, 12, 1))


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("9840012345", "+919840012345"),
        ("098400 12345", "+919840012345"),
        ("+91 98400-12345", "+919840012345"),
        ("919840012345", "+919840012345"),
        ("+44 20 7946 0958", "+442079460958"),
    ],
)
def test_normalize_phone(raw: str, e164: str) -> None:
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize("bad", ["12345", "", "+1234567890123456"])
def test_normalize_phone_rejects_bad_numbers(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(bad)


def test_phone_keys_validation() -> None:
    with pytest.raises(ValueError):
        PhoneKeys("short", "also-short")
    with pytest.raises(ValueError):
        PhoneKeys("same-key-0123456789", "same-key-0123456789")


def test_rate_limiter_per_chat_and_global() -> None:
    rl = RateLimiter(per_chat=timedelta(seconds=1), global_per_second=2)
    assert rl.delay("a", T0) == timedelta(0)
    rl.record("a", T0)
    assert rl.delay("a", T0) == timedelta(seconds=1)
    assert rl.delay("b", T0) == timedelta(0)
    rl.record("b", T0)
    assert rl.delay("c", T0) == timedelta(seconds=1)  # global window full
    assert rl.delay("c", T0 + timedelta(seconds=1)) == timedelta(0)
    with pytest.raises(ValueError):
        RateLimiter(global_per_second=0)

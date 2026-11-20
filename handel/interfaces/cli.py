"""Operator commands. Usage: ``python -m handel.interfaces.cli audit-verify``."""

from __future__ import annotations

import argparse
import asyncio
import sys

from handel.adapters.postgres import audit
from handel.adapters.postgres.db import make_engine
from handel.config import get_settings


async def _audit_verify() -> int:
    engine = make_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            result = await audit.verify(conn)
    finally:
        await engine.dispose()
    if result.ok:
        print(f"audit chain OK: {result.checked} events verified")
        return 0
    print(f"audit chain BROKEN at event {result.first_bad_id}: {result.reason}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handel")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit-verify", help="check the audit log's hash chain for tampering")
    args = parser.parse_args(argv)
    if args.command == "audit-verify":
        return asyncio.run(_audit_verify())
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())

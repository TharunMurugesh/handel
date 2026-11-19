"""Fixture store: recorded answers from paid/limited APIs, replayed in CI and in demo replay mode.

Layout: ``<root>/<port>/<task>/<key>.json`` where ``key`` is a SHA-256 of the canonical
request. Files are plain JSON so they can be reviewed in pull requests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class FixtureMissingError(LookupError):
    """Replay mode asked for an answer nobody recorded. Record it deliberately; never guess."""


def request_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class FixtureStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, port: str, task: str, key: str) -> Path:
        safe_task = "".join(c if c.isalnum() or c in "-_" else "_" for c in task)
        return self.root / port / safe_task / f"{key}.json"

    def load(self, port: str, task: str, key: str) -> dict[str, Any]:
        path = self._path(port, task, key)
        if not path.exists():
            raise FixtureMissingError(f"no fixture {path} (run once with HANDEL_MODEL_MODE=record)")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def save(self, port: str, task: str, key: str, record: dict[str, Any]) -> Path:
        path = self._path(port, task, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

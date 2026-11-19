"""Architecture §3: ``domain/`` imports only the standard library, Pydantic and itself.

import-linter (``lint-imports``) enforces the layer order. This test is the allow-list
companion: it fails for *any* third-party import in the domain, including ones nobody
thought to forbid.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import handel

DOMAIN = Path(handel.__file__).parent / "domain"
ALLOWED_ROOTS = set(sys.stdlib_module_names) | {"pydantic", "handel", "__future__"}


def _imported_roots(path: Path) -> set[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {(a.name.split(".")[0], node.lineno) for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add((node.module.split(".")[0], node.lineno))
    return found


def _violations(root: Path) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.py")):
        for name, line in _imported_roots(path):
            if name not in ALLOWED_ROOTS:
                bad.append(f"{path}:{line} imports {name}")
    return bad


def test_domain_imports_only_stdlib_and_pydantic() -> None:
    assert _violations(DOMAIN) == []


def test_domain_must_not_import_outer_handel_layers() -> None:
    outer = ("handel.application", "handel.ports", "handel.adapters", "handel.interfaces")
    bad = []
    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(outer):
                bad.append(f"{path}:{node.lineno} imports {node.module}")
    assert bad == []


def test_checker_catches_a_violation(tmp_path: Path) -> None:
    """The check itself works: a planted SQLAlchemy import is reported."""
    (tmp_path / "bad.py").write_text("from sqlalchemy import select\nimport decimal\n")
    assert _violations(tmp_path) == [f"{tmp_path / 'bad.py'}:1 imports sqlalchemy"]

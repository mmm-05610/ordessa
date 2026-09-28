"""T02 dependency-direction gate for `ordessa_permissions_backend`.

Allowed imports in `src/`: the standard library, `ordessa_permissions_api`,
and `server_plugin_api` only. The host, the compat layer, pacthold and the
harness are forbidden - the database arrives as an injected object typed by a
small local Protocol, never by importing the host's class.
"""
from __future__ import annotations

import ast
import pathlib
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_permissions_backend"
FORBIDDEN_ROOTS = {
    "ordessa_server", "ordessa_server_compat", "ordessa_harness", "pacthold",
    "ordessa_workspace", "ordessa_sandbox_backend", "fastapi", "pydantic", "httpx",
    "sqlite3", "subprocess", "socket", "urllib", "requests",
}
ALLOWED_ROOTS = {"__future__", "ordessa_permissions_api", "server_plugin_api"}
STDLIB_OK = set(sys.stdlib_module_names)


def _sources() -> list[pathlib.Path]:
    return sorted(SRC_ROOT.glob("**/*.py"), key=lambda p: str(p))


def _imported_roots(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def test_the_package_exists_and_is_not_empty() -> None:
    assert SRC_ROOT.is_dir(), SRC_ROOT
    assert _sources(), "no modules under src/"


def test_only_allowed_roots_are_imported() -> None:
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in _imported_roots(tree):
            assert root in ALLOWED_ROOTS | STDLIB_OK, f"{path.name} imports {root!r}"


def test_no_forbidden_module_is_mentioned_in_source_text() -> None:
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for forbidden in sorted(FORBIDDEN_ROOTS):
            assert forbidden not in text, f"{path.name} mentions {forbidden}"

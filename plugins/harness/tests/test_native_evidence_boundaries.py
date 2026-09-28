"""PE2-5 boundary: native evidence stays inside plugins/harness; no permissions import.

Scans the plugin's own source trees (not just the new modules) so the whole
native-evidence surface, API DTOs included, is covered by the import rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _plugin_py_files():
    for root in (PLUGIN_ROOT / "src", PLUGIN_ROOT / "api" / "src"):
        yield from sorted(root.rglob("*.py"))


def test_plugin_sources_never_import_the_permissions_implementation():
    for file in _plugin_py_files():
        roots = _import_roots(file)
        assert "ordessa_permissions" not in roots, file
        assert "permissions" not in roots, file


def test_api_dto_modules_stay_host_and_implementation_free():
    allowed = {"__future__", "dataclasses", "enum", "json", "math", "re",
               "typing", "ordessa_harness_api"}
    for file in sorted((PLUGIN_ROOT / "api" / "src" / "ordessa_harness_api").glob("*.py")):
        roots = _import_roots(file)
        assert "ordessa_harness" not in roots, file
        assert roots <= allowed, (file, sorted(roots - allowed))


def test_native_evidence_modules_import_only_within_the_harness_boundary():
    files = [
        PLUGIN_ROOT / "src" / "ordessa_harness" / "application" / "native_evidence.py",
        PLUGIN_ROOT / "api" / "src" / "ordessa_harness_api" / "native_evidence.py",
    ]
    allowed = {"__future__", "dataclasses", "datetime", "hashlib", "json", "re",
               "typing", "ordessa_harness", "ordessa_harness_api"}
    for file in files:
        roots = _import_roots(file)
        assert roots <= allowed, (file, sorted(roots - allowed))
        assert not {"ordessa_server", "ordessa_permissions", "server_plugin_api"} & roots, file

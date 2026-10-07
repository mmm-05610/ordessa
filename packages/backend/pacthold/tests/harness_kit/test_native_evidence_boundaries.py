"""PE2-5 boundary: native evidence stays inside plugins/harness; no permissions import.

Scans the plugin's own source trees (not just the new modules) so the whole
native-evidence surface, API DTOs included, is covered by the import rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[5] / 'plugins' / 'harness'


def _import_names(path: Path) -> set[str]:
    """Every absolute dotted module name the file imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


#: 032: the kit source is the kernel subpackage; the host-facing application
#: modules live in the product's harness_adapters binding layer.
KIT_SRC = Path(__file__).resolve().parents[2] / "src" / "pacthold" / "harness_kit"
BINDING_SRC = (Path(__file__).resolve().parents[4].parent / "products" / "server" / "src"
               / "ordessa_server_product" / "harness_adapters")


def _plugin_py_files():
    for root in (KIT_SRC, BINDING_SRC):
        yield from sorted(root.rglob("*.py"))


def test_plugin_sources_never_import_the_permissions_implementation():
    for file in _plugin_py_files():
        roots = _import_roots(file)
        assert "ordessa_permissions" not in roots, file
        assert "permissions" not in roots, file


def test_api_dto_modules_stay_host_and_implementation_free():
    """The contract edge is stdlib plus its own package tree; the kernel's
    other internals and any host/plugin implementation stay out."""
    allowed = {"__future__", "collections", "dataclasses", "enum", "json", "math",
               "os", "pathlib", "re", "stat", "hashlib", "typing"}
    for file in sorted((Path(__file__).resolve().parents[2] / "src" / "pacthold"
                        / "harness_contracts").glob("*.py")):
        roots = _import_roots(file)
        assert "pacthold.harness_kit" not in roots, file
        # a `pacthold...` root is licensed only under the contract edge itself
        pacthold_imports = {name for name in _import_names(file)
                            if name.split(".")[0] == "pacthold"}
        assert all(name == "pacthold.harness_contracts"
                   or name.startswith("pacthold.harness_contracts.") for name in pacthold_imports), (
            file, sorted(pacthold_imports))
        assert (roots - {"pacthold"}) <= allowed, (file, sorted(roots - allowed))


def test_native_evidence_modules_import_only_within_the_harness_boundary():
    files = [
        BINDING_SRC / "application" / "native_evidence.py",
        Path(__file__).resolve().parents[2] / "src" / "pacthold" / "harness_contracts" / "native_evidence.py",
    ]
    allowed = {"__future__", "dataclasses", "datetime", "hashlib", "json", "re",
               "typing", "pacthold", "ordessa_harness_records", "ordessa_server_product"}
    for file in files:
        roots = _import_roots(file)
        assert roots <= allowed, (file, sorted(roots - allowed))
        assert not {"ordessa_server", "ordessa_permissions", "server_plugin_api"} & roots, file

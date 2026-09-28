"""T01 red/green: the dependency-direction gate for this package (FR-01, plan §包归属).

`ordessa_permissions_api` is pure domain: stdlib plus itself. Anything that
would let it reach a host, a storage layer or the sandbox domain is refused
here, by source text and by AST.
"""
from __future__ import annotations

import ast
import pathlib
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_permissions_api"
TESTS_ROOT = pathlib.Path(__file__).resolve().parents[0]

FORBIDDEN_ROOTS = {
    "ordessa_server", "ordessa_server_compat", "ordessa_server_plugin_api", "ordessa_harness",
    "pacthold", "ordessa_workspace", "fastapi", "pydantic", "httpx", "sqlite3", "subprocess",
    "socket", "urllib", "requests", "numpy",
}
STDLIB_OK = set(sys.stdlib_module_names)


def _sources(folder: pathlib.Path) -> list[pathlib.Path]:
    return sorted(sorted(folder.glob("**/*.py")), key=lambda p: str(p))


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
    assert _sources(SRC_ROOT), "no modules under src/"


def test_only_the_standard_library_and_this_package_are_imported() -> None:
    for path in _sources(SRC_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in _imported_roots(tree):
            assert root in STDLIB_OK | {"__future__", "ordessa_permissions_api"}, \
                f"{path.name} imports {root!r}"


def test_no_product_or_host_module_name_appears_in_the_source_text() -> None:
    for path in _sources(SRC_ROOT):
        text = path.read_text(encoding="utf-8")
        for forbidden in sorted(FORBIDDEN_ROOTS):
            assert forbidden not in text, f"{path.name} mentions {forbidden}"


def test_the_sandbox_domain_stays_out_of_the_permissions_api() -> None:
    # FR-05: this domain is permissions, not `SandboxV1` and not the native
    # sandbox facet; neither name may show up here.
    for path in _sources(SRC_ROOT):
        text = path.read_text(encoding="utf-8").lower()
        assert "sandboxv1" not in text, path.name


def test_the_legacy_compat_engine_is_imported_by_exactly_one_test_file() -> None:
    # Assembled rather than written out, so this gate file cannot match itself:
    # the question is who *imports* the legacy engine, not who mentions it.
    legacy = "ordessa_server" + "_compat"
    importers: list[str] = []
    for path in _sources(TESTS_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if legacy in _imported_roots(tree) or any(
                isinstance(node, ast.ImportFrom) and (node.module or "").startswith(legacy)
                for node in ast.walk(tree)):
            importers.append(path.name)
    assert importers == ["test_legacy_last_match_divergence.py"], importers

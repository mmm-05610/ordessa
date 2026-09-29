"""The package shape this slice claims: published contracts only, no product or
sibling-implementation dependency.

A runtime import of the server, the harness package or the kernel would break
AGENTS.md rule 3 (import boundaries), and so would a runtime dependency on Q5's
*provider* package (§SR-13b row 4), so the claim is checked against the real
imports instead of asserted in prose. `test_boundaries_t03b.py` guards the same
line with a wider scanner; this file pins the manifest and the core slices'
narrow stdlib-only surface.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PLUGIN_DIR / "src" / "ordessa_assets_subagents"
OWNED_MODULES = (
    "__init__.py", "errors.py", "dto.py", "limits.py", "digest.py",
    "decoder.py", "store.py", "service.py",
)
FORBIDDEN_ROOTS = {
    "ordessa_server", "ordessa_server_compat", "ordessa_harness", "pacthold",
    "ordessa_server_plugin_api", "ordessa_platform_contracts",
    "requests", "httpx", "urllib3", "aiohttp", "socket", "subprocess", "urllib",
    "shutil", "asyncio", "threading", "multiprocessing",
}
LOCAL_ROOTS = {"ordessa_assets_subagents", "decoder", "digest", "dto", "errors",
               "limits", "service", "store", "scopes", "assignments", "ceiling",
               "references", "resolution", "adapters"}


def imported_roots(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def standard_library_roots() -> set[str]:
    import sysconfig
    import sys

    stdlib = set(sys.stdlib_module_names)
    assert "json" in stdlib and "pacthold" not in stdlib
    return stdlib


def test_this_slices_modules_import_only_the_standard_library_and_each_other() -> None:
    stdlib = standard_library_roots()
    for name in OWNED_MODULES:
        module = PACKAGE_DIR / name
        assert module.is_file(), module
        for root in imported_roots(module):
            assert root not in FORBIDDEN_ROOTS, f"{name} imports {root}"
            assert root in stdlib or root in LOCAL_ROOTS, f"{name} imports {root}"


def test_no_stdlib_import_reaches_the_network_or_a_subprocess() -> None:
    for name in OWNED_MODULES:
        text = (PACKAGE_DIR / name).read_text(encoding="utf-8")
        for forbidden in ("socket.", "subprocess.", "urlopen", "http.client",
                          "os.system", "os.popen", "eval(", "exec("):
            assert forbidden not in text, f"{name} uses {forbidden}"


#: The published contract distributions this package may depend on at runtime
#: (`api-requests.md` §SR-13b: exactly these three, and their import roots are
#: the only non-stdlib ones `src/**` may name).
RUNTIME_CONTRACT_DISTRIBUTIONS = frozenset({
    "ordessa-harness-api", "ordessa-permissions-api", "ordessa-server-plugin-api",
})
#: Import root -> declared distribution, so the comparison below reads the code
#: rather than a hand-typed list.
CONTRACT_ROOT_BY_DISTRIBUTION = {
    "ordessa_harness_api": "ordessa-harness-api",
    "ordessa_permissions_api": "ordessa-permissions-api",
    "server_plugin_api": "ordessa-server-plugin-api",
}
#: Q5's *provider* package: a test-time double only (§SR-13b row 4, §SR-15). It
#: must never appear in the runtime closure.
TEST_ONLY_SIBLING_DISTRIBUTION = "ordessa-permissions-backend"


def _distribution(entry: str) -> str:
    """`ordessa-harness-api>=1;python_version>="3"` -> `ordessa-harness-api`."""
    import re

    return re.split(r"[<>=!~;\[\s]", entry, maxsplit=1)[0].strip().lower() \
        .replace("_", "-")


def src_runtime_import_roots() -> set[str]:
    """Every non-stdlib, non-local root any file under `src/**` imports."""
    stdlib = standard_library_roots()
    roots: set[str] = set()
    for module in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        for root in imported_roots(module):
            if root not in stdlib and root != "ordessa_assets_subagents":
                roots.add(root)
    assert roots, f"no third-party import found under {PACKAGE_DIR} — probe is blind"
    return roots


def test_the_manifest_declares_exactly_the_published_contract_runtime_deps() -> None:
    """I-1's `dependencies = []` died with §SR-13; this is the honest set.

    Not a restatement of the manifest: the runtime closure is *derived from the
    source* and compared to what is declared, in both directions, so a new
    contract import without a dependency — or a declared dependency no source
    imports — is red here. §SR-13b row 4 adds the one direction that matters
    most: Q5's provider package is a test-only double and must not slip back
    into the runtime list.
    """
    manifest = tomllib.loads((PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    assert project["name"] == "ordessa-assets-subagents"
    assert project["version"] == "2.0.0a1"
    assert project["license"]["text"] == "MIT"
    assert project["requires-python"] == ">=3.11"
    assert manifest["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]

    declared = {_distribution(entry) for entry in project["dependencies"]}
    imported = src_runtime_import_roots()
    from_source = {CONTRACT_ROOT_BY_DISTRIBUTION[root] for root in imported
                   if root in CONTRACT_ROOT_BY_DISTRIBUTION}
    assert imported <= set(CONTRACT_ROOT_BY_DISTRIBUTION), (
        "src imports a root outside the published contract packages "
        f"(AGENTS.md rule 3, §SR-13b): {sorted(imported - set(CONTRACT_ROOT_BY_DISTRIBUTION))}")
    assert declared == from_source, (
        f"pyproject declares {sorted(declared)} but src/** imports "
        f"{sorted(imported)} → the honest runtime set is {sorted(from_source)}")
    assert declared == set(RUNTIME_CONTRACT_DISTRIBUTIONS), declared
    assert TEST_ONLY_SIBLING_DISTRIBUTION not in declared, (
        "ordessa-permissions-backend is Q5's provider package: a runtime "
        "dependency on it blesses the plugin→plugin private import §SR-13b "
        "rules out")

    dev = {_distribution(entry) for entry in project["optional-dependencies"]["dev"]}
    assert dev == {TEST_ONLY_SIBLING_DISTRIBUTION, "pytest"}, dev
    assert "pytest>=7" in [str(entry) for entry
                           in project["optional-dependencies"]["dev"]], (
        "the existing pytest pin is preserved when the test-only sibling moves "
        "into the dev extra")
    # capability: the normaliser reads a pinned entry, so the set above is not
    # comparing raw strings that can never match
    assert _distribution('ordessa-harness-api>=1.0,<2;python_version>="3.11"') == (
        "ordessa-harness-api")
    assert _distribution("ordessa_harness_api") == "ordessa-harness-api"


def test_the_package_directory_ships_only_python_source() -> None:
    sources = {path.name for path in PACKAGE_DIR.glob("*.py")}
    assert set(OWNED_MODULES) <= sources, sources
    for path in PACKAGE_DIR.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            assert path.suffix == ".py", path

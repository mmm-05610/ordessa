"""AST boundary for the current Skills source and direct public dependencies.

Production imports are checked without importing the package. The approved
external surfaces below are exact module names observed in current Skills
source and owned by currently declared distributions. Declared package roots
are limited to this plugin, the host plugin API, and PyYAML. In particular,
retired persistence/compatibility paths and sibling plugin internals do not
become grants merely because an older migration ledger named them.

`api/` remains the pure type area: it may import only stdlib and its own
package-level relatives. The boundary also checks that unlisted descendants of
the exact public modules remain forbidden.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
PKG_DIR = REPO_ROOT / "plugins" / "agents" / "resources" / "skills" / "src" / "ordessa_skills"

#: Hard-forbidden import roots (AGENTS.md rule 3: plugins never touch host
#: internals or each other; the legacy domain must not be re-imported).
FORBIDDEN_ROOTS = frozenset((
    "ordessa_server", "ordessa_server_compat", "pacthold.harness_kit",
    "ordessa_workspace", "ordessa_assets", "apps", "products",
))

#: Package roots permitted because they are this package, declared host API,
#: or the PyYAML dependency. Other distributions are narrowed to exact
#: imported public modules in PUBLIC_MODULES.
ALLOWED_ROOTS = frozenset(("ordessa_skills", "server_plugin_api", "yaml", "_yaml"))

#: Exact external public modules actually imported by current source.
#: Each is declared in pyproject.toml; see the file-level source mapping in
#: the revision-2 report. No ancestor package or sibling submodule is granted.
PUBLIC_MODULES = frozenset((
    "ordessa_execution_agents.harness.providers.resolution.artifacts.tree_identity",
    "ordessa_execution_agents.harness.providers.resolution.source_declaration",
    "ordessa_execution_agents.harness.definitions",
    "ordessa_interfaces.system_access.contracts.storage",
    "ordessa_permissions_api",
))

_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(
    sys.builtin_module_names)


def _granted(name: str) -> bool:
    return name in PUBLIC_MODULES


def _forbidden_import(name: str) -> bool:
    return any(name == root or name.startswith(root + ".")
               for root in FORBIDDEN_ROOTS)


def _allowed_import(name: str) -> bool:
    root = name.split(".")[0]
    return root in _STDLIB or root in ALLOWED_ROOTS or _granted(name)


def _absolute_imports(tree: ast.Module) -> "list[str]":
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _sibling_plugin_roots() -> frozenset[str]:
    """Top-level python package names discovered under `plugins/*/src`."""
    found = set()
    for src in (REPO_ROOT / "plugins").glob("*/src"):
        for child in src.iterdir():
            if (child.is_dir() and (child / "__init__.py").exists()) or \
                    child.suffix == ".py":
                found.add(child.stem)
    return frozenset(found)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _walk_sources(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path, _tree(path)


def _area_of(path: Path) -> str | None:
    """First package segment under the package root ('api', 'formats', …)."""
    relative = path.relative_to(PKG_DIR)
    return relative.parts[0] if len(relative.parts) > 1 else None


# -- 1 + 2. the absolute-import surface --------------------------------------


def test_no_module_imports_the_host_or_a_plugin_sibling():
    forbidden = FORBIDDEN_ROOTS | (_sibling_plugin_roots() - {"ordessa_skills"})
    for path, tree in _walk_sources(PKG_DIR):
        for name in _absolute_imports(tree):
            root = name.split(".")[0]
            assert not _forbidden_import(name) and (root not in forbidden or _granted(name)), \
                f"{path.relative_to(REPO_ROOT)}: {name}"


def test_absolute_imports_stay_in_the_declared_surface():
    for path, tree in _walk_sources(PKG_DIR):
        for name in _absolute_imports(tree):
            assert _allowed_import(name), (
                f"{path.relative_to(REPO_ROOT)}: {name} is neither stdlib, "
                "a declared package root, nor an exact current public module")
    for public in PUBLIC_MODULES:
        assert _allowed_import(public), public
    for forbidden in (
        "ordessa_execution_api.environment",
        "ordessa_execution_agents.harness.providers.resolution.source_declaration.private",
        "ordessa_execution_agents.harness.definitions.private",
        "ordessa_execution_agents.harness.providers.resolution.artifacts.private",
        "ordessa_interfaces.system_access.contracts.storage.internal",
        "ordessa_permissions_api._internal",
        "ordessa_persistence_sqlite.product_database",
        "pacthold_runtime_compat.runtime_composition",
        "pacthold.harness_contracts.runtime_artifacts",
    ):
        assert not _allowed_import(forbidden), forbidden


# -- 3. the pure-type area keeps its promise ---------------------------------


def test_the_api_area_imports_nothing_but_stdlib_and_itself():
    for path, tree in _walk_sources(PKG_DIR / "api"):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in _STDLIB, (
                        f"{path.relative_to(REPO_ROOT)}: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    assert node.module.split(".")[0] not in {
                        "formats", "library", "assignments", "native_discovery",
                        "profile_contribution", "harness_adapters", "plugin",
                    }, f"{path.relative_to(REPO_ROOT)}: {node.module}"
                elif node.module and not node.level:
                    assert node.module.split(".")[0] in _STDLIB, (
                        f"{path.relative_to(REPO_ROOT)}: {node.module}")

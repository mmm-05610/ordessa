"""Boundary pins for the ordessa_skills package (AGENTS.md import rules).

In the test_server_compat_boundary.py discipline — AST-based, no package
imports needed:

1. No module under `src/ordessa_skills/**` may import the host
   (`ordessa_server`, `ordessa_server_compat`), a sibling plugin package
   (`ordessa_harness`, `ordessa_workspace`, the legacy `ordessa_assets`,
   and anything else discovered under `plugins/*/src`), or repo path roots
   (`apps`, `products`).
2. The only non-stdlib absolute imports allowed are the declared
   dependencies: `pacthold` (the kernel), `server_plugin_api` (the plugin
   API) and PyYAML (`yaml`/`_yaml`) — plus the package itself — and, since
   the foundation checkpoint, EXACTLY the relocated-platform modules named
   in `PLATFORM_MODULE_GRANTS` below. The grants are module-exact (not
   root-wide): everything else under those distributions stays forbidden,
   so the surface is no wider than the moves force it to be.
3. `api/` is the pure-type area (plan.md 目标目录: 纯类型/错误/身份；无实
   现加载): it may import nothing outside the stdlib, its own area and the
   package root. No other area may be reached through it.

Grant ledger (why each module is unavoidable, and whose in-tree pattern it
copies — the lead review asks for exactly this list):

* `pacthold_runtime_compat.storage` — specs/010 T009 moved the product
  storage facade (`Database`, `PRODUCT_SCHEMA_VERSION`) out of
  `pacthold.storage` into this assembly (its `storage/__init__.py` docstring
  states the relocation). Pattern copied verbatim from
  `plugins/server-compat/src/ordessa_server_compat/persistence.py` (and 14
  sibling sites). Used for the injected `database` type annotation and the
  `data_root` storage fact in the migration guard.
* `pacthold_runtime_compat.resource_contracts.runtime_artifacts` — the
  kernel's `pacthold.resource_contracts` module tree is gone (only the
  runtime-compat copy remains; probe: `pacthold.resource_contracts`
  resolves to an empty namespace). Pattern copied from
  `plugins/server-compat/src/ordessa_server_compat/assets/skills.py:22`;
  `runtime_artifact_tree_digest` must be the ONE legacy implementation
  because our on-disk digests are byte-compatible with that store
  (AGENTS.md rule 5) — a private reimplementation is the drift this guards.
* `pacthold_runtime_compat.resource_contracts.agent_skill_v1` — same
  gone-kernel situation: `AgentSkillV1` (contract `agent-box.skill@1`) is
  the PUBLISHED producer contract the Q1 delivery producer must bind to
  verbatim; redeclaring it in-domain is exactly what the "do NOT redeclare
  the contract" rule forbids. The consumer side
  (`plugins/harness/src/ordessa_harness/adapters/generic_cli.py:20-38`)
  matches this contract id, and the symbol is reachable ONLY through this
  assembly (import probe on the kernel copy raises ModuleNotFoundError).
* `pacthold_runtime_compat.runtime_composition` — the published Root
  Extension SDK composition surface (`declare_source`, the DTOs and the
  fake/coordinator used by the T14 L2 proof). Same gone-kernel rationale
  (the task's `pacthold.extensions.runtime_composition` path has no .py
  left, only `__pycache__`); the package root re-exports the exact symbols
  `generic_cli.py:3` already consumes from it
  (`from pacthold_runtime_compat.runtime_composition import
  HarnessCommandSpec, declare_source`), so the grant is the published
  entry point, not a harness internal.
* `ordessa_profile.contracts` — the profile-api checkpoint's published
  contract surface (`FacetDescriptor`/`ItemDescriptor`/`Applicability`/
  `Violation`/`CompileResult`/`UNSET`/`ValueDisabled`). It is the facet-
  provider vocabulary our `profile_contribution` must speak to register a
  v2 facet at all; it is imported lazily inside the provider only (the
  package stays importable without Profile — contracts.md 可选注册不能反转
  依赖). No other `ordessa_profile` module is granted: the services object
  arrives by host injection and is consumed duck-typed through its
  documented methods.
* `ordessa_permissions_api` — the permissions-api checkpoint's PUBLIC
  package (`plugins/permissions/api`, import `ordessa_permissions_api`, per
  specs/011-plugin-rollout/checkpoints/permissions-api.json `publicExports`).
  The grant is the package ROOT rather than a submodule because that IS the
  published surface: the checkpoint's `apiExports` are re-exports of
  `ordessa_permissions_api/__init__.py:98`, so a narrower dotted name would
  not be a narrower surface. `mandatory_policy.py` imports it lazily, and
  only for the ceiling vocabulary it must not re-spell (`PolicyCeiling`,
  `PolicyRefusal`, `TOOL_EXPOSURE`). `ordessa_permissions_backend` is
  deliberately NOT granted: the store object (`PolicyRepository`, provided
  port `permissions.authorizer@1`) arrives by host injection and is consumed
  through its documented call (`ceilings_current`), never imported here.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PKG_DIR = REPO_ROOT / "plugins" / "assets" / "skills" / "src" / "ordessa_skills"

#: Hard-forbidden import roots (AGENTS.md rule 3: plugins never touch host
#: internals or each other; the legacy domain must not be re-imported).
FORBIDDEN_ROOTS = frozenset((
    "ordessa_server", "ordessa_server_compat", "ordessa_harness",
    "ordessa_workspace", "ordessa_assets", "apps", "products",
))

#: Declared dependencies (pyproject `[project].dependencies`) + own package.
#: `ordessa_harness_api` joined the list with the harness-api checkpoint
#: (publication `d3f026904e`): it is the standalone, `py.typed`,
#: dependency-free PUBLIC CONTRACT package of the Harness — the DTO surface
#: the skills configuration adapters implement — NOT the harness plugin's
#: internals (`ordessa_harness` stays hard-forbidden above; the sibling-root
#: sweep only discovers packages under `plugins/*/src`, and
#: `plugins/harness/api/src/ordessa_harness_api` imports nothing from the
#: harness runtime — its own wheel proof has no Requires-Dist).
ALLOWED_ROOTS = frozenset((
    "ordessa_skills", "pacthold", "server_plugin_api", "yaml", "_yaml",
    "ordessa_harness_api",
))

#: Module-EXACT grants for symbols the foundation moved out of the kernel
#: (see the ledger in the module docstring). A name qualifies only when the
#: imported dotted module equals a grant — not merely lives under it.
PLATFORM_MODULE_GRANTS = frozenset((
    "pacthold_runtime_compat.storage",
    "pacthold_runtime_compat.resource_contracts.runtime_artifacts",
    "pacthold_runtime_compat.resource_contracts.agent_skill_v1",
    "pacthold_runtime_compat.runtime_composition",
    "ordessa_profile.contracts",
    "ordessa_permissions_api",
))

_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(
    sys.builtin_module_names)


def _granted(name: str) -> bool:
    return name in PLATFORM_MODULE_GRANTS


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
            assert root not in forbidden or _granted(name), \
                f"{path.relative_to(REPO_ROOT)}: {name}"


def test_absolute_imports_stay_in_the_declared_surface():
    for path, tree in _walk_sources(PKG_DIR):
        for name in _absolute_imports(tree):
            root = name.split(".")[0]
            assert root in ALLOWED_ROOTS | _STDLIB or _granted(name), (
                f"{path.relative_to(REPO_ROOT)}: {name} is neither stdlib, "
                "nor a declared dependency, nor a foundation-move grant "
                "(PLATFORM_MODULE_GRANTS)")


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

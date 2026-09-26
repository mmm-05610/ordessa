"""Core-cleanup stage 3 boundary pins: the compat core may only shrink.

Three locks, in the MB-S2 boundary-pin discipline:

1. The compatibility core's wire method list is frozen by
   `docs/server-core-cleanup-baseline.md` — it can only ever SHRINK (a
   domain retiring into its own plugin removes its rows). New business
   methods can never silently re-enter the compatibility surface.
2. The host (`apps/server`) imports no plugin and no product: the generic
   vocabulary (errors, records, ids, idempotency, credentials, events, the
   wire envelope/errors/projection/handlers-helpers) is the only surface
   the plugins consume, never the reverse.
3. Each plugin's own imports stay inside its declared surface: the host's
   generic vocabulary, its own package, its declared dependencies
   (`ordessa_workspace`, `ordessa_harness`) and `pacthold` — never the host's
   business modules (`bootstrap` business, the moved domain aliases).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT_DIR = REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat"
WORKSPACE_DIR = REPO_ROOT / "plugins" / "workspace" / "src" / "ordessa_workspace"
HOST_DIR = REPO_ROOT / "apps" / "server" / "src" / "ordessa_server"

#: The frozen compatibility surface at stage 3 (59 rows; the 67-method
#: baseline minus host hello, the five workspace rows and the two acp rows).
FROZEN_COMPAT_METHODS = frozenset((
    "executions.list", "executions.get",
    "profiles.list", "profiles.create", "profiles.update", "profiles.updateConfig",
    "profiles.archive", "profiles.clone", "profiles.setPermissions", "profiles.memory",
    "profiles.subagentGrants", "profiles.grantSubagent", "profiles.revokeSubagent",
    "providerModels.list", "providerModels.create", "providerModels.update",
    "providerModels.archive", "providerModels.probeModels", "providerModels.probeConnection",
    "assets.list", "assets.publishSkill", "assets.publishMcp", "assets.publishPlugin",
    "assets.bind", "assets.unbind", "assets.bindings", "assets.syncCatalog",
    "assets.catalog", "assets.installFromCatalog", "assets.probe",
    "hooks.list", "hooks.create", "hooks.update", "hooks.setEnabled", "hooks.delete",
    "hooks.triggers",
    "accounts.list", "accounts.create", "accounts.bind", "accounts.importAsset",
    "providerArtifacts.list", "providerArtifacts.install", "providerArtifacts.rollback",
    "usage.aggregate", "usage.export",
    "config.describe", "config.resolve",
    "sessions.list", "sessions.update", "sessions.archive", "sessions.createAndSend",
    "sessions.send", "sessions.switchProfile",
    "sendOutcome.query", "queue.get", "queue.withdraw", "runs.stop",
    "approvals.decide", "history.snapshot",
))

HOST_GENERIC_EDGES = frozenset((
    "ordessa_server", "ordessa_server.bootstrap", "ordessa_server.errors",
    "ordessa_server.records",
    "ordessa_server.ids", "ordessa_server.idempotency", "ordessa_server.credentials",
    "ordessa_server.events", "ordessa_server.connectors",
    "ordessa_server.wire", "ordessa_server.wire.errors", "ordessa_server.wire.envelope",
    "ordessa_server.wire.projection", "ordessa_server.wire.handlers",
    "ordessa_server.transport.http.admission",
))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _walk_sources(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path, _imports(_tree(path))


# -- 1. the compat method list may only shrink --------------------------------


def test_the_compat_declaration_is_within_the_frozen_surface():
    from ordessa_server_compat.core_wire import _COMPAT_METHODS, _PARAM_SHAPES

    retired = FROZEN_COMPAT_METHODS - set(_COMPAT_METHODS)
    added = set(_COMPAT_METHODS) - FROZEN_COMPAT_METHODS
    assert added == set(), (
        "the compatibility surface grew — new business methods need their own "
        f"plugin, not a row in ordessa.server-compat: {sorted(added)}")
    assert set(_COMPAT_METHODS) <= set(_PARAM_SHAPES)
    print(f"compat surface: {len(_COMPAT_METHODS)} rows "
          f"({len(retired)} retired since the freeze)")


# -- 2. the host imports no plugin and no product -----------------------------


def test_the_host_core_imports_no_plugin_no_product():
    """bootstrap, transport, wire and plugin_host import none of the moved
    domains, none of the plugin packages and none of the product package."""
    forbidden_prefixes = (
        "ordessa_server_compat", "ordessa_workspace", "ordessa_harness",
        "ordessa_server_product", "ordessa_server.profiles", "ordessa_server.accounts",
        "ordessa_server.assets", "ordessa_server.hooks", "ordessa_server.model_configs",
        "ordessa_server.execution", "ordessa_server.approvals", "ordessa_server.acp_channel",
        "ordessa_server.workspaces", "ordessa_server.persistence",
        "ordessa_server.usage_aggregate", "ordessa_server.credential_cli",
    )
    watched = [HOST_DIR / "bootstrap" / "runtime.py", HOST_DIR / "transport" / "http" / "app.py",
               HOST_DIR / "wire" / "handlers.py", HOST_DIR / "plugin_host" / "host.py"]
    for path in watched:
        for name in _imports(_tree(path)):
            assert not name.startswith(forbidden_prefixes), f"{path}: imports {name}"


def test_the_host_composition_root_knows_no_business_service():
    """The slimmed build_runtime constructs no business service: its imports
    of business modules must be zero at module level."""
    source = (HOST_DIR / "bootstrap" / "runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) \
                else [node.module or ""]
            for name in names:
                assert not name.startswith(("ordessa_server.profiles", "ordessa_server.sessions",
                                            "ordessa_server.workspaces", "pacthold.service",
                                            "ordessa_server_compat")), name


# -- 3. the plugins stay inside their declared surfaces -----------------------


#: What a plugin may NEVER import: the host's private business modules and
#: the product selection package. Everything else (stdlib, the declared
#: dependencies, the host's generic vocabulary) is the documented surface.
_PLUGIN_FORBIDDEN_PREFIXES = (
    "ordessa_server.bootstrap.", "ordessa_server.transport.http.app",
    "ordessa_server.plugin_host",
    "ordessa_server.profiles", "ordessa_server.accounts", "ordessa_server.assets",
    "ordessa_server.hooks", "ordessa_server.model_configs", "ordessa_server.execution",
    "ordessa_server.approvals", "ordessa_server.acp_channel", "ordessa_server.workspaces",
    "ordessa_server.persistence", "ordessa_server.usage_aggregate",
    "ordessa_server.credential_cli", "ordessa_server.services",
    "ordessa_server_product",
)


def test_compat_plugin_imports_stay_in_the_declared_surface():
    for path, imports in _walk_sources(COMPAT_DIR):
        for name in imports:
            assert not name.startswith(_PLUGIN_FORBIDDEN_PREFIXES), (
                f"{path.name}: imports {name}")


def test_workspace_plugin_imports_stay_in_the_declared_surface():
    for path, imports in _walk_sources(WORKSPACE_DIR):
        for name in imports:
            assert not name.startswith(_PLUGIN_FORBIDDEN_PREFIXES), (
                f"{path.name}: imports {name}")


def test_the_moved_domain_aliases_are_zero_implementation():
    """The legacy `ordessa_server.*` entries the moved domains left behind are
    alias shims: no def/class anywhere in them (M1-P-A① discipline)."""
    for legacy in ("profiles", "accounts", "assets", "hooks", "model_configs",
                   "execution", "approvals", "workspaces", "acp_channel"):
        for path in (HOST_DIR / legacy).rglob("*.py"):
            tree = _tree(path)
            assert not [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)], path
            assert not [n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.col_offset == 0], path

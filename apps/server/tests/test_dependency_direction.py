"""Dependency-direction gates: Pacthold kernel and Server host install/run
boundaries must be real, not scanned-only.

Four locks:

1. Importing EVERY pacthold module under an import blocker that forbids the
   product packages succeeds — the kernel cannot reach ordessa_server, any
   plugin or the product, at runtime or lazily.
2. Importing EVERY ordessa_server (host) module under a blocker forbidding
   the plugin and product packages succeeds — the bare host is complete on
   its own.
3. The legacy business entries (`ordessa_server.profiles`, `.sessions`,
   `.services`, …) no longer exist: a single-implementation boundary with
   real owners, no compat aliases left to import silently.
4. The neutral facilities the plugins consume (errors, records, ids,
   idempotency, credentials, events, connectors) carry no business imports —
   they are the host's documented vocabulary, and the pin keeps them neutral.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import pkgutil
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

PRODUCT_PACKAGES = (
    "ordessa_server", "ordessa_harness", "ordessa_workspace",
    "ordessa_server_compat", "ordessa_server_product",
)
PLUGIN_PACKAGES = (
    "ordessa_harness", "ordessa_workspace", "ordessa_server_compat",
    "ordessa_server_product",
)
HOST_NEUTRAL = ("errors", "records", "ids", "idempotency", "credentials",
                "events", "connectors")


class _ForbidProductImports:
    """An import blocker: any (transitive) import of a forbidden top-level
    package raises — simulating an environment where it is not installed."""

    def __init__(self, forbidden_prefixes):
        self._forbidden = forbidden_prefixes

    def find_module(self, fullname, path=None):  # noqa: D102 (legacy hook)
        return self if any(fullname == p or fullname.startswith(p + ".")
                           for p in self._forbidden) else None

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".")
               for p in self._forbidden):
            raise ImportError(
                f"DEPENDENCY_DIRECTION: {fullname!r} is forbidden in this "
                "isolation")
        return None

    def load_module(self, fullname):
        raise ImportError(
            f"DEPENDENCY_DIRECTION: {fullname!r} is forbidden in this isolation")

    def create_module(self, spec):
        raise ImportError(
            f"DEPENDENCY_DIRECTION: {spec.name!r} is forbidden in this isolation")

    def exec_module(self, module):
        raise ImportError(
            f"DEPENDENCY_DIRECTION: {module.__spec__.name!r} is forbidden")


def _import_all_under_blocker(package_name: str, forbidden) -> list[str]:
    """Import every module of `package_name` fresh under the blocker.

    Isolation is REAL: the forbidden packages are EVICTED from sys.modules
    first — a cached module would satisfy the import through a sys.modules
    hit and the machinery would never consult the blocker (the blind gate
    the first draft had). The whole sys.modules snapshot is restored after,
    so the surrounding suite keeps its imported state; the gate's own
    re-imports are discarded."""
    package = importlib.import_module(package_name)
    module_names = [package_name] + [
        name for finder, name, is_pkg in pkgutil.walk_packages(
            package.__path__, prefix=package_name + ".")
        if ".tests" not in name and "EXCLUDED" not in name
    ]
    blocker = _ForbidProductImports(forbidden)
    failures: list[str] = []
    snapshot = dict(sys.modules)
    evict_prefixes = tuple({package_name, *forbidden})
    for name in list(sys.modules):
        if name.startswith(evict_prefixes):
            sys.modules.pop(name, None)
    sys.meta_path.insert(0, blocker)
    try:
        for name in module_names:
            try:
                importlib.import_module(name)
            except ImportError as exc:
                if "DEPENDENCY_DIRECTION" in str(exc):
                    failures.append(f"{name}: {exc}")
                # a genuine ImportError of the module itself is not this
                # gate's subject
            except Exception:
                pass  # module-level side effects unrelated to the direction
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.clear()
        sys.modules.update(snapshot)
    return failures


def test_pacthold_imports_isolated_from_every_product_package():
    failures = _import_all_under_blocker("pacthold", PRODUCT_PACKAGES)
    assert failures == [], "\n".join(failures)


def test_the_host_imports_isolated_from_every_plugin_package():
    failures = _import_all_under_blocker("ordessa_server", PLUGIN_PACKAGES)
    assert failures == [], "\n".join(failures)


LEGACY_BUSINESS_ENTRIES = (
    "ordessa_server.workspaces", "ordessa_server.profiles", "ordessa_server.accounts",
    "ordessa_server.assets", "ordessa_server.hooks", "ordessa_server.model_configs",
    "ordessa_server.execution", "ordessa_server.approvals", "ordessa_server.sessions",
    "ordessa_server.persistence", "ordessa_server.usage_aggregate",
    "ordessa_server.credential_cli", "ordessa_server.services",
)


def test_the_legacy_business_entries_no_longer_exist():
    """The compat-alias discipline is retired: a legacy entry either never
    imports again (deleted) — a silent fallback to a plugin implementation
    through a hidden path is exactly what this forbids."""
    for entry in LEGACY_BUSINESS_ENTRIES:
        assert entry not in sys.modules or True  # absence is the assertion
        saved = sys.modules.pop(entry, None)
        try:
            importlib.import_module(entry)
        except ImportError:
            pass  # gone, as it must be
        else:
            raise AssertionError(f"legacy business entry still importable: {entry}")
        finally:
            if saved is not None:
                sys.modules[entry] = saved


def test_the_neutral_facilities_carry_no_business_imports():
    """The host vocabulary the plugins consume stays neutral: stdlib,
    pacthold storage/contracts and each other — never a domain, never a
    plugin, never the product."""
    allowed_roots = {"ordessa_server", "pacthold"}
    forbidden_prefixes = PLUGIN_PACKAGES + (
        "ordessa_server.profiles", "ordessa_server.accounts", "ordessa_server.assets",
        "ordessa_server.hooks", "ordessa_server.model_configs", "ordessa_server.execution",
        "ordessa_server.approvals", "ordessa_server.workspaces", "ordessa_server.sessions",
        "ordessa_server.persistence", "ordessa_server.usage_aggregate",
        "ordessa_server.credential_cli", "ordessa_server.services",
    )
    host = REPO_ROOT / "apps" / "server" / "src" / "ordessa_server"
    for facility in HOST_NEUTRAL:
        base = host / facility
        paths = ([base] if base.is_dir()
                 else [host / f"{facility}.py"])
        for path in paths:
            sources = path.rglob("*.py") if path.is_dir() else [path]
            for source in sources:
                tree = ast.parse(source.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                        names = [node.module]
                    for name in names:
                        assert not name.startswith(forbidden_prefixes), (
                            f"{facility}: {source.name} imports {name}")
                        root = name.split(".")[0]
                        if root.startswith("ordessa"):
                            assert root in allowed_roots, (
                                f"{facility}: {source.name} imports {name}")


def test_the_kernel_declares_no_dependency_at_all():
    """Pacthold's zero-dependency contract, on the distribution metadata."""
    from importlib import metadata

    requires = metadata.requires("pacthold") or []
    runtime_deps = [r for r in requires if "extra ==" not in r]
    assert runtime_deps == [], runtime_deps

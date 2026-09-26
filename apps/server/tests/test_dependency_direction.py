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


def _import_all_under_blocker(package_name: str, forbidden, *,
                              report_tolerated: bool = False,
                              keep: "frozenset[str] | set[str] | None" = None):
    """Import every module of `package_name` fresh under the blocker.

    Isolation is REAL: the forbidden packages are EVICTED from sys.modules
    first — a cached module would satisfy the import through a sys.modules
    hit and the machinery would never consult the blocker (the blind gate
    the first draft had). The whole sys.modules snapshot is restored after,
    so the surrounding suite keeps its imported state; the gate's own
    re-imports are discarded.

    Non-direction import failures (module-level side effects unrelated to
    the boundary) do not count as violations, but they are never silently
    eaten: they are collected and returned alongside the failures, so a
    module that fails to import for another reason is VISIBLE — `pass` was
    exactly the false-green this file existed to prevent."""
    package = importlib.import_module(package_name)
    module_names = [package_name] + [
        name for finder, name, is_pkg in pkgutil.walk_packages(
            package.__path__, prefix=package_name + ".")
        if ".tests" not in name and "EXCLUDED" not in name
    ]
    blocker = _ForbidProductImports(forbidden)
    failures: list[str] = []
    tolerated: list[str] = []
    snapshot = dict(sys.modules)
    evict_prefixes = tuple({package_name, *forbidden})
    keep = keep or frozenset()
    for name in list(sys.modules):
        if name.startswith(evict_prefixes) and not any(
                name == k or name.startswith(k + ".") for k in keep):
            sys.modules.pop(name, None)
    sys.meta_path.insert(0, blocker)
    try:
        for name in module_names:
            try:
                importlib.import_module(name)
            except ImportError as exc:
                if "DEPENDENCY_DIRECTION" in str(exc):
                    failures.append(f"{name}: {exc}")
                else:
                    tolerated.append(f"{name}: ImportError {exc}")
            except Exception as exc:
                tolerated.append(f"{name}: {type(exc).__name__} {exc}")
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.clear()
        sys.modules.update(snapshot)
    return (failures, tolerated) if report_tolerated else failures


def test_pacthold_imports_isolated_from_every_product_package():
    failures, tolerated = _import_all_under_blocker(
        "pacthold", PRODUCT_PACKAGES, report_tolerated=True)
    assert failures == [], "\n".join(failures)
    assert tolerated == [], "modules failed to import for NON-direction reasons:\n" + "\n".join(tolerated)


def test_the_host_imports_isolated_from_every_plugin_package():
    failures, tolerated = _import_all_under_blocker(
        "ordessa_server", PLUGIN_PACKAGES, report_tolerated=True)
    assert failures == [], "\n".join(failures)
    assert tolerated == [], "modules failed to import for NON-direction reasons:\n" + "\n".join(tolerated)


LEGACY_BUSINESS_ENTRIES = (
    "ordessa_server.workspaces", "ordessa_server.profiles", "ordessa_server.accounts",
    "ordessa_server.assets", "ordessa_server.hooks", "ordessa_server.model_configs",
    "ordessa_server.execution", "ordessa_server.approvals", "ordessa_server.sessions",
    "ordessa_server.persistence", "ordessa_server.usage_aggregate",
    "ordessa_server.credential_cli", "ordessa_server.services",
)


def test_the_legacy_business_entries_no_longer_exist():
    """The compat-alias discipline is retired: a legacy entry must not
    import — and the ONLY passing failure is `ModuleNotFoundError` naming
    the entry itself. Any other ImportError (a broken shim that partially
    imports, a fallback chain dying halfway) or any other exception fails
    the gate: "it blew up" is not "it is gone"."""
    for entry in LEGACY_BUSINESS_ENTRIES:
        # A cached entry IS the resurrection: popping it first would destroy
        # the evidence and let a shim that only ever lived in sys.modules
        # pass (exactly what the zombie probe caught). Absence in the module
        # cache is the primary assertion; the fresh import then proves no
        # provider exists on disk either.
        assert entry not in sys.modules, (
            f"legacy business entry resurrected in sys.modules: {entry}")
        try:
            try:
                importlib.import_module(entry)
            except ModuleNotFoundError as exc:
                assert exc.name == entry or (exc.name or "").startswith(entry + "."), (
                    f"{entry}: unexpected ModuleNotFoundError for {exc.name!r}")
            except ImportError as exc:
                raise AssertionError(
                    f"{entry}: import failed in a NON-absence way "
                    f"(a shim residue?): {exc!r}") from exc
            except Exception as exc:
                raise AssertionError(
                    f"{entry}: import raised {type(exc).__name__} — that is not "
                    "absence either") from exc
            else:
                raise AssertionError(f"legacy business entry still importable: {entry}")
            # the fresh import must not have left anything behind
            assert entry not in sys.modules, (
                f"a failed import still cached {entry}")
        finally:
            # absence is the state under test: never resurrect a legacy entry
            sys.modules.pop(entry, None)


def test_the_isolation_scanner_is_not_silently_tolerant():
    """The module-isolation scan swallows only unexpected module-level side
    effects of the scanned tree itself — and it REPORTS them. Injected here:
    a submodule whose import raises SystemError under the blocker must
    surface in the scan's tolerated-report, proving the scanner sees
    non-direction failures instead of eating them into a bare `pass`. A
    clean scan stays clean (zero failures, zero tolerated)."""
    import shutil
    import tempfile

    pkg_name = "fake_direction_probe"
    probe_dir = Path(tempfile.mkdtemp()) / pkg_name
    probe_dir.mkdir(parents=True)
    (probe_dir / "__init__.py").write_text("", encoding="utf-8")
    (probe_dir / "boom.py").write_text(
        "raise SystemError('injected boom: a non-direction import failure')\n",
        encoding="utf-8")
    sys.path.insert(0, str(probe_dir.parent))
    try:
        failures, tolerated = _import_all_under_blocker(
            pkg_name, PRODUCT_PACKAGES, report_tolerated=True)
        assert failures == [], failures
        assert tolerated and any(
            item.split(":")[0] == pkg_name + ".boom" and "SystemError" in item
            for item in tolerated), tolerated
    finally:
        sys.path.remove(str(probe_dir.parent))
        sys.modules.pop(pkg_name, None)
        sys.modules.pop(pkg_name + ".boom", None)
        shutil.rmtree(probe_dir.parent, ignore_errors=True)


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

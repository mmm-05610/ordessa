"""Sessions boundary pins — re-pinned for the final dependency direction.

The interim discipline this file used to pin (implementation in
`pacthold.service.sessions` behind an `ordessa_server.sessions`
module-identity alias) is RETIRED by the dependency-direction batch. What
must hold now:

- exactly one implementation, in `ordessa_server_compat.sessions`;
- the legacy entries `ordessa_server.sessions(.*)` no longer import at all;
- `pacthold` has no service package and no product imports (kernel zero-dep);
- the composition root imports from the final owner;
- public surface identity: SessionService / SessionRecords / QueueRecords;
- the declared host-vocabulary edges are exactly the neutral set.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

import ordessa_server_compat.sessions as new_package
import ordessa_server_compat.sessions.queue as new_queue
import ordessa_server_compat.sessions.repository as new_repository
import ordessa_server_compat.sessions.service as new_service


REPO_ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION_DIR = REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "sessions"
KERNEL_DIR = REPO_ROOT / "packages" / "pacthold" / "src" / "pacthold"

LEGACY_ENTRIES = ("ordessa_server.sessions", "ordessa_server.sessions.queue",
                  "ordessa_server.sessions.repository", "ordessa_server.sessions.service")

#: The host's neutral vocabulary — the only ordessa_server.* edges the
#: session domain may keep.
VOCABULARY_EDGES = frozenset((
    "ordessa_server.errors",
    "ordessa_server.idempotency",
    "ordessa_server.ids",
    "ordessa_server.records",
))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _absolute_modules(source: str) -> list[str]:
    result: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            result.append(node.module)
    return result


def test_single_implementation_lives_in_the_compat_core():
    inventory: dict[str, list[str]] = {}
    for path in sorted(IMPLEMENTATION_DIR.rglob("*.py")):
        names = [node.name for node in _tree(path).body if isinstance(node, ast.ClassDef)]
        if names:
            inventory[path.relative_to(IMPLEMENTATION_DIR).as_posix()] = names
    assert inventory == {
        "service.py": ["SessionService"],
        "repository.py": ["SessionRecords"],
        "queue.py": ["QueueRecords"],
    }


def test_the_legacy_entries_no_longer_import():
    for entry in LEGACY_ENTRIES:
        saved = sys.modules.pop(entry, None)
        try:
            with pytest.raises(ImportError):
                importlib.import_module(entry)
        finally:
            if saved is not None:
                sys.modules[entry] = saved


def test_the_kernel_carries_no_service_package_and_no_product_imports():
    assert not (KERNEL_DIR / "service").exists(), (
        "pacthold.service must be gone: the kernel owns no product composition")
    for path in KERNEL_DIR.rglob("*.py"):
        for name in _absolute_modules(path.read_text(encoding="utf-8")):
            assert not name.startswith("ordessa_"), f"{path}: imports {name}"


def test_the_composition_root_imports_the_final_owner():
    plugin = (REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "plugin.py").read_text(encoding="utf-8")
    assert "from ordessa_server_compat.sessions import SessionRecords, SessionService" in plugin
    assert "from ordessa_server_compat.sessions.queue import QueueRecords" in plugin
    assert "pacthold.service" not in plugin
    persistence = (REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "persistence.py").read_text(encoding="utf-8")
    assert "from ordessa_server_compat.sessions import SessionRecords" in persistence


def test_the_declared_host_edges_are_exactly_the_neutral_vocabulary():
    edges: set[str] = set()
    for path in sorted(IMPLEMENTATION_DIR.rglob("*.py")):
        edges.update(name for name in _absolute_modules(path.read_text(encoding="utf-8"))
                     if name == "ordessa_server" or name.startswith("ordessa_server."))
    assert edges == set(VOCABULARY_EDGES), edges ^ set(VOCABULARY_EDGES)

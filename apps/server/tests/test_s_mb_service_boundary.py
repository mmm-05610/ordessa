"""Service facade boundary pins — re-pinned for the final dependency direction.

The facade's final owner is the compatibility core
(`ordessa_server_compat.facade`); the interim discipline (implementation in
`pacthold.service.facade` behind an `ordessa_server.services` alias) is
RETIRED by the dependency-direction batch. What must hold now:

- exactly one `ProductService` implementation, in `ordessa_server_compat.facade`;
- `ordessa_server.services` and `pacthold.service` no longer import at all;
- `pacthold` declares zero runtime dependencies;
- the composition root imports the facade from the compat core; the host
  bootstrap knows no product code;
- constructor signature and public method set are unchanged.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

from ordessa_server_compat.facade import ProductService


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT_DIR = REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat"
KERNEL_DIR = REPO_ROOT / "packages" / "pacthold" / "src" / "pacthold"

PUBLIC_METHODS = frozenset((
    "import_credential", "list_credentials", "readiness", "distributions",
    "probe", "browse", "create_workspace", "create_profile",
    "create_session", "create_turn", "cancel_turn",
))

#: The host's neutral vocabulary — the only ordessa_server.* edges the
#: facade may keep.
VOCABULARY_EDGES = frozenset((
    "ordessa_server.credentials",
    "ordessa_server.errors",
    "ordessa_server.events",
))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _absolute_imports(tree: ast.AST) -> list[str]:
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            assert node.level == 0, "relative import in the facade"
            result.append(node.module)
    return result


def test_single_implementation_lives_in_the_compat_core():
    tree = _tree(COMPAT_DIR / "facade.py")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == ["ProductService"]
    methods = {node.name for node in classes[0].body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert methods == PUBLIC_METHODS | {"__init__"}


def test_the_legacy_entries_no_longer_import():
    for entry in ("ordessa_server.services", "pacthold.service",
                  "pacthold.service.facade"):
        saved = sys.modules.pop(entry, None)
        try:
            with pytest.raises(ImportError):
                importlib.import_module(entry)
        finally:
            if saved is not None:
                sys.modules[entry] = saved


def test_the_kernel_declares_no_runtime_dependency():
    from importlib import metadata

    requires = metadata.requires("pacthold") or []
    runtime_deps = [r for r in requires if "extra ==" not in r]
    assert runtime_deps == [], runtime_deps
    for path in KERNEL_DIR.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("ordessa_"), (
                        f"{path}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and not node.level:
                # relative imports stay inside the kernel by construction;
                # only ABSOLUTE imports can leave it
                assert not (node.module or "").startswith("ordessa_"), (
                    f"{path}: imports {node.module}")


def test_facade_module_has_no_assembly_or_state():
    tree = _tree(COMPAT_DIR / "facade.py")
    for node in tree.body:
        assert isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.ClassDef)), (
            "module-level assembly, registration or state in the service facade")


def test_facade_imports_only_declared_vocabulary_edges():
    imports = {name for name in _absolute_imports(_tree(COMPAT_DIR / "facade.py"))
               if name == "ordessa_server" or name.startswith("ordessa_server.")}
    assert imports <= set(VOCABULARY_EDGES), imports - set(VOCABULARY_EDGES)
    # T014-S2c retired the wire vocabulary from the plugin side; a re-import is
    # a rule-3 breach, not a re-declaration of this list.
    retired = {"ordessa_server.errors", "ordessa_server.records"}
    assert not (imports & retired), f"facade imports S2c-published modules: {imports & retired}"
    assert "server_plugin_api" in {
        name for name in _absolute_imports(_tree(COMPAT_DIR / "facade.py"))}, (
        "the facade must reach the published contract for the shared vocabulary")


def test_composition_root_imports_the_final_owner():
    source = (COMPAT_DIR / "plugin.py").read_text(encoding="utf-8")
    assert "from ordessa_server_compat.facade import ProductService" in source
    assert "ordessa_server.services" not in source
    assert "pacthold.service" not in source
    host = (REPO_ROOT / "apps" / "server" / "src" / "ordessa_server" / "bootstrap" / "runtime.py").read_text(encoding="utf-8")
    assert "pacthold.service" not in host, (
        "the host composition root must not know the product facade")


def test_constructor_signature_unchanged():
    signature = inspect.signature(ProductService.__init__)
    positional = ["self", "workspaces", "profiles", "sessions"]
    keyword_only = ["harnesses", "credentials", "execution", "notifier"]
    parameters = list(signature.parameters.values())
    assert [p.name for p in parameters] == positional + keyword_only
    for parameter, expected_kind in zip(parameters, [inspect.Parameter.POSITIONAL_OR_KEYWORD] * 4 + [inspect.Parameter.KEYWORD_ONLY] * 4):
        assert parameter.kind == expected_kind, parameter

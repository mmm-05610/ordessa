"""MB-S2a service facade boundary pins: single implementation, thin legacy alias.

Locks the equivalent extraction of `ProductService` (approvals
MB-S2a-service-facade-release.md, baseline d12aa979):
- exactly one implementation, in `pacthold.service.facade`;
- the legacy entry `ordessa_server.services` re-exports the same class
  object and carries no second implementation, assembly or state;
- the composition root imports from the new entry;
- the new package never imports `ordessa_server.services` and touches only
  the declared transitional `ordessa_server.*` edges;
- constructor signature and public method set are unchanged.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from pacthold.service import ProductService as from_new_entry
from pacthold.service import facade
from ordessa_server import services as legacy_entry


REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_PACKAGE_DIR = REPO_ROOT / "packages" / "pacthold" / "src" / "pacthold" / "service"

PUBLIC_METHODS = frozenset((
    "import_credential", "list_credentials", "readiness", "distributions",
    "probe", "browse", "create_workspace", "create_profile",
    "create_session", "create_turn", "cancel_turn",
))

TRANSITIONAL_EDGES = frozenset((
    "typing", "__future__",
    "ordessa_server.credentials", "ordessa_server.errors",
    "ordessa_server.execution", "ordessa_server.events",
    "ordessa_server.profiles", "ordessa_server.workspaces",
    "pacthold.service.sessions",
))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _absolute_imports(tree: ast.AST) -> list[str]:
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in the service facade package"
            if node.module is not None:
                result.append(node.module)
    return result


def test_old_and_new_entries_are_the_same_class_object():
    assert legacy_entry.ProductService is facade.ProductService is from_new_entry
    assert legacy_entry.__all__ == ["ProductService"]


def test_single_implementation_lives_only_in_facade():
    tree = _tree(NEW_PACKAGE_DIR / "facade.py")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == ["ProductService"]
    methods = {node.name for node in classes[0].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert methods == PUBLIC_METHODS | {"__init__"}
    legacy = _tree(REPO_ROOT / "apps" / "server" / "src" / "ordessa_server" / "services.py")
    assert not [node for node in ast.walk(legacy)
                if isinstance(node, ast.ClassDef)], "second implementation in the legacy entry"
    assert not [node for node in legacy.body if isinstance(node, ast.FunctionDef)]


def test_legacy_entry_is_thin_one_way_delegation():
    tree = _tree(REPO_ROOT / "apps" / "server" / "src" / "ordessa_server" / "services.py")
    for node in tree.body:
        assert isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign)), (
            "legacy entry must stay a docstring + re-export shim")
        if isinstance(node, ast.Assign):
            assert len(node.targets) == 1
            target = node.targets[0]
            assert isinstance(target, ast.Name) and target.id == "__all__", (
                "module-level state beyond __all__ in the legacy entry")


def test_facade_module_has_no_assembly_or_state():
    tree = _tree(NEW_PACKAGE_DIR / "facade.py")
    for node in tree.body:
        assert isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.ClassDef)), (
            "module-level assembly, registration or state in the service facade")


def test_new_package_never_imports_server_services():
    for path in sorted(NEW_PACKAGE_DIR.rglob("*.py")):
        for name in _absolute_imports(_tree(path)):
            assert name != "ordessa_server.services", path
            assert not name.startswith("ordessa_server.services."), path


def test_facade_imports_only_declared_transitional_edges():
    imports = set(_absolute_imports(_tree(NEW_PACKAGE_DIR / "facade.py")))
    assert imports <= TRANSITIONAL_EDGES, imports - TRANSITIONAL_EDGES


def test_composition_root_imports_new_entry():
    # The composition root moved with the domains (core-cleanup stage 3):
    # the compatibility core's plugin is what composes the facade now, and
    # the host bootstrap imports no product code at all.
    source = (REPO_ROOT / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "plugin.py").read_text(encoding="utf-8")
    assert "from pacthold.service.facade import ProductService" in source
    assert "from ordessa_server.services import" not in source
    host = (REPO_ROOT / "apps" / "server" / "src" / "ordessa_server" / "bootstrap" / "runtime.py").read_text(encoding="utf-8")
    assert "pacthold.service" not in host, (
        "the host composition root must not know the product facade")


def test_constructor_signature_unchanged():
    signature = inspect.signature(facade.ProductService.__init__)
    positional = ["self", "workspaces", "profiles", "sessions"]
    keyword_only = ["harnesses", "credentials", "execution", "notifier"]
    parameters = list(signature.parameters.values())
    assert [p.name for p in parameters] == positional + keyword_only
    for parameter, expected_kind in zip(parameters, [inspect.Parameter.POSITIONAL_OR_KEYWORD] * 4 + [inspect.Parameter.KEYWORD_ONLY] * 4):
        assert parameter.kind is expected_kind, parameter.name
        assert parameter.default is inspect.Parameter.empty, f"{parameter.name} gained a default"

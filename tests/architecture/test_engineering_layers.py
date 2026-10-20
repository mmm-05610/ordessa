"""Small AST guard for the Engineering domain/application dependency layers.

Rules (per the confirmed architecture):
- ``domain`` must not import ``methods``, ``application`` or ``adapters``.
- ``application`` may consume ``methods`` **pure contracts/services** only:
  ``methods.definitions.*``, ``methods.validation.*``, ``methods.compilation.*`` and the exact
  pure in-memory ``methods.loading.captured`` entrypoint. Other ``methods.loading`` (file-based
  loader/parsing) is not allowed. ``application`` must not import concrete ``adapters``.
- ``pathlib`` pure path values and ``urllib.parse`` pure parsing are allowed; actual IO is still
  forbidden (``open``/``Path`` read-write/``os``/``io``/``socket``/``sqlite3``/``subprocess``/
  ``tempfile``/``http``/``requests``/``importlib``/``urllib`` other than ``urllib.parse``).

Detection boundaries (honest): this is a **static AST name scan**. It catches static imports,
aliased imports and attribute calls by name/receiver shape. It does **not** prove that arbitrary
dynamic code performs no IO — ``getattr``/``eval``/``exec``, string-built imports, reflection or a
method resolved at runtime can evade it. It is a guard, not a proof.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest


_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "engineering" / "src" / "ordessa_engineering"
_FORBIDDEN_IO_ROOTS = frozenset({
    "builtins_io", "io", "os", "socket", "sqlite3", "subprocess",
    "tempfile", "http", "requests", "importlib",
})
#: ``urllib`` is allowed only for the pure parser submodule (no network).
_PURE_URL_SUBMODULES = frozenset({"urllib.parse"})
#: Application may import these ``methods`` subtrees (pure contracts/services).
_ALLOWED_APPLICATION_METHOD_PREFIXES = (
    "ordessa_engineering.methods.definitions",
    "ordessa_engineering.methods.validation",
    "ordessa_engineering.methods.compilation",
)
#: The exact pure in-memory captured entrypoint (not a blanket ``methods.loading``).
_ALLOWED_APPLICATION_METHOD_EXACT = frozenset({
    "ordessa_engineering.methods.loading.captured",
})
#: Path IO method names flagged by name regardless of receiver.
_PATH_IO_BY_NAME = frozenset({
    "read_text", "read_bytes", "write_text", "write_bytes", "iterdir", "glob", "rglob",
    "mkdir", "rmdir", "unlink", "touch", "readlink", "symlink_to", "chmod", "lstat", "walk",
})
#: Path IO method names flagged only when the receiver is a ``Path`` (avoids ``UoW.open`` /
#: ``str.replace`` false positives).
_PATH_IO_BY_PATH_RECEIVER = frozenset({
    "open", "replace", "stat", "exists", "is_file", "is_dir", "resolve", "rename",
    "samefile", "hardlink_to",
})


@dataclass(frozen=True)
class Violation:
    rule: str
    target: str
    line: int


def _module_parts(file_path: Path, package_root: Path) -> tuple[str, ...]:
    relative = file_path.relative_to(package_root)
    parts = ("ordessa_engineering",) + relative.with_suffix("").parts
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts


def _resolve_from(node: ast.ImportFrom, current_package: tuple[str, ...]) -> str | None:
    if node.level == 0:
        return node.module or ""
    remove = node.level - 1
    if remove > len(current_package):
        return None
    prefix = current_package[:len(current_package) - remove]
    suffix = tuple(node.module.split(".")) if node.module else ()
    return ".".join(prefix + suffix)


def _is_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _allowed_application_method(module: str) -> bool:
    """Application may import only the verified pure ``methods`` contracts/services."""
    prefixes = _ALLOWED_APPLICATION_METHOD_PREFIXES + tuple(_ALLOWED_APPLICATION_METHOD_EXACT)
    return any(_is_prefix(module, prefix) for prefix in prefixes)


def _is_path_receiver(node: ast.AST) -> bool:
    """True when the attribute receiver is a ``Path(...)`` call or a bare ``Path`` name."""
    if isinstance(node, ast.Name):
        return node.id == "Path"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "Path"
        if isinstance(func, ast.Attribute):
            return func.attr == "Path"
    return False


def _scan(source: str, *, file_path: Path, package_root: Path) -> tuple[Violation, ...]:
    tree = ast.parse(source, filename=str(file_path))
    module_parts = _module_parts(file_path, package_root)
    current_package = module_parts
    if file_path.name != "__init__.py":
        current_package = module_parts[:-1]
    found: list[Violation] = []

    def imported(module: str, line: int) -> None:
        layer = ".".join(module_parts)
        if (_is_prefix(layer, "ordessa_engineering.domain.common")
                and _is_prefix(module, "ordessa_engineering")
                and not _is_prefix(module, "ordessa_engineering.domain.common")
                and module not in {"ordessa_engineering", "ordessa_engineering.domain"}):
            found.append(Violation("common-reverse-import", module, line))
        if _is_prefix(module, "ordessa_engineering.methods"):
            if _is_prefix(layer, "ordessa_engineering.domain"):
                found.append(Violation("domain-methods-import", module, line))
            elif (_is_prefix(layer, "ordessa_engineering.application")
                  and not _allowed_application_method(module)):
                found.append(Violation("application-methods-import", module, line))
        if _is_prefix(module, "ordessa_engineering.adapters"):
            found.append(Violation("persistence-adapter-import", module, line))
        if _is_prefix(module, "ordessa_engineering.application") and _is_prefix(
            layer, "ordessa_engineering.domain"
        ):
            found.append(Violation("domain-to-application-import", module, line))
        root = module.split(".", 1)[0]
        if root in _FORBIDDEN_IO_ROOTS:
            found.append(Violation("io-import", module, line))
        elif root == "urllib" and not _is_prefix(module, "urllib.parse"):
            found.append(Violation("io-import", module, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, current_package)
            if base is None:
                found.append(Violation("invalid-relative-import", node.module or "", node.lineno))
                continue
            if base:
                imported(base, node.lineno)
            if _is_prefix(base, "ordessa_engineering.domain.common") and any(
                alias.name.startswith("_") for alias in node.names
            ):
                found.append(Violation("common-private-import", base, node.lineno))
            for alias in node.names:
                if alias.name != "*":
                    target = ".".join(part for part in (base, alias.name) if part)
                    imported(target, node.lineno)
            if base == "builtins" and any(alias.name == "open" for alias in node.names):
                found.append(Violation("filesystem-open-call", "builtins.open", node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                found.append(Violation("filesystem-open-call", "open", node.lineno))
            elif isinstance(func, ast.Name) and func.id == "__import__":
                found.append(Violation("dynamic-import", "__import__", node.lineno))
            elif isinstance(func, ast.Attribute):
                if func.attr == "open" and isinstance(func.value, ast.Name) and func.value.id == "builtins":
                    found.append(Violation("filesystem-open-call", "builtins.open", node.lineno))
                elif func.attr == "import_module":
                    found.append(Violation("dynamic-import", "import_module", node.lineno))
                elif func.attr in _PATH_IO_BY_NAME:
                    found.append(Violation("filesystem-path-io", func.attr, node.lineno))
                elif func.attr in _PATH_IO_BY_PATH_RECEIVER and _is_path_receiver(func.value):
                    found.append(Violation("filesystem-path-io", func.attr, node.lineno))

    return tuple(found)


def _scan_tree(layer: str) -> tuple[Violation, ...]:
    root = _PACKAGE_ROOT / layer
    assert root.is_dir(), "missing actual layer"
    sources = sorted(root.rglob("*.py"))
    assert sources, "empty actual layer"
    violations: list[Violation] = []
    for path in sources:
        violations.extend(_scan(path.read_text(encoding="utf-8"),
                                 file_path=path, package_root=_PACKAGE_ROOT))
    return tuple(violations)


def _fixture(source: str, relative: str = "domain/reviews/probe.py") -> tuple[Violation, ...]:
    return _scan(source, file_path=_PACKAGE_ROOT / relative, package_root=_PACKAGE_ROOT)


def test_real_domain_and_application_sources_obey_layer_boundaries() -> None:
    violations = _scan_tree("domain") + _scan_tree("application")
    assert violations == ()


@pytest.mark.parametrize(
    "source",
    (
        "from ...adapters.sqlite.review_repository import SQLiteReviewRepository",
        "from ... import methods",
        "from ordessa_engineering import adapters",
        "from ordessa_engineering import methods",
        "from ...methods.definitions.models import LoadedMethod",
        "import importlib",
        "import importlib\n\nimportlib.import_module('os')",
        "__import__('os')",
        "import sqlite3",
        "import sqlite3 as _sqlite",
        "from sqlite3 import connect",
        "import socket",
        "import socket as _socket",
        "from socket import socket as _s",
        "import os",
        "import os as _os",
        "from urllib.request import urlopen",
        "from pathlib import Path\n\ndef read(p):\n    return Path(p).read_text()",
        "from pathlib import Path\n\ndef write(p):\n    Path(p).write_bytes(b'')",
        "from pathlib import Path\n\ndef open_file(p):\n    return Path(p).open()",
        "import pathlib as _pl\n\ndef read(p):\n    return _pl.Path(p).read_text()",
        "def load(path):\n    return open(path, 'rb')",
    ),
    ids=("relative-adapter", "relative-methods", "namespace-adapter", "namespace-methods",
         "relative-methods-definitions", "dynamic-import", "dynamic-import-module", "dunder-import",
         "sqlite", "sqlite-alias", "sqlite-from", "network-socket", "socket-alias", "socket-from",
         "os-import", "os-alias", "urllib-request", "path-read-text", "path-write-bytes",
         "path-open", "pathlib-alias-read", "builtin-open"),
)
def test_forbidden_domain_layer_and_io_imports_are_detected(source: str) -> None:
    assert _fixture(source)


def test_application_may_import_only_the_verified_pure_methods_paths() -> None:
    allowed = (
        "from ...methods.definitions.models import LoadedMethod",
        "from ...methods.definitions.models.identity import method_digest",
        "from ...methods.definitions.errors import MethodFailure",
        "from ...methods.validation.compatibility import validate_compatibility",
        "from ...methods.validation.schema import validate_document_schemas",
        "from ...methods.compilation.compiler import compile_program_from_source",
        "from ...methods.compilation.encoding import program_to_canonical",
        "from ...methods.loading.captured import rebuild_source_bundle",
    )
    for source in allowed:
        assert _fixture(source, "application/usecases/probe.py") == (), source


def test_application_forbidden_methods_paths_are_rejected() -> None:
    for source in (
        "from ...methods.loading.loader import load_method",
        "from ...methods.loading.parsing import parse",
        "from ...methods.loading import loader",
        "from ordessa_engineering import methods",
    ):
        violations = _fixture(source, "application/usecases/probe.py")
        assert any(v.rule == "application-methods-import" for v in violations), source


def test_domain_methods_import_is_rejected() -> None:
    violations = _fixture("from ...methods.definitions.models import LoadedMethod")
    assert any(v.rule == "domain-methods-import" for v in violations)


def test_application_pure_pathlib_value_and_urllib_parse_are_allowed() -> None:
    for source in (
        "import pathlib\n\n_ROOT = pathlib.Path('.')",
        "from pathlib import Path\n\n_ROOT = Path('.')",
        "from urllib.parse import urljoin\n\nbase = urljoin('a', 'b')",
    ):
        assert _fixture(source, "application/usecases/probe.py") == (), source


def test_application_path_io_and_dynamic_import_are_rejected() -> None:
    for source in (
        "from pathlib import Path\n\ndef read(p):\n    return Path(p).read_text()",
        "from pathlib import Path\n\ndef glob_all(p):\n    return list(Path(p).glob('*'))",
        "import importlib\n\nimportlib.import_module('os')",
        "__import__('os')",
        "import os",
    ):
        assert _fixture(source, "application/usecases/probe.py"), source


def test_domain_relative_application_import_is_detected() -> None:
    assert _fixture("from ...application.contracts.errors import ApplicationError")


def test_neutral_domain_dependencies_are_allowed() -> None:
    source = """
from dataclasses import dataclass
from hashlib import sha256
import math
from ordessa_infrastructure.encoding import canonical_bytes

@dataclass(frozen=True)
class Value:
    digest: bytes
"""
    assert _fixture(source) == ()


def test_application_can_depend_on_domain_infrastructure_and_schema_libraries() -> None:
    source = """
from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes
from ...domain.common.models.identity import Scope
"""
    violations = _scan(source, file_path=_PACKAGE_ROOT / "application/usecases/probe.py",
                       package_root=_PACKAGE_ROOT)
    assert violations == ()


def test_application_static_persistence_import_is_rejected() -> None:
    source = "from ...adapters.persistence.sqlite.review_repository import SQLiteReviewRepository"
    violations = _scan(source, file_path=_PACKAGE_ROOT / "application/usecases/probe.py",
                       package_root=_PACKAGE_ROOT)
    assert violations


@pytest.mark.parametrize("source", (
    "from ..common.models.refs import _id",
    "from ordessa_engineering.domain.common.mechanisms.codec import _digest",
))
def test_common_private_imports_are_rejected(source: str) -> None:
    assert any(v.rule == "common-private-import" for v in _fixture(source))


def _runtime_imports(tree):
    for node in ast.iter_child_nodes(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"):
            for child in node.orelse:
                yield from _runtime_imports(child)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        yield from _runtime_imports(node)


def _common_graph(sources, *, include_type_checking=False):
    prefix = "ordessa_engineering.domain.common"
    graph = {name: set() for name in sources}
    for name, source in sources.items():
        tree = ast.parse(source)
        imports = (node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))) if include_type_checking else _runtime_imports(tree)
        package = tuple(prefix.split('.')) + tuple(name.split('.')[:-1])
        if name in {'models', 'outcomes', 'mechanisms'}:
            package = tuple(prefix.split('.')) + (name,)
        for node in imports:
            if isinstance(node, ast.ImportFrom):
                target = _resolve_from(node, package)
                targets = [target] + [target + '.' + a.name for a in node.names]
            else:
                targets = [a.name for a in node.names]
            for target in targets:
                if target and target.startswith(prefix + '.'):
                    dependency = target[len(prefix) + 1:]
                    while dependency and dependency not in graph:
                        dependency = dependency.rsplit('.', 1)[0] if '.' in dependency else ''
                    if dependency in graph:
                        graph[name].add(dependency)
    return graph


def _cycles(graph):
    active, complete = set(), set()

    def visit(name):
        if name in active:
            return True
        if name in complete:
            return False
        active.add(name)
        if any(visit(dependency) for dependency in graph[name]):
            return True
        active.remove(name)
        complete.add(name)
        return False

    return any(visit(name) for name in graph)


def test_actual_common_has_no_runtime_cycles_and_foundations_stay_below_refs():
    root = _PACKAGE_ROOT / 'domain/common'
    sources = {('.'.join(p.relative_to(root).with_suffix('').parts[:-1]) or '__init__') if p.name == '__init__.py'
               else '.'.join(p.relative_to(root).with_suffix('').parts): p.read_text() for p in root.rglob('*.py')}
    graph = _common_graph(sources)
    assert not _cycles(graph), graph
    type_graph = _common_graph(sources, include_type_checking=True)
    assert not _cycles(type_graph), type_graph
    assert graph['outcomes.diagnostics'] == set()
    assert graph['models.values'] <= {'outcomes.diagnostics'}
    assert graph['mechanisms.hashing'] <= {'outcomes.diagnostics', 'models.values'}
    assert graph['models.refs'] <= {'outcomes.diagnostics', 'models.values'}
    assert 'models.selection' in graph['mechanisms.selection']
    assert not {'outcomes.errors', 'outcomes.result', 'models.provenance',
                'models.trust', 'models.mutation'} & set(graph)
    assert all(not dependencies for name, dependencies in graph.items()
               if name in {'__init__', 'models', 'outcomes', 'mechanisms'})
    assert all('mechanisms.codec' not in dependencies for name, dependencies in graph.items()
               if name != 'mechanisms.codec')
    for p in root.rglob('*.py'):
        assert not _scan(p.read_text(), file_path=p, package_root=_PACKAGE_ROOT)
    # All actual domain/application and persistence consumers switch atomically.
    for p in _PACKAGE_ROOT.rglob('*.py'):
        assert not [v for v in _scan(p.read_text(), file_path=p, package_root=_PACKAGE_ROOT)
                    if v.rule == 'common-private-import']


def test_cycle_guard_detects_injected_reverse_dependency():
    assert _cycles(_common_graph({'values': 'from .refs import Target',
                                 'refs': 'from .values import Scope'}))


@pytest.mark.parametrize('source', (
    'from ..artifacts.models import ArtifactRevision',
    'from ordessa_engineering.domain import changes',
    'from ...models import MaterialRef',
))
def test_common_rejects_business_and_prototype_reverse_imports(source):
    violations = _fixture(source, 'domain/common/probe.py')
    assert any(v.rule == 'common-reverse-import' for v in violations)


def test_common_codec_owns_canonical_value_without_hashing_alias():
    hashing = ast.parse((_PACKAGE_ROOT / 'domain/common/mechanisms/hashing.py').read_text())
    assert not any(isinstance(node, (ast.FunctionDef, ast.ImportFrom)) and
                   (getattr(node, 'name', None) == 'canonical_value' or
                    any(alias.name == 'canonical_value' for alias in getattr(node, 'names', ())))
                   for node in ast.walk(hashing))
    for path in _PACKAGE_ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith('common.mechanisms.hashing'):
                assert not any(alias.name == 'canonical_value' for alias in node.names), path


def test_type_only_ref_annotations_do_not_create_runtime_cycles():
    assert not _cycles(_common_graph({'errors': 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .refs import Target',
                                     'refs': 'from .errors import ReferenceError'}))


def _domain_graph(sources, *, package_modules=(), include_type_checking=False):
    prefix = 'ordessa_engineering'
    graph = {name: set() for name in sources}
    for name, source in sources.items():
        tree = ast.parse(source)
        imports = (node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))) if include_type_checking else _runtime_imports(tree)
        package = (prefix,) + tuple(name.split('.') if name in package_modules else name.split('.')[:-1])
        for node in imports:
            if isinstance(node, ast.ImportFrom):
                target = _resolve_from(node, package)
                targets = [target] + [target + '.' + alias.name for alias in node.names]
            else:
                targets = [alias.name for alias in node.names]
            for target in targets:
                if target and target.startswith(prefix + '.'):
                    dependency = target[len(prefix) + 1:]
                    while dependency and dependency not in graph:
                        dependency = dependency.rsplit('.', 1)[0] if '.' in dependency else ''
                    if dependency in graph:
                        graph[name].add(dependency)
    return graph


def test_actual_domain_owners_are_acyclic_without_common_or_artifact_reverse_edges():
    sources, packages = {}, set()
    for path in (_PACKAGE_ROOT / 'domain').rglob('*.py'):
        parts = path.relative_to(_PACKAGE_ROOT).with_suffix('').parts
        name = '.'.join(parts[:-1] if path.name == '__init__.py' else parts)
        sources[name] = path.read_text()
        if path.name == '__init__.py':
            packages.add(name)
    for include in (False, True):
        graph = _domain_graph(sources, package_modules=packages, include_type_checking=include)
        assert not _cycles(graph), graph
        assert all(dependency.startswith('domain.common') for name, edges in graph.items()
                   if name.startswith('domain.common') for dependency in edges)
        assert all(dependency.startswith(('domain.common', 'domain.artifacts'))
                   for name, edges in graph.items() if name.startswith('domain.artifacts')
                   for dependency in edges)
        assert 'domain.changes.refs' in graph['domain.reviews.targets']
        assert 'domain.changes.baselines' in graph['domain.reviews.targets']
        assert 'domain.reviews.requirements' in graph['domain.changes.models']
        assert 'domain.changes.models' not in graph['domain.reviews.targets']
        assert not any('ordessa_engineering.methods' in target
                       for source in sources.values() for node in ast.walk(ast.parse(source))
                       if isinstance(node, (ast.Import, ast.ImportFrom))
                       for target in ([node.module or ''] if isinstance(node, ast.ImportFrom)
                                      else [alias.name for alias in node.names]))


def test_domain_cycle_guard_detects_business_and_type_only_reverse_edges():
    sources = {'domain.artifacts.models': 'from ..reviews.models import ReviewRequirement',
               'domain.reviews.models': 'from ..artifacts.models import ArtifactRevision'}
    assert _cycles(_domain_graph(sources))
    sources['domain.artifacts.models'] = 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..reviews.models import ReviewRequirement'
    assert not _cycles(_domain_graph(sources))
    assert _cycles(_domain_graph(sources, include_type_checking=True))

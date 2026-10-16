"""Definitions ownership, isolation and pure value invariants."""
import ast
from dataclasses import FrozenInstanceError
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys
from typing import get_type_hints

import pytest

from ordessa_engineering.methods.definitions import errors, models, schemas
from ordessa_engineering.methods.definitions.models import compiled
from ordessa_engineering.methods.definitions.contracts import validation
from ordessa_engineering.methods.definitions import defaults


ROOT = Path(__file__).resolve().parents[2] / "src/ordessa_engineering/methods/definitions"


def _imports(source, module):
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = (resolve_name("." * node.level + (node.module or ""), module)
                    if node.level else node.module)
            if node.module is None:
                result.update(name + "." + item.name for item in node.names)
            else:
                result.add(name)
    return result


def _forbidden(source, package="ordessa_engineering.methods.definitions"):
    imports = _imports(source, package)
    allowed = {"__future__", "dataclasses", "pathlib", "typing", "types", "json", "re",
               "ordessa_infrastructure.encoding", "hashlib"}
    return {name for name in imports if name not in allowed
            and not name.startswith("ordessa_engineering.methods.definitions.")}


def test_definitions_imports_are_pure_and_internal_graph_is_acyclic():
    graph = {}
    for path in ROOT.rglob("*.py"):
        source = path.read_text()
        relative = path.relative_to(ROOT).with_suffix("").parts
        module = "ordessa_engineering.methods.definitions." + ".".join(relative)
        package = module.rsplit(".", 1)[0]
        if path.name == "__init__.py":
            module = package
        assert not _forbidden(source, package), path
        graph[module] = {name for name in _imports(source, package)
                         if name.startswith("ordessa_engineering.methods.definitions.")}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "__import__"}, path

    def visit(name, stack):
        assert name not in stack, (name, stack)
        for dependency in graph.get(name, ()):
            visit(dependency, stack + (name,))

    for name in graph:
        visit(name, ())


def test_foundations_do_not_import_stages_and_models_do_not_import_schemas():
    for path in (ROOT / "models").glob("*.py"):
        imports = _imports(path.read_text(), "ordessa_engineering.methods.definitions.models")
        assert "ordessa_engineering.methods.definitions.schemas" not in imports
        if path.stem in {"identity", "sources", "capabilities"}:
            assert not any(name.endswith((".loaded", ".compiled", ".snapshot", ".verification"))
                           for name in imports), path


@pytest.mark.parametrize("source", [
    "from ..loading.loader import load_method",
    "from ..validation.schema import validate_resources",
    "from ..compilation.compiler import compile_method",
    "from ordessa_engineering.domain.common import EngineeringError",
    "import ordessa_engineering.application.usecases",
    "import ordessa_engineering.adapters.persistence",
    "import ordessa_server",
    "import plugins.example",
    "import socket",
])
def test_boundary_guard_rejects_injected_reverse_dependencies(source):
    assert _forbidden(source)


def test_definitions_import_without_engineering_parents_or_stage_implementations():
    # The real root and methods initializers still compose other layers. Avoid
    # executing them here; this proves this module, not the whole public root.
    infrastructure = ROOT.parents[4] / "infrastructure/src"
    script = r'''
import importlib, importlib.abc, sys, types
from pathlib import Path
definitions, infrastructure = map(Path, sys.argv[1:])
sys.path.insert(0, str(infrastructure))
import ordessa_infrastructure.encoding
assert Path(ordessa_infrastructure.encoding.__file__).is_relative_to(infrastructure)
for name, path in [("ordessa_engineering", definitions.parent.parent),
                   ("ordessa_engineering.methods", definitions.parent)]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
class BlockHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("ordessa_engineering.domain", "ordessa_engineering.application",
                                "ordessa_engineering.adapters", "ordessa_engineering.methods.loading",
                                "ordessa_engineering.methods.validation", "ordessa_engineering.methods.compilation",
                                "ordessa_server", "plugins")):
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockHost())
for suffix in ["", ".models", ".models.identity", ".models.sources", ".models.capabilities",
               ".models.loaded", ".models.verification", ".models.compiled", ".models.snapshot", ".schemas", ".errors", ".contracts.sources", ".contracts.validation", ".defaults"]:
    importlib.import_module("ordessa_engineering.methods.definitions" + suffix)
'''
    subprocess.run([sys.executable, "-I", "-B", "-c", script, str(ROOT), str(infrastructure)],
                   check=True, capture_output=True, text=True)


def test_single_type_owners_and_resolvable_snapshot_annotations():
    assert models.CompiledMethod is compiled.CompiledMethod
    assert models.CompiledMethod.__module__ == compiled.__name__
    assert compiled.StoredProgram.__module__ == compiled.__name__
    assert models.LoadedMethod.__module__ == models.__name__ + ".loaded"
    assert models.MethodSnapshot.__module__ == models.__name__ + ".snapshot"
    assert models.MethodIdentity.__module__ == models.__name__ + ".identity"
    assert models.ResourceRef.__module__ == models.__name__ + ".identity"
    assert models.SourceBundle.__module__ == models.__name__ + ".sources"
    assert models.CompilationCapabilities.__module__ == models.__name__ + ".capabilities"
    assert schemas.CRITERION_DEFAULTS_V1 is defaults.CRITERION_DEFAULTS_V1
    assert schemas.DOCUMENT_VALIDATION_TARGET_DEFAULT_V1 is defaults.DOCUMENT_VALIDATION_TARGET_DEFAULT_V1
    assert not (ROOT / "models.py").exists()
    assert not (ROOT / "compiled.py").exists()
    assert get_type_hints(models.MethodSnapshot)["program"] == compiled.CompiledProgram | compiled.HistoricalBoundProgram
    assert get_type_hints(models.StoredSourceBundle)["manifest_ref"] is models.BlobRef
    assert get_type_hints(models.ResourceSnapshot)["blob_ref"] is models.BlobRef
    assert get_type_hints(models.CompiledMethod)["program"] is compiled.CompiledProgram
    assert not hasattr(models, "Diagnostic")
    assert not hasattr(models, "ValidationReport")
    assert errors.Diagnostic.__module__ == errors.__name__ + ".diagnostics"
    assert validation.ValidationReport.__module__ == validation.__name__
    assert not hasattr(errors, "ValidationReport")
    assert not hasattr(errors, "ValidationPhase")


def test_result_rejects_competing_success_and_failure_values():
    error = errors.MethodError("INVALID", "invalid", resource_id="r", pointer="/field")
    with pytest.raises(ValueError, match="both a value and an error"):
        errors.MethodResult(value="value", error=error)
    assert errors.MethodResult.success(None).ok
    result = errors.MethodResult.failure(error)
    assert not result.ok and result.error is error
    with pytest.raises(FrozenInstanceError):
        result.error = None


def test_shared_defaults_and_freeze_preserve_value_constraints():
    assert dict(schemas.CRITERION_DEFAULTS_V1) == {
        "required": True, "blocking": True, "applies_to": (), "required_inputs": (),
    }
    with pytest.raises(TypeError):
        schemas.CRITERION_DEFAULTS_V1["required"] = False
    assert compiled.DocumentSpec.__dataclass_fields__["validation_target"].default == (
        schemas.DOCUMENT_VALIDATION_TARGET_DEFAULT_V1)
    value = {"threshold": "0.125", "inputs": [True, None, 2]}
    assert compiled.thaw_value(compiled.freeze_value(value)) == value
    for invalid in (0.125, object(), b"bytes"):
        with pytest.raises(ValueError, match="unsupported method value"):
            compiled.freeze_value(invalid)


def test_definitions_packages_contain_no_parser_or_validator_execution():
    assert not (ROOT / "schemas.py").exists()
    assert not (ROOT / "errors.py").exists()
    assert (ROOT / "schemas/v1.py").exists()
    assert (ROOT / "errors/diagnostics.py").exists()
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {"yaml", "jsonschema", "ordessa_engineering.methods.loading.parsing"}
                assert not any(n.name in {"parse_document", "decode_json", "Draft202012Validator"} for n in node.names)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                assert node.name not in {"parse_document", "_StrictLoader", "_reject_aliases_anchors", "_construct_mapping", "_structure_errors"}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"safe_load", "iter_errors", "check_schema", "add_constructor"}


def test_strict_method_parser_has_one_actual_owner():
    methods = ROOT.parent
    owners = []
    for path in methods.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name == "parse_document": owners.append(path)
    assert owners == [methods / "loading/parsing.py"]

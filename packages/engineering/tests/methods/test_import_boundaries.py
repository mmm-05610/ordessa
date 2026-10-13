"""Guard real source imports rather than accepting a populated directory tree."""
import ast
from importlib.util import resolve_name
from pathlib import Path


def test_methods_has_no_reverse_host_imports_or_implicit_io():
    root = Path(__file__).resolve().parents[2] / "src/ordessa_engineering/methods"
    violations = []
    for file in root.rglob("*.py"):
        parts = file.relative_to(root).with_suffix("").parts
        package = "ordessa_engineering.methods" + ("." + ".".join(parts[:-1]) if len(parts) > 1 else "")
        for node in ast.walk(ast.parse(file.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                name = "." * node.level + (node.module or "")
                names = [resolve_name(name, package) if node.level else name]
            for name in names:
                if name.startswith(("ordessa_engineering.domain", "ordessa_engineering.application",
                                    "ordessa_engineering.adapters", "subprocess", "socket", "urllib.request")):
                    violations.append((str(file), node.lineno, name))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "eval", "exec"}:
                violations.append((str(file), node.lineno, node.func.id))
    assert not violations, violations


def _stage_violations(source, package, stage):
    forbidden = {
        "definitions": ("loading", "validation", "compilation"),
        "validation": ("loading", "compilation"),
        "compilation": ("loading",),
    }.get(stage, ())
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            names = [resolve_name(name, package) if node.level else name]
        else:
            continue
        for name in names:
            if any(name == "ordessa_engineering.methods." + item or name.startswith("ordessa_engineering.methods." + item + ".") for item in forbidden):
                violations.append(name)
    return violations

def test_actual_method_stages_have_no_reverse_dependencies():
    root = Path(__file__).resolve().parents[2] / "src/ordessa_engineering/methods"
    for file in root.rglob("*.py"):
        parts = file.relative_to(root).parts
        if parts[0] not in {"definitions", "validation", "compilation"}:
            continue
        package = "ordessa_engineering.methods." + ".".join(parts[:-1])
        assert not _stage_violations(file.read_text(), package, parts[0]), file

def test_method_stage_guard_rejects_function_local_reverse_imports():
    assert _stage_violations("def unsafe():\n    from ..loading.captured import verify_loaded_method", "ordessa_engineering.methods.compilation", "compilation")
    assert _stage_violations("from ..compilation.encoding import program_to_canonical", "ordessa_engineering.methods.validation", "validation")
    assert _stage_violations("import ordessa_engineering.methods.loading.parsing", "ordessa_engineering.methods.definitions", "definitions")

def test_retired_method_stage_files_are_absent():
    root = Path(__file__).resolve().parents[2] / "src/ordessa_engineering/methods"
    for name in ("loading/snapshot.py", "loading/content.py", "loading/ports.py",
                 "validation/method.py", "validation/graph.py", "compilation/hashing.py",
                 "compilation/selectors.py", "compilation/policies.py", "definitions/models/defaults.py"):
        assert not (root / name).exists(), name
    compiler = ast.parse((root / "compilation/compiler.py").read_text())
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "compile_method" for node in ast.walk(compiler))

def test_compiled_models_do_not_own_external_codecs():
    root = Path(__file__).resolve().parents[2] / "src/ordessa_engineering/methods/definitions/models"
    for path in (root / "compiled.py", root / "snapshot.py"):
        assert not any(isinstance(node, ast.FunctionDef) and node.name in {"canonical", "encoding", "plan_digest", "from_canonical", "from_wire", "to_wire"}
                       for node in ast.walk(ast.parse(path.read_text()))), path

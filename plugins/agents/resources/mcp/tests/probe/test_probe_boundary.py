"""T03 boundary guards: the probe module may only read the definition
validator and must carry no write/storage/native-config capability.
"""
import ast
import inspect

from backend import probe


def _imported_modules(source):
    absolute, relative = set(), set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                relative.add((node.module or "", node.level))
            elif node.module != "__future__":
                absolute.add(node.module or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                absolute.add(alias.name)
    return absolute, relative


def _called_names(source):
    """Every function/method name the module can actually invoke, plus the
    dotted call expressions (``module.member``) for spawn-entry counting."""
    calls = set()
    dotted = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
                if isinstance(node.func.value, ast.Name):
                    dotted.add(f"{node.func.value.id}.{node.func.attr}")
    return calls, dotted


def test_probe_dependencies_are_read_only_surface():
    absolute, relative = _imported_modules(inspect.getsource(probe))
    assert absolute <= {"json", "os", "selectors", "signal", "ssl", "subprocess", "time",
                        "http.client", "typing", "urllib.parse"}
    assert relative <= {("definition", 1), ("errors", 1), ("probe_policy", 1)}
    # explicitly: no storage, no assignment/resolve, no rendering/config writer
    forbidden = ("store", "assignment", "resolve", "render")
    assert not any(any(word in name for word in forbidden) for name in absolute | {n for n, _ in relative})


def test_probe_source_has_no_write_or_spawn_bypass_primitives():
    calls, dotted = _called_names(inspect.getsource(probe))
    for banned in ("open", "mkdir", "rename", "replace", "remove", "unlink", "system",
                   "execv", "execve", "spawnl", "spawnv"):
        assert banned not in calls, f"probe must never call {banned!r}"
    # exactly one spawn site, guarded by start_new_session cleanup
    assert len(_spawn_sites()) == 1
    assert "start_new_session=True" in inspect.getsource(probe)


def _spawn_sites():
    tree = ast.walk(ast.parse(inspect.getsource(probe)))
    return [node for node in tree
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess" and node.func.attr == "Popen"]

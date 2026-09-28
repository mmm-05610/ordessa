"""T03 red/green: compile-purity and dependency-direction gates (§C1).

"C1 ... 纯编译不得网络、spawn、访问 HOME、读取密钥" - enforced here by AST
over every module under `src/`, and behaviorally by poisoning the side-effect
entry points while running the adapters.

Allowed imports: the standard library (minus the forbidden set below),
`ordessa_permissions_api` (the consumed domain contract), `server_plugin_api`
(the public plugin surface) and this package itself. No host, no harness, no
compat, no storage.
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import socket
import subprocess
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_permissions_adapters"

EXPECTED_MODULES = (
    "__init__.py", "codes.py", "results.py", "dto.py", "ranges.py", "base.py",
    "claude_code.py", "codex.py", "pi.py", "cells.py", "matrix.py", "registry.py",
    "contribution.py",
)

FORBIDDEN_IMPORTS = {
    "subprocess", "socket", "shutil", "http", "urllib", "requests", "sqlite3",
    "ftplib", "telnetlib", "asyncio", "tempfile",
}
FORBIDDEN_PRODUCT_ROOTS = {
    "ordessa_server", "ordessa_server_compat", "ordessa_harness", "pacthold",
    "ordessa_workspace", "fastapi", "pydantic", "httpx", "uvicorn",
}
ALLOWED_NON_STDLIB = {"ordessa_permissions_api", "server_plugin_api",
                      "ordessa_harness_api",
                      "ordessa_permissions_adapters", "__future__"}
#: Call attribute names that would mean the compile path touches the filesystem,
#: a user directory or a process.
FORBIDDEN_ATTR_CALLS = {
    "expanduser", "system", "popen", "execv", "execve", "spawn", "spawnl",
    "spawnv", "read_text", "read_bytes", "write_text", "write_bytes", "listdir",
    "scandir", "urlopen", "startfile", "kill",
}
STDLIB_OK = set(sys.stdlib_module_names)


def _sources() -> list[pathlib.Path]:
    return sorted(SRC_ROOT.glob("**/*.py"), key=str)


def _imported_roots(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_the_package_modules_all_exist() -> None:
    assert SRC_ROOT.is_dir(), SRC_ROOT
    present = {path.name for path in _sources()}
    missing = [name for name in EXPECTED_MODULES if name not in present]
    assert not missing, f"missing modules: {missing}"


def test_no_forbidden_module_is_imported() -> None:
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = _imported_roots(tree)
        for root in roots:
            assert root not in FORBIDDEN_IMPORTS, f"{path.name} imports {root!r}"
            assert root not in FORBIDDEN_PRODUCT_ROOTS, f"{path.name} imports host {root!r}"
            allowed = root in STDLIB_OK or root in ALLOWED_NON_STDLIB
            assert allowed, f"{path.name} imports unexpected root {root!r}"


def test_no_side_effect_call_sites_exist() -> None:
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else \
                    func.attr if isinstance(func, ast.Attribute) else None
                assert name != "open", f"{path.name} opens a file"
                assert name not in FORBIDDEN_ATTR_CALLS, f"{path.name} calls {name}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.startswith("~"), \
                    f"{path.name} references a user home path: {node.value!r}"


def test_behaviorally_no_subprocess_no_socket_no_file_open(monkeypatch, pinned_versions) -> None:
    # Poison every side-effect entry point, then run the whole §C1 surface.
    def _boom(*args, **kwargs):
        raise AssertionError(f"forbidden side effect called: {args[0] if args else ''}")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(builtins, "open", _boom)

    from ordessa_permissions_adapters import (
        ClaudeAdapter, CodexAdapter, PiAdapter, PolicyCompileSnapshot, PolicyObservation,
        SupportEvidence,
    )
    from _permissions_adapters_helpers import make_ceiling, make_intent
    for adapter_cls in (ClaudeAdapter, CodexAdapter, PiAdapter):
        adapter = adapter_cls()
        version = pinned_versions[{"ClaudeAdapter": "claude-code",
                                   "CodexAdapter": "codex",
                                   "PiAdapter": "pi"}[adapter_cls.__name__]]
        adapter.supports(SupportEvidence.of(harness_id=adapter.harness_id,
                                            native_version=version))
        for intent in (None, make_intent(adapter.harness_id),
                        make_intent(adapter.harness_id,
                                    [{"key": "bash", "action": "deny"}])):
            adapter.compilePolicy(PolicyCompileSnapshot.of(
                harness_id=adapter.harness_id, native_version=version, intent=intent,
                ceiling=make_ceiling()))
        adapter.verifyPolicy(PolicyObservation.of(harness_id=adapter.harness_id))

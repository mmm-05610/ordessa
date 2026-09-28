"""T05 — compile purity and no-fake-apply (contracts.md §C2/§C1, FR-09).

Native-sandbox configuration compile must be pure: no network, no process
spawn, no HOME access, no key/config read or write. Enforced two ways — a
static AST gate over every module under ``src/`` and a behavioural gate that
poisons the side-effect entry points and then drives assess/compile/verify.

Allowed imports: the standard library (minus the forbidden set), the consumed
contracts (``ordessa_sandbox_api``, ``ordessa_sandbox_backend``,
``server_plugin_api`` and — since the foundation checkpoint, for the C2
descriptive edge only — ``ordessa_harness_api``) and this package. No host,
no harness CODE, no compat, no Permissions, no storage. There is NO apply
path anywhere: a refusal is a value and a compile writes no file.

One documented exception to the no-READ rule: ``points.py`` (composition-time
only) locates and reads the pinned ``harnesses.toml`` to measure
``native_versions``. No module may WRITE; assess/compile/verify keep zero
file/side-effect access (the behavioural gate below).
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import socket
import subprocess
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_sandbox_adapters"

FORBIDDEN_IMPORTS = {"subprocess", "socket", "shutil", "http", "urllib",
                     "requests", "sqlite3", "ftplib", "telnetlib", "asyncio",
                     "tempfile", "os"}
FORBIDDEN_PRODUCT_ROOTS = {"ordessa_server", "ordessa_server_compat",
                           "ordessa_harness", "pacthold", "ordessa_workspace",
                           "fastapi", "pydantic", "httpx", "uvicorn"}
ALLOWED_NON_STDLIB = {"ordessa_sandbox_api", "ordessa_sandbox_backend",
                      "server_plugin_api", "ordessa_sandbox_adapters",
                      "ordessa_harness_api", "__future__"}
FORBIDDEN_ATTR_CALLS = {"expanduser", "system", "popen", "execv", "execve",
                        "spawn", "spawnl", "spawnv",
                        "urlopen", "startfile", "kill", "mkdir", "rmdir",
                        "remove", "write_text", "write_bytes"}
#: read-side entry points allowed ONLY in the composition-time points module
READ_CALLS = {"read_text", "read_bytes", "open", "listdir", "scandir"}
READ_ALLOWED_FILE = "points.py"
STDLIB_OK = set(sys.stdlib_module_names)


def _sources():
    files = sorted(SRC_ROOT.glob("**/*.py"), key=str)
    assert files, f"no source files under {SRC_ROOT}"
    return files


def _roots(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_every_module_exists_and_is_valid_python():
    for path in _sources():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_forbidden_import():
    for path in _sources():
        roots = _roots(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for root in roots:
            assert root not in FORBIDDEN_IMPORTS, f"{path.name} imports {root!r}"
            assert root not in FORBIDDEN_PRODUCT_ROOTS, f"{path.name} imports {root!r}"
            assert root in STDLIB_OK or root in ALLOWED_NON_STDLIB, \
                f"{path.name} imports unexpected root {root!r}"


def test_no_side_effect_call_sites():
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else \
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                if name == "open":
                    assert path.name == READ_ALLOWED_FILE, \
                        f"{path.name} opens a file outside the composition-time module"
                if name in READ_CALLS:
                    assert path.name == READ_ALLOWED_FILE, \
                        f"{path.name} reads outside the composition-time module"
                assert name not in FORBIDDEN_ATTR_CALLS, f"{path.name} calls {name}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.startswith("~"), \
                    f"{path.name} references a user home path: {node.value!r}"


def test_behaviorally_no_spawn_no_socket_no_file_written(monkeypatch, pinned, tmp_path):
    from _sandbox_adapters_helpers import (
        CODEX_TARGET,
        authorized_facts,
        claude_intent,
        codex_intent,
        effect_observation,
        permissive_ceiling,
        pi_intent,
        pin,
        platform_facts,
        target_handle,
    )

    def _boom(*args, **kwargs):
        raise AssertionError("forbidden side effect during compile/verify")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(builtins, "open", _boom)

    from ordessa_sandbox_adapters import (
        ClaudeSandboxAdapter,
        CodexSandboxAdapter,
        PiSandboxAdapter,
        PiSandboxExtensionEvidence,
    )
    ext = PiSandboxExtensionEvidence.of(extension_id="sandbox-ext", loaded=True,
                                        observed_native_version="2.0")
    cases = [
        (CodexSandboxAdapter(), "codex", codex_intent(),
         authorized_facts(), pinned["codex"]),
        (ClaudeSandboxAdapter(), "claude-code", claude_intent(),
         authorized_facts(), pinned["claude-code"]),
        (PiSandboxAdapter(), "pi", pi_intent(),
         authorized_facts(pi_sandbox_extension=ext), pinned["pi"]),
    ]
    monkeypatch.chdir(tmp_path)
    for adapter, harness, intent, authorized, version in cases:
        adapter.assess(pin(harness, version), platform_facts(), authorized)
        adapter.compile(intent, target_handle(CODEX_TARGET), (permissive_ceiling(brand=harness),),
                        authorized=authorized)
        adapter.verify(effect_observation("unknown"))

    # nothing at all was written to disk by the whole surface: no fake apply
    assert list(tmp_path.rglob("*")) == []

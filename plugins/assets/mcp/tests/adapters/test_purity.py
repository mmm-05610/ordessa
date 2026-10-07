"""Purity guards for the T04 native-lane code (dispatch 需求5).

Two independent proofs:

1. **AST**: the DTO module and the brand adapters never import a filesystem /
   process / network / clock / environment capability and never call
   ``open``/``exec``/HOME-style lookups — destination paths can only come
   from injected descriptors;
2. **runtime**: the full assess/compile/verify cycle runs green while
   ``os.open``/``os.openat`` (this package's conftest) and ``socket``/
   ``subprocess`` (parent conftest) are sealed — zero side effects.
"""
import ast
from pathlib import Path

import pytest
from native_helpers import (
    DictProvenance,
    attestation,
    build_snapshot,
    claude_spec,
    instance_target,
    observed,
    observation,
    revision_provider,
    session_target,
    stdio_revision,
)

from adapters import claude, codex
from backend.definition import SecretRef

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TARGETS = [
    PACKAGE_ROOT / "backend" / "native_intents.py",
    PACKAGE_ROOT / "adapters" / "__init__.py",
    PACKAGE_ROOT / "adapters" / "common.py",
    PACKAGE_ROOT / "adapters" / "codex.py",
    PACKAGE_ROOT / "adapters" / "claude.py",
]

BANNED_IMPORT_ROOTS = {
    "os", "pathlib", "shutil", "socket", "subprocess", "tempfile", "io",
    "builtins", "importlib", "fcntl", "signal", "multiprocessing", "threading",
    "random", "time", "datetime", "platform", "getpass", "pwd", "grp",
}
BANNED_CALL_NAMES = {"open", "exec", "eval", "input"}
BANNED_ATTRS = {"environ", "getenv", "Popen", "system", "fdopen", "listdir",
                "scandir", "walk", "expanduser", "readlink", "urandom",
                "__file__"}


@pytest.mark.parametrize("path", TARGETS, ids=lambda p: str(p.name))
def test_ast_purity_no_side_effect_capabilities(path, monkeypatch):
    # this inspection itself needs the filesystem; lift the seals for the read
    monkeypatch.undo()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in BANNED_IMPORT_ROOTS, \
                    f"{path.name}:{node.lineno} imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:  # absolute only; relative intra-package is fine
                root = (node.module or "").split(".")[0]
                assert root not in BANNED_IMPORT_ROOTS, \
                    f"{path.name}:{node.lineno} imports from {node.module}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in BANNED_CALL_NAMES, \
                f"{path.name}:{node.lineno} calls {node.func.id}()"
        elif isinstance(node, ast.Attribute):
            assert node.attr not in BANNED_ATTRS, \
                f"{path.name}:{node.lineno} uses .{node.attr}"
        elif isinstance(node, ast.Name) and node.id == "__file__":
            pytest.fail(f"{path.name}:{node.lineno} resolves its own install path")


def test_full_cycle_runs_under_sealed_primitives():
    """assess + compile + verify with os.open/os.openat/socket/subprocess
    blocked by conftest fixtures: success here is the runtime purity proof."""
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a",
                         env={"TOKEN": SecretRef("cred-1")})
    snap = build_snapshot([rev], {"def-a": {"lane": "native", "enforcement": "proven"}})
    provider = revision_provider({("def-a", 1): rev})
    provenance = DictProvenance({"cred-1": attestation("cred-1")})

    verdict = claude.assess(claude_spec(), snap, revision_provider=provider)
    assert verdict.verdict == "unknown"

    plan = claude.compile(snap, instance_target("claude"), provenance,
                          revision_provider=provider)
    result = claude.verify(plan, observation(servers=[observed("alpha")]))
    assert result.facts[0].fact == "loaded"  # relayed from the injected observer

    codex_plan = codex.compile(snap, session_target("codex"), provenance,
                               revision_provider=provider)
    assert codex_plan.entries[0].native_name == "alpha"

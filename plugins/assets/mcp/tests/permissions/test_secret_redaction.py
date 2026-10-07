"""V07 gate: plaintext never escapes - container repr, deep redaction, and
the zero-file-IO module pin (FR-08, data-model "秘密与留存", counterexample 8).
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import pathlib

import pytest

from backend import secret as secret_module
from backend.errors import McpError
from backend.secret import (
    CredentialBinding,
    LaunchPlan,
    ResolvedSecrets,
    SlotProof,
    redact,
    resolve_for_launch,
)

from perms_helpers import FakeCredentialPort

ALPHA = "s3cr3t-alpha"
BETA = "s3cr3t-beta"


@pytest.fixture
def resolved():
    port = FakeCredentialPort({"cred-1": (ALPHA, "rev-1"), "cred-2": (BETA, "rev-7")})
    return resolve_for_launch(LaunchPlan(principal="alice", bindings=(
        CredentialBinding("def1", 1, "TOKEN", "cred-1", "rev-1"),
        CredentialBinding("def1", 1, "Authorization", "cred-2", "rev-7", kind="header"),
    )), port, 150.0)


def _assert_clean(blob):
    text = blob.decode() if isinstance(blob, (bytes, bytearray)) else str(blob)
    assert ALPHA not in text and BETA not in text


# -- container guarantees --------------------------------------------------------------


def test_repr_str_and_format_never_carry_plaintext(resolved):
    _assert_clean(repr(resolved))
    _assert_clean(str(resolved))
    _assert_clean(f"{resolved}")
    # but the safe identity is all there: slot + credential id + revision
    r = repr(resolved)
    assert "TOKEN" in r and "cred-1" in r and "rev-1" in r


def test_references_are_ref_only_records(resolved):
    records = resolved.references()
    assert {r["credentialId"] for r in records} == {"cred-1", "cred-2"}
    _assert_clean(json.dumps(records))
    _assert_clean(str(records))


def test_exceptions_contexts_and_event_dicts_scan_clean(resolved):
    """把解析结果塞进异常上下文/事件 dict：脱敏后字节扫描无明文."""
    exc = RuntimeError(f"launch failed while injecting {ALPHA}")
    event = {
        "message": f"injected {ALPHA} and {BETA} at once",
        "slots": [{"env": {"TOKEN": ALPHA}}, (BETA, "tail")],
        "cause": str(exc),
        b"raw": f"{ALPHA} bytes".encode(),
        ("pair", ALPHA): [BETA],
        "unrelated": "keep-me",
    }
    scrubbed = redact(event, resolved)
    _assert_clean(repr(scrubbed))
    _assert_clean(str(scrubbed))
    _assert_clean(scrubbed["message"].encode())
    # shape kept, secrets replaced, innocents untouched
    assert scrubbed["unrelated"] == "keep-me"
    assert scrubbed["message"] == "injected *** and *** at once"
    assert scrubbed["slots"][0]["env"]["TOKEN"] == "***"
    assert ("pair", "***") in scrubbed
    assert scrubbed[b"raw"] == b"*** bytes"


def test_redact_accepts_raw_value_iterables_and_single_values(resolved):
    assert redact(f"x {ALPHA} y", ALPHA) == "x *** y"
    assert redact(["a", "b"], ["b"]) == ["a", "***"]
    assert redact({"k": ALPHA}, resolved.plaintext_values())["k"] == "***"
    assert redact("nothing to see", resolved) == "nothing to see"
    assert redact({"nested": [{"deep": (BETA,)}]}, resolved) == {"nested": [{"deep": ("***",)}]}
    assert redact(42, resolved) == 42  # non-text leaves pass through untouched


def test_containers_holding_plaintext_are_not_serialisable(resolved):
    with pytest.raises(McpError):
        copy.deepcopy(resolved)
    with pytest.raises(Exception):
        import pickle
        pickle.dumps(resolved)


# -- module pin: zero file IO, no store imports (绝不写盘明文) ----------------------------

_ALLOWED_IMPORTS = {"__future__", "dataclasses", "hashlib", "typing"}
_BANNED_CALLS = {"open", "eval", "exec", "compile", "input"}
_BANNED_ATTR_CALLS = {"os", "pathlib", "socket", "subprocess", "shutil", "tempfile",
                      "pickle", "io", "fcntl", "msvcrt", "definition_store"}


def _root_module(name):
    return name.split(".")[0]


def test_secret_module_import_surface_is_closed():
    tree = ast.parse(inspect.getsource(secret_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert _root_module(alias.name) in _ALLOWED_IMPORTS, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: only the leaf .errors refusal module
                assert node.module == "errors", node.module
            else:
                assert _root_module(node.module) in _ALLOWED_IMPORTS, node.module
    assert "definition_store" not in dir(secret_module)


def test_secret_module_has_no_io_or_spawn_primitives():
    tree = ast.parse(inspect.getsource(secret_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                assert fn.id not in _BANNED_CALLS, ast.dump(node)
            elif isinstance(fn, ast.Attribute):
                base = fn
                parts = []
                while isinstance(base, ast.Attribute):
                    parts.append(base.attr)
                    base = base.value
                root = base.id if isinstance(base, ast.Name) else ""
                assert root not in _BANNED_ATTR_CALLS, f"{root}.{parts[-1] if parts else ''}"
        # plaintext must never be written via context-manager file idioms either
        if isinstance(node, ast.Attribute) and node.attr in {"write", "writelines", "mkdir",
                                                             "unlink", "rename", "save"}:
            pytest.fail(f"forbidden write-side call: .{node.attr}")


def test_secret_module_source_has_no_open_token_at_all():
    source = inspect.getsource(secret_module)
    for needle in ("open(", "Path(", "subprocess", "socket", "definition_store"):
        assert needle not in source, needle


def test_source_file_lives_read_only_in_import_check():
    # pathlib is banned inside the module; using it here (test side) to prove the
    # module was never monkey-loaded from a temp copy is intentionally not done:
    # the module file is exactly the shipped one.
    path = pathlib.Path(inspect.getfile(secret_module)).resolve()
    assert path.name == "secret.py"
    assert str(path).endswith("backend/secret.py")

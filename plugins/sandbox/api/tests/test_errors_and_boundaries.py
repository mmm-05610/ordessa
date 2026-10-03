"""Error-code set and import boundaries of the sandbox API package."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import ordessa_sandbox_api
from ordessa_sandbox_api import SandboxErrorCode

REQUIRED_CODES = {
    "SANDBOX_NATIVE_UNSUPPORTED",
    "SANDBOX_COVERAGE_UNPROVEN",
    "SANDBOX_PLATFORM_UNSUPPORTED",
    "SANDBOX_CONFIG_CONFLICT",
    "SANDBOX_EFFECT_UNKNOWN",
    "PROVIDER_BUSY",
}

SRC_ROOT = Path(ordessa_sandbox_api.__file__).parent


def test_six_stable_codes_exist_exactly_and_distinctly():
    members = {code.value for code in SandboxErrorCode}
    assert REQUIRED_CODES <= members
    values = [code.value for code in SandboxErrorCode]
    assert len(values) == len(set(values)), "codes must never be merged aliases"


def test_unsupported_and_unknown_map_to_different_codes():
    from ordessa_sandbox_api import code_for_outcome, SandboxVerificationOutcome

    assert code_for_outcome(SandboxVerificationOutcome.UNSUPPORTED) is \
        SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    assert code_for_outcome(SandboxVerificationOutcome.UNKNOWN) is \
        SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_public_exports_complete():
    assert "__all__" in vars(ordessa_sandbox_api)
    for name in ordessa_sandbox_api.__all__:
        assert getattr(ordessa_sandbox_api, name, None) is not None, name


def test_package_declares_typed_marker():
    assert (SRC_ROOT / "py.typed").exists()


def test_neutral_sandboxv1_names_are_not_used():
    # Pacthold's neutral SandboxV1/SandboxPort is a different concept; this
    # package must not carry its names nor pretend it is native isolation.
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "SandboxV1" not in text, path
        assert "SandboxPort" not in text, path


def test_src_imports_are_stdlib_or_local_only():
    forbidden_roots = {"pacthold", "ordessa_server", "ordessa_harness",
                       "ordessa_server_compat", "ordessa_sandbox", "requests",
                       "httpx"}
    stdlib = set(sys.stdlib_module_names)
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [] if node.level else [
                    (node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                if root in forbidden_roots or (root and root not in stdlib):
                    offenders.append(f"{path.name}:{root}")
    assert offenders == [], offenders


def test_tests_never_touch_real_user_config(monkeypatch, tmp_path):
    # No test or source path may read $HOME dot-configs; assert the package
    # never mentions them at all.
    forbidden = ("~/.codex", "~/.claude", "~/.pi", ".codex/config.toml")
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, (path, token)

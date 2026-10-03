"""T05 — Claude Code native-sandbox adapter: Bash/PowerShell/Monitor scope only.

Evidence: the documented sandbox scope is Bash/PowerShell/Monitor subprocesses
(harness-adapters.md Claude row; API ``ClaudeSandboxConfig.COVERABLE == {BASH}``
and the横向反例 "原生 sandbox 只罩住 Bash 却试图宣称 MCP 隔离"). Linux/WSL2
bubblewrap + macOS Seatbelt supported, native Windows unsupported, unknown OS is
`unknown` — a *different* code than `unsupported` (contracts.md §C4).
"""
from __future__ import annotations

from _sandbox_adapters_helpers import (
    CLAUDE_TARGET,
    authorized_facts,
    claude_config,
    claude_intent,
    permissive_ceiling,
    pin,
    platform_facts,
    target_handle,
)

from ordessa_sandbox_api import SandboxErrorCode, ToolCategory
from ordessa_sandbox_adapters import (
    ClaudeSandboxAdapter,
    CompileRefusal,
    CompiledIntent,
    sandbox_code_of,
)

CEILING = (permissive_ceiling(brand="claude-code"),)


def _has_no_broader_coverage_claim(result):
    for field in result.intents:
        joined = " ".join(field.field_path_segments).lower() + " " + str(field.value).lower()
        for token in ("read", "edit", "mcp", "network", "all", "coverage"):
            assert token not in joined, f"compiled field claims broader coverage: {field.field_path}"


def test_bash_only_required_coverage_compiles():
    adapter = ClaudeSandboxAdapter()
    result = adapter.compile(claude_intent(), target_handle(CLAUDE_TARGET), CEILING)
    assert isinstance(result, CompiledIntent)
    paths = {f.field_path for f in result.intents}
    assert paths <= {"bashSandbox", "powerShellSandbox", "monitorSandbox"}
    # absence, not a flag: no field asserts coverage beyond the three toggles
    _has_no_broader_coverage_claim(result)


def test_required_coverage_beyond_bash_refuses_unproven():
    adapter = ClaudeSandboxAdapter()
    for extra in (ToolCategory.READ, ToolCategory.EDIT, ToolCategory.MCP,
                  ToolCategory.NETWORK):
        intent = claude_intent(required_coverage=frozenset({ToolCategory.BASH, extra}))
        result = adapter.compile(intent, target_handle(CLAUDE_TARGET), CEILING)
        assert isinstance(result, CompileRefusal), extra
        assert result.code.value == "SANDBOX_COVERAGE_UNPROVEN"
        assert result.emitted_intents == ()


def test_adapter_never_claims_coverage_all():
    # even an empty required coverage must not fabricate a coverage=all field
    adapter = ClaudeSandboxAdapter()
    result = adapter.compile(claude_intent(required_coverage=frozenset()), target_handle(CLAUDE_TARGET), CEILING)
    assert isinstance(result, CompiledIntent)
    _has_no_broader_coverage_claim(result)


def test_linux_and_macos_supported_windows_unsupported_unknown_os_unknown():
    adapter = ClaudeSandboxAdapter()
    versions = {"linux": "6.6", "macos": "14.0", "windows": "11", "freebsd": "14"}
    results = {os_name: adapter.assess(pin("claude-code", "0.81.2"),
                                       platform_facts(os_name=os_name, os_version=v),
                                       authorized_facts())
               for os_name, v in versions.items()}
    assert results["linux"].status == "supported"
    assert results["macos"].status == "supported"
    assert results["windows"].status == "unsupported"
    assert sandbox_code_of(results["windows"].reason) is \
        SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED
    assert results["freebsd"].status == "unknown"
    assert sandbox_code_of(results["freebsd"].reason) is \
        SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    # the two are never merged: same platform status family, different stable
    # codes, and different wire families (CAPABILITY_UNSUPPORTED/OUTCOME_UNKNOWN)
    assert sandbox_code_of(results["windows"].reason) is not \
        sandbox_code_of(results["freebsd"].reason)
    from ordessa_sandbox_api.wire_family import wire_family_for
    assert wire_family_for(SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED) != \
        wire_family_for(SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN)


def test_wsl2_supported():
    adapter = ClaudeSandboxAdapter()
    r = adapter.assess(pin("claude-code", "0.81.2"),
                       platform_facts(os_name="wsl2", os_version="6.6"),
                       authorized_facts())
    assert r.status == "supported"

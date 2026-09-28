"""Shared builders for the sandbox API tests."""
from __future__ import annotations

from ordessa_sandbox_api import (
    ClaudeSandboxConfig,
    CodexSandboxConfig,
    NativeSandboxIntent,
    NetworkMode,
    PlatformFacts,
    PlatformGate,
    PiSandboxConfig,
    SandboxApplyScope,
    SandboxEvidence,
    SandboxVerificationOutcome,
    ToolCategory,
)

def codex_config(**overrides):
    base = dict(
        sandbox_mode="workspace-write",
        writable_roots=("src",),
        network_access=False,
    )
    base.update(overrides)
    return CodexSandboxConfig(**base)


def claude_config(**overrides):
    base = dict(
        enable_bash_sandbox=True,
        enable_power_shell_sandbox=False,
        enable_monitor_sandbox=False,
    )
    base.update(overrides)
    return ClaudeSandboxConfig(**base)


def pi_config(**overrides):
    base = dict(sandbox_extension="sandbox-bwrap")
    base.update(overrides)
    return PiSandboxConfig(**base)


def codex_intent(**overrides):
    base = dict(
        sandbox_id="sbx-codex-1",
        revision=1,
        harness_id="codex",
        brand="codex",
        config=codex_config(),
        read_scope=("workspace",),
        write_scope=("src",),
        network=NetworkMode.DISABLED,
        covered_categories=frozenset({ToolCategory.BASH, ToolCategory.EDIT}),
        required_coverage=frozenset({ToolCategory.BASH}),
        platform_gate=PlatformGate(allowed_os=("linux", "macos")),
        scope=SandboxApplyScope.SESSION,
        declared_impact_set=(),
    )
    base.update(overrides)
    return NativeSandboxIntent(**base)


def claude_intent(**overrides):
    base = dict(
        sandbox_id="sbx-claude-1",
        revision=1,
        harness_id="claude-code",
        brand="claude-code",
        config=claude_config(),
        read_scope=("workspace",),
        write_scope=(),
        network=NetworkMode.DISABLED,
        covered_categories=frozenset({ToolCategory.BASH}),
        required_coverage=frozenset({ToolCategory.BASH}),
        platform_gate=PlatformGate(allowed_os=("linux", "macos")),
        scope=SandboxApplyScope.SESSION,
        declared_impact_set=(),
    )
    base.update(overrides)
    return NativeSandboxIntent(**base)


def platform_facts(**overrides):
    base = dict(os_name="linux", os_version="6.6", kernel_features=("bubblewrap",))
    base.update(overrides)
    return PlatformFacts(**base)


def verified_evidence(**overrides):
    base = dict(
        server_instance_id="srv-1",
        session_id="s1",
        runtime_generation="gen-1",
        harness_id="codex",
        native_version="0.147.0",
        adapter_version="2.0",
        config_digest="sha256:aaaa",
        platform=platform_facts(),
        observed_covered_categories=frozenset({ToolCategory.BASH}),
        outcome=SandboxVerificationOutcome.VERIFIED,
        reason="controlled probe pending; verified placeholder for pure checks",
    )
    base.update(overrides)
    return SandboxEvidence(**base)

"""Shared builders for the sandbox-backend tests.

Intent/evidence builders mirror the API package's helpers; the backend adds
verification-fact and repo-data builders.
"""
from __future__ import annotations

from pathlib import Path

from ordessa_sandbox_api import (
    ClaudeSandboxConfig,
    CodexSandboxConfig,
    NativeSandboxIntent,
    NetworkMode,
    PlatformFacts,
    PlatformGate,
    SandboxApplyScope,
    SandboxEvidence,
    SandboxVerificationOutcome,
    SessionSlot,
    ToolCategory,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
HARNESSES_TOML = REPO_ROOT / "plugins/harness/src/ordessa_harness/harnesses.toml"


def repo_toml_text() -> str:
    return HARNESSES_TOML.read_text(encoding="utf-8")


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


def claude_evidence(**overrides):
    base = dict(
        server_instance_id="srv-1",
        session_id="s-a",
        runtime_generation="gen-1",
        harness_id="claude-code",
        native_version="0.81.2",
        adapter_version="0.81.2",
        config_digest="sha256:cccc",
        platform=platform_facts(),
        observed_covered_categories=frozenset({ToolCategory.BASH}),
        outcome=SandboxVerificationOutcome.VERIFIED,
        reason="probe evidence stands in for the T05 probe (blocked); "
               "facts are internally consistent with the claude/linux pin",
    )
    base.update(overrides)
    return SandboxEvidence(**base)


def codex_evidence(**overrides):
    base = dict(
        server_instance_id="srv-1",
        session_id="s-a",
        runtime_generation="gen-1",
        harness_id="codex",
        native_version="2.0",
        adapter_version="2.0",
        config_digest="sha256:cccc",
        platform=platform_facts(),
        observed_covered_categories=frozenset({ToolCategory.BASH, ToolCategory.EDIT}),
        outcome=SandboxVerificationOutcome.VERIFIED,
        reason="probe evidence stands in for the T05 probe (blocked)",
    )
    base.update(overrides)
    return SandboxEvidence(**base)


def facts(**overrides):
    """Backend VerificationFacts builder (imported lazily to keep RED clear)."""
    from ordessa_sandbox_backend import VerificationFacts

    base = dict(
        target_handle="th-codex-s-a",
        server_instance_id="srv-1",
        session_id="s-a",
        runtime_generation="gen-1",
        native_version="0.81.2",
        config_digest="sha256:cccc",
        platform_os="linux",
        platform_version="6.6",
        kernel_features=("bubblewrap",),
        adapter_available=True,
    )
    base.update(overrides)
    return VerificationFacts(**base)


def target_facts(**overrides):
    from ordessa_sandbox_backend import TargetFacts

    base = dict(
        native_version="0.81.2",
        config_digest="sha256:cccc",
        platform=platform_facts(),
        adapter_version="0.81.2",
    )
    base.update(overrides)
    return TargetFacts(**base)


def slot(session_id, **overrides):
    base = dict(session_id=session_id)
    base.update(overrides)
    return SessionSlot(**base)

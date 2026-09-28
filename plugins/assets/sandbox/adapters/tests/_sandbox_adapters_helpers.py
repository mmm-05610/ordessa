"""Shared builders for the T05 sandbox-adapter tests.

Pins are *parsed from the repository* (``harnesses.toml``), never hardcoded, so
a pin change moves the tests with it. Intents/configs are built from the
consumed ``ordessa_sandbox_api`` types (imported, never redefined). The Codex
``sandbox_mode`` vocabulary a test compares the adapter against is parsed from
the committed, version-matched App Server JSON schema (see
``CODEX_SCHEMA``) — the task's rule that the generated schema, not the docs,
is the source of accepted values.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from ordessa_sandbox_api import (
    ClaudeSandboxConfig,
    CodexSandboxConfig,
    NativeSandboxIntent,
    NetworkMode,
    PlatformFacts,
    PlatformGate,
    SandboxApplyScope,
    SandboxCeiling,
    ToolCategory,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
HARNESSES_TOML = REPO_ROOT / "plugins/harness/src/ordessa_harness/harnesses.toml"
CODEX_SCHEMA = (REPO_ROOT / "plugins/harness/adapters/acp-adapter/internal/"
                "codex/schema/codex_app_server_protocol.v2.schemas.json")


def pinned_versions() -> dict[str, str]:
    """Identity version of record per harness_type, read from the real tree."""
    data = tomllib.loads(HARNESSES_TOML.read_text(encoding="utf-8"))
    return {item["identity"]["harness_type"]: item["identity"]["version"]
            for item in data["harness"]}


def codex_schema_sandbox_modes() -> tuple[str, ...]:
    """The SandboxMode enum of the committed, version-matched Codex schema."""
    document = json.loads(CODEX_SCHEMA.read_text(encoding="utf-8"))
    return tuple(document["definitions"]["SandboxMode"]["enum"])


# --------------------------------------------------------------- platform

def platform_facts(**overrides) -> PlatformFacts:
    base = dict(os_name="linux", os_version="6.6", kernel_features=("bubblewrap",))
    base.update(overrides)
    return PlatformFacts(**base)


# -------------------------------------------------------------- ceilings

def enforce_ceiling(**overrides) -> SandboxCeiling:
    base = dict(brand="codex", enforce=True, minimum_strictness=2,
                network_allowed_max=True, required_coverage=frozenset(),
                source="signed-admin")
    base.update(overrides)
    return SandboxCeiling(**base)


def permissive_ceiling(brand: str = "codex") -> SandboxCeiling:
    return SandboxCeiling(brand=brand, enforce=False, minimum_strictness=0,
                          network_allowed_max=True, required_coverage=frozenset(),
                          source="none")


# --------------------------------------------------------------- intents

def codex_config(**overrides) -> CodexSandboxConfig:
    base = dict(sandbox_mode="workspace-write", writable_roots=("src",),
                network_access=False)
    base.update(overrides)
    return CodexSandboxConfig(**base)


def claude_config(**overrides) -> ClaudeSandboxConfig:
    base = dict(enable_bash_sandbox=True, enable_power_shell_sandbox=False,
                enable_monitor_sandbox=False)
    base.update(overrides)
    return ClaudeSandboxConfig(**base)


def codex_intent(**overrides) -> NativeSandboxIntent:
    base = dict(
        sandbox_id="sbx-codex-1", revision=1, harness_id="codex", brand="codex",
        config=codex_config(), read_scope=("workspace",), write_scope=("src",),
        network=NetworkMode.DISABLED,
        covered_categories=frozenset({ToolCategory.BASH, ToolCategory.EDIT}),
        required_coverage=frozenset({ToolCategory.BASH}),
        platform_gate=PlatformGate(allowed_os=("linux", "macos", "windows")),
        scope=SandboxApplyScope.SESSION, declared_impact_set=())
    base.update(overrides)
    return NativeSandboxIntent(**base)


def claude_intent(**overrides) -> NativeSandboxIntent:
    base = dict(
        sandbox_id="sbx-claude-1", revision=1, harness_id="claude-code",
        brand="claude-code", config=claude_config(), read_scope=("workspace",),
        write_scope=(), network=NetworkMode.DISABLED,
        covered_categories=frozenset({ToolCategory.BASH}),
        required_coverage=frozenset({ToolCategory.BASH}),
        platform_gate=PlatformGate(allowed_os=("linux", "wsl2", "macos")),
        scope=SandboxApplyScope.SESSION, declared_impact_set=())
    base.update(overrides)
    return NativeSandboxIntent(**base)


def pi_config(extension="sandbox-ext"):
    from ordessa_sandbox_api import PiSandboxConfig
    return PiSandboxConfig(sandbox_extension=extension)


def pi_intent(**overrides) -> NativeSandboxIntent:
    base = dict(
        sandbox_id="sbx-pi-1", revision=1, harness_id="pi", brand="pi",
        config=pi_config(), read_scope=("workspace",), write_scope=(),
        network=NetworkMode.DISABLED, covered_categories=frozenset(),
        required_coverage=frozenset(),
        platform_gate=PlatformGate(allowed_os=()),
        scope=SandboxApplyScope.SESSION, declared_impact_set=(),
        # the pin the real harnesses.toml records for pi — measured, not
        # guessed, so the adapter's out-of-range gate stays honest
        native_version_pin=pinned_versions()["pi"])
    base.update(overrides)
    return NativeSandboxIntent(**base)


# ---------------------------------------------------- adapter-side inputs

def target_handle(handle_id: str = "codex-config-toml", generation: int = 1):
    """The server-issued C3 target a compile is asked to bind against.

    `ordessa_harness_api.TargetHandle` is the only spelling of a config target
    after the harness-api checkpoint: this package never turns a path or a bare
    string into a handle and never invents a generation.
    """
    from ordessa_harness_api import TargetHandle
    return TargetHandle(handle_id, generation)


CODEX_TARGET = "codex-config-toml"
CLAUDE_TARGET = "claude-settings-json"
PI_TARGET = "pi-extension-target"


def authorized_facts(**overrides):
    """The adapter-side AuthorizedFacts DTO (imported lazily to keep RED clean)."""
    from ordessa_sandbox_adapters import AuthorizedFacts
    base = dict(adapter_available=True)
    base.update(overrides)
    return AuthorizedFacts(**base)


def pin(harness_id: str, native_version: str):
    from ordessa_sandbox_adapters import AdapterPin
    return AdapterPin(harness_id=harness_id, native_version=native_version)


def effect_observation(outcome, covered=(ToolCategory.BASH,), reason=""):
    from ordessa_sandbox_backend import EffectObservation
    from ordessa_sandbox_api import SandboxVerificationOutcome
    return EffectObservation(outcome=SandboxVerificationOutcome(outcome),
                             covered_categories=frozenset(covered), reason=reason)

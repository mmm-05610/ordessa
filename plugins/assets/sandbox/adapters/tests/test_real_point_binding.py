"""T05b — the brand descriptors bind the REAL Harness configuration point.

The foundation checkpoint (8844c475bc, merged) publishes
`harness.configuration-adapters` / v1 with `ConfigurationAdapterDescriptor`
payloads validated and conflict-refused by `HarnessContributionRegistry`. This
file proves the sandbox facet rides that real point: the point id/version and
the descriptor classes are the foundation's own objects (module identity, not
a copy), the pins are *measured* from `harnesses.toml`, and the payload schema
is built from the platform schema helper so a malformed payload is refused
before anything commits.
"""
from __future__ import annotations

import tomllib

import pytest
from _sandbox_adapters_helpers import HARNESSES_TOML
from ordessa_harness.contributions import (
    CONFIGURATION_POINT as REAL_CONFIGURATION_POINT,
    POINT_API_VERSION as REAL_POINT_API_VERSION,
)
from ordessa_harness.contributions import ConfigurationAdapterDescriptor as RealDescriptor
from ordessa_harness.contributions import FieldClaim as RealFieldClaim
from ordessa_harness_api import ContractError, ValueSchema
from server_plugin_api import Contribution, ContributionBatch

from ordessa_sandbox_adapters import (
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    PiSandboxAdapter,
    SANDBOX_CONFIGURATION_POINT_ID,
    SANDBOX_FACET_ID,
    SANDBOX_FACET_SCHEMA_VERSION,
    SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID,
    SANDBOX_POINT_API_VERSION,
    build_configuration_batch,
    build_configuration_descriptor,
    default_sandbox_adapters,
    HarnessSandboxConfigurationAdapter,
    pinned_harness_versions,
)


def _descriptors():
    return {d.adapter_id: d for d in (build_configuration_descriptor(a)
                                      for a in default_sandbox_adapters())}


# ------------------------------------------------------- real-point identity
def test_point_id_and_api_version_are_the_foundation_ones():
    # the package spells the point as literals (third-party shape); this is the
    # symbol-level check that those literals ARE the real point's constants.
    assert SANDBOX_CONFIGURATION_POINT_ID == REAL_CONFIGURATION_POINT
    assert SANDBOX_POINT_API_VERSION == REAL_POINT_API_VERSION
    assert REAL_CONFIGURATION_POINT == "harness.configuration-adapters"


def test_descriptors_use_the_foundation_class_not_a_private_copy():
    descriptor = build_configuration_descriptor(CodexSandboxAdapter())
    # `ordessa_harness.contributions` re-exports the point's payload contract;
    # building with it must yield the very object the host's handler isinstance-
    # checks against (module identity, same class object).
    assert isinstance(descriptor, RealDescriptor)
    assert descriptor.claims
    assert all(isinstance(claim, RealFieldClaim) for claim in descriptor.claims)
    assert isinstance(descriptor.payload_schema, ValueSchema)


# --------------------------------------------------------- harnesses.toml pins
def test_pinned_versions_are_measured_from_harnesses_toml():
    document = tomllib.loads(HARNESSES_TOML.read_text(encoding="utf-8"))
    expected = {item["identity"]["harness_type"]: item["identity"]["version"]
                for item in document["harness"]}
    pinned = pinned_harness_versions()
    for harness_id in ("codex", "claude-code", "pi"):
        assert harness_id in expected  # the toml really names the brand
        assert pinned[harness_id] == expected[harness_id]


def test_native_versions_are_the_exact_measured_pins():
    pinned = pinned_harness_versions()
    for descriptor, harness in ((build_configuration_descriptor(CodexSandboxAdapter()), "codex"),
                                (build_configuration_descriptor(ClaudeSandboxAdapter()), "claude-code"),
                                (build_configuration_descriptor(PiSandboxAdapter()), "pi")):
        assert descriptor.harness_id == harness
        pin = _semver(pinned[harness])
        # the descriptor claims exactly the pin the toml records, nothing wider
        assert descriptor.native_versions.minimum == pin
        assert descriptor.native_versions.maximum == pin


def _semver(text: str) -> tuple[int, int, int]:
    core = text.split("-", 1)[0].split("+", 1)[0]
    parts = [int(p) for p in core.split(".")]
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


# ------------------------------------------------------------- facet shape
def test_facet_identity_is_the_sandbox_native_configuration():
    assert SANDBOX_FACET_ID == "sandbox.native-configuration"
    assert f"{SANDBOX_FACET_ID}@{SANDBOX_FACET_SCHEMA_VERSION}" == \
        SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID
    for descriptor in _descriptors().values():
        assert descriptor.facet_id == SANDBOX_FACET_ID
        assert descriptor.facet_schema_version == SANDBOX_FACET_SCHEMA_VERSION
        assert descriptor.api_version == "v1"
        # §C4: owner/generation are host-assigned; the author payload never
        # carries one and the registry refuses one that does.
        assert not hasattr(descriptor, "owner")
        assert not hasattr(descriptor, "generation")


def test_codex_descriptor_owns_its_measured_native_fields():
    codex = _descriptors()["sandbox.native-config.codex"]
    assert set(codex.entries) == {"sandbox_mode", "sandbox_workspace_write"}
    assert set(codex.entries) == set(CodexSandboxAdapter().native_field_claims())
    paths = {claim.field_path for claim in codex.claims}
    assert paths == {("sandbox_mode",), ("sandbox_workspace_write",)}
    assert all(claim.target_kind == "file" and claim.target_id
               for claim in codex.claims)


def test_claude_descriptor_owns_only_the_toggles_it_can_write():
    claude = _descriptors()["sandbox.native-config.claude-code"]
    assert set(claude.entries) == {"bashSandbox", "powerShellSandbox", "monitorSandbox"}
    assert {claim.field_path for claim in claude.claims} == {
        ("bashSandbox",), ("powerShellSandbox",), ("monitorSandbox",)}
    # the Bash-only scope never claims a read/edit/MCP native field
    assert not any("read" in part or "edit" in part or "mcp" in part
                   for claim in claude.claims for part in claim.field_path)


def test_pi_descriptor_claims_nothing_and_states_absence():
    pi = _descriptors()["sandbox.native-config.pi"]
    # NO native field claims: Pi's sandbox is an optional extension, so the
    # contribution reserves nothing and its payload schema admits nothing.
    assert pi.claims == ()
    assert pi.entries  # the descriptor requires at least one entry name
    with pytest.raises(ContractError):
        pi.payload_schema.validate({"sandbox_extension": "anything"})


# ------------------------------------------------- platform payload refusal
def test_payload_schemas_refuse_malformed_payloads():
    codex = _descriptors()["sandbox.native-config.codex"]
    # valid shape round-trips
    codex.payload_schema.validate({"sandbox_mode": "workspace-write",
                                   "writable_roots": ["src"],
                                   "network_access": False})
    # a loosening posture is outside the closed enum → refused by the platform
    with pytest.raises(ContractError):
        codex.payload_schema.validate({"sandbox_mode": "danger-full-access"})
    # §C2: no arbitrary shell/path writes — unknown keys are refused
    with pytest.raises(ContractError):
        codex.payload_schema.validate({"sandbox_mode": "read-only",
                                       "shell": "/bin/bash -c 'rm -rf /'"})
    claude = _descriptors()["sandbox.native-config.claude-code"]
    claude.payload_schema.validate({"bashSandbox": True})
    with pytest.raises(ContractError):
        claude.payload_schema.validate({"coverage": "all"})


# ---------------------------------------------------------- contribution wire
def test_batch_carries_three_real_contributions_on_the_open_point():
    batch = build_configuration_batch()
    assert isinstance(batch, ContributionBatch)
    assert SANDBOX_CONFIGURATION_POINT_ID in batch.open_points
    assert len(batch.contributions) == 3
    for item in batch.contributions:
        assert isinstance(item, Contribution)
        assert item.point_id == REAL_CONFIGURATION_POINT
        assert item.api_version == REAL_POINT_API_VERSION
        assert isinstance(item.payload, HarnessSandboxConfigurationAdapter)
        assert isinstance(item.payload.descriptor, RealDescriptor)
        assert all(callable(getattr(item.payload, name)) for name in ("assess", "compile", "verify"))
        assert item.required is False

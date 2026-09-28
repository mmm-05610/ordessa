"""T03b: the real Harness public point is the sole composition authority.

The package no longer admits its own contributions: it *declares* them.
Every `permissions.policy-adapters` brand ships as a
`Contribution(point_id="harness.configuration-adapters", api_version="v1",
payload=<ConfigurationAdapterDescriptor>)` on the plugin registration, and
admission (shape, duplicate/overlap refusal, field-claim conflict, owner
injection) belongs to `ordessa_harness.contributions` + the Server host
(`server_plugin_api` staging protocol). This file pins the DECLARE side;
`test_real_admission_lifecycle.py` pins the ADMIT side against the real
registry and host.

Design refs: docs/design/safety-controls/contracts.md §C1/§C2/§C4,
docs/design/safety-controls/verification.md gates 2/3.
"""
from __future__ import annotations

import re
import tomllib

import pytest
from ordessa_harness_api import (ConfigurationAdapterDescriptor, ContractError,
                                 FieldClaim, ValueSchema, VersionRange)
from server_plugin_api import Contribution, ContributionBatch

import ordessa_permissions_adapters as adapters

REAL_POINT = "harness.configuration-adapters"
REAL_API_VERSION = "v1"
FACET = "permissions.policy-adapters"

BRAND_TO_DRIVER = {"claude-code": "claude", "codex": "codex", "pi": "pi"}


def _descriptor(adapter_id: str) -> ConfigurationAdapterDescriptor:
    for item in adapters.default_configuration_descriptors():
        if item.adapter_id == adapter_id:
            return item
    raise AssertionError(f"no configuration descriptor contributed for {adapter_id!r}")


def _pin_tuple(text: str) -> tuple[int, int, int]:
    core = re.split(r"[-+]", text.strip(), maxsplit=1)[0]
    parts = [int(p) for p in core.split(".")]
    return tuple((parts + [0] * 3)[:3])


# ------------------------------------------------------------------ the batch

def test_registration_declares_contributions_on_the_real_point() -> None:
    batch = adapters.policy_adapter_contributions()
    assert isinstance(batch, ContributionBatch)
    assert len(batch.contributions) == 3
    for item in batch.contributions:
        assert isinstance(item, Contribution)
        assert item.point_id == adapters.CONFIGURATION_POINT == REAL_POINT
        assert item.api_version == adapters.POINT_API_VERSION == REAL_API_VERSION
        assert isinstance(item.payload, adapters.PolicyConfigurationAdapter)
        assert isinstance(item.payload.descriptor, ConfigurationAdapterDescriptor)
        assert item.payload.descriptor.facet_id == adapters.FACET_ID == FACET
        assert callable(item.payload.assess)
        assert callable(item.payload.compile)
        assert callable(item.payload.verify)
    # three contributions share one point: the batch must declare it open,
    # otherwise the platform's own duplicate guard refuses (see next test).
    assert REAL_POINT in batch.open_points


def test_batch_without_open_points_is_refused_by_the_platform() -> None:
    items = tuple(adapters.policy_adapter_contributions().contributions)
    with pytest.raises(Exception) as error:
        ContributionBatch(items)  # open_points not declared
    assert type(error.value).__name__ == "DuplicateContributionError"


def test_descriptor_constants_match_the_public_harness_module() -> None:
    # drift guard against the platform's public contribution seam (the same
    # module the product composition binds; test-only import, never src).
    from ordessa_harness.contributions import (
        CONFIGURATION_POINT, POINT_API_VERSION, RUNTIME_POINT)
    assert adapters.CONFIGURATION_POINT == CONFIGURATION_POINT
    assert adapters.POINT_API_VERSION == POINT_API_VERSION
    # this package contributes configuration descriptors only - never a
    # runtime adapter on the runtime point.
    assert adapters.CONFIGURATION_POINT != RUNTIME_POINT


# ---------------------------------------------------------------- pins (drift)

def test_native_versions_are_the_pins_measured_in_harnesses_toml(families) -> None:
    # The claim compiled into each descriptor must equal the identity version
    # recorded in the real registry file; a silent pin bump fails this test
    # and forces an explicit claim update.
    for harness, driver in BRAND_TO_DRIVER.items():
        pin = families[harness]["identity"]["version"]
        descriptor = _descriptor(f"permissions.policy-adapter.{driver if driver != 'claude' else 'claude-code'}")
        assert descriptor.native_versions.minimum == _pin_tuple(pin)
        assert descriptor.native_versions.maximum == _pin_tuple(pin)
        assert descriptor.native_versions.contains(_pin_tuple(pin)) is True


def test_pinned_claims_table_is_consistent_with_descriptors() -> None:
    for harness, pin in adapters.PINNED_NATIVE_VERSIONS.items():
        descriptor = next(d for d in adapters.default_configuration_descriptors()
                          if d.harness_id == harness)
        assert descriptor.native_versions.minimum == _pin_tuple(pin), harness


# ------------------------------------------------------------- entries/claims

def test_claude_descriptor_claims_the_measured_permission_paths() -> None:
    descriptor = _descriptor("permissions.policy-adapter.claude-code")
    assert descriptor.entries == ("permissions.ask", "permissions.deny")
    assert descriptor.claims == (
        FieldClaim("file", ".claude/settings.json", ("permissions", "ask")),
        FieldClaim("file", ".claude/settings.json", ("permissions", "deny")),
    )


def test_codex_descriptor_claims_only_the_approval_field() -> None:
    # posture_config measures `sandbox_mode` + `approval_policy` as writable;
    # §C2 pre-allocation gives `sandbox_mode` to the Sandbox facet, so the
    # permissions projection claims only what it genuinely owns.
    descriptor = _descriptor("permissions.policy-adapter.codex")
    assert set(descriptor.entries) == {"sandbox_mode", "approval_policy"}
    assert descriptor.claims == (
        FieldClaim("file", ".codex/config.toml", ("approval_policy",)),
    )


def test_pi_descriptor_is_extension_backed_and_claims_nothing() -> None:
    descriptor = _descriptor("permissions.policy-adapter.pi")
    assert descriptor.claims == ()
    assert set(descriptor.entries) == {
        "toolCallGate.extensionId", "toolCallGate.ask", "toolCallGate.deny"}
    # no FieldClaim anywhere in the pi descriptor: an extension gate is not a
    # native config field.
    assert all(isinstance(c, FieldClaim) for c in descriptor.claims)


# ------------------------------------------------------------ payload schema

def test_payload_schemas_are_real_value_schemas(families) -> None:
    for descriptor in adapters.default_configuration_descriptors():
        assert isinstance(descriptor.payload_schema, ValueSchema)
        assert descriptor.payload_schema.kind == "object"
        assert descriptor.payload_schema.additional_properties is False
        # every claimed field path names a schema'd property (dotted spelling)
        for claim in descriptor.claims:
            dotted = ".".join(claim.field_path)
            assert dotted in dict(descriptor.payload_schema.properties)


def test_out_of_shape_facet_payload_is_refused_by_the_platform_schema() -> None:
    descriptor = _descriptor("permissions.policy-adapter.claude-code")
    # in shape: the closed object accepts only the two measured arrays
    descriptor.payload_schema.validate(
        {"permissions.ask": ["Bash"], "permissions.deny": []})
    # out of shape: a loosening knob (`permissions.allow`) is NOT in the
    # schema - the platform's ValueSchema refuses, not our code.
    with pytest.raises(ContractError):
        descriptor.payload_schema.validate({"permissions.allow": ["Bash"]})
    with pytest.raises(ContractError):
        descriptor.payload_schema.validate({"permissions.ask": "Bash"})


def test_descriptor_shape_guards_are_platform_side() -> None:
    # an empty-entries descriptor (a "claim nothing natively" cheat) is
    # refused by the platform dataclass, before any registry sees it.
    with pytest.raises(ContractError):
        ConfigurationAdapterDescriptor(
            "permissions.policy-adapter.fake", "v1", FACET, "v1", "codex",
            VersionRange((2, 0, 0)), VersionRange((1, 0, 0)), (),
            ValueSchema("object"), ())


# ------------------------------------------------------- no second authority

def test_package_exposes_no_private_admission_authority() -> None:
    # The private registry that used to duplicate the platform's duplicate/
    # overlap refusal is gone; nothing importable re-implements it.
    for name in ("PolicyAdapterRegistry", "build_policy_adapters_contribution",
                 "default_registry", "PolicyAdapterContribution",
                 "DuplicateAdapterIdError", "OverlappingRangeError",
                 "RegistryConflictError"):
        assert not hasattr(adapters, name), name

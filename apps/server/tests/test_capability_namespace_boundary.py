"""Two capability namespaces that must never be projected into each other.

Work Core answers "may I ask this ExecutionProvider for this operation?" with
`ExecutionProvider.capabilities()` and `ExtensionRegistry.require_capability`,
whose keys are Work Core operation names (`streaming`, `cancel`, `approvals`).

The Harness capability contract answers a different question - "what can this
harness do, as declared and observed?" - with the canonical abilities in
`resource_contracts.harness_capabilities`. This file pins the separation: the
operation keys are not canonical abilities, no canonical surface may expose
them, and `require_capability` is exercised as the live consumer of its own
vocabulary (so calling it dead code is not an option).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from pacthold_runtime_compat.resource_contracts import harness_capabilities as caps
from ordessa_server_compat.execution.sidecar_backend import _CoreSidecarProvider
from pacthold.work_core.registry import CapabilityUnsupported, ExtensionRegistry


REPO = Path(__file__).resolve().parents[3]
#: The Work Core operation vocabulary the sidecar provider declares today.
WORK_CORE_OPERATIONS = ("streaming", "cancel", "approvals")


def test_the_work_core_operation_keys_are_not_canonical_abilities():
    """They answer a different question, and the contract would refuse them."""
    assert not set(WORK_CORE_OPERATIONS) & set(caps.CANONICAL_CAPABILITY_IDS)
    with pytest.raises(caps.CapabilityDeclarationError) as refused:
        caps.validate_claims({name: True for name in WORK_CORE_OPERATIONS})
    assert refused.value.code == caps.CAPABILITY_UNKNOWN_ID


def test_require_capability_is_the_consumer_of_the_operation_vocabulary():
    """A live SPI contract, not dead code: it refuses and it admits."""
    registry = ExtensionRegistry()
    # The provider only needs a backend to exist for this contract question; the
    # capability mapping itself touches nothing else.
    provider = _CoreSidecarProvider(backend=None)
    registry.register_execution_provider(provider)

    admitted = registry.require_capability("harness-sidecar", "streaming")
    assert admitted is provider
    assert provider.capabilities() == {name: "supported" for name in WORK_CORE_OPERATIONS}
    with pytest.raises(CapabilityUnsupported):
        registry.require_capability("harness-sidecar", "teleport")


def test_no_canonical_surface_exposes_a_work_core_operation_key():
    """Ceilings, effective views and the wire namespace stay canonical."""
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry

    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "fixture", capability_claims={"stream": True, "attach": True},
    ))
    static_view = registry.capability_view("fixture")
    ids = {item["id"] for item in static_view["capabilities"]}
    assert ids == set(caps.CANONICAL_CAPABILITY_IDS)
    assert not ids & set(WORK_CORE_OPERATIONS)

    profile_view = registry.claims_for("fixture")
    assert set(profile_view) <= set(caps.CANONICAL_CAPABILITY_IDS)
    assert not set(profile_view) & set(WORK_CORE_OPERATIONS)

    # The wire namespace (server.hello) is a third vocabulary again: method ids.
    handlers = (REPO / "apps" / "server" / "src" / "ordessa_server" / "wire" / "handlers.py").read_text(
        encoding="utf-8")
    wire_ids = set(re.findall(r'"([a-z][A-Za-z]*\.[A-Za-z]+)"', handlers))
    assert not wire_ids & set(WORK_CORE_OPERATIONS)
    assert not wire_ids & set(caps.CANONICAL_CAPABILITY_IDS)


def test_a_deployment_cannot_declare_a_work_core_operation():
    """The deployment seat belongs to the Harness contract, so the keys fail."""
    for operation in WORK_CORE_OPERATIONS:
        with pytest.raises(caps.CapabilityDeclarationError) as refused:
            caps.validate_claims({operation: True})
        assert refused.value.code == caps.CAPABILITY_UNKNOWN_ID


def test_the_sidecar_backend_declares_the_boundary_in_code():
    """The docstring is part of the evidence: it names both namespaces."""
    source = (REPO / "plugins" / "server-compat" / "src" / "ordessa_server_compat"
              / "execution" / "sidecar_backend.py").read_text(encoding="utf-8")
    marker = "Work Core execution-provider operation contract"
    assert marker in source
    window = source[source.index(marker):source.index(marker) + 1200]
    assert "canonical" in window and "capabilityClaims" in window

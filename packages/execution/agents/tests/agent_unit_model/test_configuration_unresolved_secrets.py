"""Unresolved SecretRefs never reach configuration owners.

The existing owner/SQLite fixture is controlled and records only whether an
apply effect was called. SecretRefs here are valid opaque identities, not
secret values and not permission to resolve borrowed material.
"""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_ROOT / "docs/implementation/agent-tools/evidence/agent-unit-model"))

# Register fixture dependencies in this module; pytest does not inherit the
# fixture visibility of an imported fixture module.
from agent_tools_fixtures.node_publication import setup as node_fixture, Provider  # noqa: F401
from agent_tools_fixtures.management import setup, explicit_capabilities  # noqa: F401
from test_apply_profile import _base_ref, _profile

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.operations import node_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.configuration.contracts import (
    ApplicationPolicy,
    ConfigurationUnsupported,
)
from ordessa_units.configuration.service import CONFIGURATION_ATTEMPTS


def _secret_ref():
    return {
        "ref": "vault:fixture-model-key",
        "revision": "rotation-7",
        "owner_namespace": "fixture",
        "access_purpose": "model",
    }


def _secret_payload(shape):
    reference = _secret_ref()
    if shape == "mapping":
        return {"modelId": "new", "auth": {"credential": {"secretRef": reference}}}
    if shape == "list":
        return {"modelId": "new", "auth": [{"credential": {"secretRef": reference}}]}
    raise AssertionError(shape)


def _secret_declaration(declaration_id, requirement, shape):
    return {
        "declarationId": declaration_id,
        "configurationKind": "model",
        "schemaVersion": "1",
        "action": "value",
        "requirement": requirement,
        "payload": _secret_payload(shape),
    }


def _provider_with_received_changes(parts):
    store, env, _, service, node, *_ = parts
    binding = service._nodes.read(node)["binding"]
    provider = env.agent_runtime_contribution(binding["harnessDefinitionRef"]).provider
    original = provider.apply_configuration
    received = []

    def record(unit_ref, change, context):
        received.append(change.to_dict())
        return original(unit_ref, change, context)

    provider.apply_configuration = record
    return received


def _effect_baseline(parts):
    store, _, _, service, node, _, _, state, _, _, issuer = parts
    holder = node_holder("env", node.instance_id, node.generation)
    return {
        "fences": store.list_domain("env", CONFIGURATION_ATTEMPTS),
        "usages": store.read_usages("env", holder),
        "calls": state["calls"],
        "issued": len(issuer._issued),
    }


def _assert_no_reservation_or_effect(parts, request, baseline):
    store, _, _, _, node, _, _, state, _, _, issuer = parts
    holder = node_holder("env", node.instance_id, node.generation)
    assert store.read_operation(request) is None
    assert store.read_operation_step(request, "configuration-apply") is None
    assert store.list_domain("env", CONFIGURATION_ATTEMPTS) == baseline["fences"]
    assert store.read_usages("env", holder) == baseline["usages"]
    assert state["calls"] == baseline["calls"] == 0
    assert len(issuer._issued) == baseline["issued"]


@pytest.mark.parametrize("shape", ["mapping", "list"])
def test_required_nested_secret_ref_is_refused_before_reserve_or_apply(setup, shape):
    parts = setup
    request = RequestKey("env", "principal", f"required-secret-{shape}")
    declaration = _secret_declaration(f"required-secret-{shape}", "required", shape)
    change = replace(parts[6], request_id=request.request_id, declarations=(declaration,))
    baseline = _effect_baseline(parts)

    with pytest.raises(ConfigurationUnsupported):
        parts[3].apply(request, parts[4], change)

    _assert_no_reservation_or_effect(parts, request, baseline)


def test_apply_profile_required_nested_secret_ref_is_refused_before_reserve(setup):
    parts = setup
    # Preserve the base declaration's id/kind/schema so the change reaches
    # the unresolved-material gate instead of the separate omission refusal.
    declaration = _secret_declaration("model", "required", "list")
    _, profile = _profile(parts, declarations=(declaration,), name="profile-required-secret")
    request = RequestKey("env", "principal", "apply-profile-required-secret")
    baseline = _effect_baseline(parts)

    with pytest.raises(ConfigurationUnsupported):
        parts[3].apply_profile(request, parts[4], profile.current_revision,
            "native-1", ApplicationPolicy(), base_profile_ref=_base_ref(parts))

    _assert_no_reservation_or_effect(parts, request, baseline)


@pytest.mark.parametrize("shape", ["mapping", "list"])
def test_optional_nested_secret_ref_is_skipped_named_and_not_sent_to_owner(setup, shape):
    parts = setup
    store, _, _, service, node, _, original_change, *_ = parts
    request = RequestKey("env", "principal", f"optional-secret-{shape}")
    optional = _secret_declaration(f"optional-secret-{shape}", "optional", shape)
    change = replace(original_change, request_id=request.request_id,
                     declarations=original_change.declarations + (optional,))
    received = _provider_with_received_changes(parts)

    operation = service.apply(request, node, change)
    replay = service.apply(request, node, change)

    assert operation.status == "published" and replay == operation
    assert parts[7]["calls"] == 1 and len(received) == 1
    assert [item["declarationId"] for item in received[0]["declarations"]] == ["model"]
    assert "secretRef" not in safe_json(received[0])
    assert safe_json({"value": operation.intent.context_ref["change"]}) == safe_json(
        {"value": change.to_dict()})
    assert safe_json({"value": operation.intent.context_ref["effectiveDeclarations"]}) == safe_json(
        {"value": [change.to_dict()["declarations"][0]]})
    assert tuple(operation.intent.context_ref["skippedOptional"]) == (optional["declarationId"],)
    result = operation.result["configurationResult"]
    assert result["overallOutcome"] == "partial"
    assert {item["declarationId"]: item["outcome"] for item in result["itemResults"]} == {
        "model": "applied", optional["declarationId"]: "rejected"
    }


def test_required_resource_ref_still_refuses_before_reserve_or_apply(setup):
    parts = setup
    request = RequestKey("env", "principal", "required-resource-regression")
    declaration = parts[6].to_dict()["declarations"][0]
    declaration["resourceRefs"] = [{
        "environmentNamespace": "env",
        "resourceId": "borrowed-model-material",
    }]
    change = replace(parts[6], request_id=request.request_id, declarations=(declaration,))
    baseline = _effect_baseline(parts)

    with pytest.raises(ConfigurationUnsupported):
        parts[3].apply(request, parts[4], change)

    _assert_no_reservation_or_effect(parts, request, baseline)


def test_optional_resource_ref_remains_named_and_not_sent_to_owner(setup):
    parts = setup
    store, _, _, service, node, _, original_change, *_ = parts
    request = RequestKey("env", "principal", "optional-resource-regression")
    optional = {
        "declarationId": "optional-resource-regression",
        "configurationKind": "model",
        "schemaVersion": "1",
        "action": "value",
        "requirement": "optional",
        "payload": {},
        "resourceRefs": [{
            "environmentNamespace": "env",
            "resourceId": "borrowed-model-material",
        }],
    }
    change = replace(original_change, request_id=request.request_id,
                     declarations=original_change.declarations + (optional,))
    received = _provider_with_received_changes(parts)

    operation = service.apply(request, node, change)

    assert operation.status == "published" and parts[7]["calls"] == 1
    assert len(received) == 1
    assert [item["declarationId"] for item in received[0]["declarations"]] == ["model"]
    assert "resourceRefs" not in safe_json(received[0])
    assert safe_json({"value": operation.intent.context_ref["change"]["declarations"][-1]}) == safe_json(
        {"value": optional})
    assert safe_json({"value": operation.intent.context_ref["effectiveDeclarations"]}) == safe_json(
        {"value": [operation.intent.context_ref["change"]["declarations"][0]]})
    assert tuple(operation.intent.context_ref["skippedOptional"]) == (optional["declarationId"],)
    result = operation.result["configurationResult"]
    assert result["overallOutcome"] == "partial"
    assert {item["declarationId"]: item["outcome"] for item in result["itemResults"]} == {
        "model": "applied", optional["declarationId"]: "rejected"
    }

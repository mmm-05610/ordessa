"""Minimal ownerless reads of the original principal's operation metadata."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_ROOT / "products/agent-tools/tests/integration"))
sys.path.insert(0, str(_ROOT / "docs/implementation/agent-tools/evidence/agent-unit-model"))

# Register dependencies explicitly; pytest does not inherit another module's fixtures.
from test_node_publication import setup as node_fixture  # noqa: F401
from test_management import setup, explicit_capabilities  # noqa: F401
from test_lifecycle import lifecycle as history_lifecycle  # noqa: F401

from ordessa_environment_api import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    RequestKey,
)
from ordessa_environment_api.identity import ParticipantInstanceRef
from ordessa_environment_api.operations import (
    OperationIntent,
    StepIntent,
    operation_holder,
    safe_json,
)
from pacthold.agents.nodes.publication import encode_node_ref
from pacthold.agents.public import OperationNotFound, agent_services


def _services(parts):
    return agent_services(parts[1], invocation_issuer=parts[-1])


def _reserved_preparation(parts, *, request_id="metadata-preparation", principal="principal",
                          kind="agent-preparation"):
    store, env, _, _, published_node, *_ = parts
    node = ParticipantInstanceRef(env.environment_id, "planned-node", 1)
    published = parts[3]._nodes.read(published_node)
    provider_ref = published["binding"]["harnessProviderRef"]
    request = RequestKey(env.environment_id, principal, request_id)
    operation_ref = "prepare-metadata-" + request_id
    intent = OperationIntent(
        operation_ref,
        kind,
        published["lineage"]["profileSnapshotRef"],
        {"environmentNamespace": env.environment_id,
         "contextCanary": "INTENT-CONTEXT-CANARY",
         "preparationRequest": {"requestId": request_id}},
        (StepIntent("prepare", provider_ref, "input-digest-" + request_id,
                    "correlation-" + request_id),),
        encode_node_ref(node),
    )
    store.reserve_operation(request, "digest-" + request_id, intent)
    return request, operation_ref, intent


def _state(parts, request, intent):
    store, env = parts[0], parts[1]
    return (
        store.read_operation(request),
        tuple(store.read_operation_step(request, step.step_id) for step in intent.steps),
        store.read_usages(env.environment_id,
                          operation_holder(request, intent.operation_ref)),
    )


def test_reads_published_configuration_as_six_immutable_fields_without_owner_access(setup, monkeypatch):
    parts = setup
    store, env, _, _, node, request, change, state, _, _, issuer = parts
    services = _services(parts)
    declaration = dict(change.to_dict()["declarations"][0])
    declaration["payload"] = {"modelId": "INTENT-AND-CONTEXT-CANARY"}
    change = replace(change, declarations=(declaration,))
    operation = services.configuration.apply(request, node, change)
    assert operation.status == "published"

    step_before = store.read_operation_step(request, "configuration-apply")
    operation_before = store.read_operation(request)
    usages_before = store.read_usages(
        env.environment_id, operation_holder(request, operation.intent.operation_ref)
    )
    owner_calls = (state["calls"], state["queryCalls"], len(issuer._issued))

    def owner_must_not_be_resolved(*_args, **_kwargs):
        raise AssertionError("metadata read consulted the runtime provider")

    monkeypatch.setattr(env, "agent_runtime_contribution", owner_must_not_be_resolved)
    projection = services.operations.read(operation.intent.operation_ref)

    assert set(projection) == {
        "operationRef", "kind", "revision", "status", "nodeRef", "hasResult"
    }
    assert projection["operationRef"] == operation.intent.operation_ref
    assert projection["kind"] == "configuration-change"
    assert projection["revision"] == operation.revision
    assert projection["status"] == "published"
    assert projection["nodeRef"] == operation.intent.node_ref
    assert projection["hasResult"] is True
    assert "CANARY" not in safe_json(projection)
    with pytest.raises(TypeError):
        projection["status"] = "unknown"

    assert store.read_operation(request) == operation_before
    assert store.read_operation_step(request, "configuration-apply") == step_before
    assert store.read_usages(
        env.environment_id, operation_holder(request, operation.intent.operation_ref)
    ) == usages_before
    assert (state["calls"], state["queryCalls"], len(issuer._issued)) == owner_calls


def test_reserved_preparation_reads_its_planned_node_without_claiming_publication(setup):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(parts)
    services = _services(parts)
    before = _state(parts, request, intent)

    assert services.nodes.read(
        ParticipantInstanceRef("env", "planned-node", 1)
    ) is None
    projection = services.operations.read(operation_ref)

    assert dict(projection) == {
        "operationRef": operation_ref,
        "kind": "agent-preparation",
        "revision": 1,
        "status": "reserved",
        "nodeRef": encode_node_ref(ParticipantInstanceRef("env", "planned-node", 1)),
        "hasResult": False,
    }
    assert _state(parts, request, intent) == before


def test_nonpreparation_operation_cannot_read_an_absent_target_node(setup):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(
        parts, request_id="missing-configuration-node", kind="configuration-change"
    )
    services = _services(parts)

    with pytest.raises(GuaranteeUnavailableError):
        services.operations.read(operation_ref)
    assert _state(parts, request, intent)[0].status == "reserved"


def test_unknown_preparation_metadata_reads_do_not_query_or_advance(setup):
    parts = setup
    store, env = parts[0], parts[1]
    request, operation_ref, intent = _reserved_preparation(
        parts, request_id="metadata-unknown"
    )
    digest = "digest-metadata-unknown"
    claimed = store.claim_operation_step(request, digest, intent.steps[0])
    assert claimed.claimed is True
    store.record_operation_step(request, digest, "prepare", intent.steps[0].input_digest,
                                claimed.step.revision, "unknown", {})
    services = _services(parts)
    before = _state(parts, request, intent)

    first = services.operations.read(operation_ref)
    second = services.operations.read(operation_ref)

    assert first == second
    assert first["status"] == "unknown" and first["hasResult"] is False
    assert _state(parts, request, intent) == before
    assert env._store.read_usages(env.environment_id,
                                  operation_holder(request, operation_ref)) == ()


def test_canaries_in_intent_evidence_and_result_never_enter_projection(setup):
    parts = setup
    store, env = parts[0], parts[1]
    published = parts[3]._nodes.read(parts[4])
    request = RequestKey("env", "principal", "metadata-canary-result")
    operation_ref = "canary-result-operation"
    digest = "canary-result-digest"
    evidence_canary = "EVIDENCE-CANARY"
    result_canary = "RESULT-CANARY"
    intent = OperationIntent(
        operation_ref, "history-only-fixture", None,
        {"environmentNamespace": env.environment_id,
         "contextCanary": "CONTEXT-CANARY"},
        (StepIntent("inspect", published["binding"]["harnessProviderRef"],
                    "canary-input-digest", "canary-correlation"),),
    )
    store.reserve_operation(request, digest, intent)
    claim = store.claim_operation_step(request, digest, intent.steps[0])
    store.record_operation_step(request, digest, "inspect", intent.steps[0].input_digest,
                                claim.step.revision, "concluded",
                                {"evidenceCanary": evidence_canary})
    operation = store.read_operation(request)
    operation = store.publish_operation(request, digest, operation.revision,
                                        ("inspect",), (), (),
                                        {"resultCanary": result_canary})
    services = _services(parts)
    before = _state(parts, request, intent)

    projection = services.operations.read(operation_ref)

    assert projection["hasResult"] is True
    assert set(projection) == {
        "operationRef", "kind", "revision", "status", "nodeRef", "hasResult"
    }
    assert not any(canary in safe_json(projection) for canary in (
        "CONTEXT-CANARY", evidence_canary, result_canary
    ))
    assert _state(parts, request, intent) == before


def test_operation_acl_denial_happens_before_identity_lookup(setup, monkeypatch):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(parts)
    services = _services(parts)
    policy = parts[2]
    identity_reads = []
    original = parts[0].read_domain

    def record_domain_read(environment, namespace, record_id):
        if namespace == "core.operation-identities":
            identity_reads.append(record_id)
        return original(environment, namespace, record_id)

    monkeypatch.setattr(parts[0], "read_domain", record_domain_read)
    monkeypatch.setattr(policy, "admit_object_access", lambda principal, target, action:
                        not (target == f"env:operation:{operation_ref}" and action == "read"))

    with pytest.raises(AdmissionRefusedError):
        services.operations.read(operation_ref)

    assert identity_reads == []
    assert _state(parts, request, intent)[0].status == "reserved"


def test_node_acl_denial_hides_a_bound_operation_like_an_absent_operation(setup, monkeypatch):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(parts)
    services = _services(parts)
    policy = parts[2]
    planned_target = "env:agents.node:planned-node"
    monkeypatch.setattr(policy, "admit_object_access", lambda principal, target, action:
                        target != planned_target)

    with pytest.raises(OperationNotFound) as denied:
        services.operations.read(operation_ref)
    with pytest.raises(OperationNotFound) as missing:
        services.operations.read("missing-under-node-denial")
    assert type(denied.value) is type(missing.value)

    assert _state(parts, request, intent)[0].status == "reserved"


def test_foreign_principal_operation_is_indistinguishable_from_absent(setup):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(
        parts, request_id="foreign-operation", principal="other-principal"
    )
    services = _services(parts)

    with pytest.raises(OperationNotFound):
        services.operations.read(operation_ref)
    with pytest.raises(OperationNotFound):
        services.operations.read("missing-operation-ref")
    assert _state(parts, request, intent)[0].status == "reserved"


def test_damaged_identity_holder_is_unverifiable_not_projected(setup, monkeypatch):
    parts = setup
    request, operation_ref, intent = _reserved_preparation(parts)
    services = _services(parts)
    original = parts[0].read_domain

    def damaged(environment, namespace, record_id):
        result = original(environment, namespace, record_id)
        if namespace == "core.operation-identities" and record_id == operation_ref:
            holder = dict(result["value"]["holder"])
            holder["operationId"] = "different-operation"
            return {**result, "value": {"holder": holder}}
        return result

    monkeypatch.setattr(parts[0], "read_domain", damaged)
    with pytest.raises(GuaranteeUnavailableError):
        services.operations.read(operation_ref)
    assert _state(parts, request, intent)[0].status == "reserved"


def test_released_node_history_remains_readable_without_runtime_provider(history_lifecycle, monkeypatch):
    lifecycle, _, provider, node_ref, _, env, store, request, _, _ = history_lifecycle
    lifecycle.release(request, node_ref, {})
    operation = store.read_operation(request)
    services = agent_services(env, invocation_issuer=lifecycle._issuer)
    holder = {"kind": "node", "environmentNamespace": env.environment_id,
              "instanceId": node_ref.instance_id, "generation": node_ref.generation}
    usage_before = store.read_usages(env.environment_id, holder)
    assert usage_before and all(row["state"] == "released" for row in usage_before)
    provider_calls = tuple(provider.lifecycle_calls)

    def retired_provider(*_args, **_kwargs):
        raise AssertionError("historical operation read resolved a retired provider")

    monkeypatch.setattr(env, "agent_runtime_contribution", retired_provider)
    projection = services.operations.read(operation.intent.operation_ref)

    assert projection["kind"] == "agent-release"
    assert projection["status"] == "running"
    assert store.read_operation(request) == operation
    assert store.read_usages(env.environment_id, holder) == usage_before
    assert tuple(provider.lifecycle_calls) == provider_calls

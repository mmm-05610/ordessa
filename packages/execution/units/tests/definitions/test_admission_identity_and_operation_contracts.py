"""Unit-owned admission identities and original operation record wire shape."""
import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.admission_identity import (
    AdmissionNamespace,
    AgentNodeRef,
    MaterialProviderActivationRef,
)
from ordessa_units.definitions.operations import OperationIntent, StepIntent, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.definitions.staged_operations import OperationRecipePhase


def test_admission_identity_preserves_namespace_and_participant_fields():
    assert AdmissionNamespace("env.alpha").value == "env.alpha"
    ref = AgentNodeRef("env.alpha", "agent-1", 3)
    assert (ref.environment, ref.instance_id, ref.generation) == (
        "env.alpha", "agent-1", 3
    )
    with pytest.raises(ValueError):
        AgentNodeRef("env.alpha", "agent-1", True)
    activation = MaterialProviderActivationRef("env.alpha", "resource.host", 4)
    assert (activation.environment, activation.plugin_id, activation.generation) == (
        "env.alpha", "resource.host", 4
    )


def test_operation_intent_keeps_the_original_serialized_field_names():
    request = RequestKey("env.alpha", "local", "request-1")
    step = StepIntent("prepare", {"providerId": "local"}, "input-digest", "prepare-1")
    intent = OperationIntent(
        "operation-1", "unit-prepare", None,
        {"environmentNamespace": "env.alpha"}, (step,),
    )
    assert intent.to_dict() == {
        "operationRef": "operation-1",
        "kind": "unit-prepare",
        "profileSnapshotRef": None,
        "contextRef": {"environmentNamespace": "env.alpha"},
        "steps": [{
            "stepId": "prepare",
            "pinnedProviderRef": {"providerId": "local"},
            "inputDigest": "input-digest",
            "recoveryCorrelation": "prepare-1",
            "prerequisiteSteps": [],
            "managementEpoch": 0,
        }],
        "nodeRef": None,
        "managementEpoch": 0,
    }
    assert OperationIntent.from_dict(intent.to_dict()) == intent
    assert safe_json(intent.to_dict()) == (
        '{"contextRef":{"environmentNamespace":"env.alpha"},'
        '"kind":"unit-prepare","managementEpoch":0,"nodeRef":null,'
        '"operationRef":"operation-1","profileSnapshotRef":null,'
        '"steps":[{"inputDigest":"input-digest","managementEpoch":0,'
        '"pinnedProviderRef":{"providerId":"local"},"prerequisiteSteps":[],'
        '"recoveryCorrelation":"prepare-1","stepId":"prepare"}]}'
    )
    assert operation_holder(request, "operation-1") == {
        "kind": "operation",
        "environmentNamespace": "env.alpha",
        "principalScope": "local",
        "requestId": "request-1",
        "operationId": "operation-1",
    }


def test_recipe_phase_round_trip_preserves_original_contract_fields():
    step = StepIntent("release", {"providerId": "local"}, "input", "release-1")
    phase = OperationRecipePhase(
        "cleanup-1",
        (step,),
        {
            "release": {
                "action": "release",
                "targetRef": {"environmentNamespace": "env.alpha"},
                "delegationRef": None,
                "cleanup": True,
            }
        },
        {"reason": "confirmed-stop"},
    )
    decoded = OperationRecipePhase.from_dict(phase.to_dict())
    assert decoded == phase
    assert decoded.to_dict() == {
        "phaseId": "cleanup-1",
        "steps": [step.to_dict()],
        "invocationBindings": {
            "release": {
                "action": "release",
                "targetRef": {"environmentNamespace": "env.alpha"},
                "delegationRef": None,
                "cleanup": True,
            }
        },
        "contextFacts": {"reason": "confirmed-stop"},
    }
    assert len(decoded.digest) == 64

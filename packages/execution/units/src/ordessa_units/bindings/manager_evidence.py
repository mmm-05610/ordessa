"""Read-only projections from the original UnitManager/UnitRecords owners."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from ordessa_execution_api.environment import GuaranteeUnavailableError, IdentityMismatchError
from ordessa_execution_api.environment.operations import (
    UsageMutation, operation_holder, safe_json, sealed_mapping,
)
from ordessa_units.lifecycle.unit_lifecycle import same_reference
from ordessa_units.management.instance import UnitInstance


def _plain(value):
    return json.loads(safe_json(value))


def _digest(value):
    return "sha256:" + hashlib.sha256(safe_json(value).encode("utf-8")).hexdigest()


def _request_ref(request):
    return {"environmentNamespace": request.environment_namespace,
            "principalScope": request.principal_scope,
            "requestId": request.request_id}


def _record_correlation(operation, step):
    return safe_json({"request": _request_ref(operation.request),
                      "operationRef": operation.intent.operation_ref,
                      "stepId": step.step_id})


def _owner_ref(environment, provider, source_revision, ref):
    if (not isinstance(source_revision, str) or not source_revision
            or not isinstance(ref, str) or not ref):
        raise GuaranteeUnavailableError("original Unit evidence reference unavailable")
    return sealed_mapping({"environmentNamespace": environment,
                           "ownerProviderRef": provider,
                           "sourceRevision": source_revision,
                           "ref": ref})


class UnitOwnerEvidence:
    """Re-read exact Unit, session, and termination facts; never keeps outcomes."""

    def __init__(self, manager):
        from ordessa_units.management.manager import UnitManager
        if type(manager) is not UnitManager:
            raise TypeError("original UnitManager required")
        self._manager = manager
        self._records = manager.records

    @property
    def manager(self):
        return self._manager

    def _unit_ref_from(self, reply):
        if type(reply) is UnitInstance:
            return reply.prepared_unit["unitRef"], reply
        if not isinstance(reply, Mapping):
            raise GuaranteeUnavailableError("original Unit reply unavailable")
        value = reply.get("unitRef")
        if value is None and isinstance(reply.get("preparedUnit"), Mapping):
            value = reply["preparedUnit"].get("unitRef")
        if not isinstance(value, Mapping):
            raise GuaranteeUnavailableError("original Unit reference unavailable")
        return value, None

    def _unit(self, operation, step, reply):
        unit_ref, replied_unit = self._unit_ref_from(reply)
        unit = self._manager.find(unit_ref)
        if replied_unit is not None and replied_unit is not unit:
            raise IdentityMismatchError("reply is not the manager's original Unit")
        owner = self._records.owner_read_unit(unit_ref["unitId"])
        facts = owner.facts
        if (not same_reference(owner.public_ref, unit_ref)
                or not same_reference(unit_ref, unit.prepared_unit["unitRef"])
                or not same_reference(facts.get("providerRef"), step.pinned_provider_ref)
                or not same_reference(facts.get("nodeRef"), operation.intent.node_ref)
                or facts.get("managementEpoch") != step.management_epoch
                or facts.get("inputDigest") != step.input_digest
                or facts.get("correlation") != _record_correlation(operation, step)):
            raise IdentityMismatchError("original Unit facts differ from reserved operation step")
        prepared = unit.prepared_agent
        if (prepared is None
                or prepared.profile_revision != safe_json(operation.intent.profile_snapshot_ref)
                or not prepared.harness.resources.applied):
            raise GuaranteeUnavailableError("original prepared resources/Profile revision unavailable")
        descriptor = getattr(unit.descriptor, "definition_ref", None)
        if (not isinstance(descriptor, Mapping)
                or descriptor.get("environmentNamespace") != operation.request.environment_namespace):
            raise GuaranteeUnavailableError("original Harness definition pin unavailable")
        return unit, owner, facts, prepared, _plain(descriptor)

    def _prepare_observation(self, operation, step, reply):
        from ordessa_units.bindings.assembly import PreparationObservation
        unit, owner, facts, prepared, definition_ref = self._unit(operation, step, reply)
        if step.step_id != "prepare":
            raise IdentityMismatchError("preparation observation requested for another step")
        provider = facts["providerRef"]
        evidence_ref = _owner_ref(
            operation.request.environment_namespace, provider,
            owner.public_ref["sourceRevision"],
            _digest({"unitRef": owner.public_ref, "facts": {
                key: facts[key] for key in
                ("providerRef", "nodeRef", "managementEpoch", "inputDigest", "correlation")},
                "profileRevision": prepared.profile_revision,
                "resourcesApplied": prepared.harness.resources.applied}))
        usage = UsageMutation(
            operation.intent.operation_ref + ".unit", 0, None,
            operation_holder(operation.request, operation.intent.operation_ref),
            owner.public_ref, ("use",), "active")
        return PreparationObservation(step.step_id, provider, step.input_digest,
            step.recovery_correlation, evidence_ref, {"unitRef": owner.public_ref}, (usage,))

    def _session_observation(self, operation, step, reply):
        from ordessa_units.bindings.assembly import PreparationObservation
        unit_ref, _ = self._unit_ref_from(reply)
        prepare_step = next((item for item in operation.intent.steps if item.step_id == "prepare"), None)
        if (prepare_step is None or step.step_id != "start"
                or not same_reference(step.pinned_provider_ref, prepare_step.pinned_provider_ref)
                or step.input_digest != prepare_step.input_digest
                or step.management_epoch != prepare_step.management_epoch):
            raise IdentityMismatchError("start step differs from original prepared Unit scope")
        unit, owner, facts, prepared, _ = self._unit(operation, prepare_step, {"unitRef": unit_ref})
        session = self._records.owner_read_session(unit_ref["unitId"])
        expected = _record_correlation(operation, step)
        native = session.native_facts
        if (step.step_id != "start" or session.state != "confirmed"
                or session.creation_correlation != expected
                or not isinstance(native, Mapping)
                or not isinstance(native.get("evidenceRef"), str)
                or not native["evidenceRef"]):
            raise GuaranteeUnavailableError("original confirmed Unit session evidence unavailable")
        if isinstance(reply, Mapping) and reply.get("unitRef") is not None \
                and not same_reference(reply["unitRef"], owner.public_ref):
            raise IdentityMismatchError("start reply changed the original Unit reference")
        evidence_ref = _owner_ref(operation.request.environment_namespace,
            facts["providerRef"], str(session.source_revision), native["evidenceRef"])
        return PreparationObservation(step.step_id, facts["providerRef"], step.input_digest,
            step.recovery_correlation, evidence_ref, {"unitRef": owner.public_ref}, ())

    def observe(self, operation, step, reply):
        if step.step_id == "prepare":
            return self._prepare_observation(operation, step, reply)
        if step.step_id == "start":
            return self._session_observation(operation, step, reply)
        return self._stop_observation(operation, step, reply)

    def _stop_observation(self, operation, step, reply):
        from ordessa_units.lifecycle.service import LifecycleObservation
        if operation.intent.kind not in ("agent-stop", "agent-release") or step.step_id not in ("stop", "release"):
            raise GuaranteeUnavailableError("unsupported original Unit lifecycle observation")
        action = step.step_id
        if operation.intent.kind != "agent-" + action:
            raise GuaranteeUnavailableError("unsupported original Unit lifecycle observation")
        unit_ref, _ = self._unit_ref_from(reply)
        unit = self._manager.find(unit_ref)
        owner = self._records.owner_read_unit(unit_ref["unitId"])
        facts = owner.facts
        expected_correlation = _record_correlation(operation, step)
        record = self._records.owner_read_termination(unit_ref["unitId"], action)
        if (not same_reference(owner.public_ref, unit_ref)
                or not same_reference(facts.get("providerRef"), step.pinned_provider_ref)
                or not same_reference(facts.get("nodeRef"), operation.intent.node_ref)
                or facts.get("managementEpoch") != step.management_epoch
                or record is None or record.get("state") != "confirmed"
                or record.get("identity", {}).get("action") != action
                or record.get("identity", {}).get("correlation") != expected_correlation
                or record.get("identity", {}).get("inputDigest") != step.input_digest
                or not same_reference(record.get("identity", {}).get("unitRef"), owner.public_ref)
                or not isinstance(record.get("outcome"), Mapping)
                or not record["outcome"]):
            raise GuaranteeUnavailableError("original confirmed stop record unavailable")
        if isinstance(reply, Mapping) and (
                reply.get("action") != action or reply.get("state") != "confirmed"
                or not same_reference(reply.get("unitRef"), owner.public_ref)
                or not same_reference(reply.get("outcome"), record["outcome"])):
            raise IdentityMismatchError("stop reply differs from original UnitRecords outcome")
        provider = facts["providerRef"]
        evidence_ref = _owner_ref(operation.request.environment_namespace, provider,
            str(record["sourceRevision"]), record["outcome"].get("terminationEvidenceRef"))
        return LifecycleObservation(step.step_id, provider, step.input_digest,
            step.recovery_correlation, evidence_ref, termination=record)

    def inspect(self, operation, steps):
        from ordessa_units.bindings.publication import NodePublicationEvidence
        if operation.intent.kind != "agent-preparation" or len(steps) != len(operation.intent.steps):
            raise GuaranteeUnavailableError("complete original preparation steps required")
        observations = []
        unit = None
        owner = None
        facts = None
        prepared = None
        definition_ref = None
        for stored, intent in zip(steps, operation.intent.steps):
            if (stored is None or stored.outcome != "concluded"
                    or not same_reference(stored.intent.to_dict(), intent.to_dict())):
                raise GuaranteeUnavailableError("original concluded preparation step unavailable")
            observed = self.observe(operation, stored.intent, stored.evidence)
            if (not same_reference(stored.evidence.get("evidenceRef"), observed.evidence_ref)
                    or not same_reference(stored.evidence.get("preparedUnit"), observed.prepared_unit)):
                raise IdentityMismatchError("stored preparation evidence differs from original Unit owner")
            observations.append(observed)
            if intent.step_id == "prepare":
                unit_ref = observed.prepared_unit["unitRef"]
                unit, owner, facts, prepared, definition_ref = self._unit(
                    operation, intent, {"unitRef": unit_ref})
        if unit is None or owner is None or facts is None or prepared is None:
            raise GuaranteeUnavailableError("original prepared Unit unavailable")
        session = self._records.owner_read_session(owner.unit_ref)
        if session.state != "confirmed" or not isinstance(session.native_facts, Mapping):
            raise GuaranteeUnavailableError("original confirmed session unavailable for publication")
        access = unit.describe_access(owner.public_ref)
        if not same_reference(access.get("unitRef"), owner.public_ref):
            raise IdentityMismatchError("access surface differs from original Unit")
        safe_access = {"protocol": access.get("protocol"),
                       "leaseRequired": access.get("leaseRequired"),
                       "fullNativeSideEffects": access.get("fullNativeSideEffects"),
                       "readonlySupported": access.get("readonlySupported")}
        if any(value is None for value in safe_access.values()):
            raise GuaranteeUnavailableError("safe original Unit access surface unavailable")
        access_ref = _owner_ref(operation.request.environment_namespace, facts["providerRef"],
            str(session.source_revision), _digest({"unitRef": owner.public_ref,
                "sessionEvidenceRef": session.native_facts.get("evidenceRef"),
                "access": safe_access}))
        native_ref = _owner_ref(operation.request.environment_namespace, facts["providerRef"],
            str(session.source_revision), session.native_facts.get("evidenceRef"))
        binding = {
            "nodeRef": _plain(operation.intent.node_ref),
            "operationRef": operation.intent.operation_ref,
            "harnessProviderRef": _plain(facts["providerRef"]),
            "harnessDefinitionRef": definition_ref,
            "harnessUnitRef": _plain(owner.public_ref),
            "profileSnapshotRef": _plain(operation.intent.profile_snapshot_ref),
            "preparationContextRef": _plain(operation.intent.context_ref),
            "configurationTargetRef": _plain(owner.configuration_target_ref),
            "nativeSessionRefs": (native_ref,),
        }
        sources = tuple({"stepId": intent.step_id,
                         "providerRef": _plain(intent.pinned_provider_ref),
                         "inputDigest": intent.input_digest,
                         "recoveryCorrelation": intent.recovery_correlation,
                         "evidenceRef": _plain(observed.evidence_ref)}
                        for intent, observed in zip(operation.intent.steps, observations))
        return NodePublicationEvidence(facts["providerRef"], binding, sources, (access_ref,))


__all__ = ["UnitOwnerEvidence"]

"""Authorized material read handoff and consumption-evidence release gate.

This module coordinates the freeze's "authorized read / consumption evidence"
handoff (material-authorized-handoff-freeze-v1): a designated consumer host
reads an already-acquired material through the original provider, and the
copyComplete release gate accepts release only on owner-verified consumption
evidence. It follows ``material_operations.py``'s ``_gate``/``_check_result``
patterns, builds no separate execution ledger, and never relays material
bodies — only pointers, digests and safe evidence.

Semantics frozen by the handoff freeze:

- read is its own action, never "query" (§2/§6.4): a read ticket cannot serve
  as a query receipt lookup and a query ticket cannot authorize a read. Read
  replay of a recorded step revalidates fixed facts and admission and returns
  the durable pointer-only record; it issues no ticket and never re-resolves.
- The consumer pin is an admission-side copy (§1): never self-reported. The
  admitted-consumer evidence port supplies the expected copy; comparison is
  field-wise (``_pin_equal`` style); missing port, unknown consumer, mismatch,
  cross-environment and different-generation pins are all refused. The port is
  the seam for B's Registry query; tests use a controlled fixture (freeze §5:
  controlled fixture stands in for the absent B interface; no fabricated
  configuration-consumer admission).
- Consumption holds iff MaterialConsumptionEvidence is verified against the
  owner ticket (§3): the evidence must bind the durable, owner-verified read
  step (success is only persisted after ``verified_consumption``) and match
  admission-side consumer facts. Read success alone is never consumption.
- Release (§4): the release trio and the "release"+cleanup binding family are
  reused; the new gate conditions decide hold vs proceed. copyComplete accepts
  only with owner-verified consumption evidence; runtimeRequired needs proven
  stop/replace evidence (Node lifecycle, not wired this slice → hold); dynamic
  is A-route-bound (separately bound → hold). Missing owner evidence keeps the
  hold and lists the remaining conditions.
- Cold recovery is NOT_RUN: no rehydrate seam is claimed; same-generation
  consumer pins only (the registered gap makes different generations refused).
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    UnknownResultError,
)
from ordessa_execution_api.environment.identity import ActivationRef
from ordessa_execution_api.environment.operations import (
    OperationStorePort,
    OperationRevisionConflict,
    StepRecord,
    UsageMutation,
    operation_holder,
    safe_json,
)

from ordessa_units.admission.material_contracts import MaterialContractError
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_units.bindings.material_operations import (
    AGENT_MATERIAL_OPERATION_CONTRACT_VERSION,
    MaterialOperations,
    env_principal,
    material_invocation_target,
    material_provider_ref,
)
from ordessa_units.bindings.materials import (
    MaterialCorrelation,
    MaterialConsumerPin,
    MaterialConsumptionEvidence,
    MaterialProviderPin,
    MaterialUseTarget,
    MaterialEvidenceRef,
    MaterialLifetime,
    MaterialObjectRef,
    MaterialOutcome,
    MaterialReadResult,
    MaterialReceipt,
    MaterialReleaseReceipt,
    MaterialReleaseRequest,
    MaterialReleaseResult,
    MaterialRequest,
    ResourceMaterialDescriptor,
)


AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION = "agent-material-consumption/1"

READ_ACTION = "read"
RELEASE_ACTION = "release"


def _fail(message: str = "material consumption facts are invalid") -> None:
    raise IdentityMismatchError(message)


def _plain(value):
    """Normalize sealed recipe mappings to plain JSON-safe dicts.

    Operation context values are sealed (MappingProxyType); every envelope
    field must round-trip through safe_json before closed-dict parsing,
    mirroring material_operations' recipe handling.
    """
    import json as _json
    return _json.loads(safe_json(value))


def _consumer_pin_equal(left: MaterialConsumerPin, right: MaterialConsumerPin) -> bool:
    """Field-wise admission-side copy comparison (``_pin_equal`` pattern)."""
    return (left.consumer_id == right.consumer_id
            and left.consumer_version == right.consumer_version
            and left.owner_activation.environment == right.owner_activation.environment
            and left.owner_activation.plugin_id == right.owner_activation.plugin_id
            and left.owner_activation.generation == right.owner_activation.generation)


def _activation_data(value: ActivationRef) -> dict[str, Any]:
    if type(value) is not ActivationRef:
        _fail()
    return {"environmentNamespace": value.environment,
            "pluginId": value.plugin_id, "generation": value.generation}


def _consumer_pin_data(value: MaterialConsumerPin) -> dict[str, Any]:
    if type(value) is not MaterialConsumerPin:
        _fail()
    return {"consumerId": value.consumer_id, "consumerVersion": value.consumer_version,
            "ownerActivation": _activation_data(value.owner_activation)}


def _object_ref_data(value: MaterialObjectRef) -> dict[str, Any]:
    if type(value) is not MaterialObjectRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "materialId": value.material_id, "revision": value.revision}


def _evidence_ref_data(value: MaterialEvidenceRef) -> dict[str, Any]:
    if type(value) is not MaterialEvidenceRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "referenceId": value.reference_id, "revision": value.revision}


def _acquisition_evidence_data(value: Mapping[str, Any]) -> dict[str, Any]:
    """The §1 handoff field set: four pointer items, no body."""
    value = _plain(value)
    if (type(value) is not dict
            or set(value) != {"immutableMaterialRef", "contentDigest", "evidenceRef", "provenanceRef"}):
        _fail("handoff acquisition evidence is invalid")
    try:
        immutable = MaterialObjectRef.from_dict(value["immutableMaterialRef"])
        evidence = MaterialEvidenceRef.from_dict(value["evidenceRef"])
        provenance = MaterialEvidenceRef.from_dict(value["provenanceRef"])
        content_digest = value["contentDigest"]
    except (TypeError, ValueError, KeyError, AttributeError):
        _fail("handoff acquisition evidence is invalid")
    return {"immutableMaterialRef": _object_ref_data(immutable),
            "contentDigest": content_digest,
            "evidenceRef": _evidence_ref_data(evidence),
            "provenanceRef": _evidence_ref_data(provenance)}


def _descriptor_data(value: ResourceMaterialDescriptor) -> dict[str, Any]:
    if type(value) is not ResourceMaterialDescriptor:
        _fail()
    return {"resourceRef": {"environmentNamespace": value.resource_ref.environment_namespace,
                            "providerId": value.resource_ref.provider_id,
                            "contractId": value.resource_ref.contract_id,
                            "resourceId": value.resource_ref.resource_id,
                            "revision": value.resource_ref.revision},
            "materialType": value.material_type, "schemaVersion": value.schema_version,
            "contentDigest": value.content_digest, "lifetime": value.lifetime.value,
            "accessMode": value.access_mode.value,
            "provenanceRef": _evidence_ref_data(value.provenance_ref),
            "evidenceRef": _evidence_ref_data(value.evidence_ref)}


def _read_result_data(value) -> dict[str, Any]:
    if type(value) is not MaterialReadResult:
        _fail("provider material read result is invalid")
    return {"outcome": value.outcome.value,
            "correlation": {"operationRef": value.correlation.operation_ref,
                            "stepId": value.correlation.step_id,
                            "recoveryCorrelation": value.correlation.recovery_correlation,
                            "inputDigest": value.correlation.input_digest},
            "immutableMaterialRef": None if value.immutable_material_ref is None
            else _object_ref_data(value.immutable_material_ref),
            "contentDigest": value.content_digest,
            "evidenceRef": None if value.evidence_ref is None
            else _evidence_ref_data(value.evidence_ref),
            "errorCode": value.error_code}


def _read_result_snapshot(value) -> MaterialReadResult:
    if type(value) is not MaterialReadResult or type(value.outcome) is not MaterialOutcome:
        _fail("provider material read result is invalid")
    try:
        return MaterialReadResult.from_dict(_read_result_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail("provider material read result is invalid")


def _release_result_data(value) -> dict[str, Any]:
    if type(value) is not MaterialReleaseResult:
        _fail("provider material release result is invalid")
    receipt = value.receipt
    return {"outcome": value.outcome.value,
            "correlation": {"operationRef": value.correlation.operation_ref,
                            "stepId": value.correlation.step_id,
                            "recoveryCorrelation": value.correlation.recovery_correlation,
                            "inputDigest": value.correlation.input_digest},
            "receipt": None if receipt is None else {
                "leaseRef": {"leaseId": receipt.lease_ref.lease_id,
                             "resourceRef": {"environmentNamespace": receipt.lease_ref.resource_ref.environment_namespace,
                                             "providerId": receipt.lease_ref.resource_ref.provider_id,
                                             "contractId": receipt.lease_ref.resource_ref.contract_id,
                                             "resourceId": receipt.lease_ref.resource_ref.resource_id,
                                             "revision": receipt.lease_ref.resource_ref.revision},
                             "providerPin": _pin_data(receipt.lease_ref.provider_pin),
                             "target": _target_data(receipt.lease_ref.target),
                             "acquisitionCorrelation": {"operationRef": receipt.lease_ref.acquisition_correlation.operation_ref,
                                                        "stepId": receipt.lease_ref.acquisition_correlation.step_id,
                                                        "recoveryCorrelation": receipt.lease_ref.acquisition_correlation.recovery_correlation,
                                                        "inputDigest": receipt.lease_ref.acquisition_correlation.input_digest}},
                "correlation": {"operationRef": receipt.correlation.operation_ref,
                                "stepId": receipt.correlation.step_id,
                                "recoveryCorrelation": receipt.correlation.recovery_correlation,
                                "inputDigest": receipt.correlation.input_digest},
                "evidenceRef": _evidence_ref_data(receipt.evidence_ref)},
            "errorCode": value.error_code}


def _release_result_snapshot(value) -> MaterialReleaseResult:
    if type(value) is not MaterialReleaseResult or type(value.outcome) is not MaterialOutcome:
        _fail("provider material release result is invalid")
    try:
        return MaterialReleaseResult.from_dict(_release_result_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail("provider material release result is invalid")


def _pin_data(value) -> dict[str, Any]:
    if type(value) is not MaterialProviderPin:
        _fail()
    return {"providerId": value.provider_id, "providerVersion": value.provider_version,
            "ownerActivation": _activation_data(value.owner_activation)}


def _target_data(value) -> dict[str, Any]:
    if type(value) is not MaterialUseTarget:
        _fail()
    return {"nodeRef": {"environmentNamespace": value.node_ref.environment,
                        "instanceId": value.node_ref.instance_id,
                        "generation": value.node_ref.generation},
            "directoryBindingRef": {"environmentNamespace": value.directory_binding_ref.environment_namespace,
                                    "bindingId": value.directory_binding_ref.binding_id,
                                    "bindingRevision": value.directory_binding_ref.binding_revision,
                                    "contentDigest": value.directory_binding_ref.content_digest},
            "managementEpoch": value.management_epoch, "purpose": value.purpose}


@runtime_checkable
class AdmittedConsumerEvidence(Protocol):
    """Admission-side trusted consumer evidence (B Registry query seam).

    Returns the admission-side copied ``MaterialConsumerPin`` for a claimed
    consumer identity, or None when the consumer is not admitted. The expected
    value semantics is "admission-side copy", never caller-supplied (freeze §1).
    """

    def admitted_consumer_pin(self, consumer_id: str, consumer_version: str) -> MaterialConsumerPin | None: ...


@dataclass(frozen=True)
class MaterialReleaseGateDecision:
    """Outcome of the §4 release gate: accepted-and-released or held."""

    released: bool
    remaining: tuple[str, ...]
    step_record: StepRecord | None = None


class MaterialConsumption:
    """Coordinate authorized material read handoffs and the release gate."""

    def __init__(self, environment, *, invocation_issuer: InvocationIssuer | None = None,
                 admitted_consumer: AdmittedConsumerEvidence | None = None):
        self._environment = environment
        from ordessa_units.admission.material_admission import MaterialAdmission
        self._material_admission = MaterialAdmission(environment)
        self._issuer = invocation_issuer
        self._admitted_consumer = admitted_consumer

    # ------------------------------------------------------------------ gates

    def _gate(self, request: RequestKey):
        env = self._environment
        if type(request) is not RequestKey:
            raise IdentityMismatchError("complete material consumption request identity required")
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("material consumption principal differs from this Environment")
            self._material_admission._admit_resource_metadata_read()
        store = env._store
        if not isinstance(store, OperationStorePort):
            raise GuaranteeUnavailableError("same-Environment operation Store is unavailable")
        if not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not store:
            raise InvocationAuthorityRefused("same-Store InvocationIssuer is required")
        return store

    def _read_operation(self, store, request: RequestKey, operation_digest: str):
        if type(operation_digest) is not str or not operation_digest:
            raise IdentityMismatchError("fixed material consumption operation digest is required")
        operation = store.read_operation(request)
        if operation is None:
            raise UnknownResultError("material consumption operation is not reserved")
        if operation.digest != operation_digest:
            raise IdentityMismatchError("material consumption operation digest differs from its reservation")
        return operation

    @staticmethod
    def _consumer_pin_gate(consumer_pin: MaterialConsumerPin, admitted_consumer,
                           material_request: MaterialRequest) -> None:
        if admitted_consumer is None:
            raise GuaranteeUnavailableError("admission-side consumer evidence is unavailable")
        try:
            admitted = admitted_consumer.admitted_consumer_pin(
                consumer_pin.consumer_id, consumer_pin.consumer_version)
        except Exception:
            raise GuaranteeUnavailableError("admission-side consumer evidence is unavailable") from None
        if admitted is None:
            raise AdmissionRefusedError("consumer is not admitted on the admission side")
        if not _consumer_pin_equal(consumer_pin, admitted):
            raise AdmissionRefusedError("consumer pin is not an admission-side copy")
        if (consumer_pin.owner_activation.environment
                != material_request.resource_ref.environment_namespace):
            _fail("consumer pin crosses Environment identity")

    def _provider(self, material_request: MaterialRequest):
        env = self._environment
        pin = material_request.provider_pin
        try:
            metadata, provider = self._material_admission._material_provider_for_operation(
                material_request.resource_ref.provider_id,
                material_request.resource_ref.contract_id,
                pin.provider_version,
                pin.owner_activation,
            )
        except (AdmissionRefusedError, GuaranteeUnavailableError):
            raise
        except Exception:
            raise GuaranteeUnavailableError("admitted material provider is unavailable") from None
        if (metadata.resource_provider.descriptor.id != material_request.resource_ref.provider_id
                or metadata.resource_provider.descriptor.version != pin.provider_version
                or metadata.resource_provider.owner_activation != pin.owner_activation
                or material_request.resource_ref.contract_id not in metadata.resource_provider.supported_contract_ids):
            raise AdmissionRefusedError("material provider pin or contract changed")
        return metadata, provider

    @staticmethod
    def _check_lifetime(metadata, descriptor: ResourceMaterialDescriptor) -> None:
        if descriptor.lifetime not in metadata.capability.lifetimes:
            raise GuaranteeUnavailableError("material provider does not support the fixed resource lifetime")

    @staticmethod
    def _check_descriptor(provider, principal: str, material_request: MaterialRequest,
                          descriptor: ResourceMaterialDescriptor) -> None:
        try:
            described = provider.describe_material(material_request.resource_ref, principal)
            snapshot = ResourceMaterialDescriptor.from_dict(_descriptor_data(described))
        except Exception:
            raise GuaranteeUnavailableError("material provider description is unavailable") from None
        if safe_json(_descriptor_data(snapshot)) != safe_json(_descriptor_data(descriptor)):
            raise AdmissionRefusedError("material provider descriptor differs from its fixed facts")

    @staticmethod
    def _check_read_result(result: MaterialReadResult, material_request: MaterialRequest,
                           acquisition_evidence: Mapping[str, Any]) -> None:
        if result.correlation != material_request.correlation:
            _fail("material read result correlation differs")
        if result.outcome is MaterialOutcome.SUCCESS:
            if (result.immutable_material_ref is None or result.content_digest is None
                    or result.evidence_ref is None or result.error_code is not None):
                _fail("material read success carries incomplete pointer fields")
            if safe_json(_object_ref_data(result.immutable_material_ref)) != safe_json(acquisition_evidence["immutableMaterialRef"]):
                _fail("material read immutable reference differs from the original receipt")
            if result.content_digest != acquisition_evidence["contentDigest"]:
                _fail("material read content digest differs from the original receipt")
            if safe_json(_evidence_ref_data(result.evidence_ref)) != safe_json(acquisition_evidence["evidenceRef"]):
                _fail("material read evidence reference differs from the original receipt")
        elif result.outcome is MaterialOutcome.REFUSED:
            if result.error_code is None:
                _fail("material read refusal lacks an error code")
        elif result.immutable_material_ref is not None or result.content_digest is not None or result.evidence_ref is not None or result.error_code is not None:
            _fail("material read unknown carries result fields")

    # ------------------------------------------------------- fixed facts

    @staticmethod
    def _fixed_facts_read(operation, step_id: str, request: RequestKey, store):
        """Validate one read-step recipe and resolve the original receipt.

        Returns (step, material_request, consumer_pin, acquisition_evidence,
        original_receipt, binding). Raises typed refusals on any drift: the
        read request must pin the original acquisition's fixed facts, the
        consumer pin must be an admission-side copy, and the four handoff
        items must equal the original receipt's pointer fields.
        """
        if type(step_id) is not str or not step_id:
            raise IdentityMismatchError("fixed material read step identity is required")
        intent = operation.intent
        step = next((item for item in intent.steps if item.step_id == step_id), None)
        if step is None:
            raise IdentityMismatchError("material read step is outside the fixed operation recipe")
        context = intent.context_ref
        try:
            envelope = _plain(context["materialReads"][step_id])
            encoded = {
                "contractVersion": envelope["contractVersion"],
                "request": envelope["request"],
                "consumerPin": envelope["consumerPin"],
                "acquisitionEvidence": envelope["acquisitionEvidence"],
                "originalStepRef": envelope["originalStepRef"],
            }
            if (set(envelope) != set(encoded)
                    or encoded["contractVersion"] != AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION):
                raise ValueError()
            material_request = MaterialRequest.from_dict(_plain(encoded["request"]))
            consumer_pin = MaterialConsumerPin.from_dict(_plain(encoded["consumerPin"]))
            acquisition_evidence = _acquisition_evidence_data(encoded["acquisitionEvidence"])
            original_ref = _plain(encoded["originalStepRef"])
            if (type(original_ref) is not dict
                    or set(original_ref) != {"environmentNamespace", "principalScope",
                                             "requestId", "operationDigest", "stepId"}):
                raise ValueError()
            binding = _plain(context["invocationBindings"][step_id])
            if set(binding) != {"action", "targetRef", "delegationRef", "cleanup"}:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise IdentityMismatchError("fixed material read facts differ from its recipe") from None

        if (binding["action"] != READ_ACTION or binding["cleanup"] is not False
                or binding["delegationRef"] is not None):
            raise IdentityMismatchError("material read binding is not the frozen read family")
        expected_target = material_invocation_target(material_request)
        try:
            if (safe_json(binding["targetRef"]) != safe_json(expected_target)
                    or safe_json(step.pinned_provider_ref.to_dict() if hasattr(step.pinned_provider_ref, "to_dict") else dict(step.pinned_provider_ref))
                    != safe_json(material_provider_ref(material_request.provider_pin))
                    or material_request.correlation.operation_ref != intent.operation_ref
                    or material_request.correlation.step_id != step.step_id
                    or material_request.correlation.recovery_correlation != step.recovery_correlation
                    or material_request.correlation.input_digest != step.input_digest
                    or step.input_digest != material_request.input_digest
                    or original_ref["environmentNamespace"] != request.environment_namespace):
                raise ValueError()
        except (TypeError, ValueError, AttributeError, RecursionError):
            raise IdentityMismatchError("fixed material read binding differs from its step") from None

        # Cross-identity environment gate (freeze §1): consumer pin env ==
        # material resource env == target envs == acquisition evidence envs.
        pin_env = consumer_pin.owner_activation.environment
        try:
            _environment_equal(pin_env,
                               material_request.resource_ref.environment_namespace,
                               material_request.target.node_ref.environment,
                               material_request.target.directory_binding_ref.environment_namespace,
                               acquisition_evidence["immutableMaterialRef"]["environmentNamespace"],
                               acquisition_evidence["evidenceRef"]["environmentNamespace"],
                               acquisition_evidence["provenanceRef"]["environmentNamespace"])
        except MaterialContractError:
            _fail("consumer pin crosses material identity environments")

        # Original acquisition relation (freeze §6.1): resolve the original
        # step record and pin the four handoff items to its receipt.
        original_request = RequestKey(original_ref["environmentNamespace"],
                                      original_ref["principalScope"], original_ref["requestId"])
        original_operation = store.read_operation(original_request)
        if original_operation is None or original_operation.digest != original_ref["operationDigest"]:
            raise GuaranteeUnavailableError("original material acquisition operation is unavailable")
        original_step = store.read_operation_step(original_request, original_ref["stepId"])
        if (original_step is None or original_step.outcome != "concluded"
                or "materialResult" not in original_step.evidence):
            raise GuaranteeUnavailableError("original material acquisition evidence is unavailable")
        original_receipt_dict = original_step.evidence["materialResult"].get("receipt")
        if not isinstance(original_receipt_dict, dict):
            raise GuaranteeUnavailableError("original material acquisition receipt is unavailable")
        try:
            original_receipt = MaterialReceipt.from_dict(original_receipt_dict)
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("original material acquisition receipt is invalid") from None

        # Four handoff items must equal the original receipt (§1/§6.1).
        try:
            _environment_equal(request.environment_namespace,
                               original_receipt.immutable_material_ref.environment_namespace,
                               original_receipt.evidence_ref.environment_namespace,
                               original_receipt.provenance_ref.environment_namespace)
        except MaterialContractError:
            _fail("acquisition evidence crosses original receipt environments")
        if (safe_json(acquisition_evidence["immutableMaterialRef"])
                != safe_json(_object_ref_data(original_receipt.immutable_material_ref))
                or acquisition_evidence["contentDigest"] != original_receipt.content_digest
                or safe_json(acquisition_evidence["evidenceRef"])
                != safe_json(_evidence_ref_data(original_receipt.evidence_ref))
                or safe_json(acquisition_evidence["provenanceRef"])
                != safe_json(_evidence_ref_data(original_receipt.provenance_ref))):
            _fail("handoff acquisition evidence differs from the original receipt")

        # The read request must pin the original acquisition's fixed facts:
        # wrong purpose/directory/epoch/version/resource all surface here.
        if (material_request.resource_ref != original_receipt.resource_ref
                or material_request.provider_pin != original_receipt.provider_pin
                or material_request.target != original_receipt.target
                or material_request.descriptor_digest != original_receipt.descriptor_digest):
            _fail("material read request differs from the original acquisition")

        # Descriptor for lifetime/describe checks comes from the original recipe.
        try:
            original_envelope = _plain(original_operation.intent.context_ref["materialRequests"][original_ref["stepId"]])
            descriptor = ResourceMaterialDescriptor.from_dict(_plain(original_envelope["descriptor"]))
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("original material descriptor is unavailable") from None
        return step, material_request, consumer_pin, acquisition_evidence, original_receipt, binding, descriptor

    def _persist_read(self, store, operation, step, material_request, claim,
                      result: MaterialReadResult | None, *, forced_unknown: bool = False):
        if forced_unknown:
            outcome = "unknown"
            evidence = {"materialReadOperation": "unknown"}
        else:
            outcome = {MaterialOutcome.SUCCESS: "concluded",
                       MaterialOutcome.REFUSED: "refused",
                       MaterialOutcome.UNKNOWN: "unknown"}[result.outcome]
            evidence = {"materialReadResult": _read_result_data(result)}
        try:
            return store.record_operation_step(
                operation.request, operation.digest, step.step_id,
                step.input_digest, claim.revision, outcome, evidence)
        except OperationRevisionConflict:
            current = store.read_operation_step(operation.request, step.step_id)
            if current is not None:
                return current
            raise GuaranteeUnavailableError("material read result could not be durably associated") from None
        except Exception:
            raise GuaranteeUnavailableError("material read result could not be durably recorded") from None

    def _authorize_read_replay(self, request, operation, step, binding):
        """Revalidate fixed facts and admission for a recorded read step.

        Read replay issues no ticket and never re-resolves (freeze §6.2);
        read and query semantics stay isolated (freeze §6.4): no query ticket
        is ever issued for a read replay. Authority for returning a
        pointer-only record is the principal gate plus the same fixed-facts
        and admission re-checks used before dispatch.
        """
        if binding["action"] != READ_ACTION:
            raise InvocationAuthorityRefused("recorded step is not an authorized read")

    def read(self, request: RequestKey, operation_digest: str, step_id: str) -> StepRecord:
        """Coordinate one authorized material read handoff through its Step."""
        store = self._gate(request)
        operation = self._read_operation(store, request, operation_digest)
        (step, material_request, consumer_pin, acquisition_evidence,
         original_receipt, binding, descriptor) = self._fixed_facts_read(
             operation, step_id, request, store)

        existing = store.read_operation_step(request, step_id)
        if existing is not None:
            # Replay: revalidate admission and fixed facts; no ticket, no
            # dispatch, no re-resolve (freeze §6.2/§6.4).
            self._authorize_read_replay(request, operation, step, binding)
            metadata, _ = self._provider(material_request)
            self._check_lifetime(metadata, descriptor)
            self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise GuaranteeUnavailableError("material read claim disappeared during authorized read")
            return current

        # Consumer pin admission-side copy check before any claim (freeze §1/§6.3).
        self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)

        metadata, provider = self._provider(material_request)
        self._check_lifetime(metadata, descriptor)
        self._check_descriptor(provider, env_principal(self._environment),
                               material_request, descriptor)

        current_metadata, current_provider = self._provider(material_request)
        if current_provider is not provider or current_metadata != metadata:
            raise AdmissionRefusedError("material provider pin changed before dispatch")

        claim = None
        try:
            context = self._issuer.issue(
                request, operation.digest, step.step_id, READ_ACTION,
                binding["targetRef"], delegation_ref=None, cleanup=False)
            claim = store.read_operation_step(request, step.step_id)
            if claim is None:
                raise GuaranteeUnavailableError("material read dispatch claim is missing")
        except UnknownResultError:
            current = store.read_operation_step(request, step_id)
            if current is not None and claim is None:
                metadata, _ = self._provider(material_request)
                self._check_lifetime(metadata, descriptor)
                self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)
                return store.read_operation_step(request, step_id)
            raise
        except Exception:
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise
            if claim is None:
                claim = current
            return self._persist_read(store, operation, step, material_request,
                                      claim, None, forced_unknown=True)

        # After the step claim, dispatch failures become the one UNKNOWN
        # conclusion; the durable claim is never overwritten by a retry.
        try:
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed before dispatch")
            reader = getattr(provider, "read_material", None)
            if not callable(reader):
                raise GuaranteeUnavailableError("material provider cannot serve authorized reads")
            result_value = reader(_request_snapshot(material_request), context)
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed after dispatch")
            if not self._issuer.verified_consumption(context):
                raise GuaranteeUnavailableError("provider did not verify the original material read invocation")
            result = _read_result_snapshot(result_value)
            self._check_read_result(result, material_request, acquisition_evidence)
        except Exception:
            return self._persist_read(store, operation, step, material_request,
                                      claim, None, forced_unknown=True)
        return self._persist_read(store, operation, step, material_request, claim, result)


    # ------------------------------------------------------- release gate

    @staticmethod
    def _fixed_facts_release(operation, step_id: str, request: RequestKey, store):
        """Validate one release-step recipe and resolve its lease + descriptor.

        Returns (step, material_request, consumer_pin, receipt, binding,
        descriptor, read_step_ref). The release request itself is rebuilt at
        dispatch time from the receipt's lease; the DTO validates the
        non-reuse and digest-binding rules.
        """
        if type(step_id) is not str or not step_id:
            raise IdentityMismatchError("fixed material release step identity is required")
        intent = operation.intent
        step = next((item for item in intent.steps if item.step_id == step_id), None)
        if step is None:
            raise IdentityMismatchError("material release step is outside the fixed operation recipe")
        context = intent.context_ref
        try:
            envelope = _plain(context["materialReleases"][step_id])
            if (set(envelope) != {"contractVersion", "request", "consumerPin",
                                   "originalStepId", "readStepRef"}
                    or envelope["contractVersion"] != AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION):
                raise ValueError()
            material_request = MaterialRequest.from_dict(_plain(envelope["request"]))
            consumer_pin = MaterialConsumerPin.from_dict(_plain(envelope["consumerPin"]))
            original_step_id = envelope["originalStepId"]
            if type(original_step_id) is not str or not original_step_id:
                raise ValueError()
            read_step_ref = _plain(envelope["readStepRef"])
            if (type(read_step_ref) is not dict
                    or set(read_step_ref) != {"environmentNamespace", "principalScope",
                                              "requestId", "operationDigest", "stepId"}):
                raise ValueError()
            binding = _plain(context["invocationBindings"][step_id])
            if set(binding) != {"action", "targetRef", "delegationRef", "cleanup"}:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise IdentityMismatchError("fixed material release facts differ from its recipe") from None

        if (binding["action"] != RELEASE_ACTION or binding["cleanup"] is not True
                or binding["delegationRef"] is not None):
            raise IdentityMismatchError("material release binding is not the frozen release family")
        expected_target = material_invocation_target(material_request)
        try:
            if (safe_json(binding["targetRef"]) != safe_json(expected_target)
                    or safe_json(dict(step.pinned_provider_ref))
                    != safe_json(material_provider_ref(material_request.provider_pin))
                    or material_request.correlation.operation_ref != intent.operation_ref
                    or material_request.correlation.step_id != step.step_id
                    or material_request.correlation.recovery_correlation != step.recovery_correlation
                    or read_step_ref["environmentNamespace"] != request.environment_namespace
                    or original_step_id == step_id):
                raise ValueError()
        except (TypeError, ValueError, AttributeError, RecursionError):
            raise IdentityMismatchError("fixed material release binding differs from its step") from None

        pin_env = consumer_pin.owner_activation.environment
        try:
            _environment_equal(pin_env,
                               material_request.resource_ref.environment_namespace,
                               material_request.target.node_ref.environment,
                               material_request.target.directory_binding_ref.environment_namespace)
        except MaterialContractError:
            _fail("consumer pin crosses material identity environments")

        # The original acquire step lives in this same operation (freeze: the
        # release coordinates the original operation's holds).
        original_step = store.read_operation_step(request, original_step_id)
        if (original_step is None or original_step.outcome != "concluded"
                or "materialResult" not in original_step.evidence):
            raise GuaranteeUnavailableError("original material acquisition evidence is unavailable")
        original_receipt_dict = original_step.evidence["materialResult"].get("receipt")
        if not isinstance(original_receipt_dict, dict):
            raise GuaranteeUnavailableError("original material acquisition receipt is unavailable")
        try:
            receipt = MaterialReceipt.from_dict(original_receipt_dict)
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("original material acquisition receipt is invalid") from None

        if (material_request.resource_ref != receipt.resource_ref
                or material_request.provider_pin != receipt.provider_pin
                or material_request.target != receipt.target
                or material_request.descriptor_digest != receipt.descriptor_digest):
            _fail("material release request differs from the original acquisition")

        try:
            original_envelope = _plain(intent.context_ref["materialRequests"][original_step_id])
            descriptor = ResourceMaterialDescriptor.from_dict(_plain(original_envelope["descriptor"]))
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("original material descriptor is unavailable") from None
        return (step, material_request, consumer_pin, receipt, binding, descriptor,
                read_step_ref, original_step_id)

    def _verify_consumption_evidence(self, store, request, consumption_evidence,
                                     receipt, material_request, read_step_ref):
        """Shape-and-association check for §3 consumption evidence.

        The core checks shape and association only; consumption truth belongs
        to the Runtime owner. Verification = the evidence binds the durable,
        owner-verified read step (success is persisted only after
        ``verified_consumption``) and matches admission-side consumer facts.
        """
        try:
            evidence = MaterialConsumptionEvidence.from_dict(
                consumption_evidence.to_dict())
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            return False
        if safe_json(evidence.immutable_material_ref.to_dict()) != safe_json(
                _object_ref_data(receipt.immutable_material_ref)):
            return False
        if safe_json(evidence.target.to_dict()) != safe_json(_target_data(material_request.target)):
            return False
        try:
            self._consumer_pin_gate(evidence.consumer_pin, self._admitted_consumer,
                                    material_request)
        except (AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError):
            return False
        read_request = RequestKey(read_step_ref["environmentNamespace"],
                                  read_step_ref["principalScope"], read_step_ref["requestId"])
        read_operation = store.read_operation(read_request)
        if read_operation is None or read_operation.digest != read_step_ref["operationDigest"]:
            return False
        read_step_record = store.read_operation_step(read_request, read_step_ref["stepId"])
        if read_step_record is None or read_step_record.outcome != "concluded":
            return False
        read_evidence = read_step_record.evidence
        if not isinstance(read_evidence, Mapping):
            return False
        read_result = read_evidence.get("materialReadResult")
        if not isinstance(read_result, dict) or read_result.get("outcome") != "success":
            return False
        if safe_json(evidence.correlation.to_dict()) != safe_json(read_result.get("correlation")):
            return False
        if safe_json(evidence.immutable_material_ref.to_dict()) != safe_json(
                read_result.get("immutableMaterialRef")):
            return False
        return True

    def _persist_release(self, store, operation, step, release_request, claim,
                         result: MaterialReleaseResult | None, mutations, *,
                         forced_unknown: bool = False):
        if forced_unknown:
            outcome = "unknown"
            evidence = {"materialReleaseOperation": "unknown"}
            mutations = ()
        else:
            outcome = {MaterialOutcome.SUCCESS: "concluded",
                       MaterialOutcome.REFUSED: "refused",
                       MaterialOutcome.UNKNOWN: "unknown"}[result.outcome]
            evidence = {"materialReleaseResult": _release_result_data(result)}
            if outcome != "concluded":
                mutations = ()
        try:
            return store.record_operation_step(
                operation.request, operation.digest, step.step_id,
                step.input_digest, claim.revision, outcome, evidence, usages=mutations)
        except OperationRevisionConflict:
            current = store.read_operation_step(operation.request, step.step_id)
            if current is not None:
                return current
            raise GuaranteeUnavailableError("material release result could not be durably associated") from None
        except Exception:
            raise GuaranteeUnavailableError("material release result could not be durably recorded") from None

    @staticmethod
    def _release_usage_mutations(store, request, operation, material_request, original_step_id):
        """Release the original acquisition's two Usage holds (§4 mechanism).

        The holds live under the ORIGINAL acquire step's prefix; the release
        step itself never created holds (no separate execution ledger).
        """
        reader = getattr(store, "read_usages", None)
        if not callable(reader):
            raise GuaranteeUnavailableError("same-Store material Usage reads are unavailable")
        holder = operation_holder(request, operation.intent.operation_ref)
        prefix = (f"{operation.intent.operation_ref}.material."
                  f"{original_step_id}")
        try:
            rows = reader(request.environment_namespace, holder)
        except Exception:
            raise GuaranteeUnavailableError("material Usage facts are unavailable") from None
        by_id = {row.get("usageId"): row for row in rows if isinstance(row, Mapping)}
        expected = {
            prefix + ".provider": material_provider_ref(material_request.provider_pin),
            prefix + ".resource": {"environmentNamespace": material_request.resource_ref.environment_namespace,
                                   "providerId": material_request.resource_ref.provider_id,
                                   "contractId": material_request.resource_ref.contract_id,
                                   "resourceId": material_request.resource_ref.resource_id,
                                   "revision": material_request.resource_ref.revision},
        }
        mutations = []
        for usage_id, target in expected.items():
            row = by_id.get(usage_id)
            if row is None:
                raise GuaranteeUnavailableError("required material Usage hold is missing")
            if (row.get("holderRef") != dict(holder) or row.get("targetRef") != target
                    or row.get("rights") != ["use"] or row.get("state") != "active"
                    or type(row.get("revision")) is not int or row["revision"] < 1):
                raise GuaranteeUnavailableError("material Usage hold identity or state is unavailable")
            mutations.append(UsageMutation(
                usage_id, row["revision"], holder, holder, row["targetRef"],
                ("use",), "released", row["payload"],
            ))
        return tuple(mutations)

    def release(self, request: RequestKey, operation_digest: str, step_id: str,
                *, consumption_evidence: MaterialConsumptionEvidence | None = None
                ) -> MaterialReleaseGateDecision:
        """Evaluate the §4 release gate and, when open, coordinate release."""
        store = self._gate(request)
        operation = self._read_operation(store, request, operation_digest)
        (step, material_request, consumer_pin, receipt, binding,
         descriptor, read_step_ref, original_step_id) = self._fixed_facts_release(
             operation, step_id, request, store)

        existing = store.read_operation_step(request, step_id)
        if existing is not None:
            # Replay of a recorded release: revalidate admission and return.
            metadata, _ = self._provider(material_request)
            self._check_lifetime(metadata, descriptor)
            self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise GuaranteeUnavailableError("material release claim disappeared")
            released = current.outcome == "concluded"
            return MaterialReleaseGateDecision(
                released=released,
                remaining=() if released else ("release-outcome-unknown",),
                step_record=current)

        # Gate conditions (freeze §4). Held gates claim nothing and touch
        # nothing: the original holds keep their occupation.
        remaining: list[str] = []
        lifetime = descriptor.lifetime
        if lifetime is MaterialLifetime.COPY_COMPLETE:
            if consumption_evidence is None:
                remaining.append("owner-consumption-evidence")
            elif not self._verify_consumption_evidence(
                    store, request, consumption_evidence, receipt,
                    material_request, read_step_ref):
                remaining.append("owner-consumption-verification")
        elif lifetime is MaterialLifetime.RUNTIME_REQUIRED:
            # Proven stop/replace evidence comes from Node lifecycle
            # conclusions (A-route), not wired in this slice: hold.
            remaining.append("runtime-stop-replace-evidence")
        elif lifetime is MaterialLifetime.DYNAMIC:
            # Candidate confirmation and same-transaction switch are A-route
            # staged semantics, separately bound: hold.
            remaining.append("dynamic-a-route-binding")
        if remaining:
            return MaterialReleaseGateDecision(released=False,
                                               remaining=tuple(remaining),
                                               step_record=None)

        # Gate open: full release mechanism (reused release trio + binding).
        self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)
        metadata, provider = self._provider(material_request)
        self._check_lifetime(metadata, descriptor)
        self._check_descriptor(provider, env_principal(self._environment),
                               material_request, descriptor)
        current_metadata, current_provider = self._provider(material_request)
        if current_provider is not provider or current_metadata != metadata:
            raise AdmissionRefusedError("material provider pin changed before dispatch")

        try:
            lease = receipt.lease_ref
            release_request = MaterialReleaseRequest(
                lease,
                _release_correlation(operation.intent.operation_ref, step.step_id,
                                     step.recovery_correlation, step.input_digest))
            if step.input_digest != release_request.input_digest:
                raise IdentityMismatchError("release step digest differs from the lease-bound release request")
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError,
                MaterialContractError) as exc:
            if isinstance(exc, IdentityMismatchError):
                raise
            raise IdentityMismatchError("release request differs from its lease binding") from None

        claim = None
        try:
            context = self._issuer.issue(
                request, operation.digest, step.step_id, RELEASE_ACTION,
                binding["targetRef"], delegation_ref=None, cleanup=True)
            claim = store.read_operation_step(request, step.step_id)
            if claim is None:
                raise GuaranteeUnavailableError("material release dispatch claim is missing")
        except UnknownResultError:
            current = store.read_operation_step(request, step_id)
            if current is not None and claim is None:
                self._consumer_pin_gate(consumer_pin, self._admitted_consumer, material_request)
                return MaterialReleaseGateDecision(
                    released=current.outcome == "concluded",
                    remaining=() if current.outcome == "concluded" else ("release-outcome-unknown",),
                    step_record=current)
            raise
        except Exception:
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise
            if claim is None:
                claim = current
            return MaterialReleaseGateDecision(
                released=False, remaining=(),
                step_record=self._persist_release(store, operation, step, release_request,
                                                 claim, None, (), forced_unknown=True))

        try:
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed before dispatch")
            releaser = getattr(provider, "release_material", None)
            if not callable(releaser):
                raise GuaranteeUnavailableError("material provider cannot release material")
            result_value = releaser(_release_request_snapshot(release_request), context)
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed after dispatch")
            if not self._issuer.verified_consumption(context):
                raise GuaranteeUnavailableError("provider did not verify the original material release invocation")
            result = _release_result_snapshot(result_value)
            self._check_release_result(result, release_request)
        except Exception:
            return MaterialReleaseGateDecision(
                released=False, remaining=(),
                step_record=self._persist_release(store, operation, step, release_request,
                                                 claim, None, (), forced_unknown=True))

        mutations = self._release_usage_mutations(store, request, operation,
                                                material_request, original_step_id)
        step_record = self._persist_release(store, operation, step, release_request,
                                           claim, result, mutations)
        return MaterialReleaseGateDecision(released=True, remaining=(),
                                           step_record=step_record)

    @staticmethod
    def _check_release_result(result: MaterialReleaseResult, release_request) -> None:
        if result.correlation != release_request.correlation:
            _fail("material release result correlation differs")
        if result.outcome is MaterialOutcome.SUCCESS:
            receipt = result.receipt
            if (receipt is None or receipt.lease_ref != release_request.lease_ref
                    or receipt.correlation != release_request.correlation
                    or result.error_code is not None):
                _fail("material release receipt differs from its request")
        elif result.outcome is MaterialOutcome.REFUSED:
            if result.receipt is not None or result.error_code is None:
                _fail("material release refusal carries a receipt")
        elif result.receipt is not None or result.error_code is not None:
            _fail("material release unknown carries result fields")


def _release_correlation(operation_ref: str, step_id: str, recovery_correlation: str,
                         input_digest: str) -> MaterialCorrelation:
    return MaterialCorrelation(operation_ref, step_id, recovery_correlation, input_digest)


def _release_request_snapshot(value: MaterialReleaseRequest) -> MaterialReleaseRequest:
    try:
        return MaterialReleaseRequest.from_dict(_release_request_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail("provider material release request is invalid")


def _release_request_data(value: MaterialReleaseRequest) -> dict[str, Any]:
    if type(value) is not MaterialReleaseRequest:
        _fail()
    lease = value.lease_ref
    return {"leaseRef": {"leaseId": lease.lease_id,
                         "resourceRef": {"environmentNamespace": lease.resource_ref.environment_namespace,
                                         "providerId": lease.resource_ref.provider_id,
                                         "contractId": lease.resource_ref.contract_id,
                                         "resourceId": lease.resource_ref.resource_id,
                                         "revision": lease.resource_ref.revision},
                         "providerPin": _pin_data(lease.provider_pin),
                         "target": _target_data(lease.target),
                         "acquisitionCorrelation": {"operationRef": lease.acquisition_correlation.operation_ref,
                                                    "stepId": lease.acquisition_correlation.step_id,
                                                    "recoveryCorrelation": lease.acquisition_correlation.recovery_correlation,
                                                    "inputDigest": lease.acquisition_correlation.input_digest}},
            "correlation": {"operationRef": value.correlation.operation_ref,
                            "stepId": value.correlation.step_id,
                            "recoveryCorrelation": value.correlation.recovery_correlation,
                            "inputDigest": value.correlation.input_digest}}



def _request_snapshot(value: MaterialRequest) -> MaterialRequest:
    try:
        return MaterialRequest.from_dict(_request_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail("provider material request is invalid")


def _request_data(value: MaterialRequest) -> dict[str, Any]:
    if type(value) is not MaterialRequest:
        _fail()
    return {"resourceRef": {"environmentNamespace": value.resource_ref.environment_namespace,
                            "providerId": value.resource_ref.provider_id,
                            "contractId": value.resource_ref.contract_id,
                            "resourceId": value.resource_ref.resource_id,
                            "revision": value.resource_ref.revision},
            "providerPin": _pin_data(value.provider_pin),
            "target": _target_data(value.target),
            "descriptorDigest": value.descriptor_digest,
            "correlation": {"operationRef": value.correlation.operation_ref,
                            "stepId": value.correlation.step_id,
                            "recoveryCorrelation": value.correlation.recovery_correlation,
                            "inputDigest": value.correlation.input_digest}}


def _environment_equal(environment: str, *values: str) -> None:
    if any(value != environment for value in values):
        raise MaterialContractError()


__all__ = [
    "AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION",
    "READ_ACTION", "RELEASE_ACTION",
    "AdmittedConsumerEvidence", "MaterialConsumption", "MaterialReleaseGateDecision",
]

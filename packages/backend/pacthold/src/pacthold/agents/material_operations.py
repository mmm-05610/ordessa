"""Operation-bound coordination for non-secret material requests.

This service consumes facts already frozen in the original Agent Operation.
It does not extract references from Profiles, create another ledger, or transfer
material to a consumer. Provider effects always use the Environment's existing
InvocationIssuer and the operation's original Step/Usage rows.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ordessa_environment_api import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    RequestKey,
    UnknownResultError,
)
from ordessa_environment_api.identity import ActivationRef, ParticipantInstanceRef
from ordessa_environment_api.operations import (
    OperationStorePort,
    OperationRevisionConflict,
    StepRecord,
    UsageMutation,
    operation_holder,
    safe_json,
)

from ..core.resource_admission import MaterialContractError
from .directory import DirectoryBindingRef
from .invocation import InvocationAuthorityRefused, InvocationIssuer
from .materials import (
    MaterialAccessMode,
    MaterialCorrelation,
    MaterialEvidenceRef,
    MaterialLeaseRef,
    MaterialObjectRef,
    MaterialOutcome,
    MaterialProviderPin,
    MaterialReleaseReceipt,
    MaterialReleaseResult,
    MaterialRequest,
    MaterialResult,
    MaterialUseTarget,
    ResourceMaterialDescriptor,
    ResourceRef,
    MaterialLifetime,
)


AGENT_MATERIAL_OPERATION_CONTRACT_VERSION = "agent-material-operation/1"


def _fail(message: str = "material operation facts are invalid") -> None:
    raise IdentityMismatchError(message)


def _activation_data(value: ActivationRef) -> dict[str, Any]:
    if type(value) is not ActivationRef:
        _fail()
    return {"environmentNamespace": value.environment,
            "pluginId": value.plugin_id, "generation": value.generation}


def _resource_ref_data(value: ResourceRef) -> dict[str, Any]:
    if type(value) is not ResourceRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "providerId": value.provider_id, "contractId": value.contract_id,
            "resourceId": value.resource_id, "revision": value.revision}


def _pin_data(value: MaterialProviderPin) -> dict[str, Any]:
    if type(value) is not MaterialProviderPin:
        _fail()
    return {"providerId": value.provider_id, "providerVersion": value.provider_version,
            "ownerActivation": _activation_data(value.owner_activation)}


def _directory_data(value: DirectoryBindingRef) -> dict[str, Any]:
    if type(value) is not DirectoryBindingRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "bindingId": value.binding_id, "bindingRevision": value.binding_revision,
            "contentDigest": value.content_digest}


def _target_data(value: MaterialUseTarget) -> dict[str, Any]:
    if type(value) is not MaterialUseTarget or type(value.node_ref) is not ParticipantInstanceRef:
        _fail()
    return {"nodeRef": {"environmentNamespace": value.node_ref.environment,
                        "instanceId": value.node_ref.instance_id,
                        "generation": value.node_ref.generation},
            "directoryBindingRef": _directory_data(value.directory_binding_ref),
            "managementEpoch": value.management_epoch, "purpose": value.purpose}


def _correlation_data(value: MaterialCorrelation) -> dict[str, Any]:
    if type(value) is not MaterialCorrelation:
        _fail()
    return {"operationRef": value.operation_ref, "stepId": value.step_id,
            "recoveryCorrelation": value.recovery_correlation, "inputDigest": value.input_digest}


def _request_data(value: MaterialRequest) -> dict[str, Any]:
    if type(value) is not MaterialRequest:
        _fail()
    return {"resourceRef": _resource_ref_data(value.resource_ref),
            "providerPin": _pin_data(value.provider_pin),
            "target": _target_data(value.target),
            "descriptorDigest": value.descriptor_digest,
            "correlation": _correlation_data(value.correlation)}


def _request_snapshot(value: MaterialRequest) -> MaterialRequest:
    try:
        return MaterialRequest.from_dict(_request_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail()


def _descriptor_data(value: ResourceMaterialDescriptor) -> dict[str, Any]:
    if type(value) is not ResourceMaterialDescriptor:
        _fail()
    if (type(value.lifetime) is not MaterialLifetime
            or type(value.access_mode) is not MaterialAccessMode):
        _fail()
    return {"resourceRef": _resource_ref_data(value.resource_ref),
            "materialType": value.material_type,
            "schemaVersion": value.schema_version,
            "contentDigest": value.content_digest,
            "lifetime": value.lifetime.value,
            "accessMode": value.access_mode.value,
            "provenanceRef": _evidence_ref_data(value.provenance_ref),
            "evidenceRef": _evidence_ref_data(value.evidence_ref)}


def _descriptor_snapshot(value: ResourceMaterialDescriptor) -> ResourceMaterialDescriptor:
    try:
        return ResourceMaterialDescriptor.from_dict(_descriptor_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail()


def _evidence_ref_data(value: MaterialEvidenceRef) -> dict[str, Any]:
    if type(value) is not MaterialEvidenceRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "referenceId": value.reference_id, "revision": value.revision}


def _object_ref_data(value: MaterialObjectRef) -> dict[str, Any]:
    if type(value) is not MaterialObjectRef:
        _fail()
    return {"environmentNamespace": value.environment_namespace,
            "materialId": value.material_id, "revision": value.revision}


def _lease_ref_data(value: MaterialLeaseRef) -> dict[str, Any]:
    if type(value) is not MaterialLeaseRef:
        _fail()
    return {"leaseId": value.lease_id,
            "resourceRef": _resource_ref_data(value.resource_ref),
            "providerPin": _pin_data(value.provider_pin),
            "target": _target_data(value.target),
            "acquisitionCorrelation": _correlation_data(value.acquisition_correlation)}


def _receipt_data(value) -> dict[str, Any]:
    if type(value) is MaterialResult:
        receipt = value.receipt
        return {"outcome": value.outcome.value,
                "correlation": _correlation_data(value.correlation),
                "receipt": None if receipt is None else {
                    "resourceRef": _resource_ref_data(receipt.resource_ref),
                    "providerPin": _pin_data(receipt.provider_pin),
                    "target": _target_data(receipt.target),
                    "correlation": _correlation_data(receipt.correlation),
                    "descriptorDigest": receipt.descriptor_digest,
                    "immutableMaterialRef": _object_ref_data(receipt.immutable_material_ref),
                    "contentDigest": receipt.content_digest,
                    "materialType": receipt.material_type,
                    "schemaVersion": receipt.schema_version,
                    "leaseRef": _lease_ref_data(receipt.lease_ref),
                    "provenanceRef": _evidence_ref_data(receipt.provenance_ref),
                    "evidenceRef": _evidence_ref_data(receipt.evidence_ref)},
                "errorCode": value.error_code}
    return _release_result_data(value)


def _release_receipt_data(value: MaterialReleaseReceipt) -> dict[str, Any]:
    if type(value) is not MaterialReleaseReceipt:
        _fail()
    return {"leaseRef": _lease_ref_data(value.lease_ref),
            "correlation": _correlation_data(value.correlation),
            "evidenceRef": _evidence_ref_data(value.evidence_ref)}


def _release_result_data(value: MaterialReleaseResult) -> dict[str, Any]:
    if type(value) is not MaterialReleaseResult:
        _fail()
    return {"outcome": value.outcome.value,
            "correlation": _correlation_data(value.correlation),
            "receipt": None if value.receipt is None else _release_receipt_data(value.receipt),
            "errorCode": value.error_code}


def _result_snapshot(value: object) -> MaterialResult:
    if type(value) is not MaterialResult or type(value.outcome) is not MaterialOutcome:
        _fail("provider material result is invalid")
    try:
        return MaterialResult.from_dict(_receipt_data(value))
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail("provider material result is invalid")


def material_provider_ref(pin: MaterialProviderPin) -> Mapping[str, Any]:
    """Return the frozen Operation Step provider reference for an admitted pin."""
    snapshot = MaterialProviderPin.from_dict(_pin_data(pin))
    activation = snapshot.owner_activation
    if type(activation.generation) is not int or activation.generation <= 0:
        _fail()
    return {
        "environmentNamespace": activation.environment,
        "providerId": snapshot.provider_id,
        "providerVersion": snapshot.provider_version,
        "ownerActivation": _activation_data(activation),
        "generation": activation.generation,
    }


def material_invocation_target(request: MaterialRequest) -> Mapping[str, Any]:
    """Return the exact fixed invocation target and request facts."""
    snapshot = _request_snapshot(request)
    return {
        "environmentNamespace": snapshot.resource_ref.environment_namespace,
        "resourceRef": _resource_ref_data(snapshot.resource_ref),
        "providerPin": _pin_data(snapshot.provider_pin),
        "target": _target_data(snapshot.target),
        "descriptorDigest": snapshot.descriptor_digest,
    }


def material_operation_facts(request: MaterialRequest,
                             descriptor: ResourceMaterialDescriptor) -> Mapping[str, Any]:
    """Build the safe immutable fact envelope frozen in the root Operation."""
    request_snapshot = _request_snapshot(request)
    descriptor_snapshot = _descriptor_snapshot(descriptor)
    if (descriptor_snapshot.resource_ref != request_snapshot.resource_ref
            or descriptor_snapshot.descriptor_digest != request_snapshot.descriptor_digest):
        _fail("material descriptor differs from the fixed request")
    return {
        "contractVersion": AGENT_MATERIAL_OPERATION_CONTRACT_VERSION,
        "request": _request_data(request_snapshot),
        "descriptor": _descriptor_data(descriptor_snapshot),
    }


def material_reservation_usages(request: RequestKey,
                                material_request: MaterialRequest) -> tuple[UsageMutation, ...]:
    """Build the two original operation holds; this helper performs no write."""
    if type(request) is not RequestKey:
        raise IdentityMismatchError("complete material operation request identity required")
    material = _request_snapshot(material_request)
    correlation = material.correlation
    if request.environment_namespace != material.resource_ref.environment_namespace:
        raise IdentityMismatchError("material hold crosses Environment identity")
    if request.principal_scope == "":
        raise IdentityMismatchError("material operation principal is unavailable")
    holder = operation_holder(request, correlation.operation_ref)
    provider_target = material_provider_ref(material.provider_pin)
    resource_target = _resource_ref_data(material.resource_ref)
    prefix = f"{correlation.operation_ref}.material.{correlation.step_id}"
    return (
        UsageMutation(prefix + ".provider", 0, None, holder, provider_target,
                      ("use",), "active"),
        UsageMutation(prefix + ".resource", 0, None, holder, resource_target,
                      ("use",), "active"),
    )


class MaterialOperations:
    """Coordinate one fixed MaterialRequest through its original Step."""

    def __init__(self, environment, *, invocation_issuer: InvocationIssuer | None = None):
        self._environment = environment
        self._issuer = invocation_issuer

    def _gate(self, request: RequestKey):
        env = self._environment
        if type(request) is not RequestKey:
            raise IdentityMismatchError("complete material operation request identity required")
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("material operation principal differs from this Environment")
            env._admit_resource_metadata_read()
        store = env._store
        if not isinstance(store, OperationStorePort):
            raise GuaranteeUnavailableError("same-Environment operation Store is unavailable")
        if not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not store:
            raise InvocationAuthorityRefused("same-Store InvocationIssuer is required")
        return store

    def _read_operation(self, store, request: RequestKey, operation_digest: str):
        if type(operation_digest) is not str or not operation_digest:
            raise IdentityMismatchError("fixed material operation digest is required")
        operation = store.read_operation(request)
        if operation is None:
            raise UnknownResultError("material operation is not reserved")
        if operation.digest != operation_digest:
            raise IdentityMismatchError("material operation digest differs from its reservation")
        return operation

    @staticmethod
    def _fixed_facts(operation, step_id: str, request: RequestKey):
        if type(step_id) is not str or not step_id:
            raise IdentityMismatchError("fixed material step identity is required")
        intent = operation.intent
        step = next((item for item in intent.steps if item.step_id == step_id), None)
        if step is None:
            raise IdentityMismatchError("material step is outside the fixed operation recipe")
        context = intent.context_ref
        try:
            entries = context["materialRequests"]
            envelope = entries[step_id]
            encoded = json.loads(safe_json(envelope))
            if (type(encoded) is not dict or set(encoded) != {"contractVersion", "request", "descriptor"}
                    or encoded["contractVersion"] != AGENT_MATERIAL_OPERATION_CONTRACT_VERSION):
                raise ValueError()
            material_request = MaterialRequest.from_dict(encoded["request"])
            descriptor = ResourceMaterialDescriptor.from_dict(encoded["descriptor"])
            binding = context["invocationBindings"][step_id]
            if set(binding) != {"action", "targetRef", "delegationRef", "cleanup"}:
                raise ValueError()
            expected_target = material_invocation_target(material_request)
            expected_provider = material_provider_ref(material_request.provider_pin)
            expected_directory = _directory_data(material_request.target.directory_binding_ref)
            operation_directory = context["directoryBindingRef"]
            if (safe_json(binding["targetRef"]) != safe_json(expected_target)
                    or binding["action"] != "acquire" or binding["delegationRef"] is not None
                    or binding["cleanup"] is not False
                    or safe_json(step.pinned_provider_ref) != safe_json(expected_provider)
                    or safe_json(descriptor.resource_ref.to_dict()) != safe_json(material_request.resource_ref.to_dict())
                    or descriptor.descriptor_digest != material_request.descriptor_digest
                    or safe_json(operation_directory) != safe_json(expected_directory)
                    or safe_json(intent.node_ref) != safe_json(_target_data(material_request.target)["nodeRef"])
                    or intent.management_epoch != material_request.target.management_epoch
                    or step.management_epoch != intent.management_epoch
                    or material_request.resource_ref.environment_namespace != request.environment_namespace
                    or material_request.provider_pin.provider_id != material_request.resource_ref.provider_id
                    or material_request.correlation.operation_ref != intent.operation_ref
                    or material_request.correlation.step_id != step.step_id
                    or material_request.correlation.recovery_correlation != step.recovery_correlation
                    or material_request.correlation.input_digest != step.input_digest
                    or step.input_digest != material_request.input_digest):
                raise ValueError()
            return step, material_request, descriptor, binding
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise IdentityMismatchError("fixed material request differs from its original operation step") from None

    def _usage_rows(self, store, operation, request, material_request, *, claimed: bool):
        reader = getattr(store, "read_usages", None)
        if not callable(reader):
            raise GuaranteeUnavailableError("same-Store material Usage reads are unavailable")
        holder = operation_holder(request, operation.intent.operation_ref)
        try:
            rows = reader(request.environment_namespace, holder)
        except Exception:
            raise GuaranteeUnavailableError("material Usage facts are unavailable") from None
        expected = {
            f"{operation.intent.operation_ref}.material.{material_request.correlation.step_id}.provider":
                material_provider_ref(material_request.provider_pin),
            f"{operation.intent.operation_ref}.material.{material_request.correlation.step_id}.resource":
                _resource_ref_data(material_request.resource_ref),
        }
        by_id = {row.get("usageId"): row for row in rows if isinstance(row, Mapping)}
        result = []
        for usage_id, target in expected.items():
            row = by_id.get(usage_id)
            if row is None:
                raise GuaranteeUnavailableError("required material Usage hold is missing")
            state = row.get("state")
            allowed_states = {"active", "unknown"} if claimed else {"active"}
            if (row.get("holderRef") != holder or row.get("targetRef") != target
                    or row.get("rights") != ["use"] or state not in allowed_states
                    or type(row.get("revision")) is not int or row["revision"] < 1
                    or row.get("payload") != {}):
                raise GuaranteeUnavailableError("material Usage hold identity or state is unavailable")
            result.append(row)
        return tuple(result)

    @staticmethod
    def _usage_mutations(rows, operation, request, material_request, outcome: str):
        holder = operation_holder(request, operation.intent.operation_ref)
        prefix = f"{operation.intent.operation_ref}.material.{material_request.correlation.step_id}"
        state_by_name = {
            "concluded": "active",
            "refused": None,
            "unknown": "unknown",
        }
        new_state = state_by_name[outcome]
        mutations = []
        for suffix, row in zip((".provider", ".resource"), rows):
            state = row["state"] if new_state is None else new_state
            mutations.append(UsageMutation(
                prefix + suffix, row["revision"], holder, holder, row["targetRef"],
                ("use",), state, row["payload"],
            ))
        return tuple(mutations)

    def _authorize_claim_read(self, request, operation, step, binding):
        issuer = self._issuer
        context = issuer.issue_query(request, operation.digest, step.step_id)
        try:
            verifier = issuer.verifier()
            verifier.verify_and_consume(
                context, "query", step.pinned_provider_ref,
                binding["targetRef"], step.input_digest,
            )
            verifier.verify_claimed_query(
                context, step.pinned_provider_ref, binding["targetRef"], step.input_digest,
                operation_kind=operation.intent.kind,
            )
        except Exception:
            # Keep the original authorization family's safe refusal without
            # exposing callback details or allowing a material result to leak.
            raise InvocationAuthorityRefused("current query authority for the material step is unavailable") from None
        if not issuer.verified_observation(context):
            raise InvocationAuthorityRefused("original material step was not verified for query")

    def _provider(self, material_request: MaterialRequest):
        env = self._environment
        pin = material_request.provider_pin
        try:
            metadata, provider = env._material_provider_for_operation(
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
    def _check_lifetime(metadata, descriptor):
        if descriptor.lifetime not in metadata.capability.lifetimes:
            raise GuaranteeUnavailableError("material provider does not support the fixed resource lifetime")

    @staticmethod
    def _check_descriptor(provider, principal: str, material_request, descriptor):
        try:
            described = provider.describe_material(
                ResourceRef.from_dict(_resource_ref_data(material_request.resource_ref)), principal)
            snapshot = _descriptor_snapshot(described)
        except Exception:
            raise GuaranteeUnavailableError("material provider description is unavailable") from None
        if safe_json(_descriptor_data(snapshot)) != safe_json(_descriptor_data(descriptor)):
            raise AdmissionRefusedError("material provider descriptor differs from its fixed facts")

    @staticmethod
    def _check_result(result: MaterialResult, material_request, descriptor):
        if result.correlation != material_request.correlation:
            raise ValueError("material result correlation differs")
        if result.outcome is MaterialOutcome.SUCCESS:
            receipt = result.receipt
            if (receipt.resource_ref != material_request.resource_ref
                    or receipt.provider_pin != material_request.provider_pin
                    or receipt.target != material_request.target
                    or receipt.correlation != material_request.correlation
                    or receipt.descriptor_digest != material_request.descriptor_digest
                    or receipt.content_digest != descriptor.content_digest
                    or receipt.material_type != descriptor.material_type
                    or receipt.schema_version != descriptor.schema_version
                    or receipt.provenance_ref != descriptor.provenance_ref):
                raise ValueError("material receipt differs from the fixed request")

    def _persist(self, store, operation, step, material_request, descriptor, claim,
                 result: MaterialResult | None, rows, *, forced_unknown: bool = False):
        if forced_unknown:
            outcome = "unknown"
            evidence = {"materialOperation": "unknown"}
        else:
            outcome = {
                MaterialOutcome.SUCCESS: "concluded",
                MaterialOutcome.REFUSED: "refused",
                MaterialOutcome.UNKNOWN: "unknown",
            }[result.outcome]
            evidence = {"materialResult": _receipt_data(result)}
        mutations = self._usage_mutations(rows, operation, operation.request,
                                          material_request, outcome)
        try:
            return store.record_operation_step(
                operation.request, operation.digest, step.step_id,
                step.input_digest, claim.revision, outcome, evidence,
                usages=mutations,
            )
        except OperationRevisionConflict:
            current = store.read_operation_step(operation.request, step.step_id)
            if current is not None:
                return current
            raise GuaranteeUnavailableError("material result could not be durably associated") from None
        except Exception:
            raise GuaranteeUnavailableError("material result could not be durably recorded") from None

    def acquire(self, request: RequestKey, operation_digest: str, step_id: str) -> StepRecord:
        store = self._gate(request)
        operation = self._read_operation(store, request, operation_digest)
        step, material_request, descriptor, binding = self._fixed_facts(operation, step_id, request)
        existing = store.read_operation_step(request, step_id)
        if existing is not None:
            metadata, _ = self._provider(material_request)
            self._check_lifetime(metadata, descriptor)
            self._authorize_claim_read(request, operation, step, binding)
            self._usage_rows(store, operation, request, material_request, claimed=True)
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise GuaranteeUnavailableError("material step claim disappeared during authorized read")
            return current

        rows = self._usage_rows(store, operation, request, material_request, claimed=False)
        metadata, provider = self._provider(material_request)
        self._check_lifetime(metadata, descriptor)
        if not metadata.capability.query_acquire:
            raise GuaranteeUnavailableError("material provider cannot query a lost acquisition receipt")
        self._check_descriptor(provider, env_principal(self._environment), material_request, descriptor)
        current_metadata, current_provider = self._provider(material_request)
        if current_provider is not provider or current_metadata != metadata:
            raise AdmissionRefusedError("material provider pin changed before dispatch")

        claim = None
        try:
            context = self._issuer.issue(
                request, operation.digest, step.step_id, "acquire",
                binding["targetRef"], delegation_ref=None, cleanup=False,
            )
            claim = store.read_operation_step(request, step.step_id)
            if claim is None:
                raise GuaranteeUnavailableError("material dispatch claim is missing")
        except UnknownResultError:
            current = store.read_operation_step(request, step_id)
            if current is not None and claim is None:
                metadata, _ = self._provider(material_request)
                self._check_lifetime(metadata, descriptor)
                self._authorize_claim_read(request, operation, step, binding)
                self._usage_rows(store, operation, request, material_request, claimed=True)
                return store.read_operation_step(request, step_id)
            raise
        except Exception:
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise
            if claim is None:
                claim = current
            return self._persist(store, operation, step, material_request, descriptor,
                                 claim, None, rows, forced_unknown=True)

        # Once issue() has claimed the step, all failures while dispatching or
        # validating the callback result become the one original UNKNOWN
        # conclusion. Persistence itself is intentionally outside the catch so
        # a failed success write cannot be overwritten by a second UNKNOWN
        # write with a fresh CAS revision.
        try:
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed before dispatch")
            result_value = provider.resolve_material(_request_snapshot(material_request), context)
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed after dispatch")
            if not self._issuer.verified_consumption(context):
                raise GuaranteeUnavailableError("provider did not verify the original material invocation")
            result = _result_snapshot(result_value)
            self._check_result(result, material_request, descriptor)
        except Exception:
            return self._persist(store, operation, step, material_request, descriptor,
                                 claim, None, rows, forced_unknown=True)
        return self._persist(store, operation, step, material_request, descriptor,
                             claim, result, rows)

    def reconcile(self, request: RequestKey, operation_digest: str, step_id: str) -> StepRecord | None:
        store = self._gate(request)
        operation = self._read_operation(store, request, operation_digest)
        step, material_request, descriptor, binding = self._fixed_facts(operation, step_id, request)
        existing = store.read_operation_step(request, step_id)
        if existing is None:
            return None
        if existing.outcome in {"concluded", "refused"}:
            metadata, _ = self._provider(material_request)
            self._check_lifetime(metadata, descriptor)
            self._authorize_claim_read(request, operation, step, binding)
            self._usage_rows(store, operation, request, material_request, claimed=True)
            current = store.read_operation_step(request, step_id)
            if current is None:
                raise GuaranteeUnavailableError("material step claim disappeared during authorized read")
            return current

        claimed_step = existing
        rows = self._usage_rows(store, operation, request, material_request, claimed=True)
        metadata, provider = self._provider(material_request)
        self._check_lifetime(metadata, descriptor)
        self._authorize_claim_read(request, operation, step, binding)
        if not metadata.capability.query_acquire:
            return existing
        self._check_descriptor(provider, env_principal(self._environment), material_request, descriptor)
        current_metadata, current_provider = self._provider(material_request)
        if current_provider is not provider or current_metadata != metadata:
            raise AdmissionRefusedError("material provider pin changed before query")

        query = self._issuer.issue_query(request, operation.digest, step.step_id)
        current_metadata, current_provider = self._provider(material_request)
        if current_provider is not provider or current_metadata != metadata:
            raise AdmissionRefusedError("material provider pin changed before query")
        try:
            result_value = provider.query_material(_request_snapshot(material_request), query)
            current_metadata, current_provider = self._provider(material_request)
            if current_provider is not provider or current_metadata != metadata:
                raise AdmissionRefusedError("material provider pin changed after query")
            # The provider must verify the original claim under this query
            # ticket; a generic read observation cannot stand in for it.
            if not self._issuer.verified_observation(query):
                raise GuaranteeUnavailableError("provider did not verify the original material query")
            verifier = self._issuer.verifier()
            verifier.verify_claimed_query(query, step.pinned_provider_ref,
                                          binding["targetRef"], step.input_digest,
                                          operation_kind=operation.intent.kind)
            if not self._issuer.verified_observation(query):
                raise GuaranteeUnavailableError("provider did not verify the original material query")
            result = _result_snapshot(result_value)
            self._check_result(result, material_request, descriptor)
        except Exception:
            return self._persist(store, operation, step, material_request, descriptor,
                                 claimed_step, None, rows, forced_unknown=True)
        return self._persist(store, operation, step, material_request, descriptor,
                             claimed_step, result, rows)


def env_principal(environment) -> str:
    """Return only the Environment's trusted principal after open-state check."""
    with environment._admission_lock:
        environment._check_open()
        return environment._principal_scope


__all__ = [
    "AGENT_MATERIAL_OPERATION_CONTRACT_VERSION", "MaterialOperations",
    "material_provider_ref", "material_invocation_target",
    "material_operation_facts", "material_reservation_usages",
]

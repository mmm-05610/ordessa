"""Pure contract tests for the non-secret Agent material DTOs and port.

This file exercises closed data shapes and the optional provider capability
declaration only. It never resolves, queries, releases, or consumes material.
"""
from dataclasses import FrozenInstanceError, dataclass
import hashlib
import inspect
import json
from typing import ClassVar, get_type_hints

import pytest

from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.public import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    AuthorizedMaterialProvider,
    DirectoryBindingRef,
    InvocationContext,
    MaterialCapability,
    MaterialContractError,
    MaterialCorrelation,
    MaterialEvidenceRef,
    MaterialLeaseRef,
    MaterialObjectRef,
    MaterialProviderPin,
    MaterialReceipt,
    MaterialReleaseRequest,
    MaterialReleaseReceipt,
    MaterialReleaseResult,
    MaterialRequest,
    MaterialResult,
    MaterialUnavailable,
    ResourceMaterialDescriptor,
    ResourceRef,
    MaterialUseTarget,
    read_material_capability,
)
from pacthold.public import (
    CoreContributionSet, Environment, InstallationRecord, ReconcileSupport,
    ResourceProviderDescriptor,
)
from ordessa_units.admission.material_contracts import MaterialCapability as CoreMaterialCapability




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

_HEX = "a" * 64
_CONTENT_DIGEST = "sha256:" + _HEX


def _digest(value):
    return hashlib.sha256(safe_json(value).encode("utf-8")).hexdigest()


def _refs(environment="env", provider="provider.alpha"):
    activation = HarnessActivationRef(environment, "owner.alpha", 3)
    resource = ResourceRef(
        environment, provider, "sample.alpha@1", "model-material", "revision-7")
    pin = MaterialProviderPin(provider, "2.4.1", activation)
    directory = DirectoryBindingRef(
        environment, "directory.alpha", 4, _CONTENT_DIGEST)
    node = AgentNodeRef(environment, "planned-node-1", 2)
    target = MaterialUseTarget(node, directory, 9, "configure-model")
    return activation, resource, pin, directory, node, target


def _request(resource=None, pin=None, target=None, *, descriptor_digest=None,
             operation="operation-1", step="material.resolve", recovery="corr-1"):
    _, default_resource, default_pin, _, _, default_target = _refs()
    resource = resource or default_resource
    pin = pin or default_pin
    target = target or default_target
    descriptor_digest = descriptor_digest or _HEX
    facts = {
        "resourceRef": resource.to_dict(),
        "providerPin": pin.to_dict(),
        "target": target.to_dict(),
        "descriptorDigest": descriptor_digest,
    }
    correlation = MaterialCorrelation(
        operation, step, recovery, _digest(facts))
    return MaterialRequest(resource, pin, target, descriptor_digest, correlation)


def _lease(request=None):
    request = request or _request()
    return MaterialLeaseRef(
        "lease.alpha", request.resource_ref, request.provider_pin,
        request.target, request.correlation)


def _release_request(lease=None):
    lease = lease or _lease()
    facts = {"leaseRef": lease.to_dict()}
    correlation = MaterialCorrelation(
        "operation-1", "material.release", "release-corr-1", _digest(facts))
    return MaterialReleaseRequest(lease, correlation)


def _release_receipt(release=None):
    release = release or _release_request()
    environment = release.lease_ref.resource_ref.environment_namespace
    return MaterialReleaseReceipt(
        release.lease_ref, release.correlation,
        MaterialEvidenceRef(environment, "release-evidence.alpha", "rev-6"))


def _descriptor(resource=None):
    _, default_resource, _, _, _, _ = _refs()
    resource = resource or default_resource
    provenance = MaterialEvidenceRef(resource.environment_namespace, "source.alpha", "rev-2")
    evidence = MaterialEvidenceRef(resource.environment_namespace, "evidence.alpha", "rev-5")
    return ResourceMaterialDescriptor(
        resource, "model-config", "schema/1", _CONTENT_DIGEST,
        "copyComplete", "readOnly", provenance, evidence)


def _receipt(request=None):
    request = request or _request()
    lease = _lease(request)
    env = request.resource_ref.environment_namespace
    return MaterialReceipt(
        request.resource_ref, request.provider_pin, request.target,
        request.correlation, request.descriptor_digest,
        MaterialObjectRef(env, "material.object.alpha", "revision-8"),
        _CONTENT_DIGEST, "model-config", "schema/1", lease,
        MaterialEvidenceRef(env, "source.alpha", "rev-2"),
        MaterialEvidenceRef(env, "evidence.alpha", "rev-5"))


def _roundtrip(dto):
    assert type(dto).from_dict(dto.to_dict()) == dto


def _assert_no_effects(provider, *, describe_calls=0):
    assert provider.describe_calls == describe_calls
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    assert provider.material_effect_calls == {
        "describe_material": 0, "resolve_material": 0,
        "query_material": 0, "release_material": 0}


def test_public_exports_and_capability_type_identity():
    assert AGENT_MATERIAL_CONTRACT_VERSION == "agent-material/1"
    assert MaterialCapability is CoreMaterialCapability
    assert all(hasattr(__import__('ordessa_units.public', fromlist=[name]), name)
               for name in (
                   "ResourceRef", "MaterialProviderPin", "MaterialUseTarget",
                   "MaterialCorrelation", "MaterialObjectRef", "MaterialEvidenceRef",
                   "MaterialCapability", "ResourceMaterialDescriptor", "MaterialRequest",
                   "MaterialLeaseRef", "MaterialReceipt", "MaterialResult",
                   "MaterialReleaseRequest", "MaterialReleaseReceipt", "MaterialReleaseResult",
                   "AuthorizedMaterialProvider", "read_material_capability",
                   "MaterialContractError", "MaterialUnavailable"))


def test_identity_dtos_are_closed_frozen_and_roundtrip_with_separate_provider_pin():
    activation, resource, pin, directory, node, target = _refs()
    correlation = MaterialCorrelation("operation-1", "step-1", "corr-1", _HEX)
    object_ref = MaterialObjectRef("env", "opaque-material-1", "rev-1")
    evidence_ref = MaterialEvidenceRef("env", "evidence-1", "rev-2")

    for dto in (resource, pin, target, correlation, object_ref, evidence_ref):
        _roundtrip(dto)
        with pytest.raises(FrozenInstanceError):
            dto._mutation_probe = "changed"

    assert resource.provider_id == pin.provider_id
    assert resource.environment_namespace == pin.owner_activation.environment
    assert pin.owner_activation == activation
    assert pin.owner_activation is not activation
    assert type(target.node_ref) is AgentNodeRef
    assert target.node_ref == node
    assert target.directory_binding_ref == directory
    assert target.purpose == "configure-model"
    assert type(object_ref) is MaterialObjectRef
    assert type(evidence_ref) is MaterialEvidenceRef
    assert set(object_ref.to_dict()) == {
        "environmentNamespace", "materialId", "revision"}
    assert set(evidence_ref.to_dict()) == {
        "environmentNamespace", "referenceId", "revision"}


def test_activation_and_target_inputs_are_copied_and_wrong_environment_is_rejected():
    activation, resource, _, directory, node, _ = _refs()
    correlation = MaterialCorrelation("operation-1", "step-1", "corr-1", _HEX)
    activation_copy = HarnessActivationRef(
        activation.environment, activation.plugin_id, activation.generation)
    pin = MaterialProviderPin("provider.alpha", "2.4.1", activation_copy)
    assert pin.owner_activation is not activation_copy
    object.__setattr__(pin.owner_activation, "generation", 99)
    assert activation_copy.generation == 3

    target = MaterialUseTarget(node, directory, 9, "configure-model")
    assert target.node_ref is not node
    assert target.directory_binding_ref is not directory
    incoming = target.to_dict()
    incoming["nodeRef"]["generation"] = 88
    assert target.node_ref.generation == 2
    source = target.to_dict()
    copied_target = MaterialUseTarget.from_dict(source)
    source["nodeRef"]["generation"] = 77
    assert copied_target.node_ref.generation == 2

    with pytest.raises(MaterialContractError):
        MaterialUseTarget(
            AgentNodeRef("other", "planned-node-1", 2), directory, 9,
            "configure-model")
    with pytest.raises(MaterialContractError):
        MaterialRequest(resource, pin, target, _HEX, _request().correlation)
    with pytest.raises(MaterialContractError):
        _request(pin=MaterialProviderPin("provider.other", "2.4.1", activation))
    with pytest.raises(MaterialContractError):
        _request(resource=ResourceRef(
            "other", "provider.alpha", "sample.alpha@1", "model-material", "revision-7"))
    with pytest.raises(MaterialContractError):
        _request(pin=MaterialProviderPin(
            "provider.alpha", "2.4.1", HarnessActivationRef("other", "owner.alpha", 3)))
    with pytest.raises(MaterialContractError):
        MaterialUseTarget(node, DirectoryBindingRef(
            "other", "directory.alpha", 4, _CONTENT_DIGEST), 9, "configure-model")
    with pytest.raises(MaterialContractError):
        MaterialUseTarget(node, directory, True, "configure-model")

    assert set(correlation.to_dict()) == {
        "operationRef", "stepId", "recoveryCorrelation", "inputDigest"}
    with pytest.raises(MaterialContractError):
        ResourceRef("env", "provider.alpha", "sample.alpha", "m", "revision-1")
    with pytest.raises(MaterialContractError):
        ResourceRef("env", "provider.alpha", "sample.alpha@1", "m", "latest")
    with pytest.raises(MaterialContractError):
        MaterialCorrelation("operation-1", "step-1", "corr-1", "A" * 64)


def test_every_dto_from_dict_rejects_extra_fields_without_echoing_secret_values():
    dtos = (
        _refs()[1], _refs()[2], _refs()[5],
        MaterialCorrelation("operation-1", "step-1", "corr-1", _HEX),
        MaterialObjectRef("env", "opaque-1", "rev-1"),
        MaterialEvidenceRef("env", "evidence-1", "rev-1"),
        MaterialCapability(AGENT_MATERIAL_CONTRACT_VERSION,
                           ("copyComplete", "dynamic", "runtimeRequired"), True, "both"),
        _descriptor(), _request(), _lease(), _receipt(),
        MaterialResult("unknown", _request().correlation),
        _release_request(), _release_receipt(),
        MaterialReleaseResult("unknown", _release_request().correlation),
    )
    for dto in dtos:
        payload = dto.to_dict()
        for field, hostile_value in (
            ("unapprovedPayload", "MATERIAL_SECRET_CANARY"),
            ("secretRef", {"secret": "MATERIAL_SECRET_CANARY"}),
            ("bytesValue", b"MATERIAL_SECRET_CANARY"),
            ("path", "/private/material"),
            ("command", ["cat", "/private/material"]),
            ("callback", lambda: None),
        ):
            hostile = dict(payload)
            hostile[field] = hostile_value
            with pytest.raises(MaterialContractError) as error:
                type(dto).from_dict(hostile)
            assert "MATERIAL_SECRET_CANARY" not in str(error.value)


def test_capability_has_explicit_closed_contract_and_canonical_lifetimes():
    capability = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION,
        ("copyComplete", "dynamic", "runtimeRequired"), True, "both")
    _roundtrip(capability)
    assert capability.lifetimes == ("copyComplete", "dynamic", "runtimeRequired")
    assert type(capability.query_acquire) is bool
    assert set(capability.to_dict()) == {
        "contractVersion", "lifetimes", "queryAcquire", "releaseRecovery"}

    invalid = (
        (AGENT_MATERIAL_CONTRACT_VERSION, (), True, "both"),
        (AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic", "dynamic"), True, "both"),
        (AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic", "copyComplete"), True, "both"),
        ("agent-material/latest", ("dynamic",), True, "both"),
        (AGENT_MATERIAL_CONTRACT_VERSION, ("secretLifetime",), True, "both"),
        (AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic",), 1, "both"),
        (AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic",), True, "sometimes"),
    )
    for args in invalid:
        with pytest.raises(MaterialContractError):
            MaterialCapability(*args)

    no_query = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic",), False, "unsupported")
    assert no_query.query_acquire is False
    assert read_material_capability(_DeclaredMaterialProvider(no_query)).query_acquire is False
    incoming = capability.to_dict()
    incoming["lifetimes"] = list(incoming["lifetimes"])
    copied = MaterialCapability.from_dict(incoming)
    incoming["lifetimes"].append("lateMutation")
    assert copied.lifetimes == ("copyComplete", "dynamic", "runtimeRequired")


def test_material_descriptors_are_nonsecret_and_derive_their_own_digest():
    descriptor = _descriptor()
    _roundtrip(descriptor)
    assert len(descriptor.descriptor_digest) == 64
    assert descriptor.descriptor_digest == _digest(descriptor.to_dict())
    assert descriptor.provenance_ref.environment_namespace == "env"
    assert descriptor.evidence_ref.environment_namespace == "env"
    assert "descriptorDigest" not in descriptor.to_dict()

    for changed in (
        {"contentDigest": "not-a-sha256"},
        {"descriptorDigest": _HEX},
        {"payload": "MATERIAL_SECRET_CANARY"},
        {"path": "/private/material"},
        {"command": ["cat", "/private/material"]},
    ):
        payload = descriptor.to_dict()
        payload.update(changed)
        with pytest.raises(MaterialContractError) as error:
            ResourceMaterialDescriptor.from_dict(payload)
        assert "MATERIAL_SECRET_CANARY" not in str(error.value)

    with pytest.raises(MaterialContractError):
        ResourceMaterialDescriptor(
            ResourceRef("other", "provider.alpha", "sample.alpha@1", "m", "r1"),
            "model-config", "schema/1", _CONTENT_DIGEST, "copyComplete", "readOnly",
            descriptor.provenance_ref, descriptor.evidence_ref)
    for schema_version in ("/private/schema", "schema/../1"):
        payload = descriptor.to_dict()
        payload["schemaVersion"] = schema_version
        with pytest.raises(MaterialContractError):
            ResourceMaterialDescriptor.from_dict(payload)


def test_request_facts_bind_stable_refs_and_exclude_correlation_and_lease():
    request = _request()
    _roundtrip(request)
    assert set(request.input_facts()) == {
        "resourceRef", "providerPin", "target", "descriptorDigest"}
    assert request.input_digest == _digest(request.input_facts())
    assert request.correlation.input_digest == request.input_digest
    assert "leaseRef" not in request.to_dict()
    assert "handle" not in json.dumps(request.to_dict())

    base = request.input_digest
    variants = (
        _request(resource=ResourceRef("env", "provider.alpha", "sample.alpha@1",
                                      "other-resource", "revision-7")),
        _request(pin=MaterialProviderPin("provider.alpha", "2.4.2",
                                         HarnessActivationRef("env", "owner.alpha", 3))),
        _request(target=MaterialUseTarget(
            request.target.node_ref, request.target.directory_binding_ref, 10,
            "configure-model")),
        _request(target=MaterialUseTarget(
            request.target.node_ref, request.target.directory_binding_ref, 9,
            "configure-prompt")),
        _request(descriptor_digest="b" * 64),
    )
    assert all(item.input_digest != base for item in variants)
    different_query_correlation = _request(
        operation="operation-elsewhere", step="material.query", recovery="query-corr")
    assert different_query_correlation.input_digest == base
    wrong_correlation = MaterialCorrelation(
        "operation-1", "material.resolve", "corr-1", "0" * 64)
    with pytest.raises(MaterialContractError):
        MaterialRequest(request.resource_ref, request.provider_pin, request.target,
                        request.descriptor_digest, wrong_correlation)


def test_release_facts_cover_full_lease_and_use_a_new_correlation():
    request = _request()
    lease = _lease(request)
    _roundtrip(lease)
    release = _release_request(lease)
    _roundtrip(release)
    assert release.correlation != lease.acquisition_correlation
    assert set(release.input_facts()) == {"leaseRef"}
    assert release.input_facts()["leaseRef"] == lease.to_dict()
    assert release.input_digest == _digest({"leaseRef": lease.to_dict()})
    assert release.correlation.input_digest == release.input_digest
    another_release_correlation = MaterialCorrelation(
        "operation-elsewhere", "release-recovery", "release-corr-2", release.input_digest)
    assert MaterialReleaseRequest(lease, another_release_correlation).input_digest == release.input_digest
    same_step_new_operation = MaterialCorrelation(
        "operation-2", lease.acquisition_correlation.step_id,
        lease.acquisition_correlation.recovery_correlation, release.input_digest)
    assert MaterialReleaseRequest(lease, same_step_new_operation).input_digest == release.input_digest
    reused_identity = MaterialCorrelation(
        lease.acquisition_correlation.operation_ref,
        lease.acquisition_correlation.step_id,
        lease.acquisition_correlation.recovery_correlation,
        release.input_digest)
    with pytest.raises(MaterialContractError):
        MaterialReleaseRequest(lease, reused_identity)

    facts = {"leaseRef": lease.to_dict()}
    facts["leaseRef"]["leaseId"] = "lease.changed"
    assert _digest(facts) != release.input_digest
    bad_correlation = MaterialCorrelation(
        "operation-1", "material.release", "release-corr-1", _HEX)
    with pytest.raises(MaterialContractError):
        MaterialReleaseRequest(lease, bad_correlation)


def test_receipt_lease_and_result_outcomes_are_closed_and_identity_bound():
    request = _request()
    receipt = _receipt(request)
    _roundtrip(receipt)
    assert receipt.lease_ref.resource_ref == receipt.resource_ref
    assert receipt.lease_ref.provider_pin == receipt.provider_pin
    assert receipt.lease_ref.target == receipt.target
    assert receipt.lease_ref.acquisition_correlation == receipt.correlation
    assert receipt.immutable_material_ref.environment_namespace == "env"
    assert receipt.provenance_ref.environment_namespace == "env"
    assert receipt.evidence_ref.environment_namespace == "env"

    wrong_target = MaterialUseTarget(
        request.target.node_ref, request.target.directory_binding_ref,
        request.target.management_epoch + 1, request.target.purpose)
    wrong_lease = MaterialLeaseRef(
        receipt.lease_ref.lease_id, request.resource_ref, request.provider_pin,
        wrong_target, request.correlation)
    with pytest.raises(MaterialContractError):
        MaterialReceipt(
            request.resource_ref, request.provider_pin, request.target,
            request.correlation, request.descriptor_digest,
            receipt.immutable_material_ref, receipt.content_digest,
            receipt.material_type, receipt.schema_version, wrong_lease,
            receipt.provenance_ref, receipt.evidence_ref)
    with pytest.raises(MaterialContractError):
        MaterialReceipt(
            request.resource_ref, request.provider_pin, request.target,
            request.correlation, request.descriptor_digest,
            receipt.immutable_material_ref, "invalid", receipt.material_type,
            receipt.schema_version, receipt.lease_ref, receipt.provenance_ref,
            receipt.evidence_ref)

    success = MaterialResult("success", request.correlation, receipt)
    refused = MaterialResult("refused", request.correlation, error_code="DENIED")
    unknown = MaterialResult("unknown", request.correlation)
    for result in (success, refused, unknown):
        _roundtrip(result)
    assert success.receipt == receipt and success.error_code is None
    assert refused.receipt is None and refused.error_code == "DENIED"
    assert unknown.receipt is None and unknown.error_code is None

    malformed = (
        ("success", request.correlation, None, None),
        ("success", request.correlation, receipt, "DENIED"),
        ("refused", request.correlation, receipt, "DENIED"),
        ("refused", request.correlation, None, None),
        ("unknown", request.correlation, receipt, None),
        ("unknown", request.correlation, None, "DENIED"),
        ("mystery", request.correlation, None, None),
        ("refused", request.correlation, None, "SECRET CODE"),
        ("refused", request.correlation, None, "lowercase"),
        ("refused", request.correlation, None, "A" * 65),
    )
    for args in malformed:
        with pytest.raises(MaterialContractError) as error:
            MaterialResult(*args)
        assert "SECRET CODE" not in str(error.value)

    with pytest.raises(MaterialContractError):
        MaterialResult("success", MaterialCorrelation(
            "other-operation", "material.resolve", "corr-1", request.input_digest), receipt)

    assert set(unknown.to_dict()) == {"outcome", "correlation", "receipt", "errorCode"}
    assert unknown.to_dict()["receipt"] is None
    assert unknown.to_dict()["errorCode"] is None


def test_release_result_closes_success_refused_and_unknown_without_claiming_usage():
    release = _release_request()
    receipt = _release_receipt(release)
    _roundtrip(receipt)
    assert receipt.lease_ref == release.lease_ref
    assert receipt.correlation == release.correlation
    assert receipt.evidence_ref.environment_namespace == "env"
    results = (
        MaterialReleaseResult("success", release.correlation, receipt),
        MaterialReleaseResult("refused", release.correlation, error_code="DENIED"),
        MaterialReleaseResult("unknown", release.correlation),
    )
    for result in results:
        _roundtrip(result)
        assert set(result.to_dict()) == {"outcome", "correlation", "receipt", "errorCode"}
    assert results[0].receipt == receipt and results[0].error_code is None
    assert results[1].receipt is None and results[1].error_code == "DENIED"
    assert results[2].receipt is None and results[2].error_code is None
    for outcome, code in (("success", "DENIED"), ("unknown", "DENIED"),
                          ("refused", None), ("refused", "SECRET CODE"),
                          ("refused", "lowercase"), ("refused", "A" * 65)):
        with pytest.raises(MaterialContractError) as error:
            MaterialReleaseResult(
                outcome, release.correlation,
                receipt if outcome in {"unknown", "refused"} else None, code)
        assert "SECRET CODE" not in str(error.value)
    with pytest.raises(MaterialContractError):
        MaterialReleaseResult("success", release.correlation)
    foreign_correlation = MaterialCorrelation(
        "operation-other", release.correlation.step_id,
        release.correlation.recovery_correlation, release.input_digest)
    foreign_receipt = MaterialReleaseReceipt(
        release.lease_ref, foreign_correlation, receipt.evidence_ref)
    with pytest.raises(MaterialContractError):
        MaterialReleaseResult("success", release.correlation, foreign_receipt)
    with pytest.raises(MaterialContractError):
        MaterialReleaseReceipt(
            release.lease_ref, release.correlation,
            MaterialEvidenceRef("other", "release-evidence.alpha", "rev-6"))


def test_optional_protocol_uses_the_original_invocation_context_and_closed_query_union():
    hints = get_type_hints(AuthorizedMaterialProvider.describe_material)
    assert hints["return"] is ResourceMaterialDescriptor
    assert hints["resource_ref"] is ResourceRef
    assert hints["principal"] is str

    resolve_hints = get_type_hints(AuthorizedMaterialProvider.resolve_material)
    assert resolve_hints["request"] is MaterialRequest
    assert resolve_hints["invocation"] is InvocationContext
    assert resolve_hints["return"] is MaterialResult

    query_hints = get_type_hints(AuthorizedMaterialProvider.query_material)
    assert query_hints["request"] == MaterialRequest | MaterialReleaseRequest
    assert query_hints["invocation"] is InvocationContext
    assert query_hints["return"] == MaterialResult | MaterialReleaseResult
    assert "lease" not in inspect.signature(
        AuthorizedMaterialProvider.query_material).parameters
    assert "handle" not in inspect.signature(
        AuthorizedMaterialProvider.query_material).parameters

    release_hints = get_type_hints(AuthorizedMaterialProvider.release_material)
    assert release_hints["request"] is MaterialReleaseRequest
    assert release_hints["invocation"] is InvocationContext
    assert release_hints["return"] is MaterialReleaseResult


class _LegacyResourceProvider:
    provider_id = "provider.legacy"
    supported_contract_ids = frozenset({"sample.alpha@1"})

    def __init__(self):
        self.describe_calls = 0
        self.effect_calls = {name: 0 for name in ("acquire", "release", "reconcile")}
        self.material_effect_calls = {
            name: 0 for name in (
                "describe_material", "resolve_material", "query_material", "release_material")}

    def describe(self):
        self.describe_calls += 1
        return ResourceProviderDescriptor(
            self.provider_id, "Legacy provider", "1.0", ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        self.effect_calls["acquire"] += 1
        raise AssertionError("material capability discovery must not call C1 acquire")

    def release(self, request):
        self.effect_calls["release"] += 1
        raise AssertionError("material capability discovery must not call C1 release")

    def reconcile(self, request):
        self.effect_calls["reconcile"] += 1
        raise AssertionError("material capability discovery must not call C1 reconcile")


def test_absent_optional_capability_preserves_c1_registration_and_fails_closed():
    @dataclass(frozen=True)
    class AlphaContract:
        contract_id: ClassVar[str] = "sample.alpha@1"

    provider = _LegacyResourceProvider()
    env = Environment("env", resource_extension_snapshot=_test_resource_snapshot)
    owner = "owner.legacy"
    env.install(InstallationRecord(owner, "b" * 64))
    env.enable(owner)
    env.activate(owner, CoreContributionSet(
        contracts=(AlphaContract,), resource_providers=(provider,)))

    assert "provider.legacy" in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider("provider.legacy") == (owner, provider)
    describe_calls = provider.describe_calls
    with pytest.raises(MaterialUnavailable) as error:
        read_material_capability(provider)
    assert "MATERIAL_SECRET_CANARY" not in str(error.value)
    _assert_no_effects(provider, describe_calls=describe_calls)


class _DeclaredMaterialProvider(_LegacyResourceProvider):
    def __init__(self, capability=None):
        super().__init__()
        self._material_capability = capability or MaterialCapability(
            AGENT_MATERIAL_CONTRACT_VERSION,
            ("copyComplete", "dynamic", "runtimeRequired"), True, "both")

    @property
    def material_capability(self):
        return self._material_capability

    def describe_material(self, resource_ref, principal):
        self.material_effect_calls["describe_material"] += 1
        raise AssertionError("capability helper must not describe resources")

    def resolve_material(self, request, invocation):
        self.material_effect_calls["resolve_material"] += 1
        raise AssertionError("contract-only test must not resolve material")

    def query_material(self, request, invocation):
        self.material_effect_calls["query_material"] += 1
        raise AssertionError("contract-only test must not query material")

    def release_material(self, request, invocation):
        self.material_effect_calls["release_material"] += 1
        raise AssertionError("contract-only test must not release material")


def test_capability_helper_copies_declaration_and_never_calls_provider_methods():
    declared = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION,
        ("copyComplete", "dynamic", "runtimeRequired"), True, "both")
    provider = _DeclaredMaterialProvider(declared)
    copied = read_material_capability(provider)
    assert copied == declared
    assert copied is not declared
    object.__setattr__(declared, "query_acquire", False)
    assert copied.query_acquire is True
    _assert_no_effects(provider)


def test_malformed_optional_capability_or_missing_protocol_method_is_typed_refusal():
    legacy = _LegacyResourceProvider()

    class BadVersion(_DeclaredMaterialProvider):
        def __init__(self):
            super().__init__()
            object.__setattr__(self._material_capability,
                               "contract_version", "agent-material/2")

        @property
        def material_capability(self):
            return self._material_capability

    class MissingQuery(_DeclaredMaterialProvider):
        query_material = None

    class MissingC1Acquire(_DeclaredMaterialProvider):
        acquire = None

    class AttributeErrorCapability(_DeclaredMaterialProvider):
        @property
        def material_capability(self):
            raise AttributeError("MATERIAL_SECRET_CANARY")

    class RuntimeErrorCapability(_DeclaredMaterialProvider):
        @property
        def material_capability(self):
            raise RuntimeError("MATERIAL_SECRET_CANARY")

    class DynamicCapability(_LegacyResourceProvider):
        def __getattr__(self, name):
            if name == "material_capability":
                return MaterialCapability(
                    AGENT_MATERIAL_CONTRACT_VERSION,
                    ("copyComplete", "dynamic", "runtimeRequired"), True, "both")
            raise AttributeError(name)

    for provider, error_type in (
        (BadVersion(), MaterialContractError),
        (MissingQuery(), MaterialContractError),
        (MissingC1Acquire(), MaterialContractError),
        (AttributeErrorCapability(), MaterialContractError),
        (RuntimeErrorCapability(), MaterialContractError),
    ):
        with pytest.raises(error_type) as error:
            read_material_capability(provider)
        assert "agent-material/2" not in str(error.value)
        assert "MATERIAL_SECRET_CANARY" not in str(error.value)
        _assert_no_effects(provider)

    with pytest.raises(MaterialUnavailable):
        read_material_capability(legacy)
    with pytest.raises(MaterialUnavailable):
        read_material_capability(DynamicCapability())

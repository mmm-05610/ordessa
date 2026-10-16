"""021 authorized material read handoff and consumption-evidence release gate.

Controlled provider; kernel/store/issuer contract only. These tests prove the
freeze's §6 acceptance gates for the authorized-read handoff; they do not
represent a production material service, Harness, or native consumer. The
consumer admission port is a controlled fixture standing in for B's Registry
query (freeze §5); no configuration-consumer admission is fabricated.

Cold recovery is registered NOT_RUN: no rehydrate seam is claimed and no
Store/issuer is privately swapped; the same-generation refusal control is the
compensating guarantee.
"""
from dataclasses import dataclass
from typing import ClassVar
import hashlib

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    UnknownResultError,
)
from ordessa_execution_api.environment.operations import (
    OperationIntent,
    StepIntent,
    operation_holder,
    safe_json,
)
from ordessa_execution_api.environment.identity import ActivationRef, ParticipantInstanceRef
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import (
    InvocationAuthorityRefused,
    InvocationCurrentState,
    InvocationGrant,
    InvocationIssuer,
)
from ordessa_units.bindings.material_consumption import (
    AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
    MaterialConsumption,
    MaterialReleaseGateDecision,
    READ_ACTION,
)
from ordessa_units.bindings.material_operations import (
    MaterialOperations,
    material_invocation_target,
    material_operation_facts,
    material_provider_ref,
    material_reservation_usages,
)
from ordessa_units.bindings.materials import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialAccessMode,
    MaterialCapability,
    MaterialConsumerPin,
    MaterialConsumptionEvidence,
    MaterialCorrelation,
    MaterialEvidenceRef,
    MaterialLeaseRef,
    MaterialLifetime,
    MaterialObjectRef,
    MaterialOutcome,
    MaterialProviderPin,
    MaterialReadResult,
    MaterialReceipt,
    MaterialResult,
    MaterialReleaseReceipt,
    MaterialReleaseRequest,
    MaterialReleaseResult,
    MaterialRequest,
    MaterialUseTarget,
    ResourceMaterialDescriptor,
    ResourceRef,
)
from pacthold.public import (
    CoreContributionSet,
    Environment,
    InstallationRecord,
    ReconcileSupport,
    ResourceProviderDescriptor,
)




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

_ENV = "env"
_PRINCIPAL = "principal"
_OUTER_DIGEST = "operation-request-digest"
_READ_DIGEST = "handoff-request-digest"
_CONTRACT_ID = "sample.alpha@1"
_ACQUIRE_STEP = "material-fetch"
_READ_STEP = "material-read"
_RELEASE_STEP = "material-release"
_OPERATION_KIND = "material-consumption-fixture"
_CANARY = "CANARY-MATERIAL-BODY-9f3a7e21"
_CONSUMER_ID = "consumer.host"
_CONSUMER_VERSION = "1.0"


@dataclass(frozen=True)
class AlphaContract:
    contract_id: ClassVar[str] = _CONTRACT_ID


class ReadPolicy:
    def __init__(self, environment=_ENV, *, allowed=True):
        self.object_ref = f"{environment}:agents.resources"
        self.allowed = allowed
        self.calls = []

    def admit_object_access(self, principal, object_ref, permission):
        self.calls.append((principal, object_ref, permission))
        return (self.allowed and principal == _PRINCIPAL
                and object_ref == self.object_ref and permission == "read")


class Authority:
    issuer_ref = {"environmentNamespace": _ENV, "issuerId": "controlled-authority"}

    def __init__(self):
        self.revision = "authority-rev-1"
        self.allowed = True

    def authorize(self, request, actions, target_ref, delegation_ref):
        if not self.allowed:
            raise PermissionError("controlled authorization refusal")
        return InvocationGrant(
            principal_scope=request.principal_scope,
            delegation_ref=delegation_ref,
            actions=actions,
            target_ref=target_ref,
            authority_revision=self.revision,
            expires_at=100,
            issuer_ref=self.issuer_ref,
        )

    def revalidate(self, grant, request, actions, target_ref):
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class CurrentState:
    def __init__(self, provider_ref, directory_ref, *, epoch=4,
                 acquired_target_ref=None, acquisition_evidence_ref=None):
        self.provider_ref = provider_ref
        self.directory_ref = directory_ref
        self.active = True
        self.epoch = epoch
        self.permitted = True
        self.acquired_target_ref = acquired_target_ref
        self.acquisition_evidence_ref = acquisition_evidence_ref

    def inspect(self, request, provider_ref, context_ref, target_ref, action):
        return InvocationCurrentState(
            self.provider_ref, self.active, self.epoch, self.directory_ref,
            self.permitted, self.acquired_target_ref, self.acquisition_evidence_ref,
        )


class AdmittedConsumerFixture:
    """Controlled stand-in for B's Registry admission query (freeze §5).

    Returns the admission-side copied consumer pin; never fabricates
    configuration-consumer admission for unknown identities.
    """

    def __init__(self, admitted_pin):
        self.admitted_pin = admitted_pin
        self.lookups = []

    def admitted_consumer_pin(self, consumer_id, consumer_version):
        self.lookups.append((consumer_id, consumer_version))
        if ((consumer_id, consumer_version)
                == (self.admitted_pin.consumer_id, self.admitted_pin.consumer_version)):
            return self.admitted_pin
        return None


class ControlledMaterialProvider:
    """Registered provider fixture with verifier-bound, inspectable counters."""

    def __init__(self, provider_id, capability, *, version="1.0"):
        self.provider_id = provider_id
        self.display_name = "Controlled material fixture"
        self.version = version
        self.supported_contract_ids = frozenset({_CONTRACT_ID})
        self.material_capability = capability
        self.descriptor = None
        self.verifier = None
        self.operation_kind = _OPERATION_KIND
        self.material_target = None
        self.material_provider = None
        self.resolve_response = None
        self.acquisition_receipt = None
        self.read_calls = 0
        self.release_calls = 0
        self.content_reads = 0
        self.content_body = _CANARY
        self.query_calls = 0
        self.describe_material_calls = 0
        self.c1_calls = {"acquire": 0, "release": 0, "reconcile": 0}
        self.verify_calls = []
        self.on_read = None

    def describe(self):
        return ResourceProviderDescriptor(
            self.provider_id, self.display_name, self.version, ReconcileSupport.SUPPORTED
        )

    def acquire(self, request):
        self.c1_calls["acquire"] += 1
        raise AssertionError("material coordination must not fall back to C1 acquire")

    def release(self, request):
        self.c1_calls["release"] += 1
        raise AssertionError("material coordination must not fall back to C1 release")

    def reconcile(self, request):
        self.c1_calls["reconcile"] += 1
        raise AssertionError("material coordination must not fall back to C1 reconcile")

    def describe_material(self, resource_ref, principal):
        self.describe_material_calls += 1
        assert principal == _PRINCIPAL
        return self.descriptor

    def _verify(self, invocation, request, action):
        assert self.verifier is not None
        provider_ref = self.material_provider
        target_ref = self.material_target
        facts = self.verifier.verify_and_consume(
            invocation, action, provider_ref, target_ref, request.input_digest)
        self.verify_calls.append((action, facts["request"]["requestId"]))

    def resolve_material(self, request, invocation):
        self._verify(invocation, request, "acquire")
        result = _success_result(request, self.descriptor)
        self.acquisition_receipt = result.receipt
        return self.resolve_response or result

    def read_material(self, request, invocation):
        self.read_calls += 1
        self._verify(invocation, request, READ_ACTION)
        if self.on_read is not None:
            self.on_read()
        self.content_reads += 1
        _ = self.content_body  # content access counted; body never leaves
        receipt = self.acquisition_receipt
        return MaterialReadResult(
            MaterialOutcome.SUCCESS, request.correlation,
            receipt.immutable_material_ref, receipt.content_digest,
            receipt.evidence_ref, None)

    def query_material(self, request, invocation):
        self.query_calls += 1
        raise AssertionError("read handoff must not use query semantics")

    def release_material(self, request, invocation):
        self.release_calls += 1
        self._verify(invocation, request, "release")
        return MaterialReleaseResult(
            MaterialOutcome.SUCCESS, request.correlation,
            receipt=MaterialReleaseReceipt(
                request.lease_ref, request.correlation,
                MaterialEvidenceRef(_ENV, "fixture-release-evidence", "1")))


def _descriptor(resource_ref, lifetime=MaterialLifetime.COPY_COMPLETE):
    return ResourceMaterialDescriptor(
        resource_ref,
        "fixture.material",
        "schema/1",
        "sha256:" + "1" * 64,
        lifetime,
        MaterialAccessMode.READ_ONLY,
        MaterialEvidenceRef(_ENV, "fixture-provenance", "1"),
        MaterialEvidenceRef(_ENV, "fixture-description", "1"),
    )


def _success_result(request, descriptor):
    lease = MaterialLeaseRef(
        "lease-fixture", request.resource_ref, request.provider_pin,
        request.target, request.correlation,
    )
    receipt = MaterialReceipt(
        request.resource_ref, request.provider_pin, request.target,
        request.correlation, descriptor.descriptor_digest,
        MaterialObjectRef(_ENV, "opaque-material", "1"),
        descriptor.content_digest, descriptor.material_type,
        descriptor.schema_version, lease, descriptor.provenance_ref,
        MaterialEvidenceRef(_ENV, "fixture-acquisition-evidence", "1"),
    )
    return MaterialResult(MaterialOutcome.SUCCESS, request.correlation, receipt=receipt)


def _make_material_request(resource_ref, pin, target, descriptor, *, operation_ref, step_id):
    facts = {
        "resourceRef": resource_ref.to_dict(),
        "providerPin": pin.to_dict(),
        "target": target.to_dict(),
        "descriptorDigest": descriptor.descriptor_digest,
    }
    input_digest = hashlib.sha256(safe_json(facts).encode("utf-8")).hexdigest()
    correlation = MaterialCorrelation(
        operation_ref, step_id, f"recovery-{operation_ref}-{step_id}", input_digest
    )
    return MaterialRequest(resource_ref, pin, target, descriptor.descriptor_digest, correlation)


def _acquisition_evidence(receipt):
    return {
        "immutableMaterialRef": receipt.immutable_material_ref.to_dict(),
        "contentDigest": receipt.content_digest,
        "evidenceRef": receipt.evidence_ref.to_dict(),
        "provenanceRef": receipt.provenance_ref.to_dict(),
    }


def _release_input_digest(expected_lease):
    return hashlib.sha256(safe_json({"leaseRef": expected_lease.to_dict()}).encode("utf-8")).hexdigest()


def _setup(tmp_path, *, provider_lifetimes=("copyComplete",),
           descriptor_lifetime=None, request_id="material-handoff"):
    if descriptor_lifetime is None:
        descriptor_lifetime = MaterialLifetime(provider_lifetimes[0])
    db_path = tmp_path / f"{request_id}.sqlite"
    store = SqliteStorePort(db_path)
    policy = ReadPolicy()
    environment = Environment(
        _ENV, store=store, policy=policy, principal_scope=_PRINCIPAL
    , resource_extension_snapshot=_test_resource_snapshot)
    environment.install(InstallationRecord("contracts.owner", "a" * 64))
    environment.enable("contracts.owner")
    environment.activate("contracts.owner", CoreContributionSet(contracts=(AlphaContract,)))

    capability = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION, tuple(provider_lifetimes), True, "both")
    provider = ControlledMaterialProvider("provider.material", capability)
    owner_id = "owner.material"
    environment.install(InstallationRecord(owner_id, "b" * 64))
    environment.enable(owner_id)
    activation = environment.activate(
        owner_id, CoreContributionSet(resource_providers=(provider,))
    ).activation

    consumer_id = "owner.consumer"
    environment.install(InstallationRecord(consumer_id, "c" * 64))
    environment.enable(consumer_id)
    consumer_activation = environment.activate(
        consumer_id, CoreContributionSet()
    ).activation
    consumer_pin = MaterialConsumerPin(_CONSUMER_ID, _CONSUMER_VERSION, consumer_activation)
    admitted_consumer = AdmittedConsumerFixture(consumer_pin)

    authority = Authority()
    directory = DirectoryBindingRef(_ENV, "binding", 1, "sha256:" + "a" * 64)
    resource_ref = ResourceRef(_ENV, provider.provider_id, _CONTRACT_ID, "resource-fixture", "r1")
    pin = MaterialProviderPin(provider.provider_id, provider.version, activation)
    target = MaterialUseTarget(
        ParticipantInstanceRef(_ENV, "planned-node", 1), directory, 4, "profile-material")
    fixed_descriptor = _descriptor(resource_ref, descriptor_lifetime)

    op_ref = f"operation-{request_id}"
    acquire_request = _make_material_request(
        resource_ref, pin, target, fixed_descriptor,
        operation_ref=op_ref, step_id=_ACQUIRE_STEP,
    )
    release_request = MaterialRequest(
        resource_ref, pin, target, fixed_descriptor.descriptor_digest,
        MaterialCorrelation(op_ref, _RELEASE_STEP,
                            f"recovery-{op_ref}-{_RELEASE_STEP}",
                            acquire_request.input_digest),
    )
    expected_lease = MaterialLeaseRef(
        "lease-fixture", resource_ref, pin, target, acquire_request.correlation)
    read_op_ref = f"operation-{request_id}-read"
    read_request = MaterialRequest(
        resource_ref, pin, target, fixed_descriptor.descriptor_digest,
        MaterialCorrelation(read_op_ref, _READ_STEP,
                            f"recovery-{read_op_ref}-{_READ_STEP}",
                            acquire_request.input_digest),
    )

    context = {
        "environmentNamespace": _ENV,
        "directoryBindingRef": directory.to_dict(),
        "materialRequests": {
            _ACQUIRE_STEP: material_operation_facts(acquire_request, fixed_descriptor),
        },
        "materialReleases": {
            _RELEASE_STEP: {
                "contractVersion": AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
                "request": release_request.to_dict(),
                "consumerPin": consumer_pin.to_dict(),
                "originalStepId": _ACQUIRE_STEP,
                "readStepRef": {
                    "environmentNamespace": _ENV,
                    "principalScope": _PRINCIPAL,
                    "requestId": f"{request_id}-read",
                    "operationDigest": _READ_DIGEST,
                    "stepId": _READ_STEP,
                },
            },
        },
        "invocationBindings": {
            _ACQUIRE_STEP: {"action": "acquire",
                            "targetRef": material_invocation_target(acquire_request),
                            "delegationRef": None, "cleanup": False},
            _RELEASE_STEP: {"action": "release",
                            "targetRef": material_invocation_target(acquire_request),
                            "delegationRef": None, "cleanup": True},
        },
    }
    node_ref = {"environmentNamespace": _ENV, "instanceId": "planned-node", "generation": 1}
    intent = OperationIntent(
        op_ref, _OPERATION_KIND, None, context,
        (StepIntent(_ACQUIRE_STEP, material_provider_ref(pin),
                    acquire_request.input_digest,
                    acquire_request.correlation.recovery_correlation,
                    management_epoch=4),
         StepIntent(_RELEASE_STEP, material_provider_ref(pin),
                    _release_input_digest(expected_lease),
                    f"recovery-{op_ref}-{_RELEASE_STEP}",
                    prerequisite_steps=(_ACQUIRE_STEP,), management_epoch=4)),
        node_ref, 4,
    )
    request_key = RequestKey(_ENV, _PRINCIPAL, request_id)
    store.reserve_operation(
        request_key, _OUTER_DIGEST, intent,
        usages=material_reservation_usages(request_key, acquire_request),
    )

    current = CurrentState(
        material_provider_ref(pin), directory, epoch=4,
        acquired_target_ref=material_invocation_target(acquire_request),
        acquisition_evidence_ref={"environmentNamespace": _ENV,
                                  "evidenceId": "fixture-acquisition"},
    )
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    operations = MaterialOperations(environment, invocation_issuer=issuer)
    consumption = MaterialConsumption(
        environment, invocation_issuer=issuer, admitted_consumer=admitted_consumer)

    provider.descriptor = fixed_descriptor
    provider.material_provider = material_provider_ref(pin)
    provider.material_target = material_invocation_target(acquire_request)
    provider.verifier = issuer.verifier()

    return {
        "db_path": db_path,
        "store": store,
        "environment": environment,
        "policy": policy,
        "provider": provider,
        "activation": activation,
        "consumer_activation": consumer_activation,
        "consumer_pin": consumer_pin,
        "admitted_consumer": admitted_consumer,
        "authority": authority,
        "directory": directory,
        "resource_ref": resource_ref,
        "pin": pin,
        "target": target,
        "descriptor": fixed_descriptor,
        "acquire_request": acquire_request,
        "release_request": release_request,
        "read_request": read_request,
        "expected_lease": expected_lease,
        "request_key": request_key,
        "op_ref": op_ref,
        "read_op_ref": read_op_ref,
        "issuer": issuer,
        "operations": operations,
        "consumption": consumption,
    }


def _acquire(parts):
    step = parts["operations"].acquire(
        parts["request_key"], _OUTER_DIGEST, _ACQUIRE_STEP)
    assert step.outcome == "concluded"
    return step


def _reserve_read(parts, *, tamper=None):
    """Reserve the handoff operation K2 with one read step."""
    tamper = tamper or {}
    store = parts["store"]
    read_request = tamper.get("read_request", parts["read_request"])
    consumer_pin = tamper.get("consumer_pin", parts["consumer_pin"])
    acquisition_evidence = tamper.get(
        "acquisition_evidence", _acquisition_evidence(parts["provider"].acquisition_receipt))
    original_step_ref = {
        "environmentNamespace": _ENV,
        "principalScope": _PRINCIPAL,
        "requestId": parts["request_key"].request_id,
        "operationDigest": _OUTER_DIGEST,
        "stepId": _ACQUIRE_STEP,
    }
    context = {
        "environmentNamespace": _ENV,
        "directoryBindingRef": parts["directory"].to_dict(),
        "materialReads": {
            _READ_STEP: {
                "contractVersion": AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
                "request": read_request.to_dict(),
                "consumerPin": consumer_pin.to_dict(),
                "acquisitionEvidence": acquisition_evidence,
                "originalStepRef": original_step_ref,
            },
        },
        "invocationBindings": {
            _READ_STEP: {"action": READ_ACTION,
                         "targetRef": material_invocation_target(read_request),
                         "delegationRef": None, "cleanup": False},
        },
    }
    intent = OperationIntent(
        parts["read_op_ref"], _OPERATION_KIND, None, context,
        (StepIntent(_READ_STEP, material_provider_ref(parts["pin"]),
                    read_request.input_digest,
                    read_request.correlation.recovery_correlation,
                    management_epoch=4),),
        {"environmentNamespace": _ENV, "instanceId": "planned-node", "generation": 1},
        4,
    )
    read_key = RequestKey(_ENV, _PRINCIPAL, f"{parts['request_key'].request_id}-read")
    store.reserve_operation(read_key, _READ_DIGEST, intent)
    return read_key


def _usage_rows(parts, holder):
    return parts["store"].read_usages(_ENV, holder)


def _hold_rows(parts):
    holder = operation_holder(parts["request_key"], parts["op_ref"])
    rows = _usage_rows(parts, holder)
    prefix = f"{parts['op_ref']}.material.{_ACQUIRE_STEP}"
    return {row["usageId"]: row for row in rows
            if row["usageId"].startswith(prefix)}


def _assert_holds_active(parts, revision=2):
    holds = _hold_rows(parts)
    assert len(holds) == 2
    for row in holds.values():
        assert row["state"] == "active"
        assert row["revision"] == revision


def _assert_holds_released(parts, revision=3):
    holds = _hold_rows(parts)
    assert len(holds) == 2
    for row in holds.values():
        assert row["state"] == "released"
        assert row["revision"] == revision


def _close(parts):
    parts["issuer"].close()
    parts["environment"].close()
    parts["store"].close()


def test_authorized_read_success_checks_original_receipt_and_counts_content_reads(tmp_path):
    parts = _setup(tmp_path, request_id="read-success")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "concluded"
        receipt = parts["provider"].acquisition_receipt
        evidence = step.evidence["materialReadResult"]
        assert evidence["outcome"] == "success"
        assert evidence["immutableMaterialRef"] == receipt.immutable_material_ref.to_dict()
        assert evidence["contentDigest"] == receipt.content_digest
        assert evidence["evidenceRef"] == receipt.evidence_ref.to_dict()
        # Read success carries no lease and no body (§3); success stands on
        # pointer match alone (§6.2: no-lease is not no-resource).
        assert "leaseRef" not in evidence
        assert _CANARY.encode() not in safe_json(evidence).encode()
        assert parts["provider"].read_calls == 1
        assert parts["provider"].content_reads == 1
        assert parts["provider"].query_calls == 0
        assert parts["provider"].c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
        _assert_holds_active(parts)
        # Replay of a recorded read revalidates and returns; no re-resolve,
        # no query ticket, no second content read (§6.2/§6.4).
        replay = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert replay == step
        assert parts["provider"].read_calls == 1
        assert parts["provider"].content_reads == 1
        assert parts["provider"].query_calls == 0
    finally:
        _close(parts)


def _tampered_read_request(parts, *, purpose=None, binding_id=None, epoch=None,
                           provider_version=None):
    request = parts["acquire_request"]
    target = request.target
    if purpose is not None:
        target = MaterialUseTarget(
            target.node_ref, target.directory_binding_ref,
            target.management_epoch, purpose)
    if binding_id is not None:
        target = MaterialUseTarget(
            target.node_ref,
            DirectoryBindingRef(_ENV, binding_id, 2, "sha256:" + "b" * 64),
            target.management_epoch, target.purpose)
    if epoch is not None:
        target = MaterialUseTarget(
            target.node_ref, target.directory_binding_ref, epoch, target.purpose)
    pin = parts["pin"]
    if provider_version is not None:
        pin = MaterialProviderPin(pin.provider_id, provider_version,
                                  pin.owner_activation)
    return _make_material_request(
        request.resource_ref, pin, target, parts["descriptor"],
        operation_ref=parts["read_op_ref"], step_id=_READ_STEP)


@pytest.mark.parametrize("tamper", ["purpose", "directory", "epoch",
                                    "provider-version", "acquisition-evidence",
                                    "wrong-issuer"])
def test_read_refusals_pre_claim(tmp_path, tamper):
    parts = _setup(tmp_path, request_id=f"read-refusal-{tamper}")
    try:
        _acquire(parts)
        overrides = {}
        if tamper == "purpose":
            overrides["read_request"] = _tampered_read_request(parts, purpose="tampered-purpose")
        elif tamper == "directory":
            overrides["read_request"] = _tampered_read_request(parts, binding_id="changed-binding")
        elif tamper == "epoch":
            overrides["read_request"] = _tampered_read_request(parts, epoch=99)
        elif tamper == "provider-version":
            overrides["read_request"] = _tampered_read_request(parts, provider_version="9.9")
        elif tamper == "acquisition-evidence":
            receipt = parts["provider"].acquisition_receipt
            tampered = _acquisition_evidence(receipt)
            tampered["contentDigest"] = "sha256:" + "2" * 64
            overrides["acquisition_evidence"] = tampered
        read_key = _reserve_read(parts, tamper=overrides)

        if tamper == "wrong-issuer":
            other_store = SqliteStorePort(tmp_path / "other.sqlite")
            try:
                other_authority = Authority()
                other_current = CurrentState(
                    material_provider_ref(parts["pin"]), parts["directory"], epoch=4,
                    acquired_target_ref=material_invocation_target(parts["acquire_request"]),
                    acquisition_evidence_ref={"environmentNamespace": _ENV,
                                              "evidenceId": "fixture-acquisition"})
                other_issuer = InvocationIssuer(other_store, other_authority, other_current,
                                                clock=lambda: 50)
                wrong = MaterialConsumption(
                    parts["environment"], invocation_issuer=other_issuer,
                    admitted_consumer=parts["admitted_consumer"])
                with pytest.raises((InvocationAuthorityRefused, GuaranteeUnavailableError)):
                    wrong.read(read_key, _READ_DIGEST, _READ_STEP)
            finally:
                other_store.close()
        else:
            with pytest.raises((AdmissionRefusedError, IdentityMismatchError,
                                GuaranteeUnavailableError)):
                parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)

        assert parts["store"].read_operation_step(read_key, _READ_STEP) is None
        assert parts["provider"].read_calls == 0
        assert parts["provider"].content_reads == 0
        assert parts["provider"].c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
        _assert_holds_active(parts)
    finally:
        _close(parts)


@pytest.mark.parametrize("case", ["self-reported-id", "self-reported-version",
                                  "cross-env", "different-generation"])
def test_consumer_pin_refusals(tmp_path, case):
    parts = _setup(tmp_path, request_id=f"pin-refusal-{case}")
    try:
        _acquire(parts)
        consumer_pin = parts["consumer_pin"]
        if case == "self-reported-id":
            bad = MaterialConsumerPin("evil.host", consumer_pin.consumer_version,
                                      consumer_pin.owner_activation)
        elif case == "self-reported-version":
            bad = MaterialConsumerPin(consumer_pin.consumer_id, "9.9",
                                      consumer_pin.owner_activation)
        elif case == "cross-env":
            bad = MaterialConsumerPin(consumer_pin.consumer_id, consumer_pin.consumer_version,
                                      ActivationRef("other-env", "consumer.host", 3))
        else:
            bad = MaterialConsumerPin(consumer_pin.consumer_id, consumer_pin.consumer_version,
                                      ActivationRef(_ENV, "consumer.host", 99))
        read_key = _reserve_read(parts, tamper={"consumer_pin": bad})
        with pytest.raises((AdmissionRefusedError, IdentityMismatchError)):
            parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert parts["store"].read_operation_step(read_key, _READ_STEP) is None
        assert parts["provider"].read_calls == 0
        assert parts["provider"].content_reads == 0
        _assert_holds_active(parts)
    finally:
        _close(parts)


def test_unknown_read_does_not_resolve_again_and_no_lease_is_not_no_resource(tmp_path):
    parts = _setup(tmp_path, request_id="read-unknown")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)

        def controlled_failure():
            raise RuntimeError("controlled read dispatch failure")

        parts["provider"].on_read = controlled_failure
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "unknown"
        assert step.evidence == {"materialReadOperation": "unknown"}
        assert parts["provider"].read_calls == 1
        assert parts["provider"].content_reads == 0
        # Unknown does not re-resolve and never falls back to query (§6.2/§6.4).
        replay = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert replay == step
        assert parts["provider"].read_calls == 1
        assert parts["provider"].query_calls == 0
        assert parts["provider"].content_reads == 0
        _assert_holds_active(parts)
        # Unknown keeps its hold: the original occupation is untouched.
        _assert_holds_active(parts)
    finally:
        _close(parts)


def test_read_success_is_not_consumption_and_release_holds_without_owner_evidence(tmp_path):
    parts = _setup(tmp_path, request_id="read-not-consumption")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "concluded"
        # Read success is not consumption: without owner consumption evidence
        # the copyComplete release gate holds and lists the remaining (§6.2/§4).
        decision = parts["consumption"].release(
            parts["request_key"], _OUTER_DIGEST, _RELEASE_STEP,
            consumption_evidence=None)
        assert isinstance(decision, MaterialReleaseGateDecision)
        assert decision.released is False
        assert "owner-consumption-evidence" in decision.remaining
        assert decision.step_record is None
        assert parts["store"].read_operation_step(parts["request_key"], _RELEASE_STEP) is None
        _assert_holds_active(parts)
        assert parts["provider"].release_calls == 0
        assert parts["provider"].c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_copy_complete_release_with_verified_consumption_evidence(tmp_path):
    parts = _setup(tmp_path, request_id="release-copy-complete")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "concluded"
        receipt = parts["provider"].acquisition_receipt
        evidence = MaterialConsumptionEvidence(
            receipt.immutable_material_ref,
            parts["consumer_pin"],
            parts["target"],
            parts["read_request"].correlation,
            MaterialEvidenceRef(_ENV, "runtime-owner-consumption", "1"),
        )
        decision = parts["consumption"].release(
            parts["request_key"], _OUTER_DIGEST, _RELEASE_STEP,
            consumption_evidence=evidence)
        assert decision.released is True
        assert decision.remaining == ()
        assert decision.step_record is not None
        assert decision.step_record.outcome == "concluded"
        release_evidence = decision.step_record.evidence["materialReleaseResult"]
        assert release_evidence["outcome"] == "success"
        assert release_evidence["receipt"]["leaseRef"] == receipt.lease_ref.to_dict()
        _assert_holds_released(parts)
        assert parts["provider"].release_calls == 1
        assert parts["provider"].content_reads == 1
        assert parts["provider"].c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


@pytest.mark.parametrize("lifetime,remaining", [
    (MaterialLifetime.RUNTIME_REQUIRED, "runtime-stop-replace-evidence"),
    (MaterialLifetime.DYNAMIC, "dynamic-a-route-binding"),
])
def test_release_gate_holds_unproven_lifetimes(tmp_path, lifetime, remaining):
    parts = _setup(
        tmp_path,
        provider_lifetimes=(lifetime.value,),
        descriptor_lifetime=lifetime,
        request_id=f"release-hold-{lifetime.value.lower()}",
    )
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "concluded"
        receipt = parts["provider"].acquisition_receipt
        evidence = MaterialConsumptionEvidence(
            receipt.immutable_material_ref,
            parts["consumer_pin"],
            parts["target"],
            parts["read_request"].correlation,
            MaterialEvidenceRef(_ENV, "runtime-owner-consumption", "1"),
        )
        decision = parts["consumption"].release(
            parts["request_key"], _OUTER_DIGEST, _RELEASE_STEP,
            consumption_evidence=evidence)
        assert decision.released is False
        assert remaining in decision.remaining
        assert decision.step_record is None
        assert parts["store"].read_operation_step(parts["request_key"], _RELEASE_STEP) is None
        _assert_holds_active(parts)
        assert parts["provider"].release_calls == 0
    finally:
        _close(parts)


def test_read_and_query_ticket_semantic_isolation(tmp_path):
    parts = _setup(tmp_path, request_id="read-query-isolation")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        target = material_invocation_target(parts["read_request"])
        provider_ref = material_provider_ref(parts["pin"])
        input_digest = parts["read_request"].input_digest
        issuer = parts["issuer"]
        verifier = issuer.verifier()

        # A read ticket cannot serve as a query receipt lookup (§6.4).
        ctx_read = issuer.issue(
            read_key, _READ_DIGEST, _READ_STEP, READ_ACTION, target,
            delegation_ref=None, cleanup=False)
        with pytest.raises(InvocationAuthorityRefused):
            verifier.verify_and_consume(
                ctx_read, "query", provider_ref, target, input_digest)
        with pytest.raises(InvocationAuthorityRefused):
            verifier.verify_claimed_query(
                ctx_read, provider_ref, target, input_digest,
                operation_kind=_OPERATION_KIND)

        # A query ticket cannot authorize a read (§6.4).
        ctx_query = issuer.issue_query(read_key, _READ_DIGEST, _READ_STEP)
        with pytest.raises(InvocationAuthorityRefused):
            verifier.verify_and_consume(
                ctx_query, READ_ACTION, provider_ref, target, input_digest)

        # Flow-level: the read step is already claimed above; a replay of a
        # claimed step returns the durable record without re-dispatch and
        # without any query fallback (§6.2/§6.4). The provider guard raises
        # if the flow ever called query_material.
        parts["provider"].on_read = None
        replay = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert replay.outcome == "possibly-dispatched"
        assert parts["provider"].query_calls == 0
        assert parts["provider"].read_calls == 0
        verify_actions = [action for action, _ in parts["provider"].verify_calls]
        assert "query" not in verify_actions
    finally:
        _close(parts)


def test_cold_recovery_gap_registered_not_run(tmp_path):
    """Cold recovery is registered NOT_RUN; no capability is claimed.

    The compensating control this slice proves: a different-generation
    consumer pin is refused (same generation only), so a lost in-memory host
    activation can never silently rehydrate through the handoff. True cold
    recovery (new host activation + rehydrate through formal composition)
    remains a registered dependency gap; no Store/issuer is privately swapped
    here and no rehydrate API exists on the module.
    """
    parts = _setup(tmp_path, request_id="cold-recovery-not-run")
    try:
        assert not hasattr(MaterialConsumption, "rehydrate")
        assert not hasattr(MaterialConsumption, "cold_recovery")
        foreign = MaterialConsumerPin(
            parts["consumer_pin"].consumer_id,
            parts["consumer_pin"].consumer_version,
            ActivationRef(_ENV, "consumer.host", 99),
        )
        with pytest.raises(AdmissionRefusedError):
            MaterialConsumption._consumer_pin_gate(
                foreign, parts["admitted_consumer"], parts["acquire_request"])
    finally:
        _close(parts)


def test_canary_body_never_persisted_or_logged(tmp_path, caplog):
    parts = _setup(tmp_path, request_id="canary-scan")
    try:
        _acquire(parts)
        read_key = _reserve_read(parts)
        step = parts["consumption"].read(read_key, _READ_DIGEST, _READ_STEP)
        assert step.outcome == "concluded"
        assert parts["provider"].content_reads == 1
        receipt = parts["provider"].acquisition_receipt
        evidence = MaterialConsumptionEvidence(
            receipt.immutable_material_ref,
            parts["consumer_pin"],
            parts["target"],
            parts["read_request"].correlation,
            MaterialEvidenceRef(_ENV, "runtime-owner-consumption", "1"),
        )
        decision = parts["consumption"].release(
            parts["request_key"], _OUTER_DIGEST, _RELEASE_STEP,
            consumption_evidence=evidence)
        assert decision.released is True
        assert parts["provider"].content_reads == 1

        # §6.5: the provider content canary never reaches persisted records
        # or logs — the core coordinates pointers and digests only.
        canary = _CANARY.encode()
        db_bytes = parts["db_path"].read_bytes()
        assert canary not in db_bytes
        assert canary not in caplog.text.encode()
        read_record = parts["store"].read_operation_step(read_key, _READ_STEP)
        release_record = decision.step_record
        for record in (read_record, release_record):
            assert canary not in record.evidence_json.encode()
            assert canary not in record.intent_json.encode()
        holder = operation_holder(parts["request_key"], parts["op_ref"])
        for row in _usage_rows(parts, holder):
            assert canary not in safe_json(row).encode()
    finally:
        _close(parts)

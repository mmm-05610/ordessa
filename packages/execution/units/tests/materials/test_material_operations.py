"""019 material-step coordination on a Unit context and SQLite.

The provider below is a controlled registered contribution. These tests prove
the kernel/store/issuer contract only; they do not represent a production
material service, Harness, or native consumer.
"""
import hashlib
from threading import RLock

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch, UnitOperationUnknown
from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.definitions.admission_identity import AgentNodeRef, MaterialProviderActivationRef
from ordessa_units.persistence.sqlite.store import SqliteUnitStore
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import (
    InvocationAuthorityRefused,
    InvocationCurrentState,
    InvocationGrant,
    InvocationIssuer,
)
from ordessa_units.public import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialAccessMode,
    MaterialCapability,
    MaterialCorrelation,
    MaterialEvidenceRef,
    MaterialLeaseRef,
    MaterialLifetime,
    MaterialObjectRef,
    MaterialOutcome,
    MaterialProviderPin,
    MaterialReceipt,
    MaterialRequest,
    MaterialResult,
    ResourceMaterialDescriptor,
    ResourceRef,
    MaterialUseTarget,
    material_invocation_target,
    material_operation_facts,
    material_provider_ref,
    material_reservation_usages,
)
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.material_admission import MaterialAdmission
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.bindings.material_operations import MaterialOperations
from ordessa_units.definitions.materials import ReconcileSupport, ResourceProviderDescriptor
from ordessa_agents.harness.providers.registry import HarnessCatalog

_ENV = "env"
_PRINCIPAL = "principal"
_OUTER_DIGEST = "operation-request-digest"
_CONTRACT_ID = "sample.alpha@1"
_STEP_ID = "material-fetch"
_OPERATION_KIND = "material-operation-fixture"


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
        self.revalidate_calls = 0
        self.on_revalidate = None

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
        self.revalidate_calls += 1
        if self.on_revalidate is not None:
            self.on_revalidate(self.revalidate_calls)
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class CurrentState:
    def __init__(self, provider_ref, directory_ref, *, epoch=4):
        self.provider_ref = provider_ref
        self.directory_ref = directory_ref
        self.active = True
        self.epoch = epoch
        self.permitted = True
        self.inspect_calls = 0
        self.fail_on = None

    def inspect(self, request, provider_ref, context_ref, target_ref, action):
        self.inspect_calls += 1
        if self.inspect_calls == self.fail_on:
            raise RuntimeError("controlled current-state failure")
        return InvocationCurrentState(
            self.provider_ref,
            self.active,
            self.epoch,
            self.directory_ref,
            self.permitted,
            None,
            None,
        )


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
        self.stored_results = {}
        self.resolve_calls = 0
        self.query_calls = 0
        self.describe_material_calls = 0
        self.c1_calls = {"acquire": 0, "release": 0, "reconcile": 0}
        self.verify_calls = []
        self.on_resolve = None
        self.on_query = None

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
            invocation, action, provider_ref, target_ref, request.input_digest
        )
        self.verify_calls.append((action, facts["request"]["requestId"]))
        if action == "query":
            self.verifier.verify_claimed_query(
                invocation, provider_ref, target_ref, request.input_digest,
                operation_kind=self.operation_kind,
            )

    def resolve_material(self, request, invocation):
        self.resolve_calls += 1
        self._verify(invocation, request, "acquire")
        if self.on_resolve is not None:
            self.on_resolve()
        persisted = _success_result(request, self.descriptor)
        self.stored_results[request.correlation.to_dict()["recoveryCorrelation"]] = persisted
        return self.resolve_response or persisted

    def query_material(self, request, invocation):
        self.query_calls += 1
        assert type(request) is MaterialRequest
        self._verify(invocation, request, "query")
        if self.on_query is not None:
            self.on_query()
        return self.stored_results.get(
            request.correlation.to_dict()["recoveryCorrelation"],
            MaterialResult(MaterialOutcome.UNKNOWN, request.correlation),
        )

    def release_material(self, request, invocation):
        raise AssertionError("019 does not release material")


def _descriptor(resource_ref):
    return ResourceMaterialDescriptor(
        resource_ref,
        "fixture.material",
        "schema/1",
        "sha256:" + "1" * 64,
        MaterialLifetime.COPY_COMPLETE,
        MaterialAccessMode.READ_ONLY,
        MaterialEvidenceRef(_ENV, "fixture-provenance", "1"),
        MaterialEvidenceRef(_ENV, "fixture-description", "1"),
    )


def _request_facts(resource_ref, pin, target, descriptor):
    facts = {
        "resourceRef": resource_ref.to_dict(),
        "providerPin": pin.to_dict(),
        "target": target.to_dict(),
        "descriptorDigest": descriptor.descriptor_digest,
    }
    input_digest = hashlib.sha256(safe_json(facts).encode("utf-8")).hexdigest()
    return facts, input_digest


def _make_material_request(resource_ref, pin, target, descriptor, *, operation_ref, step_id):
    _, input_digest = _request_facts(resource_ref, pin, target, descriptor)
    correlation = MaterialCorrelation(
        operation_ref, step_id, f"recovery-{operation_ref}-{step_id}", input_digest
    )
    return MaterialRequest(resource_ref, pin, target, descriptor.descriptor_digest, correlation)


def _success_result(request, descriptor, *, provenance_ref=None, evidence_ref=None):
    lease = MaterialLeaseRef(
        "lease-fixture", request.resource_ref, request.provider_pin,
        request.target, request.correlation,
    )
    receipt = MaterialReceipt(
        request.resource_ref,
        request.provider_pin,
        request.target,
        request.correlation,
        request.descriptor_digest,
        MaterialObjectRef(_ENV, "opaque-material", "1"),
        descriptor.content_digest,
        descriptor.material_type,
        descriptor.schema_version,
        lease,
        provenance_ref or descriptor.provenance_ref,
        evidence_ref or MaterialEvidenceRef(_ENV, "fixture-acquisition-evidence", "1"),
    )
    return MaterialResult(MaterialOutcome.SUCCESS, request.correlation, receipt=receipt)


def _setup(tmp_path, *, provider_capability=True, with_issuer=True,
           provider_version="1.0", descriptor=None, request_pin_version=None,
           provider_lifetimes=("copyComplete",),
           request_epoch=4, operation_epoch=4, step_epoch=None,
           policy_allowed=True, request_id="material-request"):
    db_path = tmp_path / f"{request_id}.sqlite"
    store = SqliteUnitStore(db_path)
    policy = ReadPolicy(allowed=policy_allowed)
    admission_lock = RLock()
    harness_catalog = HarnessCatalog(
        _ENV, policy=policy, principal_scope=_PRINCIPAL,
        admission_lock=admission_lock,
    )
    context_ref = {}
    material_catalog = MaterialCatalog(
        _ENV,
        admission_lock=admission_lock,
        retirement_guard=lambda owner, generation: context_ref[
            "context"
        ].provider_retirement_guard(owner, generation),
    )
    unit_context = UnitAdmissionContext(
        _ENV,
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"test": b"material-operations-fixture"}, active_key_id="test"
        ),
        harness_catalog=harness_catalog,
        material_catalog=material_catalog,
        principal_scope=_PRINCIPAL,
        admission_lock=admission_lock,
    )
    context_ref["context"] = unit_context

    capability = (MaterialCapability(AGENT_MATERIAL_CONTRACT_VERSION,
                    provider_lifetimes, provider_capability, "both")
                  if provider_capability is not None else None)
    provider = ControlledMaterialProvider("provider.material", capability,
                                          version=provider_version)
    owner_id = "owner.material"
    activation = MaterialProviderActivationRef(_ENV, owner_id, 1)
    material_catalog.stage(
        owner_id, activation.generation, (provider,), (_CONTRACT_ID,)
    ).commit()

    authority = Authority()
    directory = DirectoryBindingRef(
        _ENV, "binding", 1, "sha256:" + "a" * 64
    )
    resource_ref = ResourceRef(
        _ENV, provider.provider_id, _CONTRACT_ID, "resource-fixture", "r1"
    )
    pin = MaterialProviderPin(
        provider.provider_id,
        provider.version if request_pin_version is None else request_pin_version,
        activation,
    )
    target = MaterialUseTarget(
        AgentNodeRef(_ENV, "planned-node", 1),
        directory,
        request_epoch,
        "profile-material",
    )
    fixed_descriptor = descriptor or _descriptor(resource_ref)
    material_request = _make_material_request(
        resource_ref, pin, target, fixed_descriptor,
        operation_ref=f"operation-{request_id}", step_id=_STEP_ID,
    )
    operation_digest = _OUTER_DIGEST
    step_epoch_value = operation_epoch if step_epoch is None else step_epoch
    context = {
        "environmentNamespace": _ENV,
        "directoryBindingRef": directory.to_dict(),
        "materialRequests": {
            _STEP_ID: material_operation_facts(material_request, fixed_descriptor)
        },
        "invocationBindings": {
            _STEP_ID: {
                "action": "acquire",
                "targetRef": material_invocation_target(material_request),
                "delegationRef": None,
                "cleanup": False,
            }
        },
    }
    node_ref = {
        "environmentNamespace": _ENV,
        "instanceId": "planned-node",
        "generation": 1,
    }
    intent = OperationIntent(
        material_request.correlation.operation_ref,
        _OPERATION_KIND,
        None,
        context,
        (StepIntent(
            _STEP_ID,
            material_provider_ref(pin),
            material_request.input_digest,
            material_request.correlation.recovery_correlation,
            management_epoch=step_epoch_value,
        ),),
        node_ref,
        operation_epoch,
    )
    request_key = RequestKey(_ENV, _PRINCIPAL, request_id)
    store.reserve_operation(
        request_key,
        operation_digest,
        intent,
        usages=material_reservation_usages(request_key, material_request),
    )

    issuer = None
    current = CurrentState(material_provider_ref(pin), directory, epoch=request_epoch)
    if with_issuer:
        issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    operations = MaterialOperations(unit_context, invocation_issuer=issuer)
    admission = MaterialAdmission(unit_context)
    admitted = admission.material_provider_contribution(provider.provider_id)
    assert admitted.resource_provider.owner_activation == activation
    provider.descriptor = fixed_descriptor
    provider.material_provider = material_provider_ref(pin)
    provider.material_target = material_invocation_target(material_request)
    provider.verifier = issuer.verifier() if issuer is not None else None
    return {
        "db_path": db_path,
        "store": store,
        "context": unit_context,
        "material_catalog": material_catalog,
        "harness_catalog": harness_catalog,
        "admission": admission,
        "policy": policy,
        "provider": provider,
        "activation": activation,
        "authority": authority,
        "current": current,
        "issuer": issuer,
        "operations": operations,
        "request_key": request_key,
        "operation_digest": operation_digest,
        "intent": intent,
        "material_request": material_request,
        "descriptor": fixed_descriptor,
    }


def _usage_rows(parts):
    holder = operation_holder(parts["request_key"], parts["intent"].operation_ref)
    return parts["store"].read_usages(_ENV, holder)


def _assert_two_original_holds(parts, expected_state="active", expected_revision=None):
    rows = _usage_rows(parts)
    request = parts["material_request"]
    holder = operation_holder(parts["request_key"], parts["intent"].operation_ref)
    provider_target = material_provider_ref(request.provider_pin)
    expected = {
        f"{parts['intent'].operation_ref}.material.{_STEP_ID}.provider": provider_target,
        f"{parts['intent'].operation_ref}.material.{_STEP_ID}.resource": request.resource_ref.to_dict(),
    }
    assert len(rows) == 2
    assert {row["usageId"] for row in rows} == set(expected)
    if expected_revision is None:
        expected_revision = 1 if expected_state == "active" else 2
    for row in rows:
        assert row["state"] == expected_state
        assert row["holderRef"] == dict(holder)
        assert row["targetRef"] == expected[row["usageId"]]
        assert row["rights"] == ["use"]
        assert row["revision"] == expected_revision


def _close(parts):
    if parts["issuer"] is not None:
        parts["issuer"].close()
    parts["store"].close()


def test_registered_provider_resolves_exact_fixed_request_and_updates_two_existing_holds(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        _assert_two_original_holds(parts)
        step = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert step.outcome == "concluded"
        assert step.evidence == {"materialResult": _success_result(
            parts["material_request"], parts["descriptor"]
        ).to_dict()}
        receipt = step.evidence["materialResult"]["receipt"]
        assert receipt["provenanceRef"] == parts["descriptor"].provenance_ref.to_dict()
        assert receipt["evidenceRef"] != parts["descriptor"].evidence_ref.to_dict()
        assert provider.resolve_calls == 1
        assert provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
        assert provider.verify_calls == [("acquire", parts["request_key"].request_id)]
        _assert_two_original_holds(parts, expected_revision=2)
    finally:
        _close(parts)


def test_success_receipt_with_provenance_different_from_fixed_descriptor_is_unknown(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        forged_provenance = MaterialEvidenceRef(_ENV, "other-provenance", "1")
        provider.resolve_response = _success_result(
            parts["material_request"], parts["descriptor"],
            provenance_ref=forged_provenance,
        )
        step = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert step.outcome == "unknown"
        assert step.evidence == {"materialOperation": "unknown"}
        _assert_two_original_holds(parts, expected_state="unknown")
        assert provider.resolve_calls == 1 and provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_existing_claim_replay_requires_query_authority_but_never_calls_provider_query(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        original = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        replay = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert replay == original
        assert provider.resolve_calls == 1
        assert provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
        assert provider.verify_calls == [("acquire", parts["request_key"].request_id)]
    finally:
        _close(parts)


@pytest.mark.parametrize("failure", ["authority", "directory", "epoch"])
def test_first_dispatch_authority_or_current_binding_refusal_has_no_claim_or_provider_effect(tmp_path, failure):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        before_usages = _usage_rows(parts)
        if failure == "authority":
            parts["authority"].allowed = False
        elif failure == "directory":
            parts["current"].directory_ref = DirectoryBindingRef(
                _ENV, "changed-binding", 2, "sha256:" + "b" * 64
            )
        else:
            parts["current"].epoch = 5

        with pytest.raises((UnitAdmissionRefused, InvocationAuthorityRefused,
                            UnitGuaranteeUnavailable, UnitOperationUnknown)):
            parts["operations"].acquire(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert parts["store"].read_operation_step(parts["request_key"], _STEP_ID) is None
        assert _usage_rows(parts) == before_usages
        assert provider.describe_material_calls == 1
        assert provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_missing_issuer_and_missing_query_coverage_fail_before_claim_or_describe(tmp_path):
    no_issuer = _setup(tmp_path, with_issuer=False, request_id="no-issuer")
    provider = no_issuer["provider"]
    try:
        with pytest.raises((UnitGuaranteeUnavailable, InvocationAuthorityRefused)):
            no_issuer["operations"].acquire(
                no_issuer["request_key"], no_issuer["operation_digest"], _STEP_ID
            )
        assert no_issuer["store"].read_operation_step(no_issuer["request_key"], _STEP_ID) is None
        assert provider.describe_material_calls == provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(no_issuer)

    no_query = _setup(tmp_path, provider_capability=False, request_id="no-query-coverage")
    provider = no_query["provider"]
    try:
        with pytest.raises(UnitGuaranteeUnavailable):
            no_query["operations"].acquire(
                no_query["request_key"], no_query["operation_digest"], _STEP_ID
            )
        assert no_query["store"].read_operation_step(no_query["request_key"], _STEP_ID) is None
        assert provider.describe_material_calls == provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(no_query)


def test_unresolved_existing_claim_without_query_coverage_remains_held_without_provider_calls(tmp_path):
    parts = _setup(tmp_path, provider_capability=False, request_id="claimed-no-query-coverage")
    provider, issuer = parts["provider"], parts["issuer"]
    try:
        target = material_invocation_target(parts["material_request"])
        issuer.issue(
            parts["request_key"], parts["operation_digest"], _STEP_ID,
            "acquire", target, delegation_ref=None, cleanup=False,
        )
        original_claim = parts["store"].read_operation_step(parts["request_key"], _STEP_ID)
        assert original_claim is not None and original_claim.outcome == "possibly-dispatched"
        before_usages = _usage_rows(parts)

        result = parts["operations"].reconcile(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert result == original_claim
        assert parts["store"].read_operation_step(parts["request_key"], _STEP_ID) == original_claim
        assert _usage_rows(parts) == before_usages
        assert provider.describe_material_calls == provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_unsupported_fixed_material_lifetime_fails_before_claim_or_effect(tmp_path):
    parts = _setup(tmp_path, provider_lifetimes=("dynamic",), request_id="unsupported-lifetime")
    provider = parts["provider"]
    try:
        with pytest.raises((UnitGuaranteeUnavailable, UnitAdmissionRefused)):
            parts["operations"].acquire(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert parts["store"].read_operation_step(parts["request_key"], _STEP_ID) is None
        assert provider.resolve_calls == provider.query_calls == provider.describe_material_calls == 0
        _assert_two_original_holds(parts)
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_descriptor_drift_wrong_pin_and_wrong_step_fail_closed_without_provider_effect(tmp_path):
    changed_descriptor = _descriptor(ResourceRef(
        _ENV, "provider.material", _CONTRACT_ID, "other-resource", "r1"
    ))
    parts = _setup(tmp_path, descriptor=_descriptor(
        ResourceRef(_ENV, "provider.material", _CONTRACT_ID, "resource-fixture", "r1")
    ), request_id="descriptor-drift")
    provider = parts["provider"]
    try:
        provider.descriptor = changed_descriptor
        with pytest.raises((UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable)):
            parts["operations"].acquire(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert parts["store"].read_operation_step(parts["request_key"], _STEP_ID) is None
        assert provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)

    wrong_pin = _setup(tmp_path, request_pin_version="9.9", request_id="wrong-pin")
    provider = wrong_pin["provider"]
    try:
        with pytest.raises((UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable)):
            wrong_pin["operations"].acquire(
                wrong_pin["request_key"], wrong_pin["operation_digest"], _STEP_ID
            )
        assert wrong_pin["store"].read_operation_step(wrong_pin["request_key"], _STEP_ID) is None
        assert provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(wrong_pin)

    wrong_step = _setup(tmp_path, request_id="wrong-step")
    provider = wrong_step["provider"]
    try:
        with pytest.raises((UnitIdentityMismatch, UnitAdmissionRefused, UnitGuaranteeUnavailable)):
            wrong_step["operations"].acquire(
                wrong_step["request_key"], wrong_step["operation_digest"], "not-the-fixed-step"
            )
        assert wrong_step["store"].read_operation_step(wrong_step["request_key"], _STEP_ID) is None
        assert provider.resolve_calls == provider.query_calls == provider.describe_material_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(wrong_step)


def test_postclaim_current_state_change_leaves_unknown_claim_and_both_holds(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        parts["current"].fail_on = 2
        result = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert result.outcome == "unknown"
        assert result.evidence == {"materialOperation": "unknown"}
        step = parts["store"].read_operation_step(parts["request_key"], _STEP_ID)
        assert step is not None and step.outcome == "unknown"
        _assert_two_original_holds(parts, expected_state="unknown", expected_revision=2)
        assert provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_provider_drained_during_authority_callback_is_rechecked_before_resolve(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    drained = []
    try:
        def drain_after_claim_revalidation(call):
            if call == 2:
                parts["material_catalog"].drain(
                    parts["activation"].plugin_id, parts["activation"].generation
                )
                drained.append((parts["activation"].plugin_id,
                                parts["activation"].generation))

        parts["authority"].on_revalidate = drain_after_claim_revalidation
        result = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert drained == [(parts["activation"].plugin_id,
                            parts["activation"].generation)]
        assert result.outcome == "unknown"
        assert result.evidence == {"materialOperation": "unknown"}
        _assert_two_original_holds(parts, expected_state="unknown")
        assert provider.resolve_calls == provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_lost_receipt_reconcile_queries_original_request_without_lease(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        provider.resolve_response = MaterialResult(
            MaterialOutcome.UNKNOWN, parts["material_request"].correlation
        )
        unresolved = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert unresolved.outcome == "unknown"
        _assert_two_original_holds(parts, expected_state="unknown")
        assert provider.resolve_calls == 1 and provider.query_calls == 0

        reconciled = parts["operations"].reconcile(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert reconciled.outcome == "concluded"
        assert reconciled.evidence == {"materialResult": _success_result(
            parts["material_request"], parts["descriptor"]
        ).to_dict()}
        assert provider.resolve_calls == 1 and provider.query_calls == 1
        assert provider.verify_calls == [
            ("acquire", parts["request_key"].request_id),
            ("query", parts["request_key"].request_id),
        ]
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
        _assert_two_original_holds(parts, expected_revision=3)
    finally:
        _close(parts)


def test_query_success_without_provider_verifier_is_unknown_and_keeps_holds(tmp_path):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        provider.resolve_response = MaterialResult(
            MaterialOutcome.UNKNOWN, parts["material_request"].correlation
        )
        unresolved = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert unresolved.outcome == "unknown"

        # Return a valid-looking success receipt while deliberately skipping
        # the provider's original InvocationVerifier checks.
        def unverified_query(request, invocation):
            provider.query_calls += 1
            return _success_result(request, parts["descriptor"])

        provider.query_material = unverified_query
        recovered = parts["operations"].reconcile(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert recovered.outcome == "unknown"
        assert recovered.evidence == {"materialOperation": "unknown"}
        assert provider.resolve_calls == 1 and provider.query_calls == 1
        _assert_two_original_holds(parts, expected_state="unknown", expected_revision=3)
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_stale_query_observation_cannot_overwrite_newer_step_without_usage_update(tmp_path):
    parts = _setup(tmp_path)
    provider, store = parts["provider"], parts["store"]
    try:
        provider.resolve_response = MaterialResult(
            MaterialOutcome.UNKNOWN, parts["material_request"].correlation
        )
        first = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert first.outcome == "unknown"
        usages_before_query = _usage_rows(parts)
        concurrent_steps = []

        def concurrent_update():
            observed = store.read_operation_step(parts["request_key"], _STEP_ID)
            assert observed is not None and observed.outcome == "unknown"
            concurrent_steps.append(store.record_operation_step(
                parts["request_key"], parts["operation_digest"], _STEP_ID,
                observed.intent.input_digest, observed.revision, "refused",
                {"concurrentObservation": "newer-step-fact"},
            ))

        provider.on_query = concurrent_update
        replay = parts["operations"].reconcile(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert len(concurrent_steps) == 1
        assert replay == concurrent_steps[0]
        assert replay.outcome == "refused"
        assert replay.evidence == {"concurrentObservation": "newer-step-fact"}
        assert _usage_rows(parts) == usages_before_query
        assert provider.resolve_calls == 1 and provider.query_calls == 1
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_provider_success_then_sqlite_conclusion_failure_keeps_claim_and_holds(tmp_path):
    parts = _setup(tmp_path)
    provider, store = parts["provider"], parts["store"]
    try:
        store._conn.execute(
            "CREATE TRIGGER reject_material_conclusion BEFORE UPDATE OF outcome ON env_request_steps "
            "WHEN NEW.outcome='concluded' BEGIN SELECT RAISE(ABORT, 'controlled persistence failure'); END"
        )
        store._conn.commit()
        with pytest.raises(UnitGuaranteeUnavailable):
            parts["operations"].acquire(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )

        claim = store.read_operation_step(parts["request_key"], _STEP_ID)
        assert claim is not None and claim.outcome == "possibly-dispatched"
        assert claim.evidence == {}
        _assert_two_original_holds(parts)
        assert provider.resolve_calls == 1 and provider.query_calls == 0

        store._conn.execute("DROP TRIGGER reject_material_conclusion")
        store._conn.commit()
        recovered = parts["operations"].reconcile(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert recovered.outcome == "concluded"
        assert provider.resolve_calls == 1 and provider.query_calls == 1
        _assert_two_original_holds(parts, expected_revision=2)
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


def test_sqlite_reopen_preserves_unknown_facts_and_new_generation_cannot_replace_old_pin(tmp_path):
    parts = _setup(tmp_path, request_id="cold-material-query")
    provider = parts["provider"]
    path = parts["db_path"]
    try:
        provider.resolve_response = MaterialResult(
            MaterialOutcome.UNKNOWN, parts["material_request"].correlation
        )
        step = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert step.outcome == "unknown"
        before_operation = parts["store"].read_operation(parts["request_key"])
        before_step = parts["store"].read_operation_step(parts["request_key"], _STEP_ID)
        before_usages = _usage_rows(parts)
        _assert_two_original_holds(parts, expected_state="unknown")
        counts = (provider.resolve_calls, provider.query_calls)
    finally:
        if parts["issuer"] is not None:
            parts["issuer"].close()
        parts["store"].close()

    reopened = SqliteUnitStore(path)
    try:
        stored_operation = reopened.read_operation(parts["request_key"])
        assert stored_operation == before_operation
        assert stored_operation.intent.context_ref["materialRequests"] == \
            before_operation.intent.context_ref["materialRequests"]
        assert reopened.read_operation_step(parts["request_key"], _STEP_ID) == before_step
        assert reopened.read_usages(
            _ENV, operation_holder(parts["request_key"], parts["intent"].operation_ref)
        ) == before_usages
        assert (provider.resolve_calls, provider.query_calls) == counts

        # A newly composed controlled Unit context has a new provider pin. The
        # old operation pin remains fixed; this is SQLite recovery evidence,
        # not production Host restart or activation rehydration evidence.
        policy = ReadPolicy()
        owner_id = "owner.material"
        generation_two = MaterialProviderActivationRef(
            _ENV, owner_id, parts["activation"].generation + 1
        )
        new_lock = RLock()
        new_harness_catalog = HarnessCatalog(
            _ENV, policy=policy, principal_scope=_PRINCIPAL, admission_lock=new_lock
        )
        new_material_catalog = MaterialCatalog(_ENV, admission_lock=new_lock)
        new_context = UnitAdmissionContext(
            _ENV,
            store=reopened,
            policy=policy,
            fingerprint_port=ProtectedFingerprintHmac(
                {"test": b"material-operations-reopened"}, active_key_id="test"
            ),
            harness_catalog=new_harness_catalog,
            material_catalog=new_material_catalog,
            principal_scope=_PRINCIPAL,
            admission_lock=new_lock,
        )
        new_material_catalog.stage(
            owner_id, generation_two.generation, (provider,), (_CONTRACT_ID,)
        ).commit()

        new_authority = Authority()
        new_directory = parts["material_request"].target.directory_binding_ref
        new_provider_ref = material_provider_ref(MaterialProviderPin(
            provider.provider_id, provider.version, generation_two
        ))
        new_current = CurrentState(new_provider_ref, new_directory, epoch=4)
        new_issuer = InvocationIssuer(reopened, new_authority, new_current, clock=lambda: 50)
        new_operations = MaterialOperations(new_context, invocation_issuer=new_issuer)
        provider.verifier = new_issuer.verifier()
        provider.material_provider = new_provider_ref
        with pytest.raises((UnitAdmissionRefused, InvocationAuthorityRefused,
                            UnitGuaranteeUnavailable, UnitOperationUnknown)):
            new_operations.reconcile(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert reopened.read_operation(parts["request_key"]) == before_operation
        assert reopened.read_operation_step(parts["request_key"], _STEP_ID) == before_step
        assert reopened.read_usages(
            _ENV, operation_holder(parts["request_key"], parts["intent"].operation_ref)
        ) == before_usages
        assert (provider.resolve_calls, provider.query_calls) == counts
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        if "new_issuer" in locals():
            new_issuer.close()
        reopened.close()


@pytest.mark.parametrize("denial", ["resources-read", "epoch", "drained-provider"])
def test_historical_step_result_is_not_returned_without_current_query_authority(tmp_path, denial):
    parts = _setup(tmp_path)
    provider = parts["provider"]
    try:
        original = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert original.outcome == "concluded"
        before_operation = parts["store"].read_operation_step(parts["request_key"], _STEP_ID)
        before_usage = _usage_rows(parts)
        assert all(row["revision"] == 2 and row["state"] == "active" for row in before_usage)
        if denial == "resources-read":
            parts["policy"].allowed = False
        elif denial == "epoch":
            parts["current"].epoch = 5
        else:
            parts["material_catalog"].drain(
                parts["activation"].plugin_id, parts["activation"].generation
            )

        with pytest.raises((UnitAdmissionRefused, InvocationAuthorityRefused,
                            UnitGuaranteeUnavailable, UnitOperationUnknown)):
            parts["operations"].acquire(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert parts["store"].read_operation_step(parts["request_key"], _STEP_ID) == before_operation
        assert _usage_rows(parts) == before_usage
        assert provider.resolve_calls == 1
        assert provider.query_calls == 0
        assert provider.c1_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    finally:
        _close(parts)


@pytest.mark.parametrize("replay_method", ["acquire", "reconcile"])
@pytest.mark.parametrize("corruption", ["missing", "released", "wrong-target"])
def test_terminal_receipt_replay_requires_both_intact_original_holds(
    tmp_path, replay_method, corruption
):
    parts = _setup(tmp_path, request_id=f"hold-replay-{replay_method}-{corruption}")
    provider, store = parts["provider"], parts["store"]
    try:
        original = parts["operations"].acquire(
            parts["request_key"], parts["operation_digest"], _STEP_ID
        )
        assert original.outcome == "concluded"
        before_step = store.read_operation_step(parts["request_key"], _STEP_ID)
        rows = _usage_rows(parts)
        assert len(rows) == 2
        target = next(
            row for row in rows
            if row["usageId"].endswith(".provider")
        )
        if corruption == "missing":
            store._conn.execute("DELETE FROM env_usages WHERE usage_id=?", (target["usageId"],))
        elif corruption == "released":
            store._conn.execute(
                "UPDATE env_usages SET state='released' WHERE usage_id=?", (target["usageId"],)
            )
        else:
            store._conn.execute(
                "UPDATE env_usages SET target_ref=? WHERE usage_id=?",
                (safe_json({"wrong": "provider-target"}), target["usageId"]),
            )
        store._conn.commit()
        provider_calls = (
            provider.resolve_calls, provider.query_calls, provider.describe_material_calls,
            dict(provider.c1_calls),
        )

        with pytest.raises((UnitGuaranteeUnavailable, UnitAdmissionRefused)):
            getattr(parts["operations"], replay_method)(
                parts["request_key"], parts["operation_digest"], _STEP_ID
            )
        assert store.read_operation_step(parts["request_key"], _STEP_ID) == before_step
        assert (
            provider.resolve_calls, provider.query_calls, provider.describe_material_calls,
            dict(provider.c1_calls),
        ) == provider_calls
    finally:
        _close(parts)

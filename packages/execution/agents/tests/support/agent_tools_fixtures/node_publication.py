"""Real SQLite publication transactions with controlled owner evidence only.

No provider process, native readiness, production evidence adapter or model.
"""
from dataclasses import replace
import json

import pytest

from ordessa_units.bindings.publication import (
    AgentNodeRef, NodePublication, NodePublicationEvidence, encode_node_ref,
    decode_node_ref, IDENTITIES, NODES,
)
from ordessa_execution_agents.harness.providers.registry.contributions import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_execution_agents.harness.providers.registry import (
    HarnessCatalog, HarnessDefinitionDeclaration, HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_units.public import UnitAdmissionContext, SqliteUnitStore
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitIdentityMismatch, UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitOperationUnknown
from ordessa_infrastructure.database.records import DomainRevisionConflict
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, operation_holder, node_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.persistence.sqlite import KeyConflictError




class Policy:
    allowed = True
    def admit_object_access(self, *args): return self.allowed
    def admit_invoke(self, *args): return self.allowed


class Provider:
    descriptor = RuntimeProviderDescriptor("fixture.runtime", RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "fixture", "revision": "1"}, "sha256:" + "a" * 64)


def _observe_fixture_installation(_installation_ref):
    return HarnessInstallationObservation("present")


class ControlledOwner:
    """Trusted contract fixture, explicitly not actual native owner proof."""
    evidence = None
    def inspect(self, operation, steps): return self.evidence


def make_context(store, policy, *, principal_scope="principal", fingerprint_port=None, register=True):
    """Controlled role registration for same original SQLite cold-read tests."""
    from threading import RLock
    admission_lock = RLock()
    context_owner = {}
    def retirement_guard(owner_id, generation):
        return context_owner["context"].provider_retirement_guard(owner_id, generation)
    def harness_retirement_guard(owner_id, generation):
        return context_owner["context"].harness_provider_retirement_guard(owner_id, generation)

    harness_catalog = HarnessCatalog(
        "env", policy=policy, principal_scope=principal_scope, admission_lock=admission_lock,
        retirement_guard=harness_retirement_guard,
    )
    material_catalog = MaterialCatalog(
        "env", admission_lock=admission_lock, retirement_guard=retirement_guard,
    )
    descriptor = HarnessDefinitionDescriptor(
        Provider.descriptor.provider_id,
        Provider.descriptor.definition_ref,
        Provider.descriptor.implementation_digest,
        "fixture/runtime-v1",
        "fixture-adapter/1",
    )
    declaration = HarnessDefinitionDeclaration(descriptor, _observe_fixture_installation)
    admitted = None
    if register:
        registration = harness_catalog.stage(
            "fixture.plugin", 1, "fixture.plugin", "a" * 64, (declaration,),
        )
        admitted, = registration.commit()
    context = UnitAdmissionContext(
        "env", store=store, policy=policy, fingerprint_port=fingerprint_port,
        harness_catalog=harness_catalog, material_catalog=material_catalog,
        principal_scope=principal_scope, admission_lock=admission_lock,
    )
    context_owner["context"] = context
    return context, admitted


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "nodes.sqlite"
    store = SqliteUnitStore(path)
    policy = Policy()
    context, admitted = make_context(store, policy)
    provider = admitted.provider_ref
    request = RequestKey("env", "principal", "request")
    ref = AgentNodeRef("env", "node", 1)
    step = StepIntent("prepare", provider, "input-digest", "fixed-correlation")
    intent = OperationIntent("operation", "prepare", {"environmentNamespace": "env", "profileId": "profile", "manifestRevision": 1, "contentDigest": "sha256:" + "b" * 64},
        {"environmentNamespace": "env", "directoryBindingRef": {"environmentNamespace": "env", "bindingId": "directory", "revision": 1}}, (step,), encode_node_ref(ref))
    owner = ControlledOwner()
    pub = NodePublication(context, evidence_port=owner)
    yield path, store, context, policy, owner, pub, request, ref, intent, admitted
    if not getattr(context, "_fixture_store_closed", False):
        # Corruption tests intentionally leave synthetic direct SQL uncommitted.
        # Restore the test-only transaction before releasing the original writer;
        # production close must never commit unrelated outstanding writes.
        if store._conn.in_transaction:
            store._conn.rollback()
        store.close()


def source(provider, identity):
    return {"environmentNamespace": "env", "ownerProviderRef": json.loads(safe_json(provider)), "sourceRevision": "native-1", "ref": identity}


def conclude(setup, *, outcome="concluded", unit_identity="actual-unit", evidence_identity="actual-preparation-receipt"):
    _, store, env, _, owner, pub, request, ref, intent, _ = setup
    pub.reserve(request, "digest", intent)
    unit = source(intent.steps[0].pinned_provider_ref, unit_identity)
    target = source(intent.steps[0].pinned_provider_ref, "actual-config-target")
    endpoint = source(intent.steps[0].pinned_provider_ref, "actual-access-descriptor")
    evidence = source(intent.steps[0].pinned_provider_ref, evidence_identity)
    step = intent.steps[0]
    acquisition = UsageMutation("resource", 0, None, operation_holder(request, intent.operation_ref), unit, ("use",), "active")
    assert store.claim_operation_step(request, "digest", step, (acquisition,)).claimed
    store.record_operation_step(request, "digest", step.step_id, step.input_digest, 1, outcome, {"evidenceRef": evidence})
    owner.evidence = NodePublicationEvidence(step.pinned_provider_ref,
        {"nodeRef": intent.node_ref, "harnessProviderRef": step.pinned_provider_ref,
         "harnessDefinitionRef": Provider.descriptor.definition_ref, "harnessUnitRef": unit,
         "profileSnapshotRef": intent.profile_snapshot_ref, "preparationContextRef": intent.context_ref,
         "configurationTargetRef": target, "nativeSessionRefs": [], "operationRef": intent.operation_ref},
        ({"stepId": step.step_id, "providerRef": step.pinned_provider_ref, "inputDigest": step.input_digest,
          "recoveryCorrelation": step.recovery_correlation, "evidenceRef": evidence},), (endpoint,))
    transfer = UsageMutation("resource", 1, operation_holder(request, intent.operation_ref), node_holder("env", "node", 1), unit, ("use",), "active")
    return store.read_operation(request).revision, (transfer,)


def _conclude_with_extra_usage(setup, monkeypatch, *, release_extra=False, outcome="concluded", only_unrelated=False):
    """Real store calls; vary acquired resources without weakening owner facts."""
    store, intent = setup[1], setup[8]
    original_claim = store.claim_operation_step
    original_record = store.record_operation_step
    extra_target = source(intent.steps[0].pinned_provider_ref, "required-extra-resource")

    def claim(request, digest, step, usages=()):
        extra = replace(usages[0], usage_id="required-extra", target_ref=extra_target)
        return original_claim(request, digest, step, (extra,) if only_unrelated else usages + (extra,))

    def record(request, digest, step_id, input_digest, revision, state, evidence, **kwargs):
        if release_extra:
            holder = operation_holder(request, intent.operation_ref)
            kwargs["usages"] = (UsageMutation("required-extra", 1, holder, holder,
                                              extra_target, ("use",), "released"),)
        return original_record(request, digest, step_id, input_digest, revision, state, evidence, **kwargs)

    monkeypatch.setattr(store, "claim_operation_step", claim)
    monkeypatch.setattr(store, "record_operation_step", record)
    revision, unit_transfer = conclude(setup, outcome=outcome)
    extra_transfer = UsageMutation("required-extra", 1, operation_holder(setup[6], intent.operation_ref),
                                  node_holder("env", "node", 1), extra_target, ("use",), "active")
    return revision, unit_transfer[0], extra_transfer



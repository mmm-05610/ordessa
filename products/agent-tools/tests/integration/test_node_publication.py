"""Real SQLite publication transactions with controlled owner evidence only.

No provider process, native readiness, production evidence adapter or model.
"""
from dataclasses import replace
import json

import pytest

from pacthold.agents.nodes import (
    AgentNodeRef, NodePublication, NodePublicationEvidence, encode_node_ref,
    decode_node_ref, IDENTITIES, NODES,
)
from pacthold.agents.runtime import RuntimeProviderDescriptor, RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION
from pacthold.agents.runtime import AgentContributionSet
from pacthold.public import Environment, InstallationRecord
from ordessa_environment_api import RequestKey, IdentityMismatchError, AdmissionRefusedError, GuaranteeUnavailableError, UnknownResultError
from ordessa_environment_api.domain import DomainRevisionConflict
from ordessa_environment_api.identity import ParticipantInstanceRef
from ordessa_environment_api.operations import OperationIntent, StepIntent, UsageMutation, operation_holder, node_holder, safe_json
from ordessa_persistence_sqlite import SqliteStorePort, KeyConflictError


class Policy:
    allowed = True
    def admit_object_access(self, *args): return self.allowed
    def admit_invoke(self, *args): return self.allowed


class Provider:
    descriptor = RuntimeProviderDescriptor("fixture.runtime", RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "fixture", "revision": "1"}, "sha256:" + "a" * 64)


for method in RUNTIME_METHODS:
    setattr(Provider, method, lambda *args: None)


class ControlledOwner:
    """Trusted contract fixture, explicitly not actual native owner proof."""
    evidence = None
    def inspect(self, operation, steps): return self.evidence


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "nodes.sqlite"
    store = SqliteStorePort(path)
    policy = Policy()
    env = Environment("env", store=store, policy=policy, principal_scope="principal")
    env.install(InstallationRecord("fixture.plugin", "a" * 64)); env.enable("fixture.plugin")
    activation = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    provider = env.agent_runtime_contribution(Provider.descriptor.definition_ref).provider_ref
    request = RequestKey("env", "principal", "request")
    ref = ParticipantInstanceRef("env", "node", 1)
    step = StepIntent("prepare", provider, "input-digest", "fixed-correlation")
    intent = OperationIntent("operation", "prepare", {"environmentNamespace": "env", "profileId": "profile", "manifestRevision": 1, "contentDigest": "sha256:" + "b" * 64},
        {"environmentNamespace": "env", "directoryBindingRef": {"environmentNamespace": "env", "bindingId": "directory", "revision": 1}}, (step,), encode_node_ref(ref))
    owner = ControlledOwner()
    pub = NodePublication(env, evidence_port=owner)
    yield path, store, env, policy, owner, pub, request, ref, intent, activation
    if not getattr(env, "_fixture_store_closed", False):
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


def test_publication_usage_transfer_cold_restart_without_runtime_provider(setup):
    path, store, env, policy, owner, pub, request, ref, intent, _ = setup
    revision, usages = conclude(setup)
    result = pub.publish(request, "digest", revision, usages)
    assert result["nodeRef"] == encode_node_ref(ref)
    assert result["binding"]["harnessUnitRef"]["ref"] == "actual-unit"
    assert "ready" not in result and "state" not in result
    assert result["lineage"]["profileSnapshotRef"] == intent.profile_snapshot_ref
    assert pub.read(ref) == result and pub.list() == (result,)
    assert store._conn.execute("SELECT revision FROM env_usages WHERE usage_id='resource'").fetchone()[0] == 2
    store.close()
    env._fixture_store_closed = True
    reopened = SqliteStorePort(path)
    try:
        cold = NodePublication(Environment("env", store=reopened, policy=policy, principal_scope="principal"))
        assert cold.read(ref) == result
        assert cold.reserve(request, "digest", intent).status == "published"
        assert cold.publish(request, "digest", revision, usages) == result
        assert not reopened.claim_operation_step(request, "digest", intent.steps[0]).claimed
    finally: reopened.close()


def test_reservation_replay_same_key_and_identity_collision_no_second_operation(setup):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    first = pub.reserve(request, "digest", intent)
    assert pub.reserve(request, "digest", intent) == first
    with pytest.raises(KeyConflictError): pub.reserve(request, "other-digest", intent)
    with pytest.raises(IdentityMismatchError):
        pub.reserve(RequestKey("env", "principal", "second"), "digest2", replace(intent, operation_ref="second"))
    assert store.read_operation(RequestKey("env", "principal", "second")) is None
    assert pub.read(ref) is None


def test_new_node_generation_not_provider_activation_generation(setup):
    _, store, env, _, _, pub, request, ref, intent, activation = setup
    env.retire_activation(activation.activation)
    second = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    assert second.activation.generation == 2
    provider = env.agent_runtime_contribution(Provider.descriptor.definition_ref).provider_ref
    intent = replace(intent, steps=(replace(intent.steps[0], pinned_provider_ref=provider),))
    operation = pub.reserve(request, "digest", intent)
    assert operation.intent.node_ref["generation"] == 1
    with pytest.raises(IdentityMismatchError):
        pub.reserve(RequestKey("env", "principal", "different"), "different", replace(intent, operation_ref="different", node_ref=encode_node_ref(ParticipantInstanceRef("env", "different", 2))))


def test_unknown_native_step_cannot_publish_or_reclaim(setup):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    revision, usages = conclude(setup, outcome="unknown")
    with pytest.raises(UnknownResultError): pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None
    assert not store.claim_operation_step(request, "digest", intent.steps[0]).claimed
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 1


def test_missing_owner_adapter_does_not_publish(setup):
    _, store, env, _, _, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    with pytest.raises(GuaranteeUnavailableError): NodePublication(env).publish(request, "digest", revision, usages)
    assert pub.read(ref) is None


def test_sqlite_publication_failure_rolls_back_node_usage_and_terminal_result(setup):
    _, store, _, _, _, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    store._conn.execute("CREATE TRIGGER refuse_nodes BEFORE INSERT ON env_domain_records WHEN NEW.namespace='agents.nodes' BEGIN SELECT RAISE(ABORT,'controlled failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError): pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 1


def test_policy_rechecked_for_read_list_publish_and_principal_scope(setup):
    _, _, _, policy, _, pub, request, ref, intent, _ = setup
    revision, usages = conclude(setup)
    with pytest.raises(AdmissionRefusedError): pub.reserve(RequestKey("env", "other", "second"), "digest", intent)
    policy.allowed = False
    for action in (lambda: pub.read(ref), pub.list, lambda: pub.publish(request, "digest", revision, usages)):
        with pytest.raises(AdmissionRefusedError): action()


@pytest.mark.parametrize("mutate", ["node", "provider", "correlation", "missing_target", "unscoped_access"])
def test_actual_owner_identity_or_evidence_mismatch_refuses_publication(setup, mutate):
    _, store, _, _, owner, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    evidence = owner.evidence
    binding = json.loads(safe_json(evidence.binding))
    sources = [json.loads(safe_json(x)) for x in evidence.step_sources]
    access = evidence.access_surface_refs
    if mutate == "node": binding["nodeRef"]["instanceId"] = "wrong"
    if mutate == "provider": binding["harnessProviderRef"]["generation"] = 99
    if mutate == "correlation": sources[0]["recoveryCorrelation"] = "wrong"
    if mutate == "missing_target": binding.pop("configurationTargetRef")
    if mutate == "unscoped_access": access = ({"ref": "fake"},)
    owner.evidence = NodePublicationEvidence(evidence.provider_ref, binding, tuple(sources), access)
    with pytest.raises((IdentityMismatchError, GuaranteeUnavailableError)):
        pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"


def test_published_record_or_step_provenance_corruption_rejected(setup):
    _, store, _, _, _, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    pub.publish(request, "digest", revision, usages)
    row = store.read_domain("env", NODES, "node:1")
    value = row["value"]
    value["sourceSteps"][0]["recoveryCorrelation"] = "forged"
    store._conn.execute("UPDATE env_domain_records SET payload=? WHERE namespace=?", (safe_json(value), NODES))
    with pytest.raises(GuaranteeUnavailableError): pub.read(ref)


def test_strict_existing_participant_identity_and_no_credentials():
    assert AgentNodeRef is ParticipantInstanceRef
    with pytest.raises(IdentityMismatchError): decode_node_ref({"environmentNamespace": "env", "instanceId": "node", "generation": 1, "nativeSessionId": "wrong"})
    with pytest.raises(IdentityMismatchError): encode_node_ref(ParticipantInstanceRef("env", "node", 0))
    with pytest.raises(IdentityMismatchError): NodePublicationEvidence({}, {"token": "secret"}, ({"x": "y"},), ({"x": "y"},))


def test_reservation_sqlite_failure_leaves_no_participant_or_operation(setup):
    _, store, _, _, _, pub, request, _, intent, _ = setup
    import sqlite3
    store._conn.execute("CREATE TRIGGER refuse_operation BEFORE INSERT ON env_requests BEGIN SELECT RAISE(ABORT,'controlled request failure'); END")
    with pytest.raises(sqlite3.IntegrityError): pub.reserve(request, "digest", intent)
    assert store.read_domain("env", IDENTITIES, "node") is None
    assert store.read_operation(request) is None
    assert store._conn.execute("SELECT COUNT(*) FROM env_domain_records").fetchone()[0] == 0


def test_two_environment_roots_same_sqlite_node_cas_only_one_reservation(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path, store, env, policy, _, pub, request, _, intent, _ = setup
    gate_read = Barrier(2)
    class ReadGate:
        def __getattr__(self, name): return getattr(store, name)
        def read_domain(self, environment, namespace, record_id):
            row = store.read_domain(environment, namespace, record_id)
            if namespace == IDENTITIES and row is None:
                gate_read.wait(timeout=5)
            return row
    from ordessa_environment_api.domain import DomainStorePort
    from ordessa_environment_api.operations import OperationStorePort
    for protocol in (DomainStorePort, OperationStorePort):
        for name in protocol.__dict__:
            if not name.startswith("_") and name != "read_domain":
                setattr(ReadGate, name, lambda self, *args, _name=name, **kwargs: getattr(store, _name)(*args, **kwargs))
    shared = ReadGate()
    env._store = shared
    other_env = Environment("env", store=shared, policy=policy, principal_scope="principal")
    other_pub = NodePublication(other_env)
    gate = Barrier(2)
    def reserve(instance, key, value):
        gate.wait()
        try:
            instance.reserve(key, "digest", value)
            return "reserved"
        except (IdentityMismatchError, DomainRevisionConflict):
            return "conflict"
    try:
        other_request = RequestKey("env", "principal", "other")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reserve, pub, request, intent)
            second = pool.submit(reserve, other_pub, other_request, replace(intent, operation_ref="other"))
            assert sorted([first.result(), second.result()]) == ["conflict", "reserved"]
        assert store._conn.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0] == 1
        assert len(store.list_domain("env", IDENTITIES)) == 1
    finally: env._store = store


def test_provider_draining_or_replaced_generation_cannot_publish(setup):
    _, store, env, _, _, pub, request, ref, _, activation = setup
    revision, usages = conclude(setup)
    env.drain(activation.activation)
    with pytest.raises(AdmissionRefusedError): pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None
    env.retire(activation.activation)
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    with pytest.raises(IdentityMismatchError): pub.publish(request, "digest", revision, usages)
    assert store.read_operation(request).status == "running"


def test_publication_replay_rejects_changed_usage_transfer(setup):
    _, _, _, _, _, pub, request, _, _, _ = setup
    revision, usages = conclude(setup)
    pub.publish(request, "digest", revision, usages)
    with pytest.raises(IdentityMismatchError):
        pub.publish(request, "digest", revision, (replace(usages[0], usage_id="different"),))


def test_identity_reservation_corruption_blocks_read_replay_and_publication(setup):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    revision, usages = conclude(setup)
    value = store.read_domain("env", IDENTITIES, "node")["value"]
    value["nodeRef"]["generation"] = 99
    store._conn.execute("UPDATE env_domain_records SET payload=? WHERE namespace=?", (safe_json(value), IDENTITIES))
    with pytest.raises(GuaranteeUnavailableError): pub.reserve(request, "digest", intent)
    with pytest.raises(GuaranteeUnavailableError): pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None


def test_no_provider_type_or_caller_boolean_can_substitute_actual_owner_evidence(setup):
    _, _, _, _, owner, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    owner.evidence = {"ready": True}
    with pytest.raises(GuaranteeUnavailableError): pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None


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


@pytest.mark.parametrize("omit", ["unit", "extra"])
def test_publication_cannot_omit_any_held_resource_usage(setup, monkeypatch, omit):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    revision, unit, extra = _conclude_with_extra_usage(setup, monkeypatch)
    partial = (extra,) if omit == "unit" else (unit,)
    with pytest.raises((IdentityMismatchError, GuaranteeUnavailableError)):
        pub.publish(request, "digest", revision, partial)
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"
    rows = store._conn.execute("SELECT usage_id,state,holder_ref,revision FROM env_usages ORDER BY usage_id").fetchall()
    assert len(rows) == 2
    for row in rows:
        assert row["state"] == "active" and row["revision"] == 1
        assert json.loads(row["holder_ref"]) == dict(operation_holder(request, intent.operation_ref))
    published = pub.publish(request, "digest", revision, (unit, extra))
    assert {item["usageId"] for item in published["resourceUsageRefs"]} == {"resource", "required-extra"}
    assert store.read_operation(request).status == "published"
    for row in store._conn.execute("SELECT holder_ref,revision FROM env_usages"):
        assert json.loads(row["holder_ref"]) == dict(node_holder("env", "node", 1))
        assert row["revision"] == 2


def test_concluded_release_evidence_excludes_resource_from_transfer(setup, monkeypatch):
    _, store, _, _, _, pub, request, _, intent, _ = setup
    revision, unit, _ = _conclude_with_extra_usage(setup, monkeypatch, release_extra=True)
    result = pub.publish(request, "digest", revision, (unit,))
    assert {item["usageId"] for item in result["resourceUsageRefs"]} == {"resource"}
    extra = store._conn.execute("SELECT state,holder_ref,revision FROM env_usages WHERE usage_id='required-extra'").fetchone()
    assert extra["state"] == "released" and extra["revision"] == 2
    assert json.loads(extra["holder_ref"]) == dict(operation_holder(request, intent.operation_ref))


def test_unknown_resource_evidence_cannot_publish_even_with_complete_transfers(setup, monkeypatch):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    revision, unit, extra = _conclude_with_extra_usage(setup, monkeypatch, outcome="unknown")
    with pytest.raises(UnknownResultError):
        pub.publish(request, "digest", revision, (unit, extra))
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "unknown"
    for row in store._conn.execute("SELECT state,holder_ref,revision FROM env_usages"):
        assert row["state"] == "active" and row["revision"] == 1
        assert json.loads(row["holder_ref"]) == dict(operation_holder(request, intent.operation_ref))


def test_unrelated_usage_cannot_stand_in_for_actual_unit_occupation(setup, monkeypatch):
    _, store, _, _, _, pub, request, ref, intent, _ = setup
    revision, _, unrelated = _conclude_with_extra_usage(setup, monkeypatch, only_unrelated=True)
    with pytest.raises((IdentityMismatchError, GuaranteeUnavailableError)):
        pub.publish(request, "digest", revision, (unrelated,))
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"
    row = store._conn.execute("SELECT state,holder_ref,revision FROM env_usages WHERE usage_id='required-extra'").fetchone()
    assert row["state"] == "active" and row["revision"] == 1
    assert json.loads(row["holder_ref"]) == dict(operation_holder(request, intent.operation_ref))


@pytest.mark.parametrize("number", [True, 1.0])
@pytest.mark.parametrize("location", ["node", "profile", "context", "provider", "unit_owner", "step_provider", "access_owner"])
def test_json_numeric_alias_cannot_publish_different_reference(setup, number, location):
    _, store, _, _, owner, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    evidence = owner.evidence
    binding = json.loads(safe_json(evidence.binding))
    sources = [json.loads(safe_json(x)) for x in evidence.step_sources]
    access = [json.loads(safe_json(x)) for x in evidence.access_surface_refs]
    if location == "node": binding["nodeRef"]["generation"] = number
    elif location == "profile": binding["profileSnapshotRef"]["manifestRevision"] = number
    elif location == "context": binding["preparationContextRef"]["directoryBindingRef"]["revision"] = number
    elif location == "provider": binding["harnessProviderRef"]["generation"] = number
    elif location == "unit_owner": binding["harnessUnitRef"]["ownerProviderRef"]["generation"] = number
    elif location == "step_provider": sources[0]["providerRef"]["generation"] = number
    elif location == "access_owner": access[0]["ownerProviderRef"]["generation"] = number
    owner.evidence = NodePublicationEvidence(evidence.provider_ref, binding, tuple(sources), tuple(access))
    with pytest.raises((IdentityMismatchError, GuaranteeUnavailableError)):
        pub.publish(request, "digest", revision, usages)
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 1


@pytest.mark.parametrize("number", [True, 1.0])
@pytest.mark.parametrize("location", ["reservation", "step_source"])
def test_json_numeric_alias_corruption_refuses_cold_publication_read(setup, number, location):
    _, store, env, _, _, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup)
    pub.publish(request, "digest", revision, usages)
    namespace = IDENTITIES if location == "reservation" else NODES
    row = store.read_domain("env", namespace, "node" if location == "reservation" else "node:1")
    value = row["value"]
    if location == "reservation": value["nodeRef"]["generation"] = number
    else: value["sourceSteps"][0]["providerRef"]["generation"] = number
    store._conn.execute("UPDATE env_domain_records SET payload=? WHERE namespace=?", (safe_json(value), namespace))
    cold = NodePublication(env)
    with pytest.raises(GuaranteeUnavailableError): cold.read(ref)
    with pytest.raises(GuaranteeUnavailableError): cold.list()
    assert store.read_operation(request).status == "published"
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 2


@pytest.mark.parametrize("number", [True, 1.0])
@pytest.mark.parametrize("location", ["unit_target", "step_receipt", "node_holder", "admitted_provider"])
def test_publication_keeps_opaque_owner_and_usage_json_identity(setup, number, location):
    _, store, _, _, owner, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup, unit_identity=1, evidence_identity=1)
    evidence = owner.evidence
    provider = json.loads(safe_json(evidence.provider_ref))
    binding = json.loads(safe_json(evidence.binding))
    sources = [json.loads(safe_json(x)) for x in evidence.step_sources]
    access = [json.loads(safe_json(x)) for x in evidence.access_surface_refs]
    if location == "unit_target": binding["harnessUnitRef"]["ref"] = number
    elif location == "step_receipt": sources[0]["evidenceRef"]["ref"] = number
    elif location == "node_holder":
        holder = json.loads(safe_json(usages[0].holder_ref))
        holder["generation"] = number
        usages = (replace(usages[0], holder_ref=holder),)
    elif location == "admitted_provider":
        # All owner projections agree with each other; the real admitted
        # activation and original dispatch still carry the integer identity.
        provider["generation"] = number
        binding["harnessProviderRef"] = provider
        for item in (binding["harnessUnitRef"], binding["configurationTargetRef"], *access):
            item["ownerProviderRef"] = provider
        for item in sources:
            item["providerRef"] = provider
            item["evidenceRef"]["ownerProviderRef"] = provider
    owner.evidence = NodePublicationEvidence(provider, binding, tuple(sources), tuple(access))
    with pytest.raises((IdentityMismatchError, GuaranteeUnavailableError)) as refused:
        pub.publish(request, "digest", revision, usages)
    if location == "admitted_provider":
        assert "currently admitted provider" in str(refused.value)
    assert pub.read(ref) is None
    assert store.read_operation(request).status == "running"
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 1


def test_opaque_numeric_owner_references_publish_and_replay_exactly(setup):
    _, store, _, _, _, pub, request, ref, _, _ = setup
    revision, usages = conclude(setup, unit_identity=1, evidence_identity=1)
    result = pub.publish(request, "digest", revision, usages)
    assert type(result["binding"]["harnessUnitRef"]["ref"]) is int
    assert pub.read(ref) == result
    assert pub.publish(request, "digest", revision, usages) == result
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 2

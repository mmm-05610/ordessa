"""Real core/Profile/SQLite coordination with controlled owner receipts only."""
from dataclasses import replace
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "products/agent-tools/tests/integration"))
from test_invocation_authority import Authority, CurrentState
from test_node_publication import Policy, source

from pacthold.public import Environment, InstallationRecord
from pacthold.agents.assembly.agent import AgentAssembly, PreparationContext, PreparationObservation
from pacthold.agents.nodes.directory import DirectoryBindingRef
from pacthold.agents.access.invocation import InvocationIssuer
from pacthold.agents.nodes.publication import NodePublication, NodePublicationEvidence, decode_node_ref
from pacthold.agents.profiles.catalog import ProfileCatalog
from pacthold.agents.runtime import AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS
from ordessa_environment_api import RequestKey, IdentityMismatchError, AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_environment_api.operations import UsageMutation, operation_holder, safe_json
from ordessa_persistence_sqlite import SqliteStorePort, ProtectedFingerprintHmac
from pacthold.agents.public import agent_services, AGENT_MANAGEMENT_CONTRACT_VERSION
from ordessa_server.agent_core_wire import agent_core_methods


class Provider:
    descriptor = RuntimeProviderDescriptor("fixture.runtime", RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "fixture", "revision": "1"}, "sha256:" + "a" * 64,
        ("plan_preparation", "prepare", "start", "query_step"))
    def __init__(self):
        self.calls = []; self.fail = None; self.verify = True; self.after_prepare = lambda: None
    def plan_preparation(self, snapshot, context, correlation):
        return {"snapshot": snapshot, "context": context, "correlation": correlation}
    def invoke(self, action, invocation):
        facts = invocation.facts
        self.calls.append(action)
        if self.verify:
            self.issuer.verify_and_consume(invocation, action, facts["providerRef"], facts["targetRef"], facts["inputDigest"])
        if self.fail == action: raise ConnectionError("private-native-error")
        if action == "prepare": self.after_prepare()
        return {"ack": True}  # ACK itself supplies no Unit or completion proof.
    def prepare(self, plan, invocation): return self.invoke("prepare", invocation)
    def start(self, prepared, invocation): return self.invoke("start", invocation)
    def query_step(self, correlation, invocation): return self.invoke("query", invocation)


for name in RUNTIME_METHODS:
    if not hasattr(Provider, name): setattr(Provider, name, lambda *args: None)


class ContextOwner:
    revision = "installation-1"
    def resolve(self, request, manifest, admitted, node, context, options):
        return PreparationContext(self.directory,
            {"installationRef": {"environmentNamespace": "env", "installationId": "isolated",
                                 "sourceRevision": self.revision}},
            {"nodeRef": node, "privateRootFacts": {"cwd": "/controlled/fixture"}})


class Owner:
    refuse = False
    wrong_correlation = False
    changed_unit = False
    def observe(self, operation, step, reply):
        if self.refuse: raise LookupError("original evidence absent")
        provider = step.pinned_provider_ref
        unit = source(provider, "actual-unit")
        if self.changed_unit and step.step_id == "start": unit = source(provider, "replacement")
        holds = () if step.step_id == "start" else (
            UsageMutation(operation.intent.operation_ref + ".unit", 0, None,
                          operation_holder(operation.request, operation.intent.operation_ref), unit, ("use",), "active"),)
        return PreparationObservation(step.step_id, provider, step.input_digest,
            "wrong" if self.wrong_correlation else step.recovery_correlation,
            source(provider, step.step_id + "-receipt"), {"unitRef": unit}, holds)
    def inspect(self, operation, steps):
        provider = operation.intent.steps[0].pinned_provider_ref
        unit = steps[0].evidence["preparedUnit"]["unitRef"]
        return NodePublicationEvidence(provider,
            {"nodeRef": operation.intent.node_ref, "operationRef": operation.intent.operation_ref,
             "profileSnapshotRef": operation.intent.profile_snapshot_ref, "preparationContextRef": operation.intent.context_ref,
             "harnessProviderRef": provider, "harnessDefinitionRef": Provider.descriptor.definition_ref,
             "harnessUnitRef": unit, "configurationTargetRef": source(provider, "target"), "nativeSessionRefs": []},
            tuple({"stepId": row.intent.step_id, "providerRef": row.intent.pinned_provider_ref,
                   "inputDigest": row.intent.input_digest, "recoveryCorrelation": row.intent.recovery_correlation,
                   "evidenceRef": row.evidence["evidenceRef"]} for row in steps),
            (source(provider, "access"),))


@pytest.fixture
def assembly(tmp_path):
    store = SqliteStorePort(tmp_path / "assembly.sqlite")
    env = Environment("env", store=store, policy=Policy(), principal_scope="principal",
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"assembly-fixture"}, active_key_id="fixture"))
    env.install(InstallationRecord("fixture.plugin", "a" * 64)); env.enable("fixture.plugin")
    provider = Provider()
    activation = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    provider_ref = env.agent_runtime_contribution(provider.descriptor.definition_ref).provider_ref
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    context_owner = ContextOwner(); context_owner.directory = directory
    authority = Authority(); current = CurrentState(provider_ref, directory, None)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50); provider.issuer = issuer
    catalog = ProfileCatalog(env)
    entry = catalog.create(profile_id="profile", display_name="Profile", manifest={
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref), "schemaVersion": "1", "declarations": []},
        request=RequestKey("env", "principal", "create-profile"))
    owner = Owner(); nodes = NodePublication(env, evidence_port=owner)
    coordinator = AgentAssembly(env, catalog, nodes, invocation_issuer=issuer, context_port=context_owner, observation_port=owner)
    request = RequestKey("env", "principal", "prepare")
    yield coordinator, request, entry.current_manifest_ref, provider, store, nodes, authority, current, context_owner, owner, env, activation
    store.close()


def prepare(parts, **kwargs):
    coordinator, request, ref, *_ = parts
    return coordinator.prepare(request, ref, kwargs.get("context", {}), kwargs.get("options", {}))


def test_profile_unit_node_and_all_holds_share_original_store(assembly):
    operation = prepare(assembly)
    coordinator, request, ref, provider, store, nodes, *_ = assembly
    assert operation.status == "published" and provider.calls == ["prepare", "start"]
    node = nodes.read(decode_node_ref(operation.intent.node_ref))
    assert node["lineage"]["profileSnapshotRef"] == ref.to_dict()
    assert len(node["resourceUsageRefs"]) == 2
    assert prepare(assembly) == operation and provider.calls == ["prepare", "start"]
    assert coordinator.query(request) == operation and provider.calls == ["prepare", "start"]
    assert "/controlled/fixture" not in operation.intent_json
    assert store.read_operation_step(request, "start").outcome == "concluded"


@pytest.mark.parametrize("action", ["prepare", "start"])
def test_disconnect_unknown_no_resend_and_holds_retained(assembly, action):
    assembly[3].fail = action
    operation = prepare(assembly)
    assert operation.status == "unknown"
    before = list(assembly[3].calls)
    assert prepare(assembly).status == "unknown" and assembly[3].calls == before
    assert assembly[5].list() == ()
    rows = assembly[4]._conn.execute("SELECT state,holder_ref FROM env_usages").fetchall()
    assert rows and all(row["state"] == "active" and '"kind":"operation"' in row["holder_ref"] for row in rows)


@pytest.mark.parametrize("failure", ["unverified", "missing-evidence", "wrong-correlation", "changed-unit"])
def test_ack_does_not_publish_without_original_owner_confirmation(assembly, failure):
    if failure == "unverified": assembly[3].verify = False
    elif failure == "missing-evidence": assembly[9].refuse = True
    elif failure == "wrong-correlation": assembly[9].wrong_correlation = True
    else: assembly[9].changed_unit = True
    assert prepare(assembly).status == "unknown"
    assert assembly[5].list() == ()


def test_changed_request_conflicts_without_new_effect(assembly):
    prepare(assembly)
    before = list(assembly[3].calls)
    with pytest.raises(IdentityMismatchError): prepare(assembly, options={"different": True})
    assert assembly[3].calls == before


@pytest.mark.parametrize("change", ["installation", "authority", "drain"])
def test_change_between_steps_prevents_start(assembly, change):
    def mutate():
        if change == "installation": assembly[8].revision = "installation-2"
        elif change == "authority": assembly[6].allowed = False
        else: assembly[10].drain(assembly[11].activation)
    assembly[3].after_prepare = mutate
    with pytest.raises(GuaranteeUnavailableError if change == "authority" else AdmissionRefusedError): prepare(assembly)
    assert assembly[3].calls == ["prepare"]
    assert assembly[4].read_operation_step(assembly[1], "start") is None
    assert assembly[5].list() == ()


def test_query_confirms_original_prepare_without_starting_missing_step(assembly):
    assembly[3].fail = "prepare"
    assert prepare(assembly).status == "unknown"
    assembly[3].fail = None
    assert assembly[0].query(assembly[1]).status == "running"
    assert assembly[3].calls == ["prepare", "query"]
    assert assembly[4].read_operation_step(assembly[1], "start") is None
    assert prepare(assembly).status == "published"
    assert assembly[3].calls == ["prepare", "query", "start"]


def test_missing_deployment_port_refuses_before_spending_key(assembly):
    assembly[0]._context_port = None
    with pytest.raises(GuaranteeUnavailableError): prepare(assembly)
    assert assembly[4].read_operation(assembly[1]) is None
    assert assembly[3].calls == []


@pytest.mark.parametrize("material", ["resource", "secret"])
def test_unresolved_material_refuses_before_plan_or_claim(assembly, material):
    env = assembly[10]
    declaration = {"declarationId": "material", "configurationKind": "fixture", "schemaVersion": "1",
                   "action": "value", "requirement": "required"}
    if material == "resource":
        declaration["resourceRefs"] = [{"environmentNamespace": "env", "resourceId": "material"}]
    else:
        declaration["payload"] = {"secretRef": {"ref": "secret", "revision": "1", "owner_namespace": "fixture", "access_purpose": "execute"}}
    catalog = assembly[0]._profiles
    entry = catalog.create(profile_id="with-material", display_name="Material", manifest={
        "harnessDefinitionRef": dict(Provider.descriptor.definition_ref), "schemaVersion": "1", "declarations": [declaration]},
        request=RequestKey("env", "principal", "create-material"))
    with pytest.raises(GuaranteeUnavailableError):
        assembly[0].prepare(assembly[1], entry.current_manifest_ref, {}, {})
    assert assembly[4].read_operation(assembly[1]) is None
    assert assembly[3].calls == []


def test_public_service_and_explicit_wire_share_same_coordinator_store(assembly):
    coordinator, request, ref, provider, store, _, _, _, context_owner, owner, env, _ = assembly
    services = agent_services(env, invocation_issuer=provider.issuer, node_evidence_port=owner,
                              preparation_context_port=context_owner, preparation_observation_port=owner)
    assert agent_services(env) is services
    handlers = {item.method_id: item.handler for item in agent_core_methods(lambda: env, contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
    caps = handlers["agents.capabilities"]({})
    assert caps["supports"]["nodePreparation"] is True
    assert "agents.nodes.prepare" in caps["supportedMethods"]
    result = handlers["agents.nodes.prepare"]({"profileRef": ref.to_dict(), "context": {}, "options": {}, "requestId": request.request_id})
    assert result["status"] == "published" and result["node"]["nodeRef"] == store.read_operation(request).intent.node_ref
    assert provider.calls == ["prepare", "start"]
    with pytest.raises(ValueError): agent_services(env, preparation_context_port=ContextOwner())


def test_query_after_unknown_start_publishes_only_original_on_explicit_prepare(assembly):
    assembly[3].fail = "start"
    assert prepare(assembly).status == "unknown"
    assembly[3].fail = None
    assert assembly[0].query(assembly[1]).status == "running"
    assert assembly[5].list() == ()
    assert prepare(assembly).status == "published"
    assert assembly[3].calls == ["prepare", "start", "query"]


def test_concurrent_replay_does_not_dispatch_held_claim(assembly):
    entered, release = Event(), Event()
    def wait_original():
        entered.set()
        assert release.wait(5)
    assembly[3].after_prepare = wait_original
    with ThreadPoolExecutor(max_workers=2) as pool:
        original = pool.submit(prepare, assembly)
        try:
            assert entered.wait(5)
            replay = prepare(assembly)
            assert replay.status == "running"
            assert assembly[3].calls == ["prepare"]
            assert assembly[4].read_operation_step(assembly[1], "prepare").outcome == "possibly-dispatched"
        finally:
            release.set()
        assert original.result(timeout=5).status == "published"
    assert assembly[3].calls == ["prepare", "start"]


def test_late_failed_effect_observation_cannot_downgrade_original_query_confirmation(assembly):
    entered, release = Event(), Event()
    def wait_original():
        entered.set()
        assert release.wait(5)
    assembly[3].after_prepare = wait_original
    with ThreadPoolExecutor(max_workers=2) as pool:
        original = pool.submit(prepare, assembly)
        try:
            assert entered.wait(5)
            assert assembly[0].query(assembly[1]).status == "running"
            confirmed = assembly[4].read_operation_step(assembly[1], "prepare")
            assert confirmed.outcome == "concluded"
            assembly[9].refuse = True  # Later observer lost its native receipt.
        finally:
            release.set()
        assert original.result(timeout=5).status == "running"
    assert assembly[4].read_operation_step(assembly[1], "prepare") == confirmed
    assembly[9].refuse = False
    assert prepare(assembly).status == "published"
    assert assembly[3].calls == ["prepare", "query", "start"]


def test_original_query_requires_read_authority_without_new_prepare_permission(assembly):
    assembly[3].fail = "prepare"
    assert prepare(assembly).status == "unknown"
    class ReadPolicy:
        def admit_object_access(self, principal, target, mode): return mode == "read"
        def admit_invoke(self, *args): return False
    assembly[10]._policy = ReadPolicy()
    assembly[3].fail = None
    assert assembly[0].query(assembly[1]).status == "running"
    assert assembly[3].calls == ["prepare", "query"]
    with pytest.raises(AdmissionRefusedError): prepare(assembly)


@pytest.mark.parametrize("context", [{"cwd": "/caller/path"}, {"runtimeBindingRef": {"environmentNamespace": "env", "privateRootFacts": {"cwd": "/caller/path"}}}])
def test_caller_host_paths_refused_without_claim(assembly, context):
    with pytest.raises(IdentityMismatchError): prepare(assembly, context=context)
    assert assembly[4].read_operation(assembly[1]) is None
    assert assembly[3].calls == []


def test_requested_directory_must_match_trusted_owner_binding(assembly):
    wrong = DirectoryBindingRef("env", "other-directory", 1, "sha256:" + "e" * 64)
    with pytest.raises(IdentityMismatchError): prepare(assembly, context={"directoryBindingRef": wrong.to_dict()})
    assert assembly[4].read_operation(assembly[1]) is None


@pytest.mark.parametrize('number', [True, 1.0])
@pytest.mark.parametrize('location', ['observation_provider', 'unit_usage', 'query_original_unit'])
def test_numeric_reference_alias_cannot_confirm_original_preparation(assembly, number, location):
    import json
    original = assembly[9].observe
    def observe(operation, step, reply):
        value = original(operation, step, reply)
        if location == 'observation_provider':
            provider = json.loads(safe_json(value.provider_ref)); provider['generation'] = number
            return replace(value, provider_ref=provider)
        unit = json.loads(safe_json(value.prepared_unit))
        unit['unitRef']['ref'] = number if location == 'query_original_unit' and assembly[3].calls[-1] == 'query' else 1
        usages = tuple(replace(usage, target_ref=dict(unit['unitRef'])) for usage in value.usages)
        if location == 'unit_usage':
            target = json.loads(safe_json(usages[0].target_ref)); target['ref'] = number
            usages = (replace(usages[0], target_ref=target),)
        return replace(value, prepared_unit=unit, usages=usages)
    assembly[9].observe = observe
    if location == 'query_original_unit':
        assembly[3].fail = 'start'
        assert prepare(assembly).status == 'unknown'
        assembly[3].fail = None
        operation = assembly[0].query(assembly[1])
        assert operation.status == 'unknown'
        assert assembly[4].read_operation_step(assembly[1], 'start').outcome == 'unknown'
        assert assembly[3].calls == ['prepare', 'start', 'query']
    else:
        operation = prepare(assembly)
        assert operation.status == 'unknown'
        assert assembly[4].read_operation_step(assembly[1], 'prepare').outcome == 'unknown'
        assert assembly[4].read_operation_step(assembly[1], 'start') is None
        assert assembly[3].calls == ['prepare']
    assert assembly[5].list() == ()

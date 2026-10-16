"""Real core/Profile/SQLite coordination with controlled owner receipts only."""
from ordessa_execution_agents.profiles import encode_revision_ref
from dataclasses import replace
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from agent_tools_fixtures.invocation_authority import Authority, CurrentState
from agent_tools_fixtures.node_publication import Policy, source

from pacthold.public import Environment, InstallationRecord
from ordessa_units.bindings.assembly import AgentAssembly, PreparationContext, PreparationObservation
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.bindings.publication import NodePublication, NodePublicationEvidence, decode_node_ref
from ordessa_execution_agents.profiles.management.service import ProfileService
from ordessa_execution_agents.harness.providers.registry.contributions import AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import IdentityMismatchError, AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import UsageMutation, operation_holder, safe_json
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_units.public import unit_services, AGENT_MANAGEMENT_CONTRACT_VERSION
from ordessa_system_access_bindings import agent_core_methods


from agent_tools_fixtures.assembly import Provider, ContextOwner, Owner, assembly, prepare
def test_profile_unit_node_and_all_holds_share_original_store(assembly):
    operation = prepare(assembly)
    coordinator, request, ref, provider, store, nodes, *_ = assembly
    assert operation.status == "published" and provider.calls == ["prepare", "start"]
    node = nodes.read(decode_node_ref(operation.intent.node_ref))
    assert node["lineage"]["profileSnapshotRef"] == encode_revision_ref(ref)
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
    entry = catalog.create(profile_id="with-material", name="Material", content={
        "harnessDefinitionRef": dict(Provider.descriptor.definition_ref), "schemaVersion": "1", "declarations": [declaration]},
        request=RequestKey("env", "principal", "create-material"))
    with pytest.raises(GuaranteeUnavailableError):
        assembly[0].prepare(assembly[1], entry.current_revision, {}, {})
    assert assembly[4].read_operation(assembly[1]) is None
    assert assembly[3].calls == []


def test_public_service_and_explicit_wire_share_same_coordinator_store(assembly):
    coordinator, request, ref, provider, store, _, _, _, context_owner, owner, env, _ = assembly
    services = unit_services(env, invocation_issuer=provider.issuer, node_evidence_port=owner,
                              preparation_context_port=context_owner, preparation_observation_port=owner)
    assert unit_services(env) is services
    handlers = {item.method_id: item.handler for item in agent_core_methods(lambda: env, contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
    caps = handlers["agents.capabilities"]({})
    assert caps["supports"]["nodePreparation"] is True
    assert "agents.nodes.prepare" in caps["supportedMethods"]
    result = handlers["agents.nodes.prepare"]({"profileRef": encode_revision_ref(ref), "context": {}, "options": {}, "requestId": request.request_id})
    assert result["status"] == "published" and result["node"]["nodeRef"] == store.read_operation(request).intent.node_ref
    assert provider.calls == ["prepare", "start"]
    with pytest.raises(ValueError): unit_services(env, preparation_context_port=ContextOwner())


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

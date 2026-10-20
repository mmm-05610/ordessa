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
from ordessa_units.errors import UnitIdentityMismatch, UnitAdmissionRefused, UnitGuaranteeUnavailable
from ordessa_units.definitions.operations import UsageMutation, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_units.public import unit_services, AGENT_MANAGEMENT_CONTRACT_VERSION
from ordessa_system_access_bindings import agent_core_methods




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

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
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"assembly-fixture"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    env.install(InstallationRecord("fixture.plugin", "a" * 64)); env.enable("fixture.plugin")
    provider = Provider()
    activation = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    provider_ref = env.agent_runtime_contribution(provider.descriptor.definition_ref).provider_ref
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    context_owner = ContextOwner(); context_owner.directory = directory
    authority = Authority(); current = CurrentState(provider_ref, directory, None)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50); provider.issuer = issuer
    catalog = ProfileService(env)
    entry = catalog.create(profile_id="profile", name="Profile", content={
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref), "schemaVersion": "1", "declarations": []},
        request=RequestKey("env", "principal", "create-profile"))
    owner = Owner(); nodes = NodePublication(env, evidence_port=owner)
    coordinator = AgentAssembly(env, catalog, nodes, invocation_issuer=issuer, context_port=context_owner, observation_port=owner)
    request = RequestKey("env", "principal", "prepare")
    yield coordinator, request, entry.current_revision, provider, store, nodes, authority, current, context_owner, owner, env, activation
    store.close()


def prepare(parts, **kwargs):
    coordinator, request, ref, *_ = parts
    return coordinator.prepare(request, ref, kwargs.get("context", {}), kwargs.get("options", {}))



"""Lifecycle coordination counterexamples: stop, release, recover (C only).

Real temporary SQLite store, real Core/Node publication/Issuer with controlled
provider and owner ports. No native process, no model. The coordinator never
fabricates outcomes, never auto-releases unknown holds and never re-dispatches
a claimed step; recover must return the original Node binding identity.
"""
from __future__ import annotations

import pytest

from ordessa_units.errors import UnitGuaranteeUnavailable, UnitIdentityMismatch
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_infrastructure.identifiers import RequestKey

from agent_tools_fixtures.assembly import (
    Authority, CurrentState, Policy, source, Environment, InstallationRecord,
    AgentContributionSet, DirectoryBindingRef, InvocationIssuer, ProfileService,
    NodePublication, NodePublicationEvidence, AgentAssembly, PreparationContext,
    PreparationObservation, SqliteStorePort, ProtectedFingerprintHmac,
    UsageMutation, operation_holder, decode_node_ref, Provider, ContextOwner, Owner,
)
from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION, RuntimeProviderDescriptor
from ordessa_units.lifecycle.service import AgentLifecycle, LifecycleObservation




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

class LifecycleProvider(Provider):
    descriptor = RuntimeProviderDescriptor("fixture.runtime", RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "fixture", "revision": "1"},
        "sha256:" + "a" * 64,
        ("plan_preparation", "prepare", "start", "query_step", "stop", "release", "recover"))

    def __init__(self):
        super().__init__()
        self.lifecycle_calls = []
        self.fail_lifecycle = None
        self.terminal = {"version": "harness-unit-termination/1", "state": "confirmed"}
        self.binding_override = None

    def _effect(self, action, invocation):
        facts = invocation.facts
        self.lifecycle_calls.append(action)
        if self.verify:
            self.issuer.verify_and_consume(invocation, action, facts["providerRef"],
                                           facts["targetRef"], facts["inputDigest"])
        if self.fail_lifecycle == action:
            raise ConnectionError("private-native-error")
        return {"action": action}

    def stop(self, unit_ref, invocation):
        self.lifecycle_calls.append(("unit", dict(unit_ref)))
        return self._effect("stop", invocation)

    def release(self, unit_ref, invocation):
        self.lifecycle_calls.append(("unit", dict(unit_ref)))
        return self._effect("release", invocation)

    def recover(self, native_binding, invocation):
        self.lifecycle_calls.append(("binding", dict(native_binding)))
        return self._effect("recover", invocation)


for name in RUNTIME_METHODS:
    if not hasattr(LifecycleProvider, name):
        setattr(LifecycleProvider, name, lambda *args: None)


class LifecycleOwner:
    """Controlled owner receipt observer with explicit corruption switches."""
    def __init__(self):
        self.unit_ref = None
        self.binding = None
        self.wrong_correlation = False
        self.wrong_unit = False
        self.terminal = None   # None -> confirmed projection; else the state to project

    def observe(self, operation, step, reply):
        action = step.step_id
        unit = {"environmentNamespace": "env", "unitId": "forged",
                "ownerProviderRef": dict(step.pinned_provider_ref), "sourceRevision": "sha256:" + "f" * 64}
        if not self.wrong_unit and self.unit_ref is not None:
            unit = dict(self.unit_ref)
        state = "confirmed" if self.terminal is None else self.terminal
        termination = {"version": "harness-unit-termination/1", "action": action, "state": state,
                       "identity": {"action": action, "inputDigest": step.input_digest,
                                    "unitRef": unit, "correlation": "original"},
                       "outcome": {"terminationEvidenceRef": "sha256:" + action}}
        return LifecycleObservation(step.step_id, step.pinned_provider_ref, step.input_digest,
            "wrong" if self.wrong_correlation else step.recovery_correlation,
            source(step.pinned_provider_ref, action + "-receipt"),
            None if action == "recover" else termination,
            self.binding if action == "recover" else None)


@pytest.fixture
def lifecycle(tmp_path):
    store = SqliteStorePort(tmp_path / "lifecycle.sqlite")
    env = Environment("env", store=store, policy=Policy(), principal_scope="principal",
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"lifecycle-fixture"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    env.install(InstallationRecord("fixture.plugin", "a" * 64))
    env.enable("fixture.plugin")
    provider = LifecycleProvider()
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    provider_ref = env.agent_runtime_contribution(provider.descriptor.definition_ref).provider_ref
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    context_owner = ContextOwner()
    context_owner.directory = directory
    authority = Authority()
    current = CurrentState(provider_ref, directory, None)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    provider.issuer = issuer
    catalog = ProfileService(env)
    entry = catalog.create(profile_id="profile", name="Profile", content={
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref),
        "schemaVersion": "1", "declarations": []},
        request=RequestKey("env", "principal", "create-profile"))
    owner = Owner()
    nodes = NodePublication(env, evidence_port=owner)
    coordinator = AgentAssembly(env, catalog, nodes, invocation_issuer=issuer,
        context_port=context_owner, observation_port=owner)
    request = RequestKey("env", "principal", "prepare")
    operation = coordinator.prepare(request, entry.current_revision, {}, {})
    node_ref = decode_node_ref(operation.intent.node_ref)
    node = nodes.read(node_ref)
    lifecycle_owner = LifecycleOwner()
    lifecycle_owner.unit_ref = dict(node["binding"]["harnessUnitRef"])
    lifecycle_owner.binding = dict(node["binding"])
    lifecycle = AgentLifecycle(env, nodes, invocation_issuer=issuer,
        observation_port=lifecycle_owner)
    # the cleanup invocation contract: the caller holds the Node's acquisition
    current.acquired = dict(operation.intent.node_ref)
    current.evidence = source(provider_ref, "acquisition")
    stop_request = RequestKey("env", "principal", "stop")
    yield (lifecycle, lifecycle_owner, provider, node_ref, node, env, store,
           stop_request, provider_ref, current)
    store.close()



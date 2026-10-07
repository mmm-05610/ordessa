"""Lifecycle coordination counterexamples: stop, release, recover (C only).

Real temporary SQLite store, real Core/Node publication/Issuer with controlled
provider and owner ports. No native process, no model. The coordinator never
fabricates outcomes, never auto-releases unknown holds and never re-dispatches
a claimed step; recover must return the original Node binding identity.
"""
from __future__ import annotations

import pytest

from ordessa_environment_api import GuaranteeUnavailableError, IdentityMismatchError
from ordessa_environment_api.identity import ParticipantInstanceRef

from test_assembly import (
    Authority, CurrentState, Policy, source, Environment, InstallationRecord,
    AgentContributionSet, DirectoryBindingRef, InvocationIssuer, ProfileCatalog,
    NodePublication, NodePublicationEvidence, AgentAssembly, PreparationContext,
    PreparationObservation, RequestKey, SqliteStorePort, ProtectedFingerprintHmac,
    UsageMutation, operation_holder, decode_node_ref, Provider, ContextOwner, Owner,
)
from pacthold.core.lifecycle import RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION, RuntimeProviderDescriptor
from pacthold.agents.lifecycle.lifecycle import AgentLifecycle, LifecycleObservation


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
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"lifecycle-fixture"}, active_key_id="fixture"))
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
    catalog = ProfileCatalog(env)
    entry = catalog.create(profile_id="profile", display_name="Profile", manifest={
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref),
        "schemaVersion": "1", "declarations": []},
        request=RequestKey("env", "principal", "create-profile"))
    owner = Owner()
    nodes = NodePublication(env, evidence_port=owner)
    coordinator = AgentAssembly(env, catalog, nodes, invocation_issuer=issuer,
        context_port=context_owner, observation_port=owner)
    request = RequestKey("env", "principal", "prepare")
    operation = coordinator.prepare(request, entry.current_manifest_ref, {}, {})
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


def test_stop_concludes_with_owner_termination_proof_and_replays_idempotently(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    view = coordinator.stop(request, node_ref, {})
    assert view["action"] == "stop" and view["status"] == "running"
    step = store.read_operation_step(request, "stop")
    assert step.outcome == "concluded"
    assert step.evidence["termination"]["state"] == "confirmed"
    assert provider.lifecycle_calls.count("stop") == 1
    # replay of the same request returns the original operation, never a resend
    replay = coordinator.stop(request, node_ref, {})
    assert replay == view
    assert provider.lifecycle_calls.count("stop") == 1


def test_failed_effect_records_unknown_and_never_resends(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    provider.fail_lifecycle = "stop"
    view = coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"
    assert view["status"] == "unknown"  # the operation honestly reports unknown
    assert provider.lifecycle_calls.count("stop") == 1
    coordinator.stop(request, node_ref, {})
    assert provider.lifecycle_calls.count("stop") == 1  # possibly-dispatched, never resent


def test_wrong_receipt_identity_records_unknown_not_concluded(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    owner.wrong_correlation = True
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"
    request = RequestKey("env", "principal", "stop-2")
    owner.wrong_correlation = False
    owner.wrong_unit = True
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"


def test_unconfirmed_termination_records_unknown_step(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    owner.terminal = "unknown"
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"


def test_release_requires_exact_active_publication_set(lifecycle):
    from ordessa_environment_api.operations import node_holder
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    holder = node_holder("env", node_ref.instance_id, node_ref.generation)
    rows_before = store.read_usages("env", holder)
    assert rows_before and all(row["state"] == "active" for row in rows_before)
    assert {row["usageId"] for row in rows_before} == {item["usageId"] for item in node["resourceUsageRefs"]}
    # happy path: the exact active set releases and the step concludes
    view = coordinator.release(request, node_ref, {})
    step = store.read_operation_step(request, "release")
    assert step.outcome == "concluded"
    rows_after = store.read_usages("env", holder)
    assert [row["state"] for row in rows_after] == ["released"] * len(rows_after)
    assert provider.lifecycle_calls.count("release") == 1
    # replay of the same request is idempotent
    assert coordinator.release(request, node_ref, {}) == view
    assert provider.lifecycle_calls.count("release") == 1
    # a NEW release request sees a non-active set and is refused before dispatch
    with pytest.raises(GuaranteeUnavailableError, match="active publication Usages"):
        coordinator.release(RequestKey("env", "principal", "release-again"), node_ref, {})
    assert provider.lifecycle_calls.count("release") == 1


def test_recover_requires_original_binding_identity(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    forged = dict(node["binding"])
    forged["nativeSessionRefs"] = [source(provider_ref, "recent-session")]
    owner.binding = forged
    coordinator.recover(request, node_ref, {})
    assert store.read_operation_step(request, "recover").outcome == "unknown"
    request = RequestKey("env", "principal", "recover-2")
    owner.binding = dict(node["binding"])
    view = coordinator.recover(request, node_ref, {})
    assert store.read_operation_step(request, "recover").outcome == "concluded"
    assert view["action"] == "recover"


def test_preconditions_shape_and_unknown_keys_are_refused(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    for bad in ("string", 5, {"unknownKey": 1}):
        with pytest.raises(IdentityMismatchError, match="preconditions"):
            coordinator.stop(RequestKey("env", "principal", "bad-" + str(type(bad).__name__)), node_ref, bad)
    assert provider.lifecycle_calls == []


def test_lifecycle_requires_composed_authorities(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    bare = AgentLifecycle(env, coordinator._nodes, invocation_issuer=coordinator._issuer)
    assert bare.capabilities() == {"nodeLifecycle": False}
    with pytest.raises(GuaranteeUnavailableError, match="lifecycle authorities"):
        bare.stop(RequestKey("env", "principal", "bare"), node_ref, {})
    assert coordinator.capabilities() == {"nodeLifecycle": True}

"""Staged effect assembly over the original preparation ledger.

Gate 2 (preparation-effects freeze s6.2): effect materials that are unknown
cannot append - the phase is refused, the unsealed occupation is kept and
publication stays blocked; a plan fact changed at seal time is refused typed.
Gate 3 (s6.3): after sealing, an old invocation context is dead (its frozen
operationIntentDigest no longer matches) and a same-key replay is read-only:
no prepare/start dispatch, query observes only.
Gate 4 (s6.4): a lost receipt keeps the original occupation (unknown, holds
retained, never a resend); native success with a failed original-ledger
persist stays unresolved and is never upgraded to success.
Gate 6 (s6.6): PARTIAL - without a real authorized-materials entry this suite
only proves the control seam. Verified materials below are a CONTROLLED
FIXTURE, not the C-lane handoff; effect-step native execution and node
publication of the expanded recipe are not claimed as working verticals.
"""
from types import SimpleNamespace
import json
import re

import pytest

from ordessa_environment_api import (
    GuaranteeUnavailableError, IdentityMismatchError, RequestKey, UnknownResultError,
)
from ordessa_environment_api.operations import (
    UsageMutation, node_holder, operation_holder, safe_json,
)
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.agents.assembly import AgentAssembly, PreparationContext, PreparationObservation
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import InvocationAuthorityRefused, InvocationIssuer
from pacthold.agents.nodes import NodePublication, NodePublicationEvidence
from pacthold.agents.preparation_effects import EffectStep, PreparationEffectPlan
from pacthold.agents.profiles import ProfileCatalog
from pacthold.agents.runtime import (
    AgentContributionSet, RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION, RuntimeProviderDescriptor,
)
from pacthold.public import Environment, InstallationRecord

from test_invocation_authority import Authority, CurrentState

# Gate 6 marker: these are controlled fixtures standing in for the C-lane
# authorized-materials handoff (material-authorized-handoff freeze s1).
CONTROLLED_MATERIAL = {
    "immutableMaterialRef": {"environmentNamespace": "env", "resourceId": "material-1"},
    "contentDigest": "sha256:" + "d" * 64,
}
CONTROLLED_VERIFIED_MATERIALS = (CONTROLLED_MATERIAL,)


class Provider:
    """Controlled runtime provider; never a real harness or native process."""

    descriptor = RuntimeProviderDescriptor(
        "fixture.runtime", RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "fixture", "revision": "1"},
        "sha256:" + "a" * 64,
        ("plan_preparation", "prepare", "start", "query_step"))

    def __init__(self):
        self.calls = []
        self.invocations = {}
        self.fail = None
        self.verify = True

    def plan_preparation(self, snapshot, context, correlation):
        return {"snapshot": snapshot, "context": context, "correlation": correlation}

    def invoke(self, action, invocation):
        facts = invocation.facts
        self.calls.append(action)
        self.invocations[action] = invocation
        if self.verify:
            self.issuer.verify_and_consume(invocation, action, facts["providerRef"],
                                           facts["targetRef"], facts["inputDigest"])
        if self.fail == action:
            raise ConnectionError("private-native-error")
        return {"ack": True}

    def prepare(self, plan, invocation):
        return self.invoke("prepare", invocation)

    def start(self, prepared, invocation):
        return self.invoke("start", invocation)

    def query_step(self, correlation, invocation):
        return self.invoke("query", invocation)


for _name in RUNTIME_METHODS:
    if not hasattr(Provider, _name):
        setattr(Provider, _name, lambda *args: None)


class ContextOwner:
    revision = "installation-1"

    def resolve(self, request, manifest, admitted, node, context, options):
        return PreparationContext(
            self.directory,
            {"installationRef": {"environmentNamespace": "env",
                                 "installationId": "isolated",
                                 "sourceRevision": self.revision}},
            {"nodeRef": node, "privateRootFacts": {"cwd": "/controlled/fixture"}})


def _source(provider, identity):
    return {"environmentNamespace": "env",
            "ownerProviderRef": json.loads(safe_json(provider)),
            "sourceRevision": "native-1", "ref": identity}


class Owner:
    """Trusted observation fixture, explicitly not native owner proof."""

    refuse = False

    def observe(self, operation, step, reply):
        if self.refuse:
            raise LookupError("original evidence absent")
        provider = step.pinned_provider_ref
        unit = _source(provider, "actual-unit")
        holds = () if step.step_id == "start" else (
            UsageMutation(operation.intent.operation_ref + ".unit", 0, None,
                          operation_holder(operation.request,
                                           operation.intent.operation_ref),
                          unit, ("use",), "active"),)
        return PreparationObservation(
            step.step_id, provider, step.input_digest, step.recovery_correlation,
            _source(provider, step.step_id + "-receipt"), {"unitRef": unit}, holds)

    def inspect(self, operation, steps):
        provider = operation.intent.steps[0].pinned_provider_ref
        unit = steps[0].evidence["preparedUnit"]["unitRef"]
        return NodePublicationEvidence(
            provider,
            {"nodeRef": operation.intent.node_ref,
             "operationRef": operation.intent.operation_ref,
             "profileSnapshotRef": operation.intent.profile_snapshot_ref,
             "preparationContextRef": operation.intent.context_ref,
             "harnessProviderRef": provider,
             "harnessDefinitionRef": Provider.descriptor.definition_ref,
             "harnessUnitRef": unit,
             "configurationTargetRef": _source(provider, "target"),
             "nativeSessionRefs": []},
            tuple({"stepId": row.intent.step_id,
                   "providerRef": row.intent.pinned_provider_ref,
                   "inputDigest": row.intent.input_digest,
                   "recoveryCorrelation": row.intent.recovery_correlation,
                   "evidenceRef": row.evidence["evidenceRef"]} for row in steps),
            (_source(provider, "access"),))


class Policy:
    def admit_object_access(self, *args):
        return True

    def admit_invoke(self, *args):
        return True


@pytest.fixture
def bundle(tmp_path):
    store = SqliteStorePort(tmp_path / "staged.sqlite")
    env = Environment(
        "env", store=store, policy=Policy(), principal_scope="principal",
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"staged-fixture"},
                                                  active_key_id="fixture"))
    env.install(InstallationRecord("fixture.plugin", "a" * 64))
    env.enable("fixture.plugin")
    provider = Provider()
    env.activate("fixture.plugin",
                 AgentContributionSet(agent_runtime_providers=(provider,)))
    provider_ref = env.agent_runtime_contribution(
        provider.descriptor.definition_ref).provider_ref
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    context_owner = ContextOwner()
    context_owner.directory = directory
    authority = Authority()
    current = CurrentState(provider_ref, directory, None)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    provider.issuer = issuer
    catalog = ProfileCatalog(env)
    entry = catalog.create(
        profile_id="profile", display_name="Profile",
        manifest={"harnessDefinitionRef": dict(provider.descriptor.definition_ref),
                  "schemaVersion": "1", "declarations": []},
        request=RequestKey("env", "principal", "create-profile"))
    owner = Owner()
    nodes = NodePublication(env, evidence_port=owner)
    coordinator = AgentAssembly(env, catalog, nodes, invocation_issuer=issuer,
                                context_port=context_owner, observation_port=owner)
    yield SimpleNamespace(coordinator=coordinator,
                          request=RequestKey("env", "principal", "prepare"),
                          ref=entry.current_manifest_ref, provider=provider,
                          store=store, nodes=nodes, owner=owner, issuer=issuer,
                          env=env)
    store.close()


def _effect_plan(root, *, material=CONTROLLED_MATERIAL, before=None,
                 declaration_char="c", pin=None, steps=None):
    context = json.loads(safe_json(root.context_ref))
    return PreparationEffectPlan(
        plan_id="effects-1",
        declaration_digest="sha256:" + declaration_char * 64,
        provider_pin=(pin if pin is not None
                      else json.loads(safe_json(root.steps[0].pinned_provider_ref))),
        material_refs=() if material is None else (material,),
        target=json.loads(safe_json(root.node_ref)),
        scope=json.loads(safe_json(root.profile_snapshot_ref)),
        before_revision=(before if before is not None
                         else context["contextSources"]["installationRef"]["sourceRevision"]),
        directory_binding_ref=context["directoryBindingRef"],
        management_epoch=root.management_epoch,
        steps=tuple(steps) if steps is not None else (
            EffectStep("configure-unit", "input-configure", material, ("prepare",),
                       "correlation-configure-unit"),))


def _seal(staged_api, bundle, plan, **overrides):
    arguments = dict(verified_materials=CONTROLLED_VERIFIED_MATERIALS,
                     declaration_digest=plan.declaration_digest,
                     approved_action_ids=tuple(step.action_id for step in plan.steps))
    arguments.update(overrides)
    return staged_api.seal(bundle.request, plan, **arguments)


def _reserve_and_run(bundle):
    staged_api = bundle.coordinator.staged_assembly()
    record = staged_api.reserve(bundle.request, bundle.ref, {}, {})
    operation = staged_api.run_root(bundle.request)
    return staged_api, record, operation


def _provider_hold_transfer(bundle, operation):
    ref = operation.intent.node_ref
    return UsageMutation(
        operation.intent.operation_ref + ".provider", 1,
        operation_holder(bundle.request, operation.intent.operation_ref),
        node_holder(ref["environmentNamespace"], ref["instanceId"], ref["generation"]),
        operation.intent.steps[0].pinned_provider_ref, ("use",), "active")


def _assert_unsealed_publish_refused(bundle):
    operation = bundle.store.read_operation(bundle.request)
    with pytest.raises(UnknownResultError):
        bundle.store.publish_operation(
            bundle.request, operation.digest, operation.revision,
            tuple(step.step_id for step in operation.intent.steps), (),
            (_provider_hold_transfer(bundle, operation),),
            {"nodeRef": dict(operation.intent.node_ref)})
    return operation


def test_control_seam_seals_after_verified_plan(bundle):
    staged_api, record, operation = _reserve_and_run(bundle)
    assert [step.step_id for step in record.root_intent.steps] == ["prepare", "start"]
    assert record.sealed is False
    assert bundle.provider.calls == ["prepare", "start"]
    assert operation.status == "running"
    plan = _effect_plan(record.root_intent)
    sealed = _seal(staged_api, bundle, plan)
    assert sealed.sealed is True
    phase = sealed.phase
    assert [step.step_id for step in phase.steps] == ["configure-unit"]
    assert phase.steps[0].prerequisite_steps == ("prepare",)
    assert phase.steps[0].pinned_provider_ref == record.root_intent.steps[0].pinned_provider_ref
    facts = phase.context_facts
    assert set(facts) == {"effectDigest", "fixedEffectScope"}
    assert re.fullmatch(r"[0-9a-f]{64}", facts["effectDigest"])
    scope = facts["fixedEffectScope"]
    # The phase facts are stored deep-frozen: sequences are tuples.
    assert tuple(scope["actionIds"]) == ("configure-unit",)
    assert tuple(scope["materialRefs"]) == (CONTROLLED_MATERIAL,)
    assert scope["beforeRevision"] == "installation-1"
    # The seal preserved every root fact and step record.
    for step_id in ("prepare", "start"):
        row = bundle.store.read_operation_step(bundle.request, step_id)
        assert row is not None and row.outcome == "concluded"
    assert bundle.store.read_staged_operation(bundle.request).root_intent == record.root_intent


def test_unsealed_recipe_cannot_publish(bundle):
    staged_api, record, _ = _reserve_and_run(bundle)
    operation = _assert_unsealed_publish_refused(bundle)
    assert bundle.store.read_staged_operation(bundle.request).sealed is False
    assert operation.status == "running"


def test_seal_requires_conclusively_recorded_root_steps(bundle):
    staged_api = bundle.coordinator.staged_assembly()
    record = staged_api.reserve(bundle.request, bundle.ref, {}, {})
    plan = _effect_plan(record.root_intent)
    with pytest.raises(UnknownResultError):
        _seal(staged_api, bundle, plan)
    assert bundle.store.read_staged_operation(bundle.request).sealed is False
    assert bundle.store.read_operation_step(bundle.request, "configure-unit") is None


def test_unknown_effect_materials_keep_occupation_without_seal(bundle):
    staged_api, record, _ = _reserve_and_run(bundle)
    plan = _effect_plan(record.root_intent)
    with pytest.raises(UnknownResultError):
        _seal(staged_api, bundle, plan, verified_materials=None)
    current = bundle.store.read_staged_operation(bundle.request)
    assert current.sealed is False
    assert current.operation.intent.steps == record.root_intent.steps
    assert bundle.store.read_operation_step(bundle.request, "configure-unit") is None
    _assert_unsealed_publish_refused(bundle)
    # A replay of the same unknown verification changes nothing.
    with pytest.raises(UnknownResultError):
        _seal(staged_api, bundle, plan, verified_materials=None)
    assert bundle.store.read_staged_operation(bundle.request) == current


def test_material_outside_the_verified_set_is_refused(bundle):
    staged_api, record, _ = _reserve_and_run(bundle)
    plan = _effect_plan(record.root_intent)
    other = ({"immutableMaterialRef": {"environmentNamespace": "env",
                                       "resourceId": "resource-elsewhere"},
              "contentDigest": "sha256:" + "e" * 64},)
    before = bundle.store.read_staged_operation(bundle.request)
    with pytest.raises(IdentityMismatchError):
        _seal(staged_api, bundle, plan, verified_materials=other)
    assert bundle.store.read_staged_operation(bundle.request) == before


@pytest.mark.parametrize("case", ["before", "declaration", "insert", "pin"])
def test_gate1_changed_plan_facts_are_refused_at_seal(bundle, case):
    staged_api, record, _ = _reserve_and_run(bundle)
    before = bundle.store.read_staged_operation(bundle.request)
    approved = ("configure-unit",)
    if case == "before":
        plan = _effect_plan(record.root_intent, before="native-2")
        facts = dict(verified_materials=CONTROLLED_VERIFIED_MATERIALS,
                     declaration_digest=plan.declaration_digest,
                     approved_action_ids=approved)
    elif case == "declaration":
        plan = _effect_plan(record.root_intent, declaration_char="x")
        facts = dict(verified_materials=CONTROLLED_VERIFIED_MATERIALS,
                     declaration_digest="sha256:" + "c" * 64,
                     approved_action_ids=approved)
    elif case == "insert":
        plan = _effect_plan(record.root_intent, steps=(
            EffectStep("configure-unit", "input-configure", CONTROLLED_MATERIAL,
                       ("prepare",), "correlation-configure-unit"),
            EffectStep("sneaky-action", "input-sneaky", None, ("configure-unit",),
                       "correlation-sneaky-action")))
        facts = dict(verified_materials=CONTROLLED_VERIFIED_MATERIALS,
                     declaration_digest=plan.declaration_digest,
                     approved_action_ids=approved)
    else:
        changed = json.loads(safe_json(record.root_intent.steps[0].pinned_provider_ref))
        changed["generation"] = 2
        plan = _effect_plan(record.root_intent, pin=changed)
        facts = dict(verified_materials=CONTROLLED_VERIFIED_MATERIALS,
                     declaration_digest=plan.declaration_digest,
                     approved_action_ids=approved)
    with pytest.raises(IdentityMismatchError):
        staged_api.seal(bundle.request, plan, **facts)
    assert bundle.store.read_staged_operation(bundle.request) == before


def test_seal_kills_old_invocation_context_and_replays_are_read_only(bundle):
    staged_api, record, _ = _reserve_and_run(bundle)
    old_context = bundle.provider.invocations["prepare"]
    plan = _effect_plan(record.root_intent)
    _seal(staged_api, bundle, plan)
    facts = old_context.facts
    with pytest.raises(InvocationAuthorityRefused):
        bundle.issuer.verify_continuation(
            old_context, "prepare", facts["providerRef"], facts["targetRef"],
            facts["inputDigest"])
    calls = list(bundle.provider.calls)
    replay = staged_api.reserve(bundle.request, bundle.ref, {}, {})
    assert replay.sealed is True
    assert staged_api.run_root(bundle.request).status == "running"
    assert bundle.provider.calls == calls
    queried = bundle.coordinator.query(bundle.request)
    assert queried.status == "running"
    assert bundle.provider.calls == calls
    assert bundle.store.read_operation_step(bundle.request, "configure-unit") is None


def test_replay_with_changed_preparation_input_is_refused(bundle):
    staged_api, _, _ = _reserve_and_run(bundle)
    with pytest.raises(IdentityMismatchError):
        staged_api.reserve(bundle.request, bundle.ref, {}, {"different": True})


@pytest.mark.parametrize("failure", ["native", "observe", "ledger"])
def test_gate4_lost_receipts_keep_occupation_and_never_fabricate_success(bundle, failure):
    staged_api = bundle.coordinator.staged_assembly()
    original_record = bundle.store.record_operation_step
    if failure == "ledger":
        def broken(*args, **kwargs):
            raise RuntimeError("controlled ledger persist failure")
        bundle.store.record_operation_step = broken
    elif failure == "observe":
        bundle.owner.refuse = True
    else:
        bundle.provider.fail = "prepare"
    staged_api.reserve(bundle.request, bundle.ref, {}, {})
    if failure == "ledger":
        with pytest.raises(RuntimeError):
            staged_api.run_root(bundle.request)
    else:
        operation = staged_api.run_root(bundle.request)
        assert operation.status == "unknown"
        row = bundle.store.read_operation_step(bundle.request, "prepare")
        assert row is not None and row.outcome == "unknown"
    calls = list(bundle.provider.calls)
    assert calls == ["prepare"]
    # The original occupation is retained: active holds on the operation owner.
    rows = bundle.store._conn.execute(
        "SELECT state, holder_ref FROM env_usages").fetchall()
    assert rows and all(row["state"] == "active"
                        and '"kind":"operation"' in row["holder_ref"] for row in rows)
    if failure == "ledger":
        claim = bundle.store.read_operation_step(bundle.request, "prepare")
        assert claim is not None and claim.outcome == "possibly-dispatched"
    # Recovery never resends: a replay is read-only, query observes only.
    bundle.store.record_operation_step = original_record
    bundle.provider.fail = None
    bundle.owner.refuse = False
    if failure == "ledger":
        assert staged_api.run_root(bundle.request).status == "running"
    else:
        assert staged_api.run_root(bundle.request).status == "unknown"
    assert bundle.provider.calls == calls
    queried = bundle.coordinator.query(bundle.request)
    assert queried.status == "running"
    assert bundle.provider.calls == calls + ["query"]
    reconciled = bundle.store.read_operation_step(bundle.request, "prepare")
    assert reconciled.outcome == "concluded"
    assert bundle.store.read_operation_step(bundle.request, "start") is None


def test_publish_refuses_incomplete_or_unprovenanced_sealed_recipe(bundle):
    staged_api, record, _ = _reserve_and_run(bundle)
    plan = _effect_plan(record.root_intent)
    sealed = _seal(staged_api, bundle, plan)
    # Effect steps are frozen into the recipe but not executed: without a
    # real authorized-materials entry the publish seam must fail closed and
    # never fabricate a node (gate 6 PARTIAL boundary).
    with pytest.raises(UnknownResultError):
        staged_api.publish(bundle.request)
    step = sealed.phase.steps[0]
    claim = bundle.store.claim_operation_step(
        bundle.request, sealed.operation.digest, step)
    assert claim.claimed
    bundle.store.record_operation_step(
        bundle.request, sealed.operation.digest, step.step_id, step.input_digest,
        claim.step.revision, "concluded",
        {"evidenceRef": "controlled-effect-receipt", "acquiredUsages": []})
    with pytest.raises(GuaranteeUnavailableError):
        staged_api.publish(bundle.request)
    assert bundle.store.read_operation(bundle.request).status == "running"

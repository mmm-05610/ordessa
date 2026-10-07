"""C only: real core SQLite/Issuer, controlled capture and Unit observations.

No owner journal association, production Harness, input writer or model. This
stage deliberately retains first-input holds until verified publication exists.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "products/agent-tools/tests/integration"))
from test_node_publication import setup as node_fixture, source, Provider, Policy, NodePublication
from test_managed_input_reservations import Native
from test_invocation_authority import Authority, CurrentState
from ordessa_environment_api import RequestKey, UnknownResultError, AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_environment_api.operations import UsageMutation, operation_holder, node_holder, safe_json
from ordessa_environment_api.domain import DomainRevisionConflict
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from ordessa_persistence_sqlite.store import WriterLockHeldError
from pacthold.public import Environment, InstallationRecord
from pacthold.agents.runtime import AgentContributionSet
from pacthold.agents.nodes.publication import NodePublicationEvidence
from pacthold.agents.nodes.directory import DirectoryBindingRef
from pacthold.agents.inputs import (
    CapturedInputRef, CapturedInputEvidence, NativeInputState, SessionlessNativeInputState,
    ManagedInputReservations, DRAFT_ATTEMPTS, FIRST_SESSION_ATTEMPTS, SESSIONLESS_INPUT_VERSION,
)
from pacthold.agents.access.invocation import InvocationIssuer, InvocationAuthorityRefused


class Captures:
    def __init__(self): self.values = {}
    def inspect(self, ref, principal): return self.values.get(ref.capture_id)


@pytest.fixture
def first_input(node_fixture):
    _, store, env, policy, owner, nodes, request, node, intent, activation = node_fixture
    provider = intent.steps[0].pinned_provider_ref
    unit = {"environmentNamespace": "env", "unitId": "controlled-original-unit",
            "ownerProviderRef": provider, "sourceRevision": "sha256:" + "1" * 64}
    nodes.reserve(request, "digest", intent)
    acquisition = UsageMutation("resource", 0, None, operation_holder(request, intent.operation_ref), unit, ("use",), "active")
    step = intent.steps[0]
    assert store.claim_operation_step(request, "digest", step, (acquisition,)).claimed
    receipt = source(provider, "controlled-preparation-receipt")
    store.record_operation_step(request, "digest", step.step_id, step.input_digest, 1, "concluded", {"evidenceRef": receipt})
    owner.evidence = NodePublicationEvidence(provider,
        {"nodeRef": intent.node_ref, "harnessProviderRef": provider,
         "harnessDefinitionRef": Provider.descriptor.definition_ref, "harnessUnitRef": unit,
         "profileSnapshotRef": intent.profile_snapshot_ref, "preparationContextRef": intent.context_ref,
         "configurationTargetRef": source(provider, "configuration"), "nativeSessionRefs": [],
         "operationRef": intent.operation_ref},
        ({"stepId": step.step_id, "providerRef": provider, "inputDigest": step.input_digest,
          "recoveryCorrelation": step.recovery_correlation, "evidenceRef": receipt},),
        (source(provider, "controlled-access"),))
    transfer = UsageMutation("resource", 1, operation_holder(request, intent.operation_ref), node_holder("env", "node", 1), unit, ("use",), "active")
    published = nodes.publish(request, "digest", store.read_operation(request).revision, (transfer,))
    env._fingerprint_port = ProtectedFingerprintHmac({"fixture": b"controlled-input-hmac"}, active_key_id="fixture")
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    state = SessionlessNativeInputState(published["nodeRef"], provider, unit,
        source(provider, "confirmed-unit"), source(provider, "session-absent"), 0,
        directory, source(provider, "before-config"))
    capture, native = Captures(), Native(state)
    authority, current = Authority(), CurrentState(provider, directory, unit)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    inputs = ManagedInputReservations(env, nodes, capture, native, invocation_issuer=issuer)
    return store, env, node, capture, native, inputs, authority, current, issuer


def reserve(p, *, key="first-input", draft="draft-a"):
    store, env, node, capture, native, inputs, *_ = p
    ref = CapturedInputRef("env", draft, 1, "sha256:" + "c" * 64)
    capture.values[draft] = CapturedInputEvidence(ref, native.state.node_ref, draft, 1)
    return inputs.reserve(RequestKey("env", "principal", key), node, ref,
        {"environmentNamespace": "env", "protocol": "controlled-native/1", "requestId": key})


def test_first_input_fixes_explicit_unit_binding_without_fake_session(first_input):
    p = first_input
    op = reserve(p)
    context = op.intent.context_ref
    assert context["sessionlessInputBinding"]["contractVersion"] == SESSIONLESS_INPUT_VERSION
    assert context["sessionlessInputBinding"] == p[4].state.binding()
    assert "nativeSessionRef" not in context and "sessionSourceRevision" not in context
    assert context["invocationBindings"]["native-input"]["targetRef"] == p[4].state.unit_ref
    before = p[4].calls
    assert reserve(p) == op and p[4].calls == before
    assert len(p[0].list_domain("env", FIRST_SESSION_ATTEMPTS)) == 1
    assert p[4].dispatch_calls == 0


def test_claim_and_original_verifier_use_complete_unit_target(first_input):
    p = first_input
    op = reserve(p)
    context = p[5].claim_dispatch(op.request, p[8])
    facts = p[8].verifier().verify_and_consume(context, "submitInput", p[4].state.provider_ref,
        p[4].state.unit_ref, op.digest)
    assert facts["targetRef"] == p[4].state.unit_ref and facts["query"] is False
    assert p[0].read_operation_step(op.request, "native-input").outcome == "possibly-dispatched"
    with pytest.raises(UnknownResultError): p[5].claim_dispatch(op.request, p[8])
    assert p[4].dispatch_calls == 0


def test_session_only_grant_cannot_authorize_unit_first_input(first_input):
    p = first_input
    op = reserve(p)
    p[6].overrides["target_ref"] = source(p[4].state.provider_ref, "session-only-grant")
    with pytest.raises(InvocationAuthorityRefused): p[5].claim_dispatch(op.request, p[8])
    assert p[0].read_operation_step(op.request, "native-input") is None


@pytest.mark.parametrize("damage", ["current-provider", "grant-unit-owner"])
def test_invocation_provider_and_unit_target_retain_json_types(first_input, damage):
    p = first_input
    op = reserve(p)
    if damage == "current-provider":
        p[7].provider = dict(p[7].provider, generation=True)
    else:
        target = dict(p[4].state.unit_ref)
        target["ownerProviderRef"] = dict(target["ownerProviderRef"], generation=True)
        p[6].overrides["target_ref"] = target
    with pytest.raises(InvocationAuthorityRefused): p[5].claim_dispatch(op.request, p[8])
    assert p[0].read_operation_step(op.request, "native-input") is None


@pytest.mark.parametrize("outcome", ["reserved", "unknown", "refused", "cancelled"])
def test_other_draft_cannot_bypass_first_unit_hold_even_if_terminal(first_input, outcome):
    p = first_input
    op = reserve(p)
    if outcome != "reserved":
        p[0].record_operation_outcome(op.request, op.digest, op.revision, outcome,
            {} if outcome == "unknown" else {"evidenceRef": source(p[4].state.provider_ref, "controlled-refusal")})
    with pytest.raises(UnknownResultError): reserve(p, key="second", draft="draft-b")
    assert p[0].read_operation(RequestKey("env", "principal", "second")) is None
    assert len(p[0].list_domain("env", DRAFT_ATTEMPTS)) == 1
    assert p[0].list_domain("env", FIRST_SESSION_ATTEMPTS)[0]["value"]["state"] == "held"


def test_observed_session_does_not_release_unknown_first_input_or_fallback(first_input):
    p = first_input
    op = reserve(p)
    old = p[4].state
    p[4].state = NativeInputState(old.node_ref, old.provider_ref, old.unit_ref,
        source(old.provider_ref, "actual-observed-session"), 1, old.management_epoch,
        old.directory_binding_ref, old.before_configuration_evidence)
    with pytest.raises(UnknownResultError): reserve(p, key="second", draft="draft-b")
    with pytest.raises(AdmissionRefusedError): p[5].claim_dispatch(op.request, p[8])
    assert p[0].read_operation_step(op.request, "native-input") is None
    assert p[4].dispatch_calls == 0


@pytest.mark.parametrize("field", ["unit_confirmation_ref", "session_absence_ref", "management_epoch", "directory_binding_ref", "before_configuration_evidence"])
def test_owner_binding_changes_refuse_before_claim(first_input, field):
    p = first_input
    op = reserve(p)
    state = p[4].state
    if field == "management_epoch": value = 1
    elif field == "directory_binding_ref": value = DirectoryBindingRef("env", "changed", 1, "sha256:" + "a" * 64)
    else: value = {**getattr(state, field), "sourceRevision": "changed"}
    p[4].state = replace(state, **{field: value})
    with pytest.raises(AdmissionRefusedError): p[5].claim_dispatch(op.request, p[8])
    assert p[0].read_operation_step(op.request, "native-input") is None


def test_configuration_source_boolean_owner_cannot_reuse_fixed_input_evidence(first_input):
    p = first_input
    op = reserve(p)
    proof = dict(p[4].state.before_configuration_evidence)
    proof["ownerProviderRef"] = dict(proof["ownerProviderRef"], generation=True)
    assert proof == op.intent.context_ref["beforeConfigurationEvidence"]
    p[4].state = replace(p[4].state, before_configuration_evidence=proof)
    with pytest.raises(AdmissionRefusedError): p[5].claim_dispatch(op.request, p[8])
    assert p[0].read_operation_step(op.request, "native-input") is None


@pytest.mark.parametrize("damage", ["owner", "boolean-owner", "missing-source", "ack", "epoch"])
def test_sessionless_projection_requires_complete_typed_original_sources(first_input, damage):
    state = first_input[4].state
    if damage == "epoch": fields = {"management_epoch": True}
    else:
        ref = dict(state.unit_confirmation_ref)
        if damage == "owner": ref["ownerProviderRef"] = {"environmentNamespace": "env", "providerId": "other"}
        elif damage == "boolean-owner": ref["ownerProviderRef"] = dict(ref["ownerProviderRef"], generation=True)
        elif damage == "missing-source": ref["sourceRevision"] = ""
        else: ref = {"environmentNamespace": "env", "accepted": True}
        fields = {"unit_confirmation_ref": ref}
    with pytest.raises(ValueError): replace(state, **fields)


def test_atomic_reservation_failure_does_not_leave_either_domain_hold(first_input):
    p = first_input
    p[0]._conn.execute("CREATE TRIGGER reject_first BEFORE INSERT ON env_requests WHEN NEW.request_id='first-input' BEGIN SELECT RAISE(ABORT,'controlled failure'); END")
    with pytest.raises(sqlite3.IntegrityError): reserve(p)
    assert p[0].read_operation(RequestKey("env", "principal", "first-input")) is None
    assert p[0].list_domain("env", FIRST_SESSION_ATTEMPTS) == ()
    assert p[0].list_domain("env", DRAFT_ATTEMPTS) == ()


def test_concurrent_different_drafts_have_only_one_original_unit_reservation(first_input):
    p = first_input
    def attempt(i):
        try: return reserve(p, key=f"first-{i}", draft=f"draft-{i}")
        except UnknownResultError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = tuple(pool.map(attempt, (1, 2)))
    assert sum(item is not None for item in outcomes) == 1
    assert len(p[0].list_domain("env", FIRST_SESSION_ATTEMPTS)) == 1
    assert len(p[0].list_domain("env", DRAFT_ATTEMPTS)) == 1
    assert p[4].dispatch_calls == 0


def test_other_sqlite_writer_cannot_take_over_first_input_store(first_input, tmp_path):
    with pytest.raises(WriterLockHeldError): SqliteStorePort(tmp_path / "nodes.sqlite")
    assert first_input[0].list_domain("env", FIRST_SESSION_ATTEMPTS) == ()


def test_same_owner_independent_environments_and_connections_compete_on_domain_cas(first_input, tmp_path):
    p = first_input
    # Explicit controlled same writer owner, never allow_takeover. This tests
    # independent connections, not permission for a second production writer.
    cold_store = SqliteStorePort(tmp_path / "nodes.sqlite", writer_token=p[0]._token)
    try:
        cold_env = Environment("env", store=cold_store, policy=Policy(), principal_scope="principal")
        cold_env.install(InstallationRecord("fixture.plugin", "a" * 64))
        cold_env.enable("fixture.plugin")
        cold_env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
        cold_env._fingerprint_port = p[1]._fingerprint_port
        cold_issuer = InvocationIssuer(cold_store, p[6], p[7], clock=lambda: 50)
        cold_inputs = ManagedInputReservations(cold_env, NodePublication(cold_env), p[3], p[4],
                                               invocation_issuer=cold_issuer)
        cold = (cold_store, cold_env, p[2], p[3], p[4], cold_inputs, p[6], p[7], cold_issuer)
        barrier = Barrier(2)
        for inputs in (p[5], cold_inputs):
            original = inputs._first_fence
            def both_observe_absent(node, unit, original=original):
                value = original(node, unit)
                assert value[1] is None
                barrier.wait(timeout=5)
                return value
            inputs._first_fence = both_observe_absent
        def attempt(item):
            index, parts = item
            try: return reserve(parts, key=f"independent-{index}", draft=f"draft-{index}")
            except DomainRevisionConflict: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(attempt, ((1, p), (2, cold))))
        assert sum(item is not None for item in outcomes) == 1
        winner = next(item for item in outcomes if item is not None)
        assert p[0].read_operation(winner.request) == cold_store.read_operation(winner.request)
        assert len(p[0].list_domain("env", FIRST_SESSION_ATTEMPTS)) == 1
        assert len(p[0].list_domain("env", DRAFT_ATTEMPTS)) == 1
        loser = RequestKey("env", "principal", "independent-2" if winner.request.request_id == "independent-1" else "independent-1")
        assert p[0].read_operation(loser) is None
        assert p[4].dispatch_calls == 0
    finally:
        if "cold_issuer" in locals(): cold_issuer.close()
        cold_store.close()

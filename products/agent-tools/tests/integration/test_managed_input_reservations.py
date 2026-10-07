"""SQLite managed-input admission with published node and controlled ports.

No native process or model is invoked. Capture/native/authority fixtures are
contract evidence only; they do not establish a production Harness mapping.
"""
from dataclasses import replace
import json
import sqlite3

import pytest

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey, UnknownResultError
from ordessa_environment_api.operations import safe_json
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.agents.nodes.directory import DirectoryBindingRef
from pacthold.agents.inputs import (
    CapturedInputRef, CapturedInputEvidence, NativeInputState,
    ManagedInputReservations, DRAFT_ATTEMPTS,
)
from pacthold.agents.access.invocation import InvocationIssuer, InvocationAuthorityRefused

from test_node_publication import setup as node_fixture, conclude as conclude_node, source
from test_invocation_authority import Authority, CurrentState


class Capture:
    """Controlled read-only capture identity projection, never input text."""
    def __init__(self, evidence): self.evidence, self.calls, self.failure = evidence, 0, False
    def inspect(self, ref, principal):
        self.calls += 1
        if self.failure: raise RuntimeError("private-capture-credential")
        return self.evidence


class Native:
    """Controlled owner mapping, not production confirmation or native I/O."""
    def __init__(self, state):
        self.state, self.calls, self.failure = state, 0, False
        self.dispatch_calls = 0
    def submit_input(self, *args):
        self.dispatch_calls += 1
        raise AssertionError("core reservation must never submit native input")
    def inspect(self, node, principal):
        self.calls += 1
        if self.failure: raise RuntimeError("private-native-credential")
        return self.state


@pytest.fixture
def managed(node_fixture):
    path, store, env, policy, owner, nodes, _, node, _, activation = node_fixture
    revision, usages = conclude_node(node_fixture)
    published = nodes.publish(node_fixture[6], "digest", revision, usages)
    env._fingerprint_port = ProtectedFingerprintHmac({"fixture": b"controlled-input-hmac"}, active_key_id="fixture")
    capture_ref = CapturedInputRef("env", "capture", 1, "sha256:" + "c" * 64)
    capture = Capture(CapturedInputEvidence(capture_ref, published["nodeRef"], "draft", 1))
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    provider = published["binding"]["harnessProviderRef"]
    state = NativeInputState(published["nodeRef"], provider, published["binding"]["harnessUnitRef"],
        source(provider, "confirmed-native-session"), 1, 0, directory, source(provider, "before-configuration-readback"))
    native = Native(state)
    authority = Authority()
    current = CurrentState(provider, directory, state.session_ref)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    reservations = ManagedInputReservations(env, nodes, capture, native, invocation_issuer=issuer)
    request = RequestKey("env", "principal", "input-request")
    correlation = {"environmentNamespace": "env", "protocol": "codex-app-server/1", "requestId": "native-1"}
    return store, env, policy, nodes, node, capture_ref, capture, native, reservations, request, correlation, authority, current, issuer, published


def reserve(parts, **changes):
    _, _, _, _, node, captured, _, _, inputs, request, correlation, *_ = parts
    fields = {"request": request, "node_ref": node, "captured_ref": captured, "native_correlation": correlation}
    fields.update(changes)
    return inputs.reserve(**fields)


def new_capture(parts, revision=2):
    capture_ref = CapturedInputRef("env", "capture", revision, "sha256:" + str(revision) * 64)
    parts[6].evidence = CapturedInputEvidence(capture_ref, parts[14]["nodeRef"], "draft", revision)
    return capture_ref


def test_reservation_fixed_native_capture_and_repeat_never_dispatches(managed):
    store, _, _, _, node, capture_ref, capture, native, inputs, request, correlation, *_ = managed
    first = reserve(managed)
    assert first.status == "reserved" and first.outcome == "unknown"
    assert first.intent.kind == "managed-input"
    assert first.intent.node_ref == managed[14]["nodeRef"]
    assert first.intent.context_ref["capturedInputRef"] == capture_ref.to_dict()
    assert first.intent.context_ref["nativeCorrelation"] == correlation
    assert first.intent.context_ref["nativeSessionRef"] == native.state.session_ref
    assert first.intent.context_ref["beforeConfigurationEvidence"] == native.state.before_configuration_evidence
    assert store.read_operation_step(request, "native-input") is None
    calls = native.calls
    assert reserve(managed) == first
    assert native.calls == calls  # replay does not refresh or initialize a session.
    assert len(store.list_domain("env", DRAFT_ATTEMPTS)) == 1
    assert "private" not in safe_json(first.intent.to_dict())


def test_same_request_changed_native_correlation_conflicts(managed):
    first = reserve(managed)
    with pytest.raises(IdentityMismatchError):
        reserve(managed, native_correlation={**managed[10], "requestId": "different"})
    assert managed[0].read_operation(managed[9]) == first


@pytest.mark.parametrize("change_revision", [False, True])
def test_same_draft_new_request_cannot_evade_unresolved_attempt(managed, change_revision):
    first = reserve(managed)
    capture_ref = new_capture(managed) if change_revision else managed[5]
    new_request = RequestKey("env", "principal", "new-request")
    with pytest.raises(UnknownResultError): reserve(managed, request=new_request, captured_ref=capture_ref)
    assert managed[0].read_operation(new_request) is None
    assert managed[0].read_operation(managed[9]) == first


def test_unknown_after_claim_blocks_new_revision_and_claim_is_not_repeated(managed):
    store, _, _, _, _, _, _, _, inputs, request, _, _, _, issuer, _ = managed
    operation = reserve(managed)
    context = inputs.claim_dispatch(request, issuer)
    step = store.read_operation_step(request, "native-input")
    assert step.outcome == "possibly-dispatched"
    assert context.facts["inputDigest"] == operation.digest
    assert context.facts["action"] == "submitInput"
    with pytest.raises(UnknownResultError): inputs.claim_dispatch(request, issuer)
    store.record_operation_step(request, operation.digest, "native-input", operation.digest, step.revision, "unknown", {})
    captured = new_capture(managed)
    with pytest.raises(UnknownResultError): reserve(managed, request=RequestKey("env", "principal", "second"), captured_ref=captured)
    assert store.read_operation(managed[9]).status == "unknown"


@pytest.mark.parametrize("outcome", ["refused", "cancelled"])
def test_terminal_old_attempt_requires_strictly_new_draft_revision(managed, outcome):
    store = managed[0]
    first = reserve(managed)
    store.record_operation_outcome(managed[9], first.digest, first.revision, outcome, {"evidenceRef": source(first.intent.steps[0].pinned_provider_ref, "controlled-refusal")})
    with pytest.raises(IdentityMismatchError): reserve(managed, request=RequestKey("env", "principal", "second"))
    capture_ref = new_capture(managed)
    second = reserve(managed, request=RequestKey("env", "principal", "second"), captured_ref=capture_ref)
    assert second.status == "reserved" and second.intent.context_ref["draftRevision"] == 2
    assert store.list_domain("env", DRAFT_ATTEMPTS)[0]["revision"] == 2


def test_policy_revocation_refuses_replay_and_claim_before_any_dispatch(managed):
    store, _, policy, _, _, _, _, _, inputs, request, _, _, _, issuer, _ = managed
    operation = reserve(managed)
    policy.allowed = False
    with pytest.raises(AdmissionRefusedError): reserve(managed)
    with pytest.raises(AdmissionRefusedError): inputs.claim_dispatch(request, issuer)
    assert store.read_operation_step(request, "native-input") is None
    assert store.read_operation(request) == operation


@pytest.mark.parametrize("changed", ["epoch", "provider", "directory", "authority"])
def test_invocation_rechecks_current_authority_provider_epoch_before_claim(managed, changed):
    store, _, _, _, _, _, _, _, inputs, request, _, authority, current, issuer, _ = managed
    reserve(managed)
    if changed == "epoch": current.epoch = 1
    if changed == "provider": current.provider = {**current.provider, "generation": 999}
    if changed == "directory": current.permitted = False
    if changed == "authority": authority.allowed = False
    with pytest.raises(InvocationAuthorityRefused): inputs.claim_dispatch(request, issuer)
    assert store.read_operation_step(request, "native-input") is None


def test_atomic_reservation_sqlite_failure_leaves_no_new_draft_fence_or_input(managed):
    store = managed[0]
    before = store._conn.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0]
    store._conn.execute("CREATE TRIGGER reject_input BEFORE INSERT ON env_requests WHEN NEW.request_id='input-request' BEGIN SELECT RAISE(ABORT,'controlled failure'); END")
    with pytest.raises(sqlite3.IntegrityError): reserve(managed)
    assert store.read_operation(managed[9]) is None
    assert store.list_domain("env", DRAFT_ATTEMPTS) == ()
    assert store._conn.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0] == before


def test_missing_capture_native_or_unpublished_node_refuses(managed):
    _, env, _, nodes, _, _, _, _, _, *_ = managed
    for capture, native in ((None, managed[7]), (managed[6], None)):
        with pytest.raises(GuaranteeUnavailableError):
            ManagedInputReservations(env, nodes, capture, native).reserve(managed[9], managed[4], managed[5], managed[10])
    from ordessa_environment_api import ParticipantInstanceRef
    with pytest.raises(GuaranteeUnavailableError): reserve(managed, node_ref=ParticipantInstanceRef("env", "absent", 1))


def test_claim_one_shot_consumption_is_authority_only_without_native_io(managed):
    store, _, _, _, _, _, _, native, inputs, request, _, _, _, issuer, _ = managed
    operation = reserve(managed)
    before = native.calls
    context = inputs.claim_dispatch(request, issuer)
    facts = issuer.verifier().verify_and_consume(context, "submitInput", operation.intent.steps[0].pinned_provider_ref,
        operation.intent.context_ref["nativeSessionRef"], operation.digest)
    assert facts["recoveryCorrelation"] == operation.intent.steps[0].recovery_correlation
    assert native.calls == before + 1  # explicit read-only current binding recheck.
    assert native.dispatch_calls == 0  # claim/verify does not submit input.
    assert store.read_operation_step(request, "native-input").outcome == "possibly-dispatched"
    with pytest.raises(UnknownResultError): inputs.claim_dispatch(request, issuer)


@pytest.mark.parametrize("port", ["capture", "native"])
def test_trusted_port_failure_is_typed_and_does_not_leak_secret(managed, port):
    managed[6 if port == "capture" else 7].failure = True
    with pytest.raises(GuaranteeUnavailableError) as error: reserve(managed)
    assert "private-" not in str(error.value)
    assert managed[0].read_operation(managed[9]) is None


@pytest.mark.parametrize("field", ["session_ref", "before_configuration_evidence"])
def test_incomplete_native_identity_or_configuration_source_refuses_reservation(managed, field):
    with pytest.raises(ValueError):
        replace(managed[7].state, **{field: {"environmentNamespace": "env"}})
    assert managed[0].read_operation(managed[9]) is None


def test_foreign_store_issuer_cannot_claim_another_ledger(managed, tmp_path):
    original = reserve(managed)
    other = SqliteStorePort(tmp_path / "foreign.sqlite")
    try:
        # Copy the same fixed identity intentionally: a request id is not an
        # authority to swap out this Environment's sole operation journal.
        other.reserve_operation(managed[9], original.digest, original.intent)
        issuer = InvocationIssuer(other, managed[11], managed[12], clock=lambda: 50)
        with pytest.raises(GuaranteeUnavailableError): managed[8].claim_dispatch(managed[9], issuer)
        assert other.read_operation_step(managed[9], "native-input") is None
        assert managed[0].read_operation_step(managed[9], "native-input") is None
    finally: other.close()


@pytest.mark.parametrize("field", ["session", "source_revision", "configuration", "epoch", "directory"])
def test_current_native_evidence_change_before_claim_refuses_without_claim(managed, field):
    operation = reserve(managed)
    state = managed[7].state
    changes = {
        "session": {"session_ref": source(state.provider_ref, "different-session")},
        "source_revision": {"source_revision": 2},
        "configuration": {"before_configuration_evidence": source(state.provider_ref, "different-readback")},
        "epoch": {"management_epoch": 1},
        "directory": {"directory_binding_ref": replace(state.directory_binding_ref, binding_revision=2)},
    }
    managed[7].state = replace(state, **changes[field])
    with pytest.raises((AdmissionRefusedError, IdentityMismatchError, GuaranteeUnavailableError)):
        managed[8].claim_dispatch(managed[9], managed[13])
    assert managed[0].read_operation_step(managed[9], "native-input") is None
    assert managed[0].read_operation(managed[9]) == operation
    assert managed[7].dispatch_calls == 0


def test_unresolved_draft_fence_cannot_be_repointed_to_another_terminal_operation(managed):
    store = managed[0]
    first = reserve(managed)
    other_key = RequestKey("env", "principal", "unrelated-terminal")
    context = json.loads(safe_json(first.intent.context_ref))
    context["draftId"] = "different-draft"
    unrelated = replace(first.intent, operation_ref="unrelated-operation", kind="unrelated", context_ref=context)
    store.reserve_operation(other_key, "unrelated-digest", unrelated)
    other = store.read_operation(other_key)
    store.record_operation_outcome(other_key, other.digest, other.revision, "refused",
        {"evidenceRef": source(first.intent.steps[0].pinned_provider_ref, "controlled-unrelated-refusal")})
    fence = store.list_domain("env", DRAFT_ATTEMPTS)[0]
    corrupted = fence["value"]
    corrupted["requestId"] = other_key.request_id
    store._conn.execute("UPDATE env_domain_records SET payload=? WHERE namespace=? AND record_id=?",
        (safe_json(corrupted), DRAFT_ATTEMPTS, fence["record_id"]))
    captured = new_capture(managed)
    next_key = RequestKey("env", "principal", "new-key")
    with pytest.raises(GuaranteeUnavailableError): reserve(managed, request=next_key, captured_ref=captured)
    assert store.read_operation(next_key) is None
    assert store.read_operation(managed[9]) == first


@pytest.mark.parametrize("mismatch", ["repoint", "wrongkind", "wrongnode", "wrongdraft", "operationRef", "fence-node", "fence-draft"])
def test_digest_consistent_draft_fence_requires_exact_source_relationship(managed, mismatch):
    """Valid CAS updates deliberately bypass the consumer's fence writer.

    Both domain and operation digests remain valid. Refusal must therefore
    come from the managed-input relation guard, not corrupted JSON checks.
    """
    from ordessa_environment_api.domain import DomainWrite
    store = managed[0]
    first = reserve(managed)
    other_key = RequestKey("env", "principal", "terminal-other")
    context = json.loads(safe_json(first.intent.context_ref))
    node = json.loads(safe_json(first.intent.node_ref))
    kind = "managed-input"
    if mismatch in {"repoint", "wrongdraft"}:
        context["draftId"] = "another-draft"
    if mismatch == "wrongkind": kind = "different-operation-kind"
    if mismatch == "wrongnode": node["instanceId"] = "another-node"
    unrelated = replace(first.intent, operation_ref="other-terminal-operation", kind=kind,
        context_ref=context, node_ref=node)
    store.reserve_operation(other_key, "other-digest", unrelated)
    other = store.read_operation(other_key)
    store.record_operation_outcome(other_key, other.digest, other.revision, "refused",
        {"evidenceRef": source(first.intent.steps[0].pinned_provider_ref, "controlled-terminal-refusal")})
    fence = store.list_domain("env", DRAFT_ATTEMPTS)[0]
    altered = dict(fence["value"])
    altered["requestId"] = other_key.request_id
    altered["operationRef"] = unrelated.operation_ref
    if mismatch == "operationRef": altered["operationRef"] = "mismatched-operation-ref"
    if mismatch == "fence-node": altered["nodeRef"] = {**altered["nodeRef"], "instanceId": "another-node"}
    if mismatch == "fence-draft": altered["draftId"] = "another-draft"
    write_request = RequestKey("env", "principal", "controlled-fence-cas")
    store.commit_domain_change(write_request, "controlled-write-digest",
        (DomainWrite(DRAFT_ATTEMPTS, fence["record_id"], fence["revision"], altered),),
        {"controlledCAS": True})
    # Successful reads prove the stored digest is self-consistent.
    written = store.read_domain("env", DRAFT_ATTEMPTS, fence["record_id"])
    assert written["revision"] == fence["revision"] + 1
    assert written["value"] == altered
    assert store.read_operation(other_key).status == "refused"
    new_key = RequestKey("env", "principal", "new-input")
    captured = new_capture(managed)
    with pytest.raises(GuaranteeUnavailableError, match="source identity"):
        reserve(managed, request=new_key, captured_ref=captured)
    assert store.read_operation(new_key) is None
    assert store.read_operation(managed[9]) == first
    assert managed[7].dispatch_calls == 0


def test_concluded_and_published_attempt_allows_only_new_draft_revision(managed):
    store, _, _, _, _, _, _, _, inputs, request, _, _, _, issuer, _ = managed
    operation = reserve(managed)
    inputs.claim_dispatch(request, issuer)
    evidence = source(operation.intent.steps[0].pinned_provider_ref, "controlled-native-input-receipt")
    store.record_operation_step(request, operation.digest, "native-input", operation.digest, 1,
        "concluded", {"evidenceRef": evidence})
    latest = store.read_operation(request)
    store.publish_operation(request, operation.digest, latest.revision, ("native-input",), (), (),
        {"nodeRef": operation.intent.node_ref, "nativeAcceptedEvidenceRef": evidence})
    with pytest.raises(IdentityMismatchError): reserve(managed, request=RequestKey("env", "principal", "next-input"))
    captured = new_capture(managed)
    next_attempt = reserve(managed, request=RequestKey("env", "principal", "next-input"), captured_ref=captured)
    assert next_attempt.status == "reserved"
    assert next_attempt.intent.context_ref["draftRevision"] == 2
    assert managed[7].dispatch_calls == 0


def test_cold_restart_read_replay_does_not_restore_dispatch_authority(managed, tmp_path):
    from pacthold.public import Environment
    from pacthold.agents.nodes.publication import NodePublication
    store, env, policy, _, node, captured, capture, native, _, request, correlation, authority, current, _, _ = managed
    first = reserve(managed)
    path = store._path
    store.close()
    env._fixture_store_closed = True
    reopened = SqliteStorePort(path)
    try:
        cold_env = Environment("env", store=reopened, policy=policy,
            fingerprint_port=env._fingerprint_port, principal_scope="principal")
        cold_issuer = InvocationIssuer(reopened, authority, current, clock=lambda: 50)
        cold = ManagedInputReservations(cold_env, NodePublication(cold_env), capture, native,
                                        invocation_issuer=cold_issuer)
        assert cold.reserve(request, node, captured, correlation) == first
        with pytest.raises(AdmissionRefusedError): cold.claim_dispatch(request, cold_issuer)
        assert reopened.read_operation_step(request, "native-input") is None
        with pytest.raises(UnknownResultError):
            cold.reserve(RequestKey("env", "principal", "cold-new-key"), node, captured, correlation)
        assert reopened.read_operation(RequestKey("env", "principal", "cold-new-key")) is None
        assert native.dispatch_calls == 0
    finally:
        if "cold_issuer" in locals(): cold_issuer.close()
        reopened.close()

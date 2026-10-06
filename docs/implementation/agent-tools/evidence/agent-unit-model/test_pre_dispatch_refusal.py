"""Pre-dispatch refusal restores the prior configuration source atomically.

The tests use the real Environment, AgentConfiguration, InvocationIssuer and
temporary SQLite operation ledger. Provider callbacks are controlled contract
fixtures; no native process or model is involved.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_ROOT / "products/agent-tools/tests/integration"))
sys.path.insert(0, str(_ROOT / "docs/implementation/agent-tools/evidence/agent-unit-model"))

# Import both modules here: pytest does not inherit another module's fixture
# dependency registration when this file is collected independently.
from test_node_publication import setup as node_fixture, Provider  # noqa: F401
from test_management import setup, explicit_capabilities  # noqa: F401
from test_apply_profile import _base_ref, _profile

from ordessa_environment_api import (
    AdmissionRefusedError, IdentityMismatchError, RequestKey, UnknownResultError,
)
from ordessa_environment_api.domain import DomainRevisionConflict, DomainWrite
from ordessa_environment_api.operations import safe_json
from pacthold.agents.configuration import ApplicationPolicy
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import InvocationAuthorityRefused
from pacthold.agents.management import CONFIGURATION_ATTEMPTS
from ordessa_persistence_sqlite.operation_records import OperationRecordsMixin


def _apply_profile(parts, request, entry, base, expected_revision):
    return parts[3].apply_profile(
        request, parts[4], entry.current_manifest_ref, expected_revision,
        ApplicationPolicy(), base_profile_ref=base)


def _scope_record(parts):
    store, env, _, service, node = parts[:5]
    binding = service._nodes.read(node)["binding"]
    target = binding["configurationTargetRef"]
    scope_id = "scope-" + hashlib.sha256(safe_json(target).encode()).hexdigest()[:48]
    return store.read_domain(env.environment_id, CONFIGURATION_ATTEMPTS, scope_id)


def _establish_prior_profile(parts):
    base = _base_ref(parts)
    _, prior = _profile(parts, name="profile-prior")
    request = RequestKey("env", "principal", "apply-profile-prior")
    outcome = _apply_profile(parts, request, prior, base, "native-1")
    assert outcome.status == "published"
    assert parts[7]["calls"] == 1
    return base, prior, outcome, _scope_record(parts)


def _next_profile(parts, name="profile-next", model="newer"):
    declaration = {
        "declarationId": "model", "configurationKind": "model", "schemaVersion": "1",
        "action": "value", "requirement": "required", "payload": {"modelId": model},
    }
    return _profile(parts, declarations=(declaration,), name=name)[1]


def _arm_pre_dispatch_change(parts, monkeypatch, changed):
    service = parts[3]
    original_reserve = service.reserve
    binding = service._nodes.read(parts[4])["binding"]
    provider = parts[1].agent_runtime_contribution(binding["harnessDefinitionRef"]).provider
    original_inspect_unit = provider.inspect_unit
    injected = False

    def reserve_then_change(*args, **kwargs):
        nonlocal injected
        operation = original_reserve(*args, **kwargs)
        if injected:
            return operation
        injected = True
        if changed == "owner-source":
            provider.inspect_unit = lambda unit: replace(
                original_inspect_unit(unit), source_revision="unit-after-reserve")
        elif changed == "management-epoch":
            provider.inspect_unit = lambda unit: replace(
                original_inspect_unit(unit), management_epoch=1)
        elif changed == "directory-binding":
            provider.inspect_unit = lambda unit: replace(
                original_inspect_unit(unit),
                directory_binding_ref=DirectoryBindingRef("env", "rotated-directory", 2,
                                                           "sha256:" + "e" * 64))
        elif changed == "configuration-revision":
            parts[7]["revision"] = "native-after-reserve"
        elif changed == "directory-permission":
            parts[9].permitted = False
        elif changed == "issuer-authorization":
            parts[8].allowed = False
        return operation

    monkeypatch.setattr(service, "reserve", reserve_then_change)
    return provider, original_inspect_unit


@pytest.mark.parametrize(
    ("changed", "expected_phase", "expected_reason"),
    [
        ("owner-source", "owner-recheck", "owner-evidence-changed"),
        ("management-epoch", "owner-recheck", "owner-evidence-changed"),
        ("directory-binding", "owner-recheck", "owner-evidence-changed"),
        ("configuration-revision", "owner-recheck", "configuration-revision-changed"),
        ("directory-permission", "invocation-issuance", "invocation-authority-refused"),
        ("issuer-authorization", "invocation-issuance", "invocation-authority-refused"),
    ],
)
def test_pre_dispatch_refusal_restores_prior_source_replays_and_allows_new_key(
        setup, monkeypatch, changed, expected_phase, expected_reason):
    parts = setup
    store = parts[0]
    base, prior, prior_outcome, prior_fence = _establish_prior_profile(parts)
    next_profile = _next_profile(parts)
    request = RequestKey("env", "principal", "apply-profile-refused-" + changed)
    provider, original_inspect_unit = _arm_pre_dispatch_change(parts, monkeypatch, changed)

    expected_exception = (InvocationAuthorityRefused
                          if changed in {"directory-permission", "issuer-authorization"}
                          else AdmissionRefusedError)
    with pytest.raises(expected_exception):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    refused = store.read_operation(request)
    assert refused is not None and refused.status == "refused"
    assert store.read_operation_step(request, "configuration-apply") is None
    assert parts[7]["calls"] == 1
    refused_fence = _scope_record(parts)
    assert refused_fence["revision"] > prior_fence["revision"]
    assert refused_fence["value"]["expectedProfileRef"] == prior.current_manifest_ref.to_dict()
    assert refused_fence["value"]["expectedProfileOperationRef"] == prior_outcome.intent.operation_ref
    assert refused_fence["value"]["expectedProfileOperationRef"] != refused.intent.operation_ref

    evidence = json.loads(refused.evidence_json)
    refusal = evidence["preDispatchRefusal"]
    assert refusal == {"phase": expected_phase, "reason": expected_reason}
    assert set(evidence) == {"preDispatchRefusal", "domainWritesDigest"}
    assert "credential-do-not-leak" not in refused.evidence_json
    assert "private-test-secret" not in refused.evidence_json

    # The identical key is a read-only replay. Restore only the controlled
    # owner/authorization condition before trying an independent request.
    if changed in {"owner-source", "management-epoch", "directory-binding"}:
        provider.inspect_unit = original_inspect_unit
    if changed == "configuration-revision":
        parts[7]["revision"] = "native-2"
    if changed == "directory-permission":
        parts[9].permitted = True
    if changed == "issuer-authorization":
        parts[8].allowed = True
    replay = _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    assert replay.status == "refused"
    assert store.read_operation(request) == refused
    assert parts[7]["calls"] == 1
    assert _scope_record(parts)["value"]["expectedProfileRef"] == prior.current_manifest_ref.to_dict()

    fresh = RequestKey("env", "principal", "apply-profile-fresh-" + changed)
    outcome = _apply_profile(parts, fresh, next_profile, prior.current_manifest_ref, "native-2")
    assert outcome.status == "published"
    assert parts[7]["calls"] == 2
    assert _scope_record(parts)["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()
    assert _scope_record(parts)["value"]["expectedProfileOperationRef"] == outcome.intent.operation_ref


def test_claimed_step_cannot_be_converted_to_unclaimed_refusal(setup, monkeypatch):
    parts = setup
    store = parts[0]
    base = _base_ref(parts)
    next_profile = _next_profile(parts, name="profile-claimed", model="claimed")
    request = RequestKey("env", "principal", "apply-profile-claimed-then-fails")
    service = parts[3]
    current = parts[9]
    original_reserve = service.reserve

    def fail_after_claim(*args, **kwargs):
        operation = original_reserve(*args, **kwargs)
        current.fail_on = current.inspect_calls + 2
        return operation

    monkeypatch.setattr(service, "reserve", fail_after_claim)
    with pytest.raises(UnknownResultError):
        _apply_profile(parts, request, next_profile, base, "native-1")
    operation = store.read_operation(request)
    step = store.read_operation_step(request, "configuration-apply")
    assert operation.status != "refused"
    assert step is not None and step.outcome == "possibly-dispatched"
    assert parts[7]["calls"] == 0
    assert _scope_record(parts)["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()


def test_owner_unknown_replay_preserves_its_claim_and_proposed_source(setup):
    parts = setup
    store = parts[0]
    base = _base_ref(parts)
    parts[7]["outcome"] = "unknown"
    unknown_request = RequestKey("env", "principal", "apply-profile-owner-unknown")
    unknown_profile = _next_profile(parts, name="profile-unknown", model="uncertain")
    unknown = _apply_profile(parts, unknown_request, unknown_profile, base, "native-1")
    assert unknown.status == "unknown"
    assert store.read_operation_step(unknown_request, "configuration-apply").outcome == "unknown"
    calls = parts[7]["calls"]
    assert parts[3].apply_profile(unknown_request, parts[4], unknown_profile.current_manifest_ref,
                                 "native-1", ApplicationPolicy(),
                                 base_profile_ref=base).status == "unknown"
    assert parts[7]["calls"] == calls
    assert store.read_operation(unknown_request).status == "unknown"
    assert _scope_record(parts)["value"]["expectedProfileRef"] == unknown_profile.current_manifest_ref.to_dict()


def test_concluded_step_replay_stays_published_and_never_refuses(setup):
    parts = setup
    store = parts[0]
    base, prior, _, _ = _establish_prior_profile(parts)
    parts[7].update(outcome="applied", revision="native-2", model="new")
    concluded_request = RequestKey("env", "principal", "apply-profile-concluded")
    concluded_profile = _next_profile(parts, name="profile-concluded", model="final")
    concluded = _apply_profile(parts, concluded_request, concluded_profile,
                               prior.current_manifest_ref, "native-2")
    assert concluded.status == "published"
    assert store.read_operation_step(concluded_request, "configuration-apply").outcome == "concluded"
    assert parts[3].apply_profile(concluded_request, parts[4], concluded_profile.current_manifest_ref,
                                 "native-2", ApplicationPolicy(),
                                 base_profile_ref=prior.current_manifest_ref).status == "published"
    assert store.read_operation(concluded_request).status == "published"
    assert _scope_record(parts)["value"]["expectedProfileRef"] == concluded_profile.current_manifest_ref.to_dict()


def test_refusal_fence_cas_conflict_preserves_competing_write_and_reserved_operation(setup, monkeypatch):
    parts = setup
    store = parts[0]
    base, prior, _, _ = _establish_prior_profile(parts)
    next_profile = _next_profile(parts, name="profile-cas", model="cas")
    request = RequestKey("env", "principal", "apply-profile-cas-conflict")
    original_reserve = parts[3].reserve
    record = {}

    def reserve_then_race(*args, **kwargs):
        operation = original_reserve(*args, **kwargs)
        record["fence"] = _scope_record(parts)
        original_refusal = store.refuse_unclaimed_operation

        def race_after_management_validation(req, digest, expected_revision, evidence, writes):
            store._conn.execute(
                "UPDATE env_domain_records SET revision=? WHERE environment=? AND namespace=? AND record_id=?",
                (record["fence"]["revision"] + 1, "env", CONFIGURATION_ATTEMPTS,
                 record["fence"]["record_id"]),
            )
            # Commit the competing write before the refusal capability starts
            # its own transaction; this is a durable CAS race, not a nested tx.
            store._conn.commit()
            return original_refusal(req, digest, expected_revision, evidence, writes)

        monkeypatch.setattr(store, "refuse_unclaimed_operation", race_after_management_validation)
        parts[9].permitted = False
        return operation

    monkeypatch.setattr(parts[3], "reserve", reserve_then_race)
    with pytest.raises(DomainRevisionConflict):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    operation = store.read_operation(request)
    fence = _scope_record(parts)
    assert operation is not None and operation.status == "reserved"
    assert store.read_operation_step(request, "configuration-apply") is None
    assert fence["revision"] == record["fence"]["revision"] + 1
    assert fence["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()
    assert parts[7]["calls"] == 1


def test_sqlite_failure_rolls_back_refusal_and_fence_restore_together(setup, monkeypatch):
    parts = setup
    store = parts[0]
    _, prior, _, _ = _establish_prior_profile(parts)
    next_profile = _next_profile(parts, name="profile-rollback", model="rollback")
    request = RequestKey("env", "principal", "apply-profile-transaction-failure")
    original_reserve = parts[3].reserve

    def reserve_then_install_trigger(*args, **kwargs):
        operation = original_reserve(*args, **kwargs)
        store._conn.execute(
            "CREATE TRIGGER reject_pre_dispatch_refusal BEFORE UPDATE ON env_requests "
            "WHEN NEW.request_id='apply-profile-transaction-failure' "
            "BEGIN SELECT RAISE(ABORT,'controlled refusal transaction failure'); END")
        parts[9].permitted = False
        return operation

    monkeypatch.setattr(parts[3], "reserve", reserve_then_install_trigger)
    with pytest.raises(sqlite3.IntegrityError):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    operation = store.read_operation(request)
    assert operation is not None and operation.status == "reserved"
    assert store.read_operation_step(request, "configuration-apply") is None
    fence = _scope_record(parts)
    assert fence["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()
    assert fence["value"]["requestId"] == request.request_id
    assert parts[7]["calls"] == 1


def test_optional_refusal_capability_missing_fails_closed_without_releasing_fence(setup, monkeypatch):
    parts = setup
    store = parts[0]
    _, prior, _, _ = _establish_prior_profile(parts)
    next_profile = _next_profile(parts, name="profile-no-refusal-port", model="no-port")
    request = RequestKey("env", "principal", "apply-profile-no-refusal-port")
    original_reserve = parts[3].reserve

    def reserve_then_remove_capability(*args, **kwargs):
        operation = original_reserve(*args, **kwargs)
        monkeypatch.delattr(OperationRecordsMixin, "refuse_unclaimed_operation")
        parts[9].permitted = False
        return operation

    monkeypatch.setattr(parts[3], "reserve", reserve_then_remove_capability)
    with pytest.raises(AdmissionRefusedError):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    operation = store.read_operation(request)
    assert operation is not None and operation.status == "reserved"
    assert store.read_operation_step(request, "configuration-apply") is None
    assert _scope_record(parts)["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()
    assert parts[7]["calls"] == 1


def test_legacy_intent_without_rollback_facts_fails_closed(setup, monkeypatch):
    parts = setup
    store = parts[0]
    _, prior, _, _ = _establish_prior_profile(parts)
    next_profile = _next_profile(parts, name="profile-legacy-intent", model="legacy")
    request = RequestKey("env", "principal", "apply-profile-legacy-intent")
    original_reserve = parts[3].reserve

    def reserve_then_remove_fixed_fact(*args, **kwargs):
        operation = original_reserve(*args, **kwargs)
        row = store._conn.execute(
            "SELECT operation_json FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
            (request.environment_namespace, request.principal_scope, request.request_id),
        ).fetchone()
        intent = json.loads(row["operation_json"])
        intent["contextRef"].pop("preDispatchRollback")
        encoded = safe_json(intent)
        store._conn.execute(
            "UPDATE env_requests SET operation_json=?,operation_intent_digest=? "
            "WHERE environment=? AND principal=? AND request_id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), request.environment_namespace,
             request.principal_scope, request.request_id),
        )
        parts[9].permitted = False
        # Model a subsequent process loading an older durable intent, rather
        # than letting this invocation keep its pre-mutation in-memory copy.
        return store.read_operation(request)

    monkeypatch.setattr(parts[3], "reserve", reserve_then_remove_fixed_fact)
    with pytest.raises(AdmissionRefusedError):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")
    operation = store.read_operation(request)
    assert operation is not None and operation.status == "reserved"
    assert "preDispatchRollback" not in operation.intent.context_ref
    assert store.read_operation_step(request, "configuration-apply") is None
    assert _scope_record(parts)["value"]["expectedProfileRef"] == next_profile.current_manifest_ref.to_dict()
    assert parts[7]["calls"] == 1


def test_refusal_store_same_arguments_replay_and_changed_writes_are_idempotent_or_rejected(
        setup, monkeypatch):
    parts = setup
    store = parts[0]
    _, prior, _, _ = _establish_prior_profile(parts)
    next_profile = _next_profile(parts, name="profile-direct-replay", model="direct-replay")
    request = RequestKey("env", "principal", "apply-profile-direct-refusal-replay")
    captured = []
    original_refusal = store.refuse_unclaimed_operation

    def capture_public_call(req, digest, expected_revision, evidence, writes):
        arguments = (req, digest, expected_revision, evidence, writes)
        captured.append(arguments)
        return original_refusal(*arguments)

    monkeypatch.setattr(store, "refuse_unclaimed_operation", capture_public_call)
    original_reserve = parts[3].reserve
    injected = False

    def reserve_then_revoke_once(*args, **kwargs):
        nonlocal injected
        operation = original_reserve(*args, **kwargs)
        if not injected:
            injected = True
            parts[9].permitted = False
        return operation

    monkeypatch.setattr(parts[3], "reserve", reserve_then_revoke_once)
    with pytest.raises(InvocationAuthorityRefused):
        _apply_profile(parts, request, next_profile, prior.current_manifest_ref, "native-2")

    refused = store.read_operation(request)
    fence = _scope_record(parts)
    assert refused.status == "refused"
    assert len(captured) == 1
    arguments = captured[0]
    assert arguments[0] == request
    assert arguments[3] == {"phase": "invocation-issuance", "reason": "invocation-authority-refused"}
    assert len(arguments[4]) == 1

    same = original_refusal(*arguments)
    assert same == refused
    assert store.read_operation(request) == refused
    assert _scope_record(parts) == fence

    write = arguments[4][0]
    changed_value = {**write.value, "principalScope": "other-principal"}
    changed_write = DomainWrite(write.namespace, write.record_id,
                                write.expected_revision, changed_value)
    with pytest.raises(IdentityMismatchError):
        original_refusal(arguments[0], arguments[1], arguments[2], arguments[3], (changed_write,))
    assert store.read_operation(request) == refused
    assert _scope_record(parts) == fence
    assert parts[7]["calls"] == 1


def test_refusal_store_rejects_a_concluded_step_without_changing_publication(setup):
    parts = setup
    store = parts[0]
    _, prior, _, _ = _establish_prior_profile(parts)
    parts[7].update(outcome="applied", revision="native-2", model="new")
    request = RequestKey("env", "principal", "apply-profile-direct-concluded")
    profile = _next_profile(parts, name="profile-direct-concluded", model="direct-concluded")
    operation = _apply_profile(parts, request, profile, prior.current_manifest_ref, "native-2")
    assert operation.status == "published"
    assert store.read_operation_step(request, "configuration-apply").outcome == "concluded"
    fence = _scope_record(parts)

    with pytest.raises(UnknownResultError):
        store.refuse_unclaimed_operation(
            request, operation.digest, operation.revision,
            {"phase": "owner-recheck", "reason": "owner-evidence-changed"}, ())

    assert store.read_operation(request) == operation
    assert store.read_operation_step(request, "configuration-apply").outcome == "concluded"
    assert _scope_record(parts) == fence

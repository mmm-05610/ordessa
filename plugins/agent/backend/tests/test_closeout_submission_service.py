"""T011 submission orchestration regressions over the actual Environment.

The controlled native adapter owns a separate effects database. The test
Environment and Agent journal use separate SQLite stores, so these checks
exercise the cross-store request fence without invoking real Harness models.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ordessa_agent.owners import AgentOwnerRegistry
from ordessa_agent.submission_journal import (
    JournalConflictError,
    ReliableSubmissionUnsupported,
    SubmissionJournal,
)
from ordessa_agent.submission_service import (
    AgentSubmissionService,
    NativeSubmitBinding,
    NativeSubmitDeclaration,
    NativeSubmitResult,
    SubmissionInput,
)
from ordessa_environment_api import GuaranteeUnavailableError, RequestKey
from ordessa_environment_api.guarantee import GuaranteeLevel
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord


@dataclass(frozen=True)
class _SubmitContract:
    contract_id = "agent.submit@1"


class _AllowInvoke:
    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool:
        return True

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool:
        return True


class _TestEnvironment(Environment):
    def __init__(self, environment_id, *, store, policy, fingerprint_port):
        super().__init__(environment_id, store=store, policy=policy,
                         fingerprint_port=fingerprint_port)
        self._test_store_port = store

    @property
    def store_port(self):
        return self._test_store_port


class _ControlledNativeSubmitPort:
    """Declared conditional adapter whose effects are recorded separately."""

    def __init__(self, effects_path, *, mode="existing", supports_existing=True,
                 supports_create_with_config=True, lose_answer=False,
                 binding_owner_ref="harness-owner:session-1", binding_barrier=None,
                 emit_session_fact=False):
        self.effects_path = effects_path
        self.mode = mode
        self.binding_owner_ref = binding_owner_ref
        self.declaration = NativeSubmitDeclaration(
            owner_ref="harness-owner:session-1",
            existing_conditional=supports_existing,
            create_with_config_conditional=supports_create_with_config,
            immutable_attachments=True,
        )
        self.effect_calls = 0
        self.binding_calls = 0
        self.query_calls = 0
        self.lose_answer = lose_answer
        self.binding_barrier = binding_barrier
        self.emit_session_fact = emit_session_fact
        self.on_effect = None

    def resolve_binding(self, target):
        self.binding_calls += 1
        if self.binding_barrier is not None:
            self.binding_barrier.wait(timeout=5)
        return NativeSubmitBinding(
            target=target,
            owner_ref=self.binding_owner_ref,
            mode=self.mode,
            surface_id="agent.submit",
            base_revision="native-r4",
            identity={"sessionId": "session-1", "generation": "2"},
        )

    def read_attachment(self, target, attachment_id):
        assert target == "session:S1"
        assert attachment_id == "attachment-1"
        return b"immutable attachment bytes"

    def submit_existing(self, request, capture):
        return self._effect(request, capture, kind="existing")

    def create_with_config(self, request, capture):
        return self._effect(request, capture, kind="createWithConfig")

    def _effect(self, request, capture, *, kind):
        self.effect_calls += 1
        if self.on_effect is not None:
            callback, self.on_effect = self.on_effect, None
            callback()
        captured = {
            "submissionId": capture.submission_id,
            "draft": _wire(capture.draft),
            "configOperationIds": list(capture.config_op_ids),
            "baseRevision": capture.base,
            "target": _wire(capture.target),
            "binding": _wire(capture.binding),
            "schema": capture.schema,
            "guarantee": capture.guarantee.value,
        }
        with sqlite3.connect(self.effects_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_effects "
                "(request_id TEXT PRIMARY KEY, count INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO native_effects VALUES (?, 1, ?, ?) "
                "ON CONFLICT(request_id) DO UPDATE SET count=count+1",
                (request.request_id, kind, json.dumps({"capture": captured}, sort_keys=True)),
            )
        if self.lose_answer:
            raise ConnectionError("native effect may have happened; answer was lost")
        return None

    def query(self, request):
        self.query_calls += 1
        with sqlite3.connect(self.effects_path) as connection:
            row = connection.execute(
                "SELECT payload FROM native_effects WHERE request_id=?", (request.request_id,),
            ).fetchone()
        if row is None or self.lose_answer:
            return NativeSubmitResult(outcome="unknown")
        capture = json.loads(row[0])["capture"]
        acceptance = {"outcome": "accepted", "draftRevision": capture["draft"]["draftRevision"]}
        if self.emit_session_fact:
            acceptance["session"] = {
                "target": capture["target"]["target"],
                "sessionId": capture["target"]["target"],
                "nativeSessionId": capture["binding"]["sessionId"],
                "generation": capture["binding"]["generation"],
                "ownerRef": capture["binding"]["ownerRef"],
            }
        return NativeSubmitResult(
            outcome="accepted",
            config_apply={"outcome": "applied", "operationIds": capture["configOperationIds"]},
            input_acceptance=acceptance,
            run_result={"outcome": "running", "runId": "run-controlled-1"},
        )

    def list_sessions(self, target):
        if not self.emit_session_fact:
            return ()
        with sqlite3.connect(self.effects_path) as connection:
            rows = connection.execute("SELECT payload FROM native_effects").fetchall()
        result = []
        for (payload,) in rows:
            session = json.loads(payload)["capture"]["target"]["target"]
            if session == target:
                result.append({
                    "target": target,
                    "sessionId": target,
                    "nativeSessionId": "session-1",
                    "generation": "2",
                    "ownerRef": "harness-owner:session-1",
                })
        return tuple(result)


def _wire(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    return value


def _input(*, text="hello", mode="existing", config_operation_ids=("op-session:S1-1",),
           submission_id="submission-1", draft_revision=7):
    return SubmissionInput(
        submission_id=submission_id,
        principal_scope="user:local:agent-test",
        target="session:S1",
        mode=mode,
        draft={
            "draftId": "draft-1",
            "draftRevision": draft_revision,
            "text": text,
            "attachmentIds": ["attachment-1"],
        },
        # Match the trusted ConfigOwner operation created by _service(); the
        # caller cannot invent an operation id and have it captured as fact.
        config_operation_ids=config_operation_ids,
        schema="agent-input/v1",
    )


def _service(tmp_path, *, mode="existing", supports_existing=True,
             supports_create_with_config=True, lose_answer=False,
             binding_owner_ref="harness-owner:session-1",
             environment_has_fingerprint=True, binding_barrier=None,
             create_config_operation=True, add_late_config_during_effect=False,
             emit_session_fact=False):
    fingerprint = ProtectedFingerprintHmac(
        {"fixture-key": b"submission-service-fixture-key"}, active_key_id="fixture-key",
    )
    backend_store = SqliteStorePort(tmp_path / "environment.sqlite", writer_token="environment-test")
    domain_store = SqliteStorePort(tmp_path / "agent-domain.sqlite", writer_token="agent-domain-test")
    environment = _TestEnvironment(
        "env-agent-service", store=backend_store, policy=_AllowInvoke(),
        fingerprint_port=fingerprint if environment_has_fingerprint else None,
    )
    environment.install(InstallationRecord("agent-submit", "a" * 64))
    environment.enable("agent-submit")
    environment.activate("agent-submit", CoreContributionSet(contracts=(_SubmitContract,)))

    owners = AgentOwnerRegistry()
    config_owner = owners.register("session:S1")["config"]
    if create_config_operation:
        operation = config_owner.submit_operation({"model": "model-a"}, "profile-selection")
        assert operation.operation_id == "op-session:S1-1"
    journal = SubmissionJournal(domain_store, fingerprint_port=fingerprint)
    port = _ControlledNativeSubmitPort(
        tmp_path / "native-effects.sqlite", mode=mode,
        supports_existing=supports_existing,
        supports_create_with_config=supports_create_with_config,
        lose_answer=lose_answer,
        binding_owner_ref=binding_owner_ref,
        binding_barrier=binding_barrier,
        emit_session_fact=emit_session_fact,
    )
    if add_late_config_during_effect:
        port.on_effect = lambda: owners.owners_of("session:S1")["config"].submit_operation(
            {"temperature": 0.4}, "late-profile-selection",
        )
    service = AgentSubmissionService(
        environment=environment,
        journal=journal,
        owners=owners,
        native_submit_port=port,
    )
    return service, environment, journal, port, backend_store, domain_store


def _key(environment, request_id="submission-1"):
    return RequestKey(
        environment.environment_id,
        "user:local:agent-test",
        request_id,
    )


def test_existing_submission_uses_environment_once_and_persists_separate_domain_facts(tmp_path):
    service, environment, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        result = service.submit(_input())

        assert result.outcome == "accepted"
        assert result.replayed is False
        assert result.record.stage == "completed"
        assert result.record.config_apply == {"outcome": "applied", "operationIds": ("op-session:S1-1",)}
        assert result.record.input_acceptance == {"outcome": "accepted", "draftRevision": 7}
        assert result.record.run_result == {"outcome": "running", "runId": "run-controlled-1"}
        assert port.effect_calls == 1
        assert service.owners.owners_of("session:S1")["config"].list_operations()[0].state == "applied"

        backend = environment.query(result.record.request)
        assert backend is not None
        assert backend[0].request.request_id == "submission-1"
        assert backend[1].outcome == "concluded"
        observation = service.query("session:S1", "submission-1", "user:local:agent-test")
        assert observation is not None
        assert observation.backend_fact == backend
        assert observation.submission.stage == "completed"

        replay = service.submit(_input())
        assert replay.replayed is True
        assert replay.request == result.request
        assert port.effect_calls == 1
        assert journal.read(result.record.request).stage == "completed"
    finally:
        backend_store.close()
        domain_store.close()


def test_same_request_id_with_changed_immutable_input_conflicts_without_second_effect(tmp_path):
    service, _, _, port, backend_store, domain_store = _service(tmp_path)
    try:
        service.submit(_input())
        with pytest.raises(JournalConflictError):
            service.submit(_input(text="changed after first capture"))
        assert port.effect_calls == 1
    finally:
        backend_store.close()
        domain_store.close()


def test_create_with_config_requires_declared_conditional_support_and_never_falls_back(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, mode="createWithConfig", supports_create_with_config=False,
    )
    try:
        with pytest.raises(ReliableSubmissionUnsupported, match="createWithConfig"):
            service.submit(_input(mode="createWithConfig"))
        assert port.effect_calls == 0
        assert journal.read(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_existing_mode_does_not_fallback_to_create_when_conditional_existing_is_absent(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, mode="existing", supports_existing=False,
    )
    try:
        with pytest.raises(ReliableSubmissionUnsupported, match="existing"):
            service.submit(_input())
        assert port.effect_calls == 0
        assert journal.read(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_mismatched_native_owner_binding_is_refused_before_mapping_or_effect(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, binding_owner_ref="harness-owner:other-session",
    )
    try:
        with pytest.raises(ReliableSubmissionUnsupported, match="owner binding"):
            service.submit(_input())
        assert port.effect_calls == 0
        assert journal.read(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_environment_without_reliable_key_refuses_before_journal_fence_or_native_effect(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, environment_has_fingerprint=False,
    )
    try:
        with pytest.raises(GuaranteeUnavailableError):
            service.submit(_input())
        assert port.effect_calls == 0
        assert journal.read(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_frontend_outcome_claim_is_not_capture_or_native_result_evidence(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    forged = _input()
    forged = SubmissionInput(
        submission_id=forged.submission_id,
        principal_scope=forged.principal_scope,
        target=forged.target,
        mode=forged.mode,
        draft={**forged.draft, "outcome": "accepted"},
        config_operation_ids=forged.config_operation_ids,
        schema=forged.schema,
    )
    try:
        with pytest.raises(ReliableSubmissionUnsupported, match="undeclared fields"):
            service.submit(forged)
        assert port.effect_calls == 0
        assert journal.read(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_unknown_native_answer_is_query_only_and_same_key_is_never_redispatched(tmp_path):
    service, environment, journal, port, backend_store, domain_store = _service(
        tmp_path, lose_answer=True,
    )
    try:
        first = service.submit(_input())
        assert first.outcome == "unknown"
        assert first.record.stage == "possibly-submitted"
        assert port.effect_calls == 1

        observed = service.query("session:S1", "submission-1", "user:local:agent-test")
        assert observed is not None
        assert observed.backend_fact[1].outcome == "unknown"
        assert observed.submission.request.request_id == "submission-1"

        replay = service.submit(_input())
        assert replay.outcome == "unknown"
        assert replay.replayed is True
        assert port.effect_calls == 1
        assert journal.read(first.request).stage == "possibly-submitted"
        assert environment.query(first.request)[1].outcome == "unknown"
        with sqlite3.connect(tmp_path / "native-effects.sqlite") as connection:
            assert connection.execute("SELECT count FROM native_effects").fetchone()[0] == 1
    finally:
        backend_store.close()
        domain_store.close()


def test_query_rejects_a_different_target_for_an_existing_submission(tmp_path):
    service, _, _, _, backend_store, domain_store = _service(tmp_path)
    try:
        service.submit(_input())
        assert service.query("session:other", "submission-1", "user:local:agent-test") is None
    finally:
        backend_store.close()
        domain_store.close()


def test_simultaneous_same_request_enters_native_effect_once(tmp_path):
    barrier = Barrier(2)
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, binding_barrier=barrier,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: service.submit(_input()), range(2)))
        assert len(results) == 2
        assert all(result.request.request_id == "submission-1" for result in results)
        assert port.effect_calls == 1
        assert journal.read(results[0].request).stage == "completed"
        with sqlite3.connect(tmp_path / "native-effects.sqlite") as connection:
            assert connection.execute("SELECT count FROM native_effects").fetchone()[0] == 1
    finally:
        backend_store.close()
        domain_store.close()


def test_configuration_capture_requires_exact_pending_operation_set(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        service.owners.owners_of("session:S1")["config"].submit_operation(
            {"temperature": 0.4}, "late-profile-selection",
        )
        with pytest.raises(ReliableSubmissionUnsupported, match="exactly capture"):
            service.submit(_input())
        assert journal.read(_key(service.environment)) is None
        assert port.effect_calls == 0
    finally:
        backend_store.close()
        domain_store.close()


def test_config_free_submission_allows_empty_owner_operation_capture(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(
        tmp_path, create_config_operation=False,
    )
    try:
        result = service.submit(_input(config_operation_ids=()))
        assert result.outcome == "accepted"
        assert result.record.stage == "completed"
        assert port.effect_calls == 1
        assert journal.read(result.request).config_apply["operationIds"] == ()
    finally:
        backend_store.close()
        domain_store.close()


def test_native_application_settles_only_captured_operations_when_late_edit_arrives_during_output(tmp_path):
    service, _, _, port, backend_store, domain_store = _service(
        tmp_path, add_late_config_during_effect=True,
    )
    try:
        first = service.submit(_input())
        operations = service.owners.owners_of("session:S1")["config"].list_operations()
        assert [operation.operation_id for operation in operations] == [
            "op-session:S1-1", "op-session:S1-2",
        ]
        assert [operation.state for operation in operations] == ["applied", "pending"]

        second = service.submit(_input(
            submission_id="submission-2", draft_revision=8,
            config_operation_ids=("op-session:S1-2",),
        ))
        captured = json.loads(second.record.encoded_input)["capture"]
        assert captured["configOperationIds"] == ["op-session:S1-2"]
        assert [operation.state for operation in
                service.owners.owners_of("session:S1")["config"].list_operations()] == [
                    "applied", "applied",
                ]
        assert port.effect_calls == 2
    finally:
        backend_store.close()
        domain_store.close()


def test_second_send_after_applied_config_is_config_free(tmp_path):
    service, _, _, port, backend_store, domain_store = _service(tmp_path)
    try:
        service.submit(_input())
        second = service.submit(_input(
            submission_id="submission-2", draft_revision=8,
            config_operation_ids=(),
        ))
        captured = json.loads(second.record.encoded_input)["capture"]
        assert captured["configOperationIds"] == []
        assert second.outcome == "accepted"
        assert port.effect_calls == 2
    finally:
        backend_store.close()
        domain_store.close()


def test_trusted_native_query_projects_session_history_without_frontend_session_claims(tmp_path):
    service, _, _, _, backend_store, domain_store = _service(tmp_path, emit_session_fact=True)
    try:
        service.submit(_input())
        sessions, source = service.list_sessions("session:S1")
        assert source == "native-query"
        assert sessions == ({
            "target": "session:S1",
            "sessionId": "session:S1",
            "nativeSessionId": "session-1",
            "generation": "2",
            "ownerRef": "harness-owner:session-1",
            "source": "native-session-query",
        },)
    finally:
        backend_store.close()
        domain_store.close()

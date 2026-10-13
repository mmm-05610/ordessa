"""C: original SQLite + actual InvocationIssuer, controlled owner/effects.

No SDK import, Claude process, model, async bridge or production owner. Reuse
existing owner fixtures read-only; a controlled factory is never product wiring.
"""
from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from agent_tools_fixtures import configuration_records as shared_fixture
from agent_tools_fixtures.native_evidence import UnitEvidence
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_units.records.unit_records import UnitRecords, UnitRecordsRefused
from ordessa_execution_api.environment.operations import safe_json
from ordessa_harness_claude_code.provider import ClaudeCodeRuntimeProvider
from ordessa_harness_claude_code.unit_lifecycle import ClaudeUnitCoordinationRefused


PROVIDER = {"environmentNamespace": "env", "providerId": "claude", "generation": 1,
            "ownerActivationRef": {"environmentNamespace": "env", "pluginId": "claude-independent", "generation": 1},
            "contractVersion": "agent-runtime/2", "implementationDigest": "sha256:" + "c" * 64}


class Projection:
    def __init__(self, records, unit, issuer, request):
        self.records, self.verifier, self.unit = records, records.verifier, unit
        self.issuer, self.request = issuer, request

    def read_unit(self, reference, context):
        # Genuine original-store read capability, not reference-as-permission.
        read = self.issuer.issue_query(self.request, "flow-digest", "prepare")
        return self.records.resolve_unit_reference(reference, read, input_digest="input")

    def resolve_original_start(self, correlation, context):
        assert correlation == "start-correlation"
        return self.read_unit(self.unit.public_ref, context)


class Effects:
    def __init__(self, records, authority, *, mode="ok"):
        self.records, self.verifier, self.native_evidence = records, records.verifier, records.native_unit_evidence
        self.authority, self.mode = authority, mode
        self.handles, self.initialized, self.contexts = [], [], []
        self.close_calls = self.kill_calls = 0

    def current(self, unit, context):
        assert not isinstance(context, dict)  # exact opaque capability, never verified facts.
        self.verifier.verify_continuation(context, "start", unit.facts["providerRef"],
                                        unit.facts["nodeRef"], "start-input")
        self.contexts.append(context)

    @contextmanager
    def dispatch_guard(self, unit, context, phase):
        self.current(unit, context)
        yield

    def open_owned(self, unit, context):
        self.current(unit, context)
        handle = object()
        self.handles.append(handle)  # original owner retains it before return/failure.
        if self.mode == "lost-open":
            raise OSError("controlled opening receipt loss")
        if self.mode == "revoke-after-open":
            self.authority.allowed = False
        return handle

    def initialize_owned(self, unit, handle, context):
        self.current(unit, context)
        assert handle is self.handles[0]
        self.initialized.append(handle)
        if self.mode == "lost-init":
            raise OSError("controlled initialize receipt loss")
        if self.mode == "ack":
            return {"accepted": True}
        return self.native_evidence.reference(unit, "receipt")


class Observations:
    def __init__(self, records, *, available=True):
        self.records, self.verifier, self.native_evidence = records, records.verifier, records.native_unit_evidence
        self.available = available
        self.calls = []

    def query_original_unit(self, unit, correlation, context):
        assert not isinstance(context, dict)
        self.calls.append((unit.public_ref, correlation, context))
        return self.native_evidence.reference(unit, "receipt") if self.available else None


def configured(tmp_path, monkeypatch, *, mode="ok"):
    monkeypatch.setattr(shared_fixture, "PROVIDER", PROVIDER)
    p, unit, store, request, issuer, authority, current, issued = shared_fixture.real_core_parts(tmp_path, start_native_session=False)
    owner = UnitEvidence()
    p[0].native_unit_evidence = owner
    projection = Projection(p[0], unit, issuer, request)
    effects = Effects(p[0], authority, mode=mode)
    observations = Observations(p[0])
    runtime = make_provider(p[0], projection, effects, observations)
    return runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations


def make_provider(records, projection, effects=None, observations=None):
    return ClaudeCodeRuntimeProvider(definition_ref={"environmentNamespace": "env", "definitionId": "claude", "revision": "1"},
        implementation_digest=PROVIDER["implementationDigest"], verifier=records.verifier, unit_records=records,
        unit_projection=projection, native_unit_effects=effects, native_unit_observations=observations)


def mark_unknown(store, request):
    store.record_operation_step(request, "flow-digest", "start", "start-input", 1, "unknown", {})


def test_original_start_confirms_unit_without_session_and_consumes_one_claim(tmp_path, monkeypatch):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch)
    try:
        context = issued("start")
        result = runtime.start({"unitRef": unit.public_ref}, context)
        assert result["state"] == "confirmed" and safe_json(result["unitRef"]) == safe_json(unit.public_ref)
        assert issuer.verified_consumption(context)
        assert effects.contexts and all(item is context for item in effects.contexts)
        assert len(effects.handles) == len(effects.initialized) == 1
        assert "sessionId" not in result and effects.close_calls == effects.kill_calls == 0
        with p[1]._connect() as db:
            assert db.execute("SELECT state FROM harness_unit_confirmations").fetchone()["state"] == "confirmed"
            assert db.execute("SELECT state FROM harness_unit_sessions").fetchone()["state"] == "notCreated"
        with pytest.raises(UnitRecordsRefused):
            runtime.start({"unitRef": unit.public_ref}, context)
        assert len(effects.handles) == 1
    finally:
        store.close()


@pytest.mark.parametrize("mode", ["lost-open", "lost-init", "ack", "revoke-after-open"])
def test_unknown_or_revocation_retains_original_handle_and_never_restarts(tmp_path, monkeypatch, mode):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch, mode=mode)
    try:
        context = issued("start")
        result = runtime.start({"unitRef": unit.public_ref}, context)
        assert result["state"] == "unknown" and "evidenceRef" not in result
        assert len(effects.handles) == 1 and effects.close_calls == effects.kill_calls == 0
        if mode == "revoke-after-open":
            assert effects.initialized == []
        with p[1]._connect() as db:
            assert db.execute("SELECT state FROM harness_unit_confirmations").fetchone()["state"] == "unknown"
            assert db.execute("SELECT state FROM harness_unit_sessions").fetchone()["state"] == "notCreated"
        authority.allowed = True
        with pytest.raises(UnitRecordsRefused):
            runtime.start({"unitRef": unit.public_ref}, context)
        with pytest.raises(Exception, match="existing step claim"):
            issued("start")
        assert len(effects.handles) == 1
    finally:
        store.close()


def test_cold_query_original_proof_without_ticket_effect_port_or_new_handle(tmp_path, monkeypatch):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch, mode="lost-init")
    try:
        assert runtime.start({"unitRef": unit.public_ref}, issued("start"))["state"] == "unknown"
        mark_unknown(store, request)
        cold = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4],
            verifier=p[0].verifier, epoch_port=p[5], native_unit_evidence=p[0].native_unit_evidence)
        cold_projection = Projection(cold, unit, issuer, request)
        cold_observations = Observations(cold)
        cold_runtime = make_provider(cold, cold_projection, observations=cold_observations)
        assert "query_step" in cold_runtime.descriptor.supported_methods and "start" not in cold_runtime.descriptor.supported_methods
        query = issuer.issue_query(request, "flow-digest", "start")
        result = cold_runtime.query_step("start-correlation", query)
        assert result["state"] == "confirmed" and issuer.verified_observation(query)
        assert cold._tickets == {} and len(effects.handles) == 1
        assert store.read_operation_step(request, "start").outcome == "unknown"  # core separately consumes owner observation.
        assert effects.close_calls == effects.kill_calls == 0
    finally:
        store.close()


def test_absent_original_query_evidence_preserves_unknown(tmp_path, monkeypatch):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch, mode="lost-init")
    try:
        assert runtime.start({"unitRef": unit.public_ref}, issued("start"))["state"] == "unknown"
        mark_unknown(store, request)
        observations.available = False
        result = runtime.query_step("start-correlation", issuer.issue_query(request, "flow-digest", "start"))
        assert result["state"] == "unknown" and len(effects.handles) == 1
        with p[1]._connect() as db:
            assert db.execute("SELECT source_revision FROM harness_unit_confirmations").fetchone()["source_revision"] == 3
    finally:
        store.close()


@pytest.mark.parametrize("damage", ["owner-unavailable", "prepare-context"])
def test_confirmed_unit_query_cannot_use_stale_owner_or_other_step(tmp_path, monkeypatch, damage):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch)
    try:
        assert runtime.start({"unitRef": unit.public_ref}, issued("start"))["state"] == "confirmed"
        step = "start"
        if damage == "owner-unavailable":
            p[0].native_unit_evidence.valid = False
        else:
            step = "prepare"
        query = issuer.issue_query(request, "flow-digest", step)
        with pytest.raises((UnitRecordsRefused, ClaudeUnitCoordinationRefused)):
            runtime.query_step("start-correlation", query)
        assert observations.calls == [] and len(effects.handles) == 1
        assert effects.close_calls == effects.kill_calls == 0
    finally:
        store.close()


@pytest.mark.parametrize("damage", ["source", "boolean-owner", "correlation"])
def test_reference_or_recovery_substitution_refused_without_native_effect(tmp_path, monkeypatch, damage):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch)
    try:
        if damage == "correlation":
            result = runtime.start({"unitRef": unit.public_ref}, issued("start"))
            assert result["state"] == "confirmed"
            query = issuer.issue_query(request, "flow-digest", "start")
            with pytest.raises(ClaudeUnitCoordinationRefused):
                runtime.query_step("different-correlation", query)
            assert observations.calls == [] and len(effects.handles) == 1
        else:
            reference = dict(unit.public_ref)
            if damage == "source": reference["sourceRevision"] = "forged-source"
            else: reference["ownerProviderRef"] = dict(reference["ownerProviderRef"], generation=True)
            with pytest.raises((UnitRecordsRefused, ClaudeUnitCoordinationRefused)):
                runtime.start({"unitRef": reference}, issued("start"))
            assert effects.handles == []
    finally:
        store.close()


@pytest.mark.parametrize("missing", ["effect-cut", "native-owner", "same-verifier", "projection"])
def test_absent_or_other_owner_ports_do_not_advertise_start(tmp_path, monkeypatch, missing):
    runtime, p, unit, store, request, issuer, authority, current, issued, effects, observations = configured(tmp_path, monkeypatch)
    try:
        projection = runtime._unit_coordinator.projection
        if missing == "effect-cut": effects.dispatch_guard = None
        elif missing == "native-owner": p[0].native_unit_evidence = None
        elif missing == "same-verifier": effects.verifier = object()
        elif missing == "projection": projection = None
        candidate = make_provider(p[0], projection, effects, observations)
        assert "start" not in candidate.descriptor.supported_methods
        assert effects.handles == []
    finally:
        store.close()

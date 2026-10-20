"""Original SQLite Submission source checks with explicitly synthetic ACP facts."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.method_report_bindings import SQLiteMethodUnitReportBindings
from ordessa_engineering.adapters.persistence.sqlite.submission_source import SQLiteSubmissionSource
from ordessa_engineering.application.assembly import build_method_run_bindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.report_source import MethodUnitReportSource
from ordessa_engineering.domain.common.models.values import Digest
from submission_wait_business_fixture import build_submission_wait_fixture
from submission_wait_native_fixture import persist_historical_dispatch


def _query_digest(unit_ref, operation_ref, prompt_digest):
    payload = canonical_bytes({
        "action": "query-acp-turn",
        "unitRef": dict(unit_ref),
        "operationRef": operation_ref,
        "expectedPromptInputDigest": prompt_digest,
    })
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _receipt_digest(value):
    return "sha256:" + hashlib.sha256(canonical_bytes({"value": value})).hexdigest()


class _SyntheticRecords:
    """Public query-shaped test peer; it is not an Execution authority."""

    acp_turn_available = True

    def __init__(self, receipt):
        self.receipt = receipt
        self.journal = SimpleNamespace(acp_turn_opt_in=True)
        self.calls = []

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest):
        return _query_digest(unit_ref, operation_ref, expected_prompt_input_digest)

    def query_acp_turn(self, unit_ref, operation_ref, invocation, *, input_digest,
                       expected_prompt_input_digest):
        self.calls.append((dict(unit_ref), operation_ref, input_digest,
                           expected_prompt_input_digest))
        assert invocation.facts["inputDigest"] == input_digest
        assert input_digest == self.acp_turn_query_digest(
            unit_ref, operation_ref, expected_prompt_input_digest)
        return self.receipt


def _fixture(tmp_path):
    e = build_submission_wait_fixture(tmp_path, report_phase=True)
    factory, controls, blobs = e["factory"], e["controls"], e["blobs"]
    old = e["submission"]
    operation_ref = "synthetic-source81-operation"
    execution = old.execution_ref
    unit_ref = {
        "environmentNamespace": execution.environment_namespace,
        "unitId": execution.unit_id,
        "ownerProviderRef": json.loads(execution.owner_provider_ref_bytes),
        "sourceRevision": execution.source_revision,
    }
    params = {"sessionId": "synthetic-session", "prompt": "fixture-only prompt"}
    input_value = {"unitRef": unit_ref, "params": params}
    prompt_digest = _receipt_digest(input_value)
    execution = replace(execution, prompt_input_digest=Digest("sha256", prompt_digest.removeprefix("sha256:")))
    query_digest = _query_digest(unit_ref, operation_ref, prompt_digest)
    report_value = {"statement": "Exact method report content from synthetic receipt."}
    report_text = canonical_bytes(report_value).decode("utf-8")
    notification = {"jsonrpc": "2.0", "method": "session/update",
                    "params": {"sessionId": "synthetic-session", "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": report_text}}}}
    response = {"jsonrpc": "2.0", "id": "source81-turn",
                "result": {"stopReason": "end_turn"}}
    events = [
        {"sequence": 1, "sessionMatched": True, "raw": notification},
        {"sequence": 2, "sessionMatched": False, "raw": response},
    ]
    frame = (json.dumps({"jsonrpc": "2.0", "id": "source81-turn",
                         "method": "session/prompt", "params": params},
                        ensure_ascii=False, separators=(",", ":")) + "\n")
    input_digest = prompt_digest
    receipt = {
        "contractVersion": "unit-acp-turn/1",
        "operationRef": operation_ref,
        "unitRef": unit_ref,
        "inputDigest": input_digest,
        "state": "completed",
        "revision": 4,
        "nativeBinding": {"sessionId": "synthetic-session"},
        "unitIntentDigest": "0" * 64,
        "input": input_value,
        "request": {"raw": {"jsonrpc": "2.0", "id": "source81-turn",
                             "method": "session/prompt", "params": params},
                    "frameUtf8": frame,
                    "frameDigest": "sha256:" + hashlib.sha256(frame.encode()).hexdigest()},
        "events": events,
        "eventsDigest": _receipt_digest(events),
        "response": response,
        "responseDigest": _receipt_digest(response),
        "observationAssociation": "session-request-window",
        "summary": {"text": report_text, "textDigest": _receipt_digest(report_text),
                    "stopReason": "end_turn", "eventCount": 2,
                    "knownRemoteFailure": False, "successfulRpcResponse": True,
                    "modelQualityVerified": False},
    }
    receipt_bytes = canonical_bytes(receipt)
    capture_ref = blobs.put_verified(
        receipt_bytes,
        Digest("sha256", hashlib.sha256(receipt_bytes).hexdigest()),
        "application/json",
    )
    execution = replace(execution, operation_ref=operation_ref,
                        captured_observation_ref=capture_ref)
    report_spec = next(d for d in e["snapshot"].program.document_definitions
                       if d.document_type == "test-document")
    resource = next(r for r in e["snapshot"].resources
                    if r.resource_id == report_spec.schema_resource.resource_id)
    from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
    exact = ExactMethodResourceRef(
        e["method_ref"], resource.logical_path,
        Digest("sha256", resource.digest), resource.resource_id,
    )
    from ordessa_engineering.domain.artifacts.models import MethodContent
    report_content = MethodContent.from_value(exact, report_value)
    submission = replace(
        old,
        submission_id="submission-source81",
        execution_ref=execution,
        method_content=report_content,
        resulting_snapshots=(),
        commit_refs=(),
        file_changes=(),
        test_evidence=(),
        effect_observations=(),
        coverage=tuple(replace(item, file_change_ids=(), evidence_refs=())
                       for item in old.coverage),
    )
    with factory.begin(submission.scope) as uow:
        uow.submissions.create(submission)
        uow.commit()

    native = persist_historical_dispatch(
        {"factory": factory, "run_id": "submission-source81-run",
         "created_at": e["now"], "registry": {"registry_id": "source81-fixture",
             "revision": 1, "registry_digest": "sha256:" + "0" * 64,
             "operations": {}}},
        snapshot=e["snapshot"], package=e["package"], grant=e["grant"],
        submission_execution_ref=execution, unit_ref=unit_ref,
        prompt_ref=capture_ref, prompt_digest=execution.prompt_input_digest,
        query_digest=query_digest,
    )
    records = _SyntheticRecords(receipt)

    def query_factory(binding):
        return SimpleNamespace(facts={"inputDigest": binding.expected_query_digest})

    source = SQLitePersistedMethodWorkSource(
        factory, controls, blobs=blobs, review_bindings=e["bindings"],
        execution_records=records, execution_query_factory=query_factory,
    )
    method_runs = build_method_run_bindings(
        factory, method_control=controls, work_condition_source=source,
        registry_loader=lambda: {"registry_id": "source81-fixture", "revision": 1,
            "registry_digest": "sha256:" + "0" * 64, "operations": {}},
    )
    report_bindings = SQLiteMethodUnitReportBindings(
        factory, controls, phase_key="record_report")
    report_source = MethodUnitReportSource(factory, controls, blobs, report_bindings)
    adapter = SQLiteSubmissionSource(
        factory, method_runs=method_runs, report_source=report_source,
        execution_records=records, blobs=blobs, execution_query_factory=query_factory,
    )
    return {**e, "submission": submission, "execution": execution,
            "unit_ref": unit_ref,
            "native": native, "records": records, "adapter": adapter}


def test_original_submission_source_binds_full_methodrun_and_exact_captured_report(tmp_path):
    e = _fixture(tmp_path)
    try:
        with e["adapter"].guard_submission(e["context"], e["submission"], e["package"]):
            assert e["records"].calls == [(
                e["unit_ref"],
                e["submission"].execution_ref.operation_ref,
                e["native"]["binding"].expected_query_digest,
                "sha256:" + e["submission"].execution_ref.prompt_input_digest.hex,
            )]
    finally:
        e["library"].close()


def test_submission_source_rejects_unpersisted_or_different_package(tmp_path):
    e = _fixture(tmp_path)
    try:
        altered = replace(e["submission"], submission_id="not-persisted")
        with pytest.raises(ApplicationError, match="NOT_FOUND"):
            with e["adapter"].guard_submission(e["context"], altered, e["package"]):
                pass
        with pytest.raises(ApplicationError, match="SUBMISSION_SOURCE_BINDING_MISMATCH"):
            with e["adapter"].guard_submission(e["context"], e["submission"], e["original_package"]):
                pass
    finally:
        e["library"].close()


def test_submission_source_rejects_unknown_native_receipt_without_reclassifying_it(tmp_path):
    e = _fixture(tmp_path)
    try:
        e["records"].receipt = {**e["records"].receipt, "state": "unknown", "revision": 2}
        with pytest.raises(ApplicationError, match="SUBMISSION_SOURCE_EXECUTION_BINDING_MISMATCH"):
            with e["adapter"].guard_submission(e["context"], e["submission"], e["package"]):
                pass
        assert e["records"].receipt["state"] == "unknown"
    finally:
        e["library"].close()

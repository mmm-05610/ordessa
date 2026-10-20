"""Schema-17 declared-Work report consumption with controlled native records.

The Work/package/Grant, dispatch row, command journal, Submission and blobs use
the fixture's real temporary Engineering SQLite authority. The ACP Records peer
is explicitly synthetic: it returns a fixed, correctly bound unit-acp-turn/1
receipt and does not start a Unit, model, service, or external process.
"""
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.submission import ExecutionRecordRef, Submission, SubmissionCoverage
from ordessa_engineering.domain.changes.submission_codec import submission_projection
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.approvals.scope import EnvironmentRef

from test_work_package_dispatch_v2 import call, row
from test_real_source_chain import NOW, SCOPE, context


def _digest(raw):
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


class _ControlledRecords:
    """A controlled public query-shaped peer, never a UnitRecords authority."""

    def __init__(self):
        self.receipt = None
        self.calls = []

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest):
        digest = Digest("sha256", expected_prompt_input_digest.removeprefix("sha256:"))
        payload = canonical_bytes([dict(unit_ref), operation_ref, asdict(digest)])
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def query_acp_turn(self, unit_ref, operation_ref, invocation, *, input_digest,
                       expected_prompt_input_digest):
        self.calls.append((dict(unit_ref), operation_ref, input_digest,
                           expected_prompt_input_digest))
        assert invocation.facts["inputDigest"] == input_digest
        return self.receipt


def _profile(environment_ref):
    # manifestRevision is a report assertion: the bound EnvironmentRef carries
    # the profile digest but does not attest this revision number.
    return {
        "environmentNamespace": environment_ref.environment_id,
        "profileId": environment_ref.profile_id,
        "manifestRevision": 1,
        "contentDigest": "sha256:" + environment_ref.profile_digest.hex,
    }


def _report_value(package, environment_ref, *, change_profile=False, change_package=False):
    value = {
        "package_digest": "sha256:" + package.ref.digest.hex,
        "profile_ref": _profile(environment_ref),
        "changed_paths": ["src/x.py"],
        "verification": [{"check": "controlled", "result": "not_run"}],
        "status": "completed",
    }
    if change_profile:
        value["profile_ref"] = {**value["profile_ref"], "profileId": "substituted-profile"}
    if change_package:
        value["package_digest"] = "sha256:" + "0" * 64
    return value


def _install_controlled_capture(fixture, *, state="completed", successful=True,
                               omit_text=False, report_value=None, native_case=None):
    transport = fixture["transport"]
    records = _ControlledRecords()
    transport.records = records
    owner = fixture["service"]._execution_dispatch
    owner.records = records
    fixture["service"]._execution_records = records

    captured = {}

    query_factory_calls = []
    fixture["query_factory_calls"] = query_factory_calls

    def query_factory(binding):
        query_factory_calls.append(binding)
        return SimpleNamespace(facts={"inputDigest": binding.expected_query_digest})

    def capture(binding):
        unit_ref = json.loads(binding.unit_ref_bytes)
        prompt_digest = "sha256:" + binding.prompt_input_digest.hex
        params = json.loads(fixture["env"].blobs.read_verified(binding.prompt_ref))
        native_input = {"unitRef": unit_ref, "params": params}
        request_id = "controlled-native-request"
        request_raw = {"jsonrpc": "2.0", "id": request_id,
                       "method": "session/prompt", "params": params}
        frame = (json.dumps(request_raw, ensure_ascii=False, separators=(",", ":")) + "\n")
        request = {"raw": request_raw, "frameUtf8": frame,
                   "frameDigest": "sha256:" + hashlib.sha256(frame.encode()).hexdigest()}
        response = {"jsonrpc": "2.0", "id": request_id,
                    "result": {"stopReason": "end_turn"}}
        report_text = canonical_bytes(report_value).decode("utf-8")
        notification = {"jsonrpc": "2.0", "method": "session/update",
                        "params": {"sessionId": params["sessionId"], "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": report_text}}}}
        events = [
            {"sequence": 1, "sessionMatched": True, "raw": notification},
            {"sequence": 2, "sessionMatched": False, "raw": response},
        ]
        summary = {
            "successfulRpcResponse": successful,
            "modelQualityVerified": False,
            "stopReason": "end_turn",
            "eventCount": len(events),
            "knownRemoteFailure": False,
        }
        if not omit_text:
            summary["text"] = report_text
            summary["textDigest"] = "sha256:" + hashlib.sha256(
                canonical_bytes({"value": report_text})).hexdigest()
        receipt = {
            "contractVersion": "unit-acp-turn/1",
            "operationRef": binding.execution_operation_ref,
            "unitRef": unit_ref,
            "inputDigest": prompt_digest,
            "state": state,
            "revision": 1,
            "nativeBinding": {"sessionId": params["sessionId"]},
            "unitIntentDigest": "0" * 64,
            "input": native_input,
            "request": request,
            "events": events,
            "eventsDigest": "sha256:" + hashlib.sha256(
                canonical_bytes({"value": events})).hexdigest(),
            "response": response,
            "responseDigest": "sha256:" + hashlib.sha256(
                canonical_bytes({"value": response})).hexdigest(),
            "observationAssociation": "session-request-window",
            "summary": summary,
        }
        if native_case == "missing_input":
            receipt.pop("input")
        elif native_case == "wrong_input_unit":
            receipt["input"]["unitRef"] = {**unit_ref, "unitId": "substituted-unit"}
        elif native_case == "wrong_input_params":
            receipt["input"]["params"] = {**params, "sessionId": "substituted-session"}
        elif native_case == "wrong_native_session":
            receipt["nativeBinding"]["sessionId"] = "substituted-session"
        elif native_case == "wrong_request":
            receipt["request"]["raw"]["method"] = "session/cancel"
        elif native_case == "missing_response":
            receipt.pop("response")
            receipt["events"] = receipt["events"][:1]
            receipt["eventsDigest"] = "sha256:" + hashlib.sha256(
                canonical_bytes({"value": receipt["events"]})).hexdigest()
            receipt["summary"]["eventCount"] = len(receipt["events"])
        elif native_case == "response_not_recorded":
            receipt["events"] = receipt["events"][:1]
            receipt["eventsDigest"] = "sha256:" + hashlib.sha256(
                canonical_bytes({"value": receipt["events"]})).hexdigest()
            receipt["summary"]["eventCount"] = len(receipt["events"])
        elif native_case == "wrong_event_count":
            receipt["summary"]["eventCount"] = 0
        elif native_case == "model_quality_claimed":
            receipt["summary"]["modelQualityVerified"] = True
        records.receipt = receipt
        raw = canonical_bytes(receipt)
        blob = fixture["env"].blobs.put_verified(raw, _digest(raw), "application/json")
        result = SimpleNamespace(
            operation_ref=binding.execution_operation_ref,
            expected_prompt_digest=prompt_digest,
            query_digest=binding.expected_query_digest,
            state=state,
            blob_ref=blob,
        )
        captured["receipt"] = receipt
        captured["ref"] = blob
        return result

    transport.capture = capture
    fixture["capture"] = captured
    fixture["service"]._execution_query_factory = query_factory
    return records, captured


def _prepare_report(fixture, *, report_value=None, execution_change=None, dispatch_result=None):
    package_ref = fixture["package_ref"]
    with fixture["factory"].begin(SCOPE, "read") as uow:
        package = uow.implementation.resolve_package(package_ref)
        grant = uow.authorization.get_grant(fixture["grant_ref"])
    payload = package.payload
    environment_ref = dict(grant.intent.authorization.scope_by_action)["edit_repository"].environment_refs[0]
    assert type(environment_ref) is EnvironmentRef
    value = _report_value(package, environment_ref) if report_value is None else report_value

    # Dispatch first so the report references the original schema-17 binding
    # and the very same observation blob captured at the dispatch edge.
    result = call(fixture) if dispatch_result is None else dispatch_result
    binding = __import__(
        "ordessa_engineering.domain.changes.dispatch_codec",
        fromlist=["decode_dispatch"],
    ).decode_dispatch(row(fixture)["binding_bytes"])
    assert result.outcome in {"completed", "unknown"}

    records = fixture["service"]._execution_records
    assert records.receipt["operationRef"] == binding.execution_operation_ref
    owner_ref = json.loads(binding.unit_ref_bytes)["ownerProviderRef"]
    unit_ref = json.loads(binding.unit_ref_bytes)
    execution = ExecutionRecordRef(
        unit_ref["environmentNamespace"], unit_ref["unitId"], canonical_bytes(owner_ref),
        unit_ref["sourceRevision"],
        binding.execution_operation_ref, binding.prompt_input_digest,
        fixture["capture"]["ref"],
    )
    if execution_change == "query":
        execution = replace(execution, prompt_input_digest=Digest("sha256", "f" * 64))
    elif execution_change == "capture_ref":
        ref = execution.captured_observation_ref
        execution = replace(execution, captured_observation_ref=BlobRef(
            Digest("sha256", "f" * 64), ref.byte_length, ref.media_type, "substituted-capture"))

    report_raw = canonical_bytes(value)
    report_blob = fixture["env"].blobs.put_verified(report_raw, _digest(report_raw), "application/json")
    schema_context = context("work-report-v2-schema")
    with fixture["env"].controls.guard(schema_context, payload.method_ref):
        exact = fixture["env"].controls.resource_ref(
            schema_context, payload.method_ref, "implementation-report-schema")
    method_content = MethodContent.from_value(exact, value, rendered_body_ref=report_blob)
    coverage = SubmissionCoverage(payload.change_ref, (report_blob,), (), (), "implemented")
    record = Submission(
        scope=package.scope,
        submission_id="work-report-v2",
        created_at=context("work-report-v2").received_at,
        created_by=context("work-report-v2").authenticated_actor,
        change_set=ChangeSet((payload.change_ref,)),
        authorization_refs=(binding.approval_ref,),
        package_ref=package.ref,
        execution_ref=execution,
        baseline_snapshots=(),
        resulting_snapshots=(),
        commit_refs=(),
        file_changes=(),
        output_refs=(report_blob,),
        test_evidence=(),
        effect_observations=(),
        coverage=(coverage,),
        source_refs=(payload.baseline, payload.candidate),
        method_content=method_content,
        schema_version=2,
    )
    from ordessa_engineering.application.assembly import build_declared_unit_report_source
    report_source = build_declared_unit_report_source(
        fixture["factory"], method_control=fixture["env"].controls,
        blobs=fixture["env"].blobs)
    fixture["service"]._submission_reports.report_source = report_source
    return record, report_blob, fixture["capture"]["ref"]


def _grant_ref(fixture):
    from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
    return decode_approval_ref(fixture["grant_result"].result["approval_ref"])


def test_schema17_work_report_is_consumed_once_and_exact_replay_does_not_query_records(
        tmp_path, monkeypatch):
    from test_work_package_dispatch_v2 import dispatch_fixture as build_dispatch_fixture

    with build_dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture["grant_ref"] = _grant_ref(fixture)
        with fixture["factory"].begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(fixture["package_ref"])
        environment_ref = dict(fixture["authorization"].scope_by_action)["edit_repository"].environment_refs[0]
        value = _report_value(package, environment_ref)
        records, captured = _install_controlled_capture(fixture, report_value=value)
        record, report_blob, _capture_ref = _prepare_report(fixture, report_value=value)
        ctx = context("work-report-v2-record")

        first = asyncio.run(fixture["service"].execute(
            "engineering.submissions.record_report",
            {"record": submission_projection(record)}, ctx))
        assert first.status == "completed"
        assert first.result["workflow_state"] == "submitted"
        assert first.result["review_status"] == "pending_review"
        assert first.result["accepted"] is False
        assert records.calls and records.calls[0][1] == record.execution_ref.operation_ref
        assert captured["ref"] == record.execution_ref.captured_observation_ref
        assert len(fixture["query_factory_calls"]) == 1
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_submissions").fetchone() == (1,)

        with fixture["factory"].begin(SCOPE, "read") as uow:
            stored = uow.submissions.resolve(record.ref)
        from ordessa_engineering.domain.changes.submission_codec import decode_submission, encode_submission
        assert decode_submission(encode_submission(stored)) == record
        assert stored.schema_version == 2
        assert stored.baseline_snapshots == stored.resulting_snapshots == ()
        assert stored.file_changes == stored.commit_refs == stored.test_evidence == ()
        assert stored.effect_observations == ()
        assert stored.output_refs == (report_blob,)

        # This new report contract has no v2 acceptance owner yet. It must not
        # enter the legacy snapshot/MethodRun acceptance graph.
        from ordessa_engineering.application.usecases.changes.acceptance_closure import resolve_submission_acceptance
        with fixture["factory"].begin(SCOPE, "read") as uow:
            with pytest.raises(ApplicationError, match="SUBMISSION_DECLARED_ACCEPTANCE_UNAVAILABLE"):
                resolve_submission_acceptance(uow, stored.ref)

        replay = asyncio.run(fixture["service"].execute(
            "engineering.submissions.record_report",
            {"record": submission_projection(record)}, ctx))
        assert replay.result_bytes == first.result_bytes
        assert len(records.calls) == 1
        assert len(fixture["query_factory_calls"]) == 1
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_submissions").fetchone() == (1,)

        altered = replace(record, submission_id="work-report-v2-changed")
        with pytest.raises(ApplicationError):
            asyncio.run(fixture["service"].execute(
                "engineering.submissions.record_report",
                {"record": submission_projection(altered)}, ctx))
        assert len(records.calls) == 1
        assert report_blob == record.method_content.rendered_body_ref


@pytest.mark.parametrize("case", ["body", "package", "profile", "query", "capture_ref", "source_ref"])
def test_schema17_report_binding_substitution_refuses_without_submission(
        tmp_path, monkeypatch, case):
    from test_work_package_dispatch_v2 import dispatch_fixture as build_dispatch_fixture

    with build_dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture["grant_ref"] = _grant_ref(fixture)
        with fixture["factory"].begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(fixture["package_ref"])
        environment_ref = dict(fixture["authorization"].scope_by_action)["edit_repository"].environment_refs[0]
        canonical_value = _report_value(package, environment_ref)
        changed_value = canonical_value
        execution_change = None
        if case == "body":
            changed_value = {**canonical_value, "changed_paths": ["src/other.py"]}
        elif case == "package":
            changed_value = _report_value(package, environment_ref, change_package=True)
        elif case == "profile":
            changed_value = _report_value(package, environment_ref, change_profile=True)
        elif case == "query":
            execution_change = "query"
        elif case == "capture_ref":
            execution_change = "capture_ref"
        records, _captured = _install_controlled_capture(
            fixture, report_value=canonical_value if case == "body" else changed_value)
        record, _report_blob, _capture_ref = _prepare_report(
            fixture, report_value=changed_value, execution_change=execution_change)
        if case == "source_ref":
            foreign_candidate = replace(record.source_refs[1], source_id="substituted-candidate")
            record = replace(record, source_refs=(record.source_refs[0], foreign_candidate))

        with pytest.raises(ApplicationError):
            asyncio.run(fixture["service"].execute(
                "engineering.submissions.record_report",
                {"record": submission_projection(record)}, context("work-report-v2-invalid")))
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_submissions").fetchone() == (0,)


@pytest.mark.parametrize("receipt_case", ["unknown", "unsuccessful", "missing_text",
                                          "missing_input", "wrong_input_unit",
                                          "wrong_input_params", "wrong_native_session",
                                          "wrong_request", "missing_response",
                                          "response_not_recorded", "wrong_event_count",
                                          "model_quality_claimed"])
def test_noncompleted_or_incomplete_native_report_receipt_is_not_persisted(
        tmp_path, monkeypatch, receipt_case):
    from test_work_package_dispatch_v2 import dispatch_fixture as build_dispatch_fixture

    with build_dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture["grant_ref"] = _grant_ref(fixture)
        with fixture["factory"].begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(fixture["package_ref"])
        environment_ref = dict(fixture["authorization"].scope_by_action)["edit_repository"].environment_refs[0]
        value = _report_value(package, environment_ref)
        records, _captured = _install_controlled_capture(
            fixture, state="unknown" if receipt_case == "unknown" else "completed",
            successful=receipt_case != "unsuccessful",
            omit_text=receipt_case == "missing_text", report_value=value,
            native_case=None if receipt_case in {"unknown", "unsuccessful", "missing_text"}
            else receipt_case)
        if receipt_case == "unknown":
            result = call(fixture)
            assert result.outcome == "unknown"
            record, _report_blob, _capture_ref = _prepare_report(
                fixture, report_value=value, dispatch_result=result)
            with pytest.raises(ApplicationError):
                asyncio.run(fixture["service"].execute(
                    "engineering.submissions.record_report",
                    {"record": submission_projection(record)}, context("work-report-v2-unknown")))
            # An unknown dispatch row is refused before the report source asks
            # the query factory or Records for a receipt; it is never retried.
            assert records.calls == []
            assert fixture["query_factory_calls"] == []
            assert fixture["env"].library._connection.execute(
                "SELECT COUNT(*) FROM eng_submissions").fetchone() == (0,)
            return
        record, _report_blob, _capture_ref = _prepare_report(fixture, report_value=value)

        with pytest.raises(ApplicationError):
            asyncio.run(fixture["service"].execute(
                "engineering.submissions.record_report",
                {"record": submission_projection(record)}, context("work-report-v2-bad-receipt")))
        assert records.calls
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_submissions").fetchone() == (0,)


def test_schema1_submission_and_report_input_schema_keep_pre_v2_golden_bytes():
    """Golden values were computed from the pre-B2 schema1 codec snapshot."""
    import runpy

    domain_fixture = Path(__file__).resolve().parents[1] / "domain" / "test_submission.py"
    legacy_record = runpy.run_path(str(domain_fixture))["record"]()
    from ordessa_engineering.domain.changes.submission_codec import encode_submission
    assert hashlib.sha256(encode_submission(legacy_record)).hexdigest() == (
        "1e638562677d94e8cc71dae9ec3c07a3539bfa0bd198814f2bdadaf622316d4b")

    from ordessa_engineering.application.contracts.submissions import report_input_schema
    assert hashlib.sha256(canonical_bytes(report_input_schema(1))).hexdigest() == (
        "9c96656411a6674c5db2b80f82fb80699eb1dba6931e526de0428de4a7bafd92")


def test_revoked_work_grant_blocks_report_commit_after_completed_dispatch(tmp_path, monkeypatch):
    from test_work_package_dispatch_v2 import dispatch_fixture as build_dispatch_fixture

    with build_dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture["grant_ref"] = _grant_ref(fixture)
        with fixture["factory"].begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(fixture["package_ref"])
        environment_ref = dict(fixture["authorization"].scope_by_action)["edit_repository"].environment_refs[0]
        value = _report_value(package, environment_ref)
        records, _captured = _install_controlled_capture(fixture, report_value=value)
        record, _report_blob, _capture_ref = _prepare_report(fixture, report_value=value)
        assert row(fixture)["dispatch_phase"] == "completed"
        before_binding = row(fixture)["binding_bytes"]
        sends, freezes = fixture["transport"].sends, fixture["transport"].freezes

        # Revoke through the original authorization owner after native dispatch
        # completed, then prove the commit-time Grant recheck blocks report write.
        with fixture["factory"].begin(SCOPE) as uow:
            uow.authorization.revoke(record.authorization_refs[0], 0, NOW,
                                     "controlled post-dispatch revoke", "report-revoke")
            uow.commit()
        with pytest.raises(ApplicationError):
            asyncio.run(fixture["service"].execute(
                "engineering.submissions.record_report",
                {"record": submission_projection(record)}, context("work-report-v2-revoked")))

        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_submissions").fetchone() == (0,)
        journal = fixture["env"].library._connection.execute(
            "SELECT state FROM eng_commands WHERE request_id=?", ("work-report-v2-revoked",)
        ).fetchone()
        assert journal is None or journal[0] != "completed"
        assert row(fixture)["binding_bytes"] == before_binding
        assert fixture["transport"].sends == sends
        assert fixture["transport"].freezes == freezes
        assert len(records.calls) <= 1
        with fixture["factory"].begin(SCOPE, "read") as uow:
            budget = uow.authorization.action_budget(record.authorization_refs[0])
        assert all(action["consumed"] == 1 for action in budget["actions"])

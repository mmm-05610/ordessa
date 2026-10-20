"""SQLite method report/acceptance bindings against a compiled test method.

The fixture has a real frozen workflow and original Submission/package/dispatch
rows. Native Unit/dispatch activity is deliberately synthetic and documented by
the fixture; these tests do not claim a production UnitRecords provider.
"""
from dataclasses import replace

import pytest

from ordessa_engineering.adapters.persistence.sqlite.method_report_bindings import (
    SQLiteMethodUnitReportBindings,
)
from ordessa_engineering.adapters.persistence.sqlite.review_bindings import (
    ConfiguredReviewPhase,
    SQLiteReviewBindings,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.assembly import (
    build_method_unit_report_source,
    build_submission_acceptance_admission,
)
from ordessa_engineering.domain.approvals.consent import AuthorizationIntent
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import CheckKey, ReviewRequirement
from ordessa_engineering.domain.reviews.targets import Target, TargetSet

from submission_wait_business_fixture import build_submission_wait_fixture


def _report_fixture(tmp_path, *, native_dispatch_phase='completed'):
    return build_submission_wait_fixture(tmp_path, report_phase=True,
        native_dispatch_phase=native_dispatch_phase)


def _authorization_intent(e, *, method_ref=None, targets=None, requirements=None,
                          actions=("accept_artifact",)):
    method_ref = e["method_ref"] if method_ref is None else method_ref
    targets = tuple(e["submission"].output_refs) if targets is None else tuple(targets)
    requirements = e["closure"].requirements if requirements is None else tuple(requirements)
    return AuthorizationIntent(
        e["scope"], "source80-acceptance-intent", targets, method_ref,
        e["notice"].ref, e["intent"].policy_ref, requirements,
        "reference", "Fixture acceptance subject selection.",
        e["now"], e["intent"].expires_at, actions=actions,
    )


def test_report_binding_resolves_exact_compiled_phase_and_native_rows(tmp_path):
    e = _report_fixture(tmp_path)
    try:
        report_bindings = SQLiteMethodUnitReportBindings(
            e["factory"], e["controls"], phase_key="record_report")
        with report_bindings.guard_report_binding(
                e["context"], e["snapshot"], e["package"], e["submission"]) as binding:
            assert binding.document_type == "test-document"
            assert binding.execution_ref == e["submission"].execution_ref
            assert binding.output_refs == e["submission"].output_refs

        acceptance = build_submission_acceptance_admission(
            e["factory"], method_control=e["controls"], bindings=e["bindings"])
        report_source = build_method_unit_report_source(e["factory"],
            method_control=e["controls"], blobs=e["blobs"], bindings=report_bindings)
        assert report_source.factory is e["factory"]
        assert report_source.methods is e["controls"]
        assert report_source.blobs is e["blobs"]
        assert report_source.bindings is report_bindings
        assert acceptance.factory is e["factory"]
        assert acceptance.methods is e["controls"]
        assert acceptance.bindings is e["bindings"]
        intent = _authorization_intent(e, actions=("accept_artifact",))
        with acceptance.guard_intent(e["context"], intent) as closure:
            assert closure.submission.ref == e["submission"].ref
            assert {revision.ref for revision in closure.artifact_revisions} == set(intent.targets)

        changed_requirement = replace(e["closure"].requirements[0], requirement_id="changed-requirement")
        altered = _authorization_intent(e, actions=("accept_artifact",),
            requirements=(changed_requirement,))
        with pytest.raises(ApplicationError) as altered_error:
            with acceptance.guard_intent(e["context"], altered):
                pass
        assert altered_error.value.code == "CONSENT_BINDING_MISMATCH"

        assert e["native"]["synthetic_native_facts"] is True
    finally:
        e["library"].close()


def test_report_binding_refuses_wrong_method_phase_schema_output_and_noncompleted_dispatch(tmp_path):
    e = _report_fixture(tmp_path)
    try:
        good = SQLiteMethodUnitReportBindings(e["factory"], e["controls"], phase_key="record_report")
        wrong_phase = SQLiteMethodUnitReportBindings(e["factory"], e["controls"], phase_key="acceptance_review")
        with pytest.raises(ApplicationError) as phase_error:
            with wrong_phase.guard_report_binding(e["context"], e["snapshot"], e["package"], e["submission"]):
                pass
        assert phase_error.value.code == "SUBMISSION_REPORT_METHOD_MISMATCH"

        foreign_method = MethodRef(e["method_ref"].method_id, "9.9.9",
            e["method_ref"].schema_version, e["method_ref"].snapshot_digest)
        foreign_payload = replace(e["package"].payload, method_ref=foreign_method)
        foreign_package = replace(e["package"], payload=foreign_payload)
        with pytest.raises(ApplicationError) as method_error:
            with good.guard_report_binding(e["context"], e["snapshot"], foreign_package, e["submission"]):
                pass
        assert method_error.value.code == "SUBMISSION_REPORT_BINDING_MISMATCH"

        wrong_schema = next(d for d in e["snapshot"].program.document_definitions
                            if d.document_type == "test-work-inputs")
        resource = next(r for r in e["snapshot"].resources
                        if r.resource_id == wrong_schema.schema_resource.resource_id)
        exact = ExactMethodResourceRef(e["method_ref"], resource.logical_path,
            Digest("sha256", resource.digest), resource.resource_id)
        wrong_content = type(e["submission"].method_content).from_value(exact, {
            "document_type": "test-work-inputs", "schema_version": 1,
            "run_id": "work-source-run", "proposal_ref": {}, "events": {},
        })
        wrong_schema_submission = replace(e["submission"], method_content=wrong_content)
        with pytest.raises(ApplicationError) as schema_error:
            with good.guard_report_binding(e["context"], e["snapshot"], e["package"], wrong_schema_submission):
                pass
        assert schema_error.value.code == "SUBMISSION_REPORT_SCHEMA_MISMATCH"

        blob = e["submission"].execution_ref.captured_observation_ref
        coverage = tuple(replace(c, output_refs=(blob,)) for c in e["submission"].coverage)
        nonmethod_output_submission = replace(e["submission"], output_refs=(blob,), coverage=coverage)
        with pytest.raises(ApplicationError) as output_error:
            with good.guard_report_binding(e["context"], e["snapshot"], e["package"], nonmethod_output_submission):
                pass
        assert output_error.value.code == "SUBMISSION_REPORT_BINDING_MISMATCH"

    finally:
        e["library"].close()


def test_report_binding_refuses_normally_recorded_unknown_dispatch(tmp_path):
    e = _report_fixture(tmp_path, native_dispatch_phase='unknown')
    try:
        assert e['native']['dispatch_phase'] == 'unknown'
        binding = SQLiteMethodUnitReportBindings(
            e['factory'], e['controls'], phase_key='record_report')
        with pytest.raises(ApplicationError) as dispatch_error:
            with binding.guard_report_binding(e['context'], e['snapshot'], e['package'], e['submission']):
                pass
        assert dispatch_error.value.code == 'SUBMISSION_REPORT_BINDING_MISMATCH'
    finally:
        e['library'].close()


def test_acceptance_submission_selection_uses_exact_method_outputs_and_phase(tmp_path):
    e = _report_fixture(tmp_path)
    try:
        bindings = e["bindings"]
        intent = _authorization_intent(e)
        assert bindings.resolve_acceptance_submission(e["context"], intent) == e["submission"].ref

        foreign_method = MethodRef(e["method_ref"].method_id, "9.9.9",
            e["method_ref"].schema_version, e["method_ref"].snapshot_digest)
        wrong_method_requirements = tuple(replace(req, method_ref=foreign_method)
                                          for req in e["closure"].requirements)
        wrong_method_intent = _authorization_intent(e, method_ref=foreign_method,
            requirements=wrong_method_requirements)
        with pytest.raises(ApplicationError) as method_error:
            bindings.resolve_acceptance_submission(e["context"], wrong_method_intent)
        # The supplied release 9.9.9 cannot resolve to a published snapshot;
        # the original method guard rejects it before subject selection.
        assert method_error.value.code == "METHOD_STATE_CORRUPT"

        other = e["other_output"].ref
        original = e["closure"].requirements[0]
        target = Target("output", other)
        key = CheckKey(target, original.required_check_keys[0].criterion_id,
                       original.required_check_keys[0].claim_id)
        wrong_target_requirement = ReviewRequirement(
            original.scope, "wrong-output-requirement", original.requirement_version,
            original.purpose, TargetSet((target,)), original.method_ref,
            original.criterion_set_ref, (key,), original.eligible_reviewer_roles,
            original.phase_key,
        )
        wrong_target_intent = _authorization_intent(e, targets=(other,),
            requirements=(wrong_target_requirement,))
        with pytest.raises(ApplicationError) as target_error:
            bindings.resolve_acceptance_submission(e["context"], wrong_target_intent)
        assert target_error.value.code == "METHOD_SUBJECT_BINDING_MISMATCH"

        wrong_phase_bindings = SQLiteReviewBindings(e["factory"], e["controls"],
            scope=e["scope"], proposal_ref=e["proposal"].ref,
            phases=(ConfiguredReviewPhase("acceptance_review", ("reviewer",),
                workflow_node_id="acceptance_review", submission_ref=e["submission"].ref,
                review_purpose="quality"),))
        with pytest.raises(ApplicationError) as phase_error:
            wrong_phase_bindings.resolve_acceptance_submission(e["context"], intent)
        assert phase_error.value.code == "METHOD_TARGET_BINDINGS_UNAVAILABLE"
    finally:
        e["library"].close()

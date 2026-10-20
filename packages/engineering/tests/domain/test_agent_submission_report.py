"""Synthetic report values and graph facts; no receipt capture or approval issuance."""
from dataclasses import fields, replace
import hashlib
from pathlib import Path
import runpy

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ordessa_engineering.domain.changes.agent_submission_report import AgentSubmissionReport
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.submission import Submission, SubmissionCoverage
from ordessa_engineering.domain.changes.submission_binding import validate_submission_graph
from ordessa_engineering.domain.changes.submission_codec import decode_submission, encode_submission, submission_projection
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.models import ImplementationPackage, PreparedPackagePayload
from ordessa_engineering.domain.reviews.refs import ReviewRef

DOMAIN = Path(__file__).parent


def fixture():
    """Existing pure Work authorization/package owners; all evidence is synthetic."""
    auth = runpy.run_path(str(DOMAIN / 'test_work_package_authorization_v2.py'))
    source = runpy.run_path(str(DOMAIN / 'test_external_record_chain.py'))
    scope, method, now = auth['SCOPE'], auth['METHOD'], auth['CREATED']
    digest = auth['_digest']
    actor = ActorRef('fixture-author', 'service', 'synthetic-report-test')
    proposal = ProposalRef(scope.realm_id, scope.project_id, 'change', 'proposal', digest('proposal'))
    schema = ExactMethodResourceRef(method, 'report.json', digest('report-schema'), 'implementation-report-schema')
    review = ReviewRef(scope.realm_id, scope.project_id, 'source-review', digest('review'))
    payload = PreparedPackagePayload(source['BASELINE'], source['CANDIDATE'], proposal, (review,), method, (schema,), ())
    package = ImplementationPackage(scope, 'agent-report-package', now, actor, payload)
    subject = auth['_subject'](package_ref=package.ref)
    notice = WorkPackageNotice('synthetic-report-notice', subject, 'Synthetic, not human approval.',
                               auth['_source'](), auth['_policy']())
    intent = WorkPackageAuthorizationIntent(subject, notice.ref, auth['_policy']())
    grant = auth['_grant'](intent)
    agent = {'schemaVersion': 'agent-instance/1', 'namespace': 'synthetic-agent',
             'instanceId': 'agent-1', 'bindingDigest': 'sha256:' + 'a' * 64}
    turn = {'schemaVersion': 'agent-turn-ref/1', 'instanceRef': agent, 'turnId': 'turn-1'}
    prompt = digest('prompt')
    query = {'schemaVersion': 'agent-turn-query/1', 'turnRef': turn, 'expectedInputDigest': 'sha256:' + prompt.hex}
    captured = BlobRef(digest('synthetic-capture'), 2, 'application/json', 'synthetic-capture')
    execution = AgentExecutionRecordRef(canonical_bytes(agent), canonical_bytes(turn), 'source-revision',
        'actual-agent-operation', 'engineering-attempt', prompt,
        'sha256:' + hashlib.sha256(canonical_bytes(query)).hexdigest(), captured)
    output = BlobRef(digest('synthetic-report'), 2, 'application/json', 'synthetic-report')
    report = AgentSubmissionReport(scope, 'agent-report', now, actor, ChangeSet((proposal,)),
        (grant.ref,), package.ref, execution, (output,),
        (SubmissionCoverage(proposal, (output,), (), (), 'implemented'),),
        (payload.baseline, payload.candidate), MethodContent.from_value(schema, {'status': 'completed'}, rendered_body_ref=output))
    return report, package, grant


def test_agent_report_roundtrips_exact_turn_operation_attempt_and_blob_locations():
    report, _, _ = fixture()
    raw = encode_submission(report)
    restored = decode_submission(raw)
    assert type(restored) is AgentSubmissionReport
    assert restored == report and encode_submission(restored) == raw
    value = decode_json(raw)
    assert value['schemaVersion'] == 'engineering-agent-submission-report/1'
    assert value['execution_ref']['schemaVersion'] == 'engineering-agent-execution-ref/2'
    assert restored.execution_ref.operation_ref == 'actual-agent-operation'
    assert restored.execution_ref.engineering_attempt_ref == 'engineering-attempt'
    assert restored.execution_ref.captured_observation_ref.storage_object_id == 'synthetic-capture'
    assert {'schema_version', 'baseline_snapshots', 'resulting_snapshots', 'file_changes',
            'commit_refs', 'test_evidence', 'effect_observations'}.isdisjoint(value)
    assert {'unit_id', 'environment_namespace', 'owner_provider_ref_bytes'}.isdisjoint(
        {field.name for field in fields(report.execution_ref)})
    checkpoint = replace(report, checkpoint_ref=report.execution_ref.captured_observation_ref)
    assert decode_submission(encode_submission(checkpoint)) == checkpoint
    assert checkpoint.digest != report.digest


@pytest.mark.parametrize('case', ['unit_identity', 'unknown_tag', 'missing_tag', 'numeric_version',
    'old_host_fact', 'nested_tag', 'turn_substitution', 'query_substitution', 'forged_digest', 'unsealed_body'])
def test_agent_codec_refuses_shape_downgrade_and_identity_substitution(case):
    report, _, _ = fixture()
    value = submission_projection(report)
    if case == 'unit_identity':
        value['execution_ref'] = submission_projection(runpy.run_path(str(DOMAIN / 'test_submission.py'))['record']())['execution_ref']
    elif case == 'unknown_tag': value['schemaVersion'] = 'engineering-agent-submission-report/2'
    elif case == 'missing_tag': value.pop('schemaVersion')
    elif case == 'numeric_version': value['schema_version'] = 2
    elif case == 'old_host_fact': value['test_evidence'] = []
    elif case == 'nested_tag': value['execution_ref']['schemaVersion'] = 'engineering-agent-execution-ref/1'
    elif case == 'turn_substitution': value['execution_ref']['turn_ref_bytes']['turnId'] = 'other-turn'
    elif case == 'query_substitution': value['execution_ref']['query_digest'] = 'sha256:' + '0' * 64
    elif case == 'forged_digest': value['digest']['hex'] = '0' * 64
    elif case == 'unsealed_body': value['method_content']['value']['status'] = 'failed'
    with pytest.raises(ReferenceError):
        decode_submission(canonical_bytes(value))


@pytest.mark.parametrize('case', ['no_coverage', 'file_claim', 'foreign_output', 'body_output',
                                 'unit_ref', 'extra_approval', 'foreign_approval', 'duplicate_source'])
def test_agent_report_keeps_original_local_report_and_coverage_invariants(case):
    report, _, _ = fixture()
    changes = {}
    if case == 'no_coverage': changes['coverage'] = ()
    elif case == 'file_claim': changes['coverage'] = (replace(report.coverage[0], file_change_ids=('unreported-file',)),)
    elif case == 'foreign_output': changes['coverage'] = (replace(report.coverage[0], output_refs=(replace(report.output_refs[0], storage_object_id='other', digest=Digest('sha256','b'*64)),)),)
    elif case == 'body_output': changes['method_content'] = replace(report.method_content, rendered_body_ref=None)
    elif case == 'unit_ref': changes['execution_ref'] = runpy.run_path(str(DOMAIN / 'test_submission.py'))['record']().execution_ref
    elif case == 'extra_approval': changes['authorization_refs'] = report.authorization_refs * 2
    elif case == 'foreign_approval': changes['authorization_refs'] = (replace(report.authorization_refs[0], realm_id='other'),)
    elif case == 'duplicate_source': changes['source_refs'] = report.source_refs + (replace(report.source_refs[0], captured_at='2026-10-15T05:00:00.000000Z'),)
    with pytest.raises(ReferenceError): replace(report, **changes)


@pytest.mark.parametrize('case', ['valid', 'sources_reversed', 'source_version', 'source_bytes',
    'source_locator', 'package', 'grant', 'proposal', 'report_method', 'grant_method', 'host_baseline',
    'host_result', 'legacy_intent'])
def test_agent_report_preserves_prepared_package_approval_source_and_method_graph(case):
    report, package, grant = fixture()
    baseline, candidate = report.source_refs
    baselines = resulting = ()
    if case == 'sources_reversed': report = replace(report, source_refs=(candidate, baseline))
    elif case == 'source_version': report = replace(report, source_refs=(baseline, replace(candidate, capture=replace(candidate.capture, upstream_version='other-version'))))
    elif case == 'source_bytes': report = replace(report, source_refs=(baseline, replace(candidate, capture=replace(candidate.capture, content_digest=Digest('sha256','b'*64)))))
    elif case == 'source_locator': report = replace(report, source_refs=(baseline, replace(candidate, locator=replace(candidate.locator, document_id='other:document'))))
    elif case == 'package': report = replace(report, package_ref=replace(report.package_ref, package_id='other'))
    elif case == 'grant': report = replace(report, authorization_refs=(replace(grant.ref, approval_id='other'),))
    elif case == 'proposal':
        proposal = replace(report.change_set.proposal_refs[0], proposal_id='other')
        report = replace(report, change_set=ChangeSet((proposal,)), coverage=(replace(report.coverage[0], proposal_ref=proposal),))
    elif case == 'report_method':
        schema = report.method_content.schema_ref
        content = MethodContent.from_value(replace(schema, method_ref=replace(schema.method_ref, release_version='other-version')),
            report.method_content.value, rendered_body_ref=report.output_refs[0])
        report = replace(report, method_content=content)
    elif case == 'grant_method':
        intent = grant.intent
        subject = replace(intent.authorization, method_ref=replace(intent.method_ref, release_version='other-version'))
        # These are deliberately forged graph facts, not issued authority.
        object.__setattr__(grant, 'intent', replace(intent, authorization=subject))
    elif case == 'host_baseline': baselines = (object(),)
    elif case == 'host_result': resulting = (object(),)
    elif case == 'legacy_intent':
        old = runpy.run_path(str(DOMAIN / 'test_submission_binding.py'))['fixture']()
        grant = old[2]
    if case == 'valid':
        assert validate_submission_graph(report, package, grant, (), ()) is report
    else:
        with pytest.raises(ReferenceError): validate_submission_graph(report, package, grant, baselines, resulting)


def test_old_submission_cannot_be_relabelled_as_agent_and_schema1_golden_remains():
    old = runpy.run_path(str(DOMAIN / 'test_submission.py'))['record']()
    assert type(decode_submission(encode_submission(old))) is Submission
    assert hashlib.sha256(encode_submission(old)).hexdigest() == '1e638562677d94e8cc71dae9ec3c07a3539bfa0bd198814f2bdadaf622316d4b'
    report, _, _ = fixture()
    with pytest.raises(ReferenceError): replace(old, execution_ref=report.execution_ref)
    value = submission_projection(old)
    value['schemaVersion'] = 'engineering-agent-submission-report/1'
    with pytest.raises(ReferenceError): decode_submission(canonical_bytes(value))

"""Source-bound contracts for the one-shot report-content rework."""
import hashlib

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.report_content_rework import (
    CONTENT_REWORK_CONTRACT, PLAN_CONTRACT, ReportContentReworkSource,
    UNRERUN_NOTE, claim_digest, claim_key, claim_operation_id)
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest


def _plan():
    origin = {
        'parent_key': {'realm_id': 'realm-a', 'principal_id': 'person-a',
                       'request_id': 'parent-request'},
        'parent_operation_id': 'parent-operation',
        'parent_request_digest': {'algorithm': 'sha256', 'hex': '1' * 64},
        'parent_version': 2,
        'review_ref': {'kind': 'review', 'realm_id': 'realm-a', 'project_id': 'project-a',
                       'review_id': 'review-a',
                       'digest': {'algorithm': 'sha256', 'hex': '2' * 64}},
        'submission_ref': {'kind': 'submission', 'realm_id': 'realm-a', 'project_id': 'project-a',
                           'submission_id': 'submission-a',
                           'digest': {'algorithm': 'sha256', 'hex': '3' * 64}},
        'work_id': 'work-a', 'work_revision': 1,
        'work_digest': {'algorithm': 'sha256', 'hex': '4' * 64},
        'action_id': 'action-a', 'step_id': 'step-a',
        'package_ref': {'package_id': 'package-a'},
        'method_ref': {'method_id': 'method-a'},
        'profile_ref': {'environmentNamespace': 'env-a', 'profileId': 'profile-a'},
        'author_unit_ref': {'environmentNamespace': 'env-a', 'unitId': 'author-a'},
        'binding_digest': {'algorithm': 'sha256', 'hex': '5' * 64},
        'dispatch_version': 1, 'execution_operation_ref': 'business-operation-a',
        'source_submission_ref': {'kind': 'submission', 'realm_id': 'realm-a',
                                  'project_id': 'project-a', 'submission_id': 'submission-a',
                                  'digest': {'algorithm': 'sha256', 'hex': '3' * 64}},
        'source_checkpoint_ref': {'digest': {'algorithm': 'sha256', 'hex': '6' * 64},
                                  'byte_length': 1, 'media_type': 'application/json',
                                  'storage_object_id': 'checkpoint-a'},
        'observation_ref': {'digest': {'algorithm': 'sha256', 'hex': '7' * 64},
                            'byte_length': 1, 'media_type': 'application/json',
                            'storage_object_id': 'capture-a'},
        'observation_revision': 3,
    }
    return {'contract': PLAN_CONTRACT, 'origin': origin,
            'materials': {}, 'limits': {'report_only': True, 'max_attempts': 1,
                'edit_repository': 0, 'run_checks': 0}}


def test_claim_identity_is_stable_on_business_operation_and_bound_to_plan_and_approval():
    from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
    plan = _plan()
    plan_ref = BlobRef(Digest('sha256', '8' * 64), 5, 'application/json', 'plan-a')
    approval_ref = BlobRef(Digest('sha256', '9' * 64), 7, 'application/json', 'approval-a')
    expected = record_digest('report-content-rework-claim', {
        'plan_ref': {'digest': {'algorithm': 'sha256', 'hex': '8' * 64},
                     'byte_length': 5, 'media_type': 'application/json',
                     'storage_object_id': 'plan-a'},
        'approval_ref': {'digest': {'algorithm': 'sha256', 'hex': '9' * 64},
                         'byte_length': 7, 'media_type': 'application/json',
                         'storage_object_id': 'approval-a'}})
    operation_hash = hashlib.sha256(b'business-operation-a').hexdigest()
    assert claim_key(plan).request_id == 'report-content-rework-' + operation_hash[:48]
    assert claim_operation_id(plan) == 'report-content-rework-claim/' + operation_hash
    assert claim_digest(plan_ref, approval_ref) == expected
    changed = _plan()
    changed['origin']['execution_operation_ref'] = 'business-operation-b'
    assert claim_key(changed) != claim_key(plan)
    assert claim_operation_id(changed) != claim_operation_id(plan)


def test_report_source_requires_only_not_run_verification_and_both_limitations():
    source = object.__new__(ReportContentReworkSource)
    valid = {'package_digest': 'sha256:' + 'a' * 64,
        'verification': [{'check': 'Historical context: limitation. ' + UNRERUN_NOTE,
                          'result': 'not_run'}]}
    # The source enforces both exact limitation statements even when the report
    # carries additional business-specific text.
    from ordessa_engineering.application.usecases.changes.declared_report import CORRECTION_LIMITATION
    valid['verification'][0]['check'] = CORRECTION_LIMITATION + '; ' + UNRERUN_NOTE
    assert source._check_report(_plan(), __import__(
        'ordessa_infrastructure.encoding', fromlist=['canonical_bytes']).canonical_bytes(valid)) == valid

    bad = {**valid, 'verification': [{'check': CORRECTION_LIMITATION + '; passed',
                                      'result': 'pass'}]}
    with pytest.raises(ApplicationError, match='REPORT_CONTENT_REWORK_REPORT_INVALID'):
        source._check_report(_plan(), __import__(
            'ordessa_infrastructure.encoding', fromlist=['canonical_bytes']).canonical_bytes(bad))


def test_rework_contract_ids_are_explicit():
    assert CONTENT_REWORK_CONTRACT == 'ordessa.declared-report-content-rework/1'
    assert PLAN_CONTRACT == 'ordessa.declared-report-content-rework-plan/1'


def test_direct_report_guard_obeys_selected_approval_revocation_before_any_write():
    from contextlib import contextmanager
    from dataclasses import asdict
    from types import SimpleNamespace
    from ordessa_infrastructure.encoding import canonical_bytes
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.domain.common.models.identity import ActorRef
    context = CommandContext(Scope('realm-a', 'project-a'), 'person-a',
        ActorRef('person-a', 'human', 'local'), 'direct-record',
        '2026-10-18T07:00:00.000000Z', 'trace-a')
    plan = BlobRef(Digest('sha256', '1' * 64), 1, 'application/json', 'plan-a')
    proof = BlobRef(Digest('sha256', '2' * 64), 1, 'application/json', 'proof-a')
    raw = canonical_bytes({'contract': CONTENT_REWORK_CONTRACT, 'plan_ref': asdict(plan),
                          'approval_ref': asdict(proof), 'report': {}})
    checkpoint = BlobRef(Digest('sha256', hashlib.sha256(raw).hexdigest()), len(raw),
                         'application/json', 'checkpoint-a')
    source = object.__new__(ReportContentReworkSource)
    required, entries = [], []
    source.factory = object()
    source.blobs = SimpleNamespace(read_verified=lambda ref: raw if ref == checkpoint else None)
    access = SimpleNamespace(require=lambda actual, operation: required.append((actual, operation)))
    source.ports = SimpleNamespace(access=access)
    class RevokedApproval:
        factory, blobs = source.factory, source.blobs
        @contextmanager
        def guard(self, actual, *, plan_ref):
            assert actual is context and plan_ref == plan
            entries.append('guard-entered')
            raise ApplicationError('CONTROLLED_APPROVAL_REVOKED')
            yield  # pragma: no cover
    approval = RevokedApproval()
    approval.access = access
    source.owner = SimpleNamespace(content_rework_approval=approval)
    with pytest.raises(ApplicationError, match='CONTROLLED_APPROVAL_REVOKED'):
        with source.guard_report(context, object(), SimpleNamespace(checkpoint_ref=checkpoint), object()):
            raise AssertionError('revoked approval cannot yield a report write admission')
    assert entries == ['guard-entered']
    assert required == [(context, 'engineering.submissions.record_report')]

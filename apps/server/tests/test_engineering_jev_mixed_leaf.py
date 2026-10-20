"""rev50 JEV leaf on original SQLite/Decision records; zero real-model calls.

The nominal source fixture uses MockTransport. This tests source correlation and
trust cuts, not production composite authority, human admission, or quality.
"""
from dataclasses import replace
import hashlib
import importlib.util
from pathlib import Path

import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest, CheckSourceAdmission
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import AccessError
from ordessa_server.composition.engineering_reviewer_source import encode_review_run

_spec = importlib.util.spec_from_file_location('mixed_leaf_nominal_fixture',
    Path(__file__).with_name('test_engineering_jev_nominal_source.py'))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def _leaf(work):
    source = work['reviews'].admission.source
    source.method_control = work['reviews'].admission.methods
    raw = encode_review_run(work['run'])
    ref = source.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
    plan, request = work['plan'], work['request']
    frozen = FrozenCheckRequest(plan.plan_digest, request.version, request.fence)
    return source, ref, frozen


def _verify(source, plan, frozen, ref, context):
    with source.method_control.guard_method(context, plan.requirement.method_ref) as snapshot:
        standard = next(s for s in snapshot.program.standard_definitions
            if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id)
        return source.verify_checks(context, plan, frozen, ref,
            standard=standard, check_keys=plan.check_keys)


def test_original_nominal_leaf_guards_historical_record_without_request_state_guess(tmp_path):
    work = _fixture._prepare(tmp_path, 'supported')
    try:
        source, raw_ref, frozen = _leaf(work)
        plan = work['plan']
        with work['admitted']('engineering.reviews.record', 'leaf') as context:
            verified = _verify(source, plan, frozen, raw_ref, context)
            admission = CheckSourceAdmission(plan, frozen, raw_ref, plan.check_keys, verified)
            with source.guard_checks(context, (admission,)):
                assert {answer.status for answer in verified.answers} == {'satisfied'}
            recorded = work['reviews'].record_response(plan.review_id, encode_review_run(work['run']),
                context, expected_request_version=frozen.request_version, fence=frozen.fence)
            assert recorded.status == 'completed'
        with work['admitted']('engineering.reviews.query', 'historical') as context:
            with work['factory'].begin(context.scope, 'read') as uow:
                assert uow.reviews.get_request(plan.review_id).state != 'requested'
            with source.guard_checks(context, (admission,)):
                assert not work['reviews'].gate(plan.requirement, context).satisfied
        assert len(work['calls']) == 2  # fixture only; source verification never calls provider
    finally:
        _fixture._close(work)


@pytest.mark.parametrize('mutation', ('version', 'provenance', 'missing-method', 'missing-key', 'answer'))
def test_nominal_leaf_rejects_changed_binding_or_missing_owner(tmp_path, mutation):
    work = _fixture._prepare(tmp_path, 'contradicted')
    try:
        source, raw_ref, frozen = _leaf(work)
        plan = work['plan']
        with work['admitted']('engineering.reviews.record', 'negative-leaf') as context:
            verified = _verify(source, plan, frozen, raw_ref, context)
            if mutation == 'version':
                with pytest.raises(ApplicationError, match='REVIEW_REQUEST_CHANGED'):
                    _verify(source, plan, replace(frozen, request_version=1), raw_ref, context)
            elif mutation == 'missing-key':
                with source.method_control.guard_method(context, plan.requirement.method_ref) as snapshot:
                    standard = snapshot.program.standard_definitions[0]
                    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_INCOMPLETE'):
                        source.verify_checks(context, plan, frozen, raw_ref, standard=standard,
                            check_keys=plan.check_keys[:1])
            else:
                if mutation == 'provenance':
                    verified = replace(verified, provenance_digest=Digest('sha256', '0'*64))
                    code = 'UNTRUSTED_REVIEWER'
                elif mutation == 'answer':
                    verified = replace(verified, answers=(replace(verified.answers[0], status='satisfied'), *verified.answers[1:]))
                    code = 'UNTRUSTED_REVIEWER'
                else:
                    source.method_control = None
                    code = 'METHOD_AUTHORITY_UNAVAILABLE'
                with pytest.raises(ApplicationError, match=code):
                    with source.guard_checks(context,
                            (CheckSourceAdmission(plan, frozen, raw_ref, plan.check_keys, verified),)):
                        pytest.fail('changed binding was admitted')
        assert len(work['calls']) == 2
    finally:
        _fixture._close(work)


def test_original_source_guard_holds_authority_and_revoked_caller_cannot_reenter(tmp_path):
    work = _fixture._prepare(tmp_path, 'insufficient')
    try:
        source, raw_ref, frozen = _leaf(work)
        plan = work['plan']
        with work['admitted']('engineering.reviews.record', 'guard-cut') as context:
            verified = _verify(source, plan, frozen, raw_ref, context)
            with source.guard_checks(context,
                    (CheckSourceAdmission(plan, frozen, raw_ref, plan.check_keys, verified),)):
                with pytest.raises(AccessError, match='AUTHORIZATION_GUARD_ACTIVE'):
                    source.access.authority.revoke()
        source.access.authority.revoke()
        with pytest.raises(AccessError):
            with work['admitted']('engineering.reviews.record', 'revoked-cut'):
                pytest.fail('revoked caller was admitted')
        assert len(work['calls']) == 2
    finally:
        _fixture._close(work)

"""Synthetic contract tests for the second, bounded Local Library Work."""
from dataclasses import replace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import canonical_bytes

from tooling.checks.server_product import local_library_successor_presentation as subject
from test_local_library_successor_presentation import _summary, _typed_pair


_TARGET_ROOT = '/home/maoqh/projects/ordessa-demo-local-library'
_BASELINE = '342d4e9a590caa50bb0749b48cee80b5a3146439'
_PACKAGE_DIGEST = '201104e51dc0d2db77f9975f160d338761f99643b88f9d8a79a77fef3e11b724'
_WORK_ID = 'local-library-implementation-third-20261017-1310'
_NOT_BEFORE = '2031-04-05T15:00:00.000000Z'  # 23:00 in Beijing
_EXPIRES_AT = '2031-04-05T19:00:00.000000Z'  # 03:00 next day in Beijing
_PRESENTED_AT = '2031-04-05T16:00:00.000000Z'


def _predecessors():
    prior = _summary()['predecessor']
    return [
        {
            **prior,
            'approval_id': '11111111-1111-4111-8111-111111111111',
            'execution_operation_ref': '22222222-2222-4222-8222-222222222222',
            'work_id': 'synthetic-prior-work-one',
            'attempt': 1,
            'unit_id': 'unit-' + '1' * 32,
        },
        {
            **prior,
            'approval_id': '33333333-3333-4333-8333-333333333333',
            'execution_operation_ref': '44444444-4444-4444-8444-444444444444',
            'work_id': 'synthetic-prior-work-two',
            'attempt': 1,
            'unit_id': 'unit-' + '2' * 32,
        },
    ]


def _third_summary():
    value = _summary()
    value.pop('predecessor')
    value['predecessors'] = _predecessors()
    value['root'] = _TARGET_ROOT
    value['baseline_commit'] = _BASELINE
    return value


def _typed_third(summary=None, *, work_id=_WORK_ID, not_before=_NOT_BEFORE,
                 expires_at=_EXPIRES_AT):
    intent, notice = _typed_pair(_third_summary() if summary is None else summary)
    authorization = replace(
        intent.authorization,
        work_id=work_id,
        package_ref=replace(
            intent.authorization.package_ref,
            package_id='generated-package',
            digest=Digest('sha256', _PACKAGE_DIGEST),
        ),
        not_before=not_before,
        expires_at=expires_at,
    )
    notice = replace(notice, authorization=authorization)
    intent = WorkPackageAuthorizationIntent(authorization, notice.ref, intent.policy_ref)
    return intent, notice


def _bind(intent, notice, presented_at=_PRESENTED_AT):
    return subject.build_local_library_successor_presentation(
        intent, notice, presented_at=presented_at)


def test_third_work_requires_exact_four_hours_and_renders_cross_midnight_window():
    intent, notice = _typed_third()
    binding = _bind(intent, notice)
    view = binding.render(intent, notice)
    assert view['question'].endswith(subject._REPLY_HINT)
    assert view['question'].count(view['necessary_context']) == 1
    context = view['necessary_context']
    for required in (
        _TARGET_ROOT,
        _BASELINE,
        _PACKAGE_DIGEST,
        _WORK_ID,
        intent.authorization.work_digest.hex,
        intent.digest.hex,
        _NOT_BEFORE,
        _EXPIRES_AT,
        '均为UTC，恰好4小时',
        'synthetic-prior-work-one',
        'synthetic-prior-work-two',
        '11111111-1111-4111-8111-111111111111',
        '33333333-3333-4333-8333-333333333333',
        '22222222-2222-4222-8222-222222222222',
        '44444444-4444-4444-8444-444444444444',
        'unit-' + '1' * 32,
        'unit-' + '2' * 32,
        'attempt 1',
        'catalog/views.py',
        'catalog/templates/catalog/book_list.html',
        'catalog/tests/test_views.py',
        'catalog/tests/test_search.py',
        'edit_repository=1、run_checks=1',
    ):
        assert required in context
    assert context.count('edit_repository/run_checks各已消费1') == 2


@pytest.mark.parametrize('expires_at', [
    '2031-04-05T18:59:59.999999Z',
    '2031-04-05T19:00:00.000001Z',
])
def test_non_four_hour_window_is_refused(expires_at):
    intent, notice = _typed_third(expires_at=expires_at)
    with pytest.raises(ApplicationError):
        _bind(intent, notice)


def test_wrong_frozen_package_digest_is_refused():
    intent, notice = _typed_third()
    auth = replace(intent.authorization, package_ref=replace(
        intent.authorization.package_ref,
        digest=Digest('sha256', '9' * 64),
    ))
    changed_notice = replace(notice, authorization=auth)
    changed_intent = WorkPackageAuthorizationIntent(auth, changed_notice.ref, intent.policy_ref)
    with pytest.raises(ApplicationError):
        _bind(changed_intent, changed_notice)


def test_duplicate_predecessor_identity_is_refused():
    summary = _third_summary()
    summary['predecessors'][1] = dict(summary['predecessors'][0])
    with pytest.raises(ApplicationError):
        _bind(*_typed_third(summary))


def test_new_work_must_not_collide_with_either_predecessor():
    summary = _third_summary()
    summary['predecessors'][1]['work_id'] = _WORK_ID
    with pytest.raises(ApplicationError):
        _bind(*_typed_third(summary))


def test_same_intent_id_with_changed_predecessor_text_refuses_old_binding():
    intent, notice = _typed_third()
    binding = _bind(intent, notice)
    changed = _third_summary()
    changed['predecessors'][0]['handling'] += ' changed'
    summary_text = canonical_bytes(changed).decode('utf-8')
    auth = replace(intent.authorization, request_summary=summary_text)
    changed_notice = replace(notice, authorization=auth)
    changed_intent = WorkPackageAuthorizationIntent(auth, changed_notice.ref, intent.policy_ref)
    assert changed_intent.intent_id == intent.intent_id
    with pytest.raises(ApplicationError):
        binding.render(changed_intent, changed_notice)

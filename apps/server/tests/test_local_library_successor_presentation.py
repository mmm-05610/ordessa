"""Synthetic contract tests for the closed Local Library chat presentation."""
from dataclasses import replace
from hashlib import sha256

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConversationSource, WorkPackageNotice
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, WorkPackageAuthorization, WorkPackageAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.refs import ConsentPolicyRef
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, EffectLimit, EnvironmentRef, PathRule, RepositoryScope,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_server.composition.engineering_chat_confirmation import FrozenChatPresentation

from tooling.checks.server_product import local_library_successor_presentation as subject


_PRESENTED_AT = '2031-04-05T10:14:49.060255Z'
_NOT_BEFORE = '2031-04-05T09:39:53.283926Z'
_EXPIRES_AT = '2031-04-05T11:25:36.948354Z'
_POLICY = ConsentPolicyRef('synthetic-chat-policy', 1, Digest('sha256', 'e' * 64))


def _summary():
    before = {path: (None if operation == 'add' else sha256(path.encode()).hexdigest())
              for path, operation in subject._PATHS}
    return {
        'allowed_operations': subject._EXPECTED_OPERATIONS,
        'baseline_commit': 'a' * 40,
        'before_sha256': before,
        'checks': subject._POLICY_TEXT['checks'],
        'excluded': subject._POLICY_TEXT['excluded'],
        'execution_note': subject._POLICY_TEXT['execution_note'],
        'material_egress': subject._POLICY_TEXT['material_egress'],
        'preflight': subject._POLICY_TEXT['preflight'],
        'provider': subject._POLICY_TEXT['provider'],
        'execution_profile_ref': {
            'contentDigest': 'sha256:' + 'f' * 64,
            'environmentNamespace': 'synthetic-realm',
            'manifestRevision': 1,
            'profileId': 'synthetic-profile',
        },
        'predecessor': {
            'approval_id': '11111111-1111-4111-8111-111111111111',
            'dispatch_phase': 'unknown',
            'execution_operation_ref': '22222222-2222-4222-8222-222222222222',
            'handling': subject._POLICY_TEXT['predecessor_handling'],
            'old_action_consumed': {'edit_repository': 1, 'run_checks': 1},
            'work_id': 'synthetic-prior-work',
        },
        'repository_id': 'synthetic-repository',
        'root': '/tmp/synthetic-local-library',
    }


def _action_scope(scope, intent_id, repository_id, constraint_digest):
    rules = tuple(PathRule(path, 'exact', (operation,))
                  for path, operation in subject._PATHS)
    return ActionScope(
        project_id=scope.project_id,
        repository_scopes=(RepositoryScope(repository_id, rules),),
        environment_refs=(EnvironmentRef(
            scope.realm_id, 'synthetic-profile', Digest('sha256', 'f' * 64)),),
        effect_limits=tuple(EffectLimit(
            action, repository_id, Digest('sha256', constraint_digest))
            for action in subject._ACTIONS),
        exclusions=(),
        implementation_intent_id=intent_id,
    )


def _typed_pair(summary_override=None):
    summary = summary_override if summary_override is not None else _summary()
    summary_text = canonical_bytes(summary).decode('utf-8')
    summary_digest = sha256(canonical_bytes(summary)).hexdigest()
    scope = Scope('synthetic-realm', 'synthetic-project')
    intent_id = 'synthetic-successor-intent'
    action_scope = _action_scope(scope, intent_id, summary['repository_id'], summary_digest)
    authorization = WorkPackageAuthorization(
        scope=scope,
        intent_id=intent_id,
        work_id='synthetic-successor-work',
        work_revision=1,
        work_digest=Digest('sha256', 'c' * 64),
        action_id='incremental.implement-package',
        step_id='implement',
        package_ref=ImplementationPackageRef(
            scope.realm_id, scope.project_id, 'synthetic-package', Digest('sha256', 'b' * 64)),
        method_ref=MethodRef(
            'ordessa.incremental-engineering', '2.7.2', 2, Digest('sha256', 'd' * 64)),
        actions=('edit_repository', 'run_checks'),
        scope_by_action=(('edit_repository', action_scope), ('run_checks', action_scope)),
        action_budgets=(ActionBudgetSlot('edit_repository', 1), ActionBudgetSlot('run_checks', 1)),
        request_summary=summary_text,
        not_before=_NOT_BEFORE,
        expires_at=_EXPIRES_AT,
    )
    source = ConversationSource(
        locator='synthetic-thread/source',
        message_refs=('synthetic-message-1',),
        limitations='synthetic source only',
        attestor_id='synthetic-agent',
        captured_at=_NOT_BEFORE,
    )
    notice = WorkPackageNotice(
        notice_id='synthetic-successor-notice',
        authorization=authorization,
        actual_text='Synthetic Notice text; not a captured conversation.',
        source=source,
        policy_ref=_POLICY,
    )
    intent = WorkPackageAuthorizationIntent(authorization, notice.ref, _POLICY)
    return intent, notice


def _bind(intent, notice, presented_at=_PRESENTED_AT):
    return subject.build_local_library_successor_presentation(
        intent, notice, presented_at=presented_at)


def test_exact_synthetic_successor_renders_complete_closed_scope():
    intent, notice = _typed_pair()
    binding = _bind(intent, notice)
    assert type(binding) is FrozenChatPresentation
    assert binding.intent == intent and binding.notice == notice
    assert binding.contract_id == 'ordessa.work-package-chat-human/1'
    view = binding.render(intent, notice)
    assert set(view) == {'question', 'necessary_context'}
    assert view['question'].startswith(subject._PREFIX + subject._APPROVAL_QUESTION + '\n\n')
    assert view['question'].endswith('\n\n' + subject._REPLY_HINT)
    assert view['question'].count(view['necessary_context']) == 1
    for dynamic in (
        intent.authorization.package_ref.digest.hex,
        intent.authorization.work_id,
        subject._summary(intent.authorization.request_summary)[0]['root'],
        subject._summary(intent.authorization.request_summary)[0]['baseline_commit'],
        intent.digest.hex,
    ):
        assert dynamic in view['necessary_context']
    assert 'catalog/tests/test_search.py' in view['necessary_context']
    assert 'deepseek-flash' in view['necessary_context']
    assert '不退款、不重放' in view['necessary_context']
    assert '最终接受/adopt' in view['necessary_context']
    assert '19:25:36（北京时间）' in view['necessary_context']
    assert 'Synthetic Notice text' not in view['question']


@pytest.mark.parametrize('mutation', ['method', 'package', 'work', 'action_budget'])
def test_changed_typed_objects_after_binding_refuse(mutation):
    intent, notice = _typed_pair()
    binding = _bind(intent, notice)
    authorization = intent.authorization
    if mutation == 'method':
        authorization = replace(authorization,
            method_ref=replace(authorization.method_ref, release_version='2.7.3'))
    elif mutation == 'package':
        authorization = replace(authorization,
            package_ref=replace(authorization.package_ref,
                digest=Digest('sha256', '9' * 64)))
    elif mutation == 'work':
        authorization = replace(authorization, work_revision=2)
    elif mutation == 'action_budget':
        authorization = replace(authorization, action_budgets=(
            ActionBudgetSlot('edit_repository', 2), ActionBudgetSlot('run_checks', 1)))
    changed_notice = replace(notice, authorization=authorization)
    changed_intent = WorkPackageAuthorizationIntent(authorization, changed_notice.ref, _POLICY)
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        binding.render(changed_intent, changed_notice)


def test_summary_widening_extra_key_and_duplicate_keys_refuse():
    intent, notice = _typed_pair()
    expanded = dict(_summary())
    expanded['unreviewed_action'] = 'publish_branch'
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        _bind(*_typed_pair(expanded))

    valid = canonical_bytes(_summary()).decode('utf-8')
    duplicate = valid[:-1] + ',"root":"/tmp/elsewhere"}'
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        subject._summary(duplicate)

    changed_summary = dict(_summary())
    changed_summary['execution_profile_ref'] = dict(changed_summary['execution_profile_ref'])
    changed_summary['execution_profile_ref']['profileId'] = 'other-profile'
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        _bind(*_typed_pair(changed_summary))


def test_path_scope_must_match_the_closed_four_path_policy():
    intent, notice = _typed_pair()
    auth = intent.authorization
    original_scope = auth.scope_by_action[0][1]
    repo = original_scope.repository_scopes[0]
    widened_repo = replace(repo, path_rules=repo.path_rules + (
        PathRule('catalog/private', 'subtree', ('modify',)),))
    widened_scope = replace(original_scope, repository_scopes=(widened_repo,))
    authorization = replace(auth, scope_by_action=(
        ('edit_repository', widened_scope), ('run_checks', widened_scope)))
    changed_notice = replace(notice, authorization=authorization)
    changed_intent = WorkPackageAuthorizationIntent(authorization, changed_notice.ref, _POLICY)
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        _bind(changed_intent, changed_notice)


@pytest.mark.parametrize('presented_at', [
    '2031-04-05T09:39:53.283925Z',
    '2031-04-05T11:25:36.948354Z',
    '2031-04-06T10:14:49.060255Z',
    '2031-04-05T10:14:49Z',
])
def test_display_time_must_be_precise_same_local_date_and_inside_window(presented_at):
    intent, notice = _typed_pair()
    with pytest.raises(ApplicationError):
        _bind(intent, notice, presented_at)


def test_renderer_refuses_foreign_notice_after_binding():
    intent, notice = _typed_pair()
    binding = _bind(intent, notice)
    foreign_notice = replace(notice, actual_text=notice.actual_text + ' changed')
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        binding.render(intent, foreign_notice)


def test_closed_summary_rejects_added_operation_and_invalid_predecessor_identity():
    summary = _summary()
    summary['allowed_operations'] = dict(summary['allowed_operations'], **{'catalog/admin.py': ['modify']})
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        _bind(*_typed_pair(summary))

    summary = _summary()
    summary['predecessor'] = dict(summary['predecessor'], approval_id='not-a-uuid')
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        _bind(*_typed_pair(summary))


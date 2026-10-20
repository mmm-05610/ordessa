"""Controlled policy peers; original Unit permission itself is tested in Units."""
from types import SimpleNamespace
import pytest
from ordessa_units.api import UnitApiRefused
from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval


@pytest.fixture
def approval(tmp_path):
    cwd = tmp_path / 'unit' / 'cwd'
    cwd.mkdir(parents=True)
    permission = SimpleNamespace(root_directory=str(tmp_path), environment_identity='original-env')
    calls = []
    unit = SimpleNamespace(snapshot=lambda: {'sessionId': 'original-session'})
    owner = SimpleNamespace(permission=permission, authorization=lambda: 'original-authorization',
        native_unit=lambda *args: calls.append(args),
        records=SimpleNamespace(owner_read_unit=lambda ref: SimpleNamespace(facts={'privateRootFacts': {'cwd': str(cwd)}})))
    runtime = SimpleNamespace(unit_execution_owner=owner, units=SimpleNamespace(get=lambda ref: unit))
    policy = UnitFileCallbackApproval(runtime=runtime, permission=permission,
        environment_instance=SimpleNamespace(identity='original-env'), allowed_relative_paths=('unit-smoke.txt',))
    return policy, calls, cwd


def authorize(fixture, method, **params):
    policy, calls, cwd = fixture
    return policy.authorize(unit_ref={'unitId': 'original-unit'}, session_id='original-session',
        environment_identity='original-env', request_id='original-callback', method=method,
        params=dict(sessionId='original-session', **params))


def test_native_relative_path_binds_original_unit_cwd_and_once_option(approval):
    policy, calls, cwd = approval
    assert authorize(approval, 'session/request_permission', approval='file', files=['unit-smoke.txt'],
        toolCall={'kind': 'edit', 'locations': [{'path': 'unit-smoke.txt'}]},
        options=[{'kind': 'allow_always', 'optionId': 'always'}, {'kind': 'allow_once', 'optionId': 'once'}]) == 'once'
    assert len(calls) == 1
    assert authorize(approval, 'fs/write_text_file', path=str(cwd / 'unit-smoke.txt')) is True
    assert authorize(approval, 'fs/write_text_file', path=str(policy.root / 'unit-smoke.txt')) is False


@pytest.mark.parametrize('path', ['../unit-smoke.txt', 'other.txt', '/tmp/unapproved-file'])
def test_other_paths_are_refused(approval, path):
    assert authorize(approval, 'fs/write_text_file', path=path) is False


def test_symlink_and_always_only_and_command_are_refused(approval, tmp_path):
    policy, calls, cwd = approval
    (cwd / 'unit-smoke.txt').symlink_to(tmp_path / 'other')
    assert authorize(approval, 'fs/write_text_file', path='unit-smoke.txt') is False
    (cwd / 'unit-smoke.txt').unlink()
    assert authorize(approval, 'session/request_permission', approval='file', files=['unit-smoke.txt'],
        toolCall={'kind': 'edit', 'locations': [{'path': 'unit-smoke.txt'}]},
        options=[{'kind': 'allow_always', 'optionId': 'always'}]) is None
    assert authorize(approval, 'session/request_permission', approval='command', files=['unit-smoke.txt'],
        toolCall={'kind': 'execute', 'locations': [{'path': 'unit-smoke.txt'}]}, options=[]) is None


def test_original_owner_refusal_is_propagated(approval):
    policy, calls, cwd = approval
    def refused(*args):
        raise UnitApiRefused('Original permission revoked')
    policy.runtime.unit_execution_owner.native_unit = refused
    with pytest.raises(UnitApiRefused):
        authorize(approval, 'fs/write_text_file', path='unit-smoke.txt')


def test_read_permission_preserves_native_kind_and_still_checks_exact_paths(approval):
    assert authorize(approval, 'session/request_permission', approval='file', files=['unit-smoke.txt'],
        toolCall={'kind': 'read', 'locations': [{'path': 'unit-smoke.txt'}]},
        options=[{'kind': 'allow_once', 'optionId': 'read-once'}]) == 'read-once'
    assert authorize(approval, 'session/request_permission', approval='file', files=['other.txt'],
        toolCall={'kind': 'read', 'locations': [{'path': 'other.txt'}]},
        options=[{'kind': 'allow_once', 'optionId': 'read-once'}]) is None


def test_external_repository_paths_require_and_recheck_original_scope_guard(approval, tmp_path):
    from contextlib import contextmanager
    policy, _, _ = approval
    external = tmp_path.parent / (tmp_path.name + '-external.py')
    options = dict(runtime=policy.runtime, permission=policy.permission,
        environment_instance=policy.environment, allowed_paths=(str(external),))
    with pytest.raises(UnitApiRefused):
        UnitFileCallbackApproval(**options)
    seen, revoked = [], [False]
    @contextmanager
    def original_scope(**facts):
        seen.append(facts)
        if revoked[0]:
            raise UnitApiRefused('Original Work Grant revoked')
        yield
    scoped = UnitFileCallbackApproval(**options, scope_guard=original_scope)
    fixture = scoped, [], approval[2]
    assert authorize(fixture, 'fs/write_text_file', path=str(external)) is True
    assert seen[-1]['unit_ref'] == {'unitId': 'original-unit'}
    revoked[0] = True
    with pytest.raises(UnitApiRefused, match='Original Work Grant revoked'):
        authorize(fixture, 'fs/write_text_file', path=str(external))


CHECK_COMMAND = 'env -i PATH=/usr/bin:/bin /tmp/isolated-python -I -B /tmp/catalog-check.py --project-root /tmp/catalog'


@pytest.fixture
def command_approval(approval):
    from contextlib import contextmanager
    policy, calls, cwd = approval
    state = {'revoked': False, 'reviewer': False, 'checks': 0}
    @contextmanager
    def current_business_scope(**facts):
        state['checks'] += 1
        if state['revoked'] or state['reviewer']:
            raise UnitApiRefused('Current Work Grant or author assignment refused')
        yield
    selected = UnitFileCallbackApproval(runtime=policy.runtime, permission=policy.permission,
        environment_instance=policy.environment, allowed_relative_paths=('unit-smoke.txt',),
        scope_guard=current_business_scope, approved_check_command=CHECK_COMMAND)
    return (selected, calls, cwd), state


def command_params(command=CHECK_COMMAND):
    return {'approval': 'command', 'command': command,
        'toolCall': {'kind': 'execute', 'rawInput': {'command': command}},
        'options': [{'kind': 'allow_once', 'optionId': 'once'},
                    {'kind': 'allow_always', 'optionId': 'always'}]}


def test_fixed_check_command_still_requires_current_original_owner_and_scope(command_approval):
    fixture, state = command_approval
    assert authorize(fixture, 'session/request_permission', **command_params()) == 'once'
    assert state['checks'] == 1 and len(fixture[1]) == 1
    state['revoked'] = True
    with pytest.raises(UnitApiRefused, match='Current Work Grant'):
        authorize(fixture, 'session/request_permission', **command_params())
    state['revoked'], state['reviewer'] = False, True
    with pytest.raises(UnitApiRefused, match='author assignment'):
        authorize(fixture, 'session/request_permission', **command_params())
    state['reviewer'] = False
    def revoked_owner(*args):
        raise UnitApiRefused('Original Unit permission revoked')
    fixture[0].runtime.unit_execution_owner.native_unit = revoked_owner
    with pytest.raises(UnitApiRefused, match='Original Unit permission revoked'):
        authorize(fixture, 'session/request_permission', **command_params())


@pytest.mark.parametrize('command', [CHECK_COMMAND + ' --extra', ' ' + CHECK_COMMAND,
    CHECK_COMMAND + '; echo extra', CHECK_COMMAND + '\n', 'env', ''])
def test_fixed_check_refuses_any_different_command(command_approval, command):
    fixture, _ = command_approval
    assert authorize(fixture, 'session/request_permission', **command_params(command)) is None


@pytest.mark.parametrize('change', [
    {'files': ['unit-smoke.txt']}, {'host': 'example.com'}, {'protocol': 'https'},
    {'mcpTool': 'tool'}, {'commandActions': ['other']},
    {'cwd': '/tmp/foreign'}, {'proposedExecpolicyAmendment': ['allow']},
    {'toolCall': {'kind': 'execute', 'rawInput': {'command': CHECK_COMMAND, 'cwd': '/tmp/foreign'}}},
    {'toolCall': {'kind': 'execute', 'rawInput': {'command': CHECK_COMMAND, 'proposedNetworkPolicyAmendments': ['allow']}}},
    {'toolCall': {'kind': 'execute', 'rawInput': {'command': CHECK_COMMAND + ' --other'}}},
    {'toolCall': {'kind': 'execute'}},
    {'toolCall': {'kind': 'execute', 'rawInput': {'command': CHECK_COMMAND, 'files': ['x']}}},
    {'toolCall': {'kind': 'execute', 'rawInput': {'command': CHECK_COMMAND}, 'locations': [{'path': 'x'}]}},
    {'options': [{'kind': 'allow_always', 'optionId': 'always'}]},
    {'options': [{'kind': 'allow_once', 'optionId': 'one'}, {'kind': 'allow_once', 'optionId': 'two'}]},
])
def test_fixed_check_refuses_mixed_effects_or_ambiguous_once_option(command_approval, change):
    fixture, _ = command_approval
    assert authorize(fixture, 'session/request_permission', **{**command_params(), **change}) is None


def test_command_is_opt_in_and_cannot_be_selected_without_business_scope(approval):
    assert authorize(approval, 'session/request_permission', **command_params()) is None
    policy, _, _ = approval
    with pytest.raises(UnitApiRefused, match='business scope guard'):
        UnitFileCallbackApproval(runtime=policy.runtime, permission=policy.permission,
            environment_instance=policy.environment, allowed_relative_paths=('unit-smoke.txt',),
            approved_check_command=CHECK_COMMAND)

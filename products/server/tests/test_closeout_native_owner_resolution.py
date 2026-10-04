"""Route keys are presentation IDs; only verified native-owner tuples bind."""
import pytest
from server_plugin_api import WireError
from test_native_model_turn_composition import runtime_at, controlled_native, bind_native


def native_owner(runtime):
    return {'sessionId': 'history-route', 'serverInstanceId': runtime.owner.instance_id,
            'connectionId': 'connection', 'nativeSessionId': 's-1',
            'harnessId': 'pi', 'workspaceId': 'workspace'}


def test_route_alias_uses_verified_distinct_native_owner(monkeypatch, tmp_path):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        binding = bind_native(controlled)
        owner = native_owner(runtime)
        owner['workspaceId'] = controlled.channel.workspace_id
        answer = runtime.wire.dispatch('agent.session.resolve', {
            'location': {'kind': 'session', 'sessionId': 'history-route', 'connectionId': 'frontend'},
            'nativeOwner': owner})
        assert answer['target'] == binding.snapshot.target.session_id
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


@pytest.mark.parametrize('defect', ['missing', 'server', 'workspace'])
def test_unverified_native_owner_refuses_without_native_effect(monkeypatch, tmp_path, defect):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        bind_native(controlled)
        owner = native_owner(runtime)
        owner['workspaceId'] = controlled.channel.workspace_id
        params = {'location': {'kind': 'session', 'sessionId': 's-1', 'connectionId': 'connection'}}
        if defect != 'missing':
            params['nativeOwner'] = owner
            owner['serverInstanceId' if defect == 'server' else 'workspaceId'] = 'wrong'
        with pytest.raises(WireError):
            runtime.wire.dispatch('agent.session.resolve', params)
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


def test_default_draft_declares_absent_reliable_capability_and_stable_namespace(tmp_path):
    from ordessa_server_product.composition import create_composition
    location = {'kind': 'draft', 'draftId': 'draft-1', 'connectionId': 'frontend-1'}
    first = create_composition().default_runtime(tmp_path / 'default-data')
    try:
        first.start()
        before = first.wire.dispatch('agent.session.resolve', {'location': location})
        assert before['submission']['available'] is False
        assert before['submission']['namespace'] == first.core_binding.environment.environment_id
        assert before['submission']['principalScope'] == 'local'
        assert before['submission']['schema'] == 'agent-input/v1'
    finally:
        first.stop()
    second = create_composition().default_runtime(tmp_path / 'default-data')
    try:
        second.start()
        after = second.wire.dispatch('agent.session.resolve', {'location': location})
        assert after['submission'] == before['submission']
        assert after['target'] == before['target']
    finally:
        second.stop()

"""Controlled real ASGI transport tests; no native process/model/user database."""
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_server.composition.runtime import build_runtime
from ordessa_interfaces.http import create_app
from server_plugin_api import HttpRouteDescriptor, ServerPluginDescriptor, ServerPluginRegistration


class RoutePlugin:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def descriptor(self):
        return ServerPluginDescriptor('test.identity-route', 'identity test', '1')

    def build(self, context):
        return ServerPluginRegistration(http_routes=(HttpRouteDescriptor(
            path='/api/v1/identity-test', methods=frozenset({'GET'}),
            endpoint=self.endpoint, owner=self.descriptor().id),))


def headers(runtime):
    return {'Authorization': 'Bearer ' + runtime.token, 'Host': '127.0.0.1'}


def test_absent_authority_fails_closed_instead_of_using_runtime_token(tmp_path):
    runtime = build_runtime(tmp_path / 'server', server_plugins=[])
    try:
        runtime.wire.identity_authority = None
        client = TestClient(create_app(runtime), base_url='http://127.0.0.1')
        response = client.post('/wire/v1/server.hello', headers=headers(runtime), json={})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'UNAVAILABLE'
        assert client.get('/api/v1/openapi.json', headers=headers(runtime)).status_code == 503
    finally:
        runtime.stop()


def test_nonlocal_machine_cannot_enter_original_rest_or_websocket_paths(tmp_path):
    calls = []
    runtime = build_runtime(tmp_path / 'server', server_plugins=[RoutePlugin(lambda: calls.append('called'))])
    runtime.wire.identity_authority = InstanceAccessAuthority(
        lambda: runtime.token, principal_id='foreign-machine', legacy_principal=None, grants=())
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        for path in ('/api/v1/openapi.json', '/api/v1/identity-test'):
            assert client.get(path, headers=headers(runtime)).status_code == 403
        for path in ('/wire/v1/event-stream?sessionId=session1', '/wire/v1/acp-channel/connection1'):
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(path, headers=headers(runtime)):
                    pytest.fail('nonlocal caller entered original local surface')
            assert refused.value.code == 4403
        assert calls == []


def test_sync_rest_guard_blocks_revocation_until_actual_endpoint_returns(tmp_path):
    attempted, revoked = Event(), Event()
    workers = []
    runtime = None

    def endpoint():
        def revoke():
            attempted.set()
            runtime.wire.identity_authority.revoke()
            revoked.set()
        thread = Thread(target=revoke)
        workers.append(thread)
        thread.start()
        assert attempted.wait(1)
        assert not revoked.wait(.03)
        return {'result': 'completed'}

    runtime = build_runtime(tmp_path / 'server', server_plugins=[RoutePlugin(endpoint)])
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        response = client.get('/api/v1/identity-test', headers=headers(runtime))
        assert response.json() == {'result': 'completed'}
        assert revoked.wait(1)
        assert client.get('/api/v1/identity-test', headers=headers(runtime)).status_code == 401
    for thread in workers:
        thread.join(1)
        assert not thread.is_alive()


def test_event_stream_rechecks_each_frame_after_revocation(tmp_path, monkeypatch):
    runtime = build_runtime(tmp_path / 'server', server_plugins=[])
    frames = [{'sequence': 1}, {'sequence': 2}]
    monkeypatch.setattr(runtime.plugin_host, 'provided_port',
                        lambda name: (lambda session, cursor: (frames, 'cursor')))
    original = WebSocket.send_json
    sent = []

    async def send_and_revoke(self, data, *args, **kwargs):
        sent.append(data)
        await original(self, data, *args, **kwargs)
        runtime.wire.identity_authority.revoke()

    monkeypatch.setattr(WebSocket, 'send_json', send_and_revoke)
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        with client.websocket_connect('/wire/v1/event-stream?sessionId=session1', headers=headers(runtime)) as ws:
            assert ws.receive_json() == frames[0]
            with pytest.raises(WebSocketDisconnect) as refused:
                ws.receive_json()
            assert refused.value.code == 4401
            assert refused.value.reason == 'AUTHORIZATION_STALE'
    assert sent == [frames[0]]


def test_acp_admission_and_send_are_one_revocation_guard(tmp_path, monkeypatch):
    attempted, revoked = Event(), Event()
    workers, sent = [], []
    runtime = build_runtime(tmp_path / 'server', server_plugins=[])
    channel = SimpleNamespace(transport=SimpleNamespace(send_line=sent.append),
                              attach=lambda loop, sink: None, detach=lambda loop, sink: None)
    monkeypatch.setattr(runtime.wire.stream_routes, 'resolve', lambda *args: channel)

    def admit(connection, text):
        def revoke():
            attempted.set()
            runtime.wire.identity_authority.revoke()
            revoked.set()
        worker = Thread(target=revoke)
        workers.append(worker)
        worker.start()
        assert attempted.wait(1)
        assert not revoked.wait(.03)

    monkeypatch.setattr(runtime.wire.acp_admission_gate, 'admit_client_frame', admit)
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        with client.websocket_connect('/wire/v1/acp-channel/connection1', headers=headers(runtime)) as ws:
            ws.send_text('controlled-frame')
            assert revoked.wait(1)
            ws.send_text('after-revoke')
            with pytest.raises(WebSocketDisconnect) as refused:
                ws.receive_text()
            assert refused.value.code == 4401
    assert sent == ['controlled-frame']
    for worker in workers:
        worker.join(1)
        assert not worker.is_alive()


def test_authenticated_async_rest_requires_task_aware_lease(tmp_path):
    async def endpoint():
        return {'result': 'must-not-run'}
    runtime = build_runtime(tmp_path / 'server', server_plugins=[RoutePlugin(endpoint)])
    try:
        with pytest.raises(RuntimeError, match='ASYNC_IDENTITY_LEASE'):
            create_app(runtime)
    finally:
        runtime.stop()


def test_live_reactivation_to_async_cannot_bypass_sync_identity_lease(tmp_path):
    def sync_endpoint():
        return {'phase': 'sync'}
    async def async_endpoint():
        pytest.fail('async endpoint must be refused before creating a coroutine')
    plugin = RoutePlugin(sync_endpoint)
    runtime = build_runtime(tmp_path / 'server', server_plugins=[plugin])
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        assert client.get('/api/v1/identity-test', headers=headers(runtime)).json() == {'phase': 'sync'}
        runtime.plugin_host.deactivate(plugin.descriptor().id)
        plugin.endpoint = async_endpoint
        runtime.plugin_host.activate(plugin)
        assert client.get('/api/v1/identity-test', headers=headers(runtime)).status_code == 503


def test_original_workspace_post_resolves_model_annotations_without_host_import(tmp_path):
    runtime = build_runtime(tmp_path / 'server')
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        response = client.post('/api/v1/connections/probe', headers={**headers(runtime), 'Idempotency-Key': 'test-annotation-key'},
                               json={'kind': 'synthetic-not-wsl', 'distribution': 'synthetic'})
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'CONNECTION_KIND_UNSUPPORTED'
        schema = client.get('/api/v1/openapi.json', headers=headers(runtime)).json()
        body = schema['paths']['/api/v1/workspaces']['post']['requestBody']
        assert body['content']['application/json']['schema']['$ref'].endswith('/WorkspaceRequest')


def test_authenticated_async_callable_instance_requires_async_identity_lease(tmp_path):
    class AsyncEndpoint:
        async def __call__(self):
            pytest.fail('async callable must be rejected before invocation')
    runtime = build_runtime(tmp_path / 'server', server_plugins=[RoutePlugin(AsyncEndpoint())])
    try:
        with pytest.raises(RuntimeError, match='ASYNC_IDENTITY_LEASE'):
            create_app(runtime)
    finally:
        runtime.stop()

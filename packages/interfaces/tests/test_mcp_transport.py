"""Real MCP transports over the generic host (stdio + loopback Streamable HTTP).

The bridge cases run without the optional SDK. The transport cases are BLOCKED
(not silently skipped) when ``mcp==2.2.0`` is absent; the companion
``mcp_stdio_server.py`` is only a test host, never a mock of the transport.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from ordessa_interfaces.channels.mcp import McpBridge, McpBridgeError
from ordessa_interfaces.system_access.assembly import build_host
from ordessa_interfaces.transport import mcp_http, mcp_stdio
from ordessa_interfaces.transport.mcp_stdio import McpTransportUnavailable

from host_fakes import FakeEntryPoint, FakeFactory, make_capability

HERE = Path(__file__).resolve().parent
SERVER = HERE / 'mcp_stdio_server.py'

requires_mcp = pytest.mark.skipif(
    not mcp_stdio.sdk_available(),
    reason=mcp_stdio.BLOCKED_MESSAGE)


def _host(handler=None):
    capability = make_capability('demo', operation_ids=('demo.run',),
                                 mcp={'tool': 'demo_run'}, handler=handler)
    return build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))


def test_bridge_exposes_the_operation_schemas():
    bridge = McpBridge(_host(), principal={'principalId': 'p'})
    assert bridge.tools == [{
        'name': 'demo_run', 'operationId': 'demo.run',
        'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'integer'}},
                        'additionalProperties': False},
        'outputSchema': {'type': 'object'}}]
    assert bridge.operation_id('demo_run') == 'demo.run'


def test_bridge_identity_comes_from_composition_not_arguments():
    seen = {}

    async def handler(request, context):
        from ordessa_interfaces_contracts import OperationResult
        seen['principal'] = dict(context.principal)
        return OperationResult(status='completed', data=dict(request))

    bridge = McpBridge(_host(handler), principal={'principalId': 'trusted'})
    envelope = asyncio.run(bridge.call('demo_run', {'value': 1}, request_id='r1'))
    assert envelope['status'] == 'completed'
    assert seen['principal'] == {'principalId': 'trusted'}
    # A client-supplied identity is not stripped/merged; it is simply not read.
    refused = asyncio.run(bridge.call('demo_run', {'value': 1, 'principalId': 'evil'},
                                      request_id='r2'))
    assert refused['status'] == 'refused'
    assert seen['principal'] == {'principalId': 'trusted'}


def test_bridge_refuses_unknown_tool_and_bad_arguments():
    bridge = McpBridge(_host(), principal={'principalId': 'p'})
    with pytest.raises(McpBridgeError, match='not registered'):
        asyncio.run(bridge.call('missing', {}, request_id='r'))
    with pytest.raises(McpBridgeError, match='JSON object'):
        asyncio.run(bridge.call('demo_run', ['not', 'a', 'map'], request_id='r'))
    with pytest.raises(McpBridgeError, match='trusted principal'):
        McpBridge(_host(), principal='client-claimed')


def test_transport_is_explicitly_blocked_without_the_sdk(monkeypatch):
    bridge = McpBridge(_host(), principal={'principalId': 'p'})
    # Simulate an absent SDK explicitly instead of relying on the environment.
    monkeypatch.setattr(mcp_stdio, '_Server', None)
    monkeypatch.setattr(mcp_stdio, '_stdio_server', None)
    monkeypatch.setattr(mcp_stdio, 'mcp_types', None)
    assert mcp_stdio.sdk_available() is False
    with pytest.raises(McpTransportUnavailable, match='BLOCKED: mcp==2.2.0'):
        mcp_stdio.build_server(bridge)
    with pytest.raises(McpTransportUnavailable, match='BLOCKED: mcp==2.2.0'):
        mcp_http.build_http_app(bridge, authenticate=lambda token: {'principalId': token})
    with pytest.raises(McpTransportUnavailable, match='BLOCKED: mcp==2.2.0'):
        asyncio.run(mcp_http.run_http(bridge, authenticate=lambda token: {'principalId': token}))


@requires_mcp
def test_stdio_transport_serves_a_real_client():
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=[str(SERVER)],
            env={'PYTHONPATH': os.pathsep.join([
                str(HERE), str(Path(mcp_stdio.__file__).resolve().parents[2])])})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ['demo_run']
                result = await session.call_tool('demo_run', {'value': 1})
        return result

    result = asyncio.run(scenario())
    envelope = json.loads(result.content[0].text)
    assert result.is_error is False
    assert envelope['status'] == 'completed'
    assert envelope['data'] == {'value': 1}
    assert result.structured_content == {'value': 1}   # official client validated it


@requires_mcp
def test_loopback_http_transport_serves_json_rpc():
    import httpx
    from ordessa_interfaces.transport.mcp_http import run_http

    async def scenario():
        bridge = McpBridge(_host(), principal={'principalId': 'composition'})
        server, port, task = await run_http(
            bridge, authenticate=lambda token: {'principalId': token})
        headers = {'Accept': 'application/json, text/event-stream',
                   'Content-Type': 'application/json',
                   'Authorization': 'Bearer http-test'}
        try:
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', headers=headers,
                                         timeout=10, trust_env=False) as client:
                unauthorized = await client.post('/mcp', headers={
                    'Authorization': 'invalid'}, json={'jsonrpc': '2.0', 'id': 0,
                                                      'method': 'tools/list'})
                assert unauthorized.status_code == 401
                init = await client.post('/mcp', json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'test', 'version': '0'}}})
                assert init.status_code == 200
                listed = await client.post('/mcp', json={
                    'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
                assert 'demo_run' in listed.text
                called = await client.post('/mcp', json={
                    'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                    'params': {'name': 'demo_run', 'arguments': {'value': 1}}})
                assert called.status_code == 200
                return called.text
        finally:
            server.should_exit = True
            await task

    body = asyncio.run(scenario())
    assert 'completed' in body


def _asgi_inner(record):
    async def app(scope, receive, send):
        record.append(scope.get('state', {}).get('principal'))
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})
    return app


def _scope(headers):
    return {'type': 'http', 'method': 'POST', 'path': '/mcp',
            'headers': [(key.encode(), value.encode()) for key, value in headers.items()]}


async def _call(app, scope):
    sent = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


def test_http_without_authenticator_refuses_to_build():
    bridge = McpBridge(_host(), principal={'principalId': 'p'})
    with pytest.raises(McpTransportUnavailable, match='external trusted authenticator'):
        mcp_http.build_http_app(bridge, authenticate=None)


def test_http_rejects_missing_or_invalid_credentials_before_dispatch():
    record = []
    app = mcp_http.AuthenticatedHttpApp(_asgi_inner(record),
                                        lambda token: {'principalId': token} if token == 'ok' else None)
    sent = asyncio.run(_call(app, _scope({})))
    assert sent[0]['status'] == 401 and record == []
    sent = asyncio.run(_call(app, _scope({'authorization': 'Bearer bad'})))
    assert sent[0]['status'] == 401 and record == []
    sent = asyncio.run(_call(app, _scope({'authorization': 'Basic ok'})))
    assert sent[0]['status'] == 401 and record == []


def test_http_binds_each_request_to_its_verified_principal():
    record = []
    app = mcp_http.AuthenticatedHttpApp(_asgi_inner(record),
                                        lambda token: {'principalId': token})
    asyncio.run(_call(app, _scope({'authorization': 'Bearer alice'})))
    asyncio.run(_call(app, _scope({'authorization': 'Bearer bob'})))
    assert record == [{'principalId': 'alice'}, {'principalId': 'bob'}]


def test_concurrent_http_requests_do_not_share_identity():
    record = []
    app = mcp_http.AuthenticatedHttpApp(_asgi_inner(record),
                                        lambda token: {'principalId': token})

    async def scenario():
        await asyncio.gather(
            *[_call(app, _scope({'authorization': f'Bearer user-{index}'}))
              for index in range(8)])

    asyncio.run(scenario())
    assert sorted(item['principalId'] for item in record) == sorted(
        f'user-{index}' for index in range(8))


def test_context_without_verified_principal_is_refused():
    class NoRequest:
        request = None
    with pytest.raises(McpTransportUnavailable, match='verified principal'):
        mcp_http.principal_from_context(NoRequest())

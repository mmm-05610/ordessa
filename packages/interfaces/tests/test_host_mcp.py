"""MCP metadata and loopback identity over the same registry/schemas."""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from ordessa_interfaces_contracts import ContractError, OperationResult
from ordessa_interfaces.channels import mcp
from ordessa_interfaces.system_access.assembly import build_host
from ordessa_interfaces.system_access.operations import RequestContext
from ordessa_interfaces.transport.loopback import LoopbackTransport

from host_fakes import FakeEntryPoint, FakeFactory, make_capability


def _host(handler=None):
    capability = make_capability('demo', operation_ids=('demo.run',),
                                 cli={'command': 'demo', 'operation': 'run'},
                                 mcp={'tool': 'demo_run'}, handler=handler)
    return build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))


def test_tool_list_uses_the_operation_schemas():
    host = _host()
    tools = mcp.tool_specs(host.registry)
    assert tools == [{'name': 'demo_run', 'operationId': 'demo.run',
                      'inputSchema': {'type': 'object',
                                      'properties': {'value': {'type': 'integer'}},
                                      'additionalProperties': False},
                      'outputSchema': {'type': 'object'}}]
    assert mcp.tool_index(host.registry) == {'demo_run': 'demo.run'}


def test_duplicate_tool_names_refuse():
    capability = make_capability('demo', operation_ids=('demo.run', 'demo.other'),
                                 mcp={'tool': 'same'})
    host = build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))
    with pytest.raises(ContractError, match='repeats'):
        mcp.tool_specs(host.registry)


def test_loopback_identity_is_carried_into_the_context_unchanged():
    seen = {}

    async def handler(request, context):
        seen['principal'] = dict(context.principal)
        return OperationResult(status='completed', data={'value': request['value']})

    host = _host(handler)
    transport = LoopbackTransport(host)
    envelope = transport.request_sync('demo.run', {'value': 7},
                                      principal={'principalId': 'caller-1',
                                                 'scopes': ['demo.run']},
                                      request_id='req-1')
    assert envelope['apiVersion'] == 'agent-tools/1'
    assert envelope['status'] == 'completed' and envelope['data'] == {'value': 7}
    assert seen['principal'] == {'principalId': 'caller-1', 'scopes': ['demo.run']}


def test_mcp_call_tool_dispatch_and_unknown_tool():
    host = _host()
    context = RequestContext(principal={'principalId': 'mcp'}, request_id='r')
    tools = mcp.tool_index(host.registry)
    result = asyncio.run(mcp.call_tool(host, tools, 'demo_run', {'value': 1}, context))
    assert result.status == 'completed'
    with pytest.raises(ContractError, match='not registered'):
        asyncio.run(mcp.call_tool(host, tools, 'missing', {}, context))


def test_cli_prints_exactly_one_json_object_in_json_mode():
    from ordessa_interfaces.channels import cli
    host = _host()
    out = io.StringIO()
    code = cli.run(['call', 'demo.run', '--input', '-', '--json'], host=host,
                           authenticate=lambda command: {'principalId': 'p'},
                           stdin=io.BytesIO(b'{"value": 2}'), stdout=out, stderr=io.StringIO())
    assert code == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])['status'] == 'completed'

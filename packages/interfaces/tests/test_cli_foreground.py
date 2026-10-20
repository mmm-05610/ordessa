"""Foreground CLI: one caller-owned event loop keeps real tasks across commands.

The synchronous ``run`` wrapper is one-shot; a long-lived host awaits
``async_run`` repeatedly on its own loop. These cases prove the actual task
survives across commands, that each command keeps its own principal/request id
and schema checks, and that the caller owns explicit cleanup.
"""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from ordessa_interfaces.channels import cli
from ordessa_interfaces.system_access.assembly import build_host
from ordessa_interfaces_contracts import OperationResult

from host_fakes import FakeEntryPoint, FakeFactory, make_capability


def _host(holder):
    async def handler(request, context):
        action = request['action']
        if action == 'start':
            holder['loop'] = asyncio.get_running_loop()
            holder['ticks'] = 0
            holder['task'] = asyncio.create_task(_peer(holder))
            holder['request_ids'].append(context.request_id)
            return OperationResult('completed', data={'started': True})
        if action == 'status':
            task = holder['task']
            holder['request_ids'].append(context.request_id)
            return OperationResult('completed', data={
                'pending': not task.done(),
                'sameLoop': asyncio.get_running_loop() is holder['loop'],
                'sameTask': task is holder['task']})
        if action == 'stop':
            holder['task'].cancel()
            return OperationResult('completed', data={'cancelled': True})
        return OperationResult('refused', error=None) if False else OperationResult(
            'refused', error=__import__('ordessa_interfaces_contracts').CapabilityError(
                'INVALID_INPUT', 'unknown action'))

    capability = make_capability(
        'demo', operation_ids=('demo.run',),
        cli={'command': 'demo', 'operation': 'run',
             'args': ({'name': 'action', 'flags': ('--action',), 'type': 'string',
                       'required': True},)},
        input_schema={'type': 'object'}, handler=handler)
    return build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))


async def _peer(holder):
    while True:
        holder['ticks'] += 1
        await asyncio.sleep(0.01)


def _io(stdin=b''):
    return io.BytesIO(stdin), io.StringIO(), io.StringIO()


def test_foreground_loop_keeps_a_real_task_across_commands():
    holder = {'request_ids': []}
    host = _host(holder)
    commands = []

    def authenticate(command):
        commands.append(command)
        return {'principalId': 'foreground'}

    async def scenario():
        loop = asyncio.get_running_loop()
        stdin, out, err = _io()
        code = await cli.async_run(['demo', 'run', '--action', 'start', '--json'],
                                   host=host, authenticate=authenticate,
                                   stdin=stdin, stdout=out, stderr=err)
        assert code == 0 and json.loads(out.getvalue())['status'] == 'completed'
        task = holder['task']
        await asyncio.sleep(0.05)
        ticks = holder['ticks']
        assert ticks > 0 and not task.done()

        stdin, out, err = _io()
        code = await cli.async_run(['demo', 'run', '--action', 'status', '--json'],
                                   host=host, authenticate=authenticate,
                                   stdin=stdin, stdout=out, stderr=err)
        assert code == 0
        data = json.loads(out.getvalue())['data']
        assert data == {'pending': True, 'sameLoop': True, 'sameTask': True}
        assert asyncio.get_running_loop() is loop
        assert task is holder['task'] and not task.done()
        await asyncio.sleep(0.03)
        assert holder['ticks'] > ticks

        # A refused command on the same loop does not disturb the live task.
        stdin, out, err = _io()
        code = await cli.async_run(['demo', 'run', '--json'], host=host,
                                   authenticate=authenticate,
                                   stdin=stdin, stdout=out, stderr=err)
        assert code == 2 and not task.done()

        stdin, out, err = _io()
        code = await cli.async_run(['demo', 'run', '--action', 'stop', '--json'],
                                   host=host, authenticate=authenticate,
                                   stdin=stdin, stdout=out, stderr=err)
        assert code == 0
        with pytest.raises(asyncio.CancelledError):
            await task
        return loop

    loop = asyncio.run(scenario())
    assert commands == ['demo run'] * 3          # authentication per dispatched command
    assert len(set(holder['request_ids'])) == 2  # distinct request ids per command
    assert loop.is_closed()


def test_one_shot_run_uses_the_same_path_as_async_run():
    holder = {'request_ids': []}
    host = _host(holder)
    stdin, out, err = _io()
    result = cli.run(['demo', 'run', '--action', 'start', '--json', '--request-id', 'fixed'],
                     host=host, authenticate=lambda command: {'principalId': 'p'},
                     stdin=stdin, stdout=out, stderr=err)
    assert result == 0
    one_shot = out.getvalue()
    # One-shot run closes its loop, so the peer task cannot outlive the command.
    assert holder['task'].cancelled()

    foreground = {'request_ids': []}
    foreground_host = _host(foreground)

    async def via_async():
        stdin, out, err = _io()
        code = await cli.async_run(
            ['demo', 'run', '--action', 'start', '--json', '--request-id', 'fixed'],
            host=foreground_host, authenticate=lambda command: {'principalId': 'p'},
            stdin=stdin, stdout=out, stderr=err)
        assert not foreground['task'].done()          # caller keeps it on the loop
        foreground['task'].cancel()
        with pytest.raises(asyncio.CancelledError):
            await foreground['task']
        return code, out.getvalue()

    code, via_async_out = asyncio.run(via_async())
    assert (result, one_shot) == (code, via_async_out)


def test_foreground_process_output_and_child_exit_semantics():
    async def handler(request, context):
        return OperationResult('completed', data={
            'exitCode': 3, 'stdout': 'out\n', 'stderr': 'err\n'})

    capability = make_capability('proc', operation_ids=('proc.run',),
                                 cli={'command': 'proc', 'operation': 'run',
                                      'render': {'kind': 'process'}},
                                 input_schema={'type': 'object'}, handler=handler)
    host = build_host(('proc',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('proc', FakeFactory(capability)),))

    async def scenario():
        stdin, out, err = _io()
        code = await cli.async_run(['proc', 'run'], host=host,
                                   authenticate=lambda command: {'principalId': 'p'},
                                   stdin=stdin, stdout=out, stderr=err)
        stdin, out_json, err_json = _io()
        code_json = await cli.async_run(['proc', 'run', '--json'], host=host,
                                        authenticate=lambda command: {'principalId': 'p'},
                                        stdin=stdin, stdout=out_json, stderr=err_json)
        return code, out.getvalue(), err.getvalue(), code_json, out_json.getvalue()

    code, out, err, code_json, out_json = asyncio.run(scenario())
    assert (code, out, err) == (3, 'out\n', 'err\n')
    assert code_json == 3 and len(out_json.splitlines()) == 1
    assert json.loads(out_json)['data']['exitCode'] == 3

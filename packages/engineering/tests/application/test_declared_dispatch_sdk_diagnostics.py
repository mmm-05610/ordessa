"""Formal Work failure projection with the official SDK and controlled IO.

Real schema17 Work/Grant/blob/debit owners are combined with the official ACP
Connection. The ProcessHandle and external permission producer are explicit
test peers; this does not launch a Unit, server, process or model.
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ordessa_environments import ProcessHandle
from ordessa_agents.harness.transport import EffectWriteGuard
from ordessa_agents.harness.transport.environment_channel import EnvironmentProcessChannel
from ordessa_engineering.adapters.native_records.recorded_dispatch import (
    failure_diagnostic as recorded_failure_diagnostic)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.failure_diagnostic import FailureDiagnostic
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_infrastructure.encoding import decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_system_access_bindings.engineering_wire import _failure
from ordessa_units.sessions.sdk_client import SdkAcpClient

from test_declared_implementation_results import _prepare_flow, _table_refs
from test_real_source_chain import SCOPE
from test_work_package_dispatch_v2 import UNIT, dispatch_fixture, row
from test_work_package_dispatch_v2 import call


def test_formal_work_sdk_response_timeout_persists_bound_diagnostic_and_wire_view(
        tmp_path, monkeypatch):
    writes, clients, captured = [], [], {}
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture, parameters, context, before_submissions, before_reviews = _prepare_flow(
            fixture, 'pass', 'work-sdk-failure-diagnostic')
        transport = fixture['transport']

        def send(binding, *, timeout):
            transport.binding = binding
            params = decode_json(fixture['env'].blobs.read_verified(binding.prompt_ref))
            process = MagicMock(spec=ProcessHandle)
            process.observe.return_value = SimpleNamespace(state='running')

            async def read_stdout(**_kwargs):
                await asyncio.Future()

            async def read_stderr(**_kwargs):
                return b''

            async def write_stdin(data, *, timeout=None):
                transport.sends += 1
                writes.append(data)
                return len(data)

            process.read_stdout = read_stdout
            process.read_stderr = read_stderr
            process.write_stdin = write_stdin
            channel = EnvironmentProcessChannel(process, name='work-diagnostic', managed=True)
            writer = channel.bind_writer(channel.acquire_writer())
            owner = object()
            client = SdkAcpClient(writer, name='work-diagnostic', connect=True,
                require_effect_write_guard=True, effect_write_owner=owner)
            clients.append(client)

            @asynccontextmanager
            async def acquire(identity, deadline):
                async with transport.dispatch.acquire_effect_write(transport.ctx, binding,
                        identity, deadline, handoff=transport.handoff):
                    yield

            guard = EffectWriteGuard(UNIT, binding.execution_operation_ref,
                'sha256:' + binding.prompt_input_digest.hex, params, acquire)
            client.request('session/prompt', params, timeout=2,
                effect_write_guard=guard, _effect_write_owner=owner)

        def capture(binding, error, stage):
            # Exercise the production binding validator without constructing
            # another runtime authority or substituting a marker dictionary.
            # The extractor is a pure function, so no live execution object or
            # owner factory takes part in reading the recorded evidence.
            diagnostic = recorded_failure_diagnostic(binding, error, stage)
            mismatch = recorded_failure_diagnostic(
                replace(binding, execution_operation_ref='different-operation'), error, stage)
            assert mismatch.to_dict()['native_write'] is None
            assert mismatch.to_dict()['recording_failure']['exception_chain'][0]['code'] == (
                'NATIVE_WRITE_BOUNDARY_BINDING_MISMATCH')
            captured['diagnostic'] = diagnostic
            return diagnostic

        monkeypatch.setattr(transport, 'send', send)
        monkeypatch.setattr(transport, 'failure_diagnostic', capture, raising=False)
        try:
            with pytest.raises(ApplicationError) as raised:
                asyncio.run(fixture['service'].execute(
                    'engineering.work.invoke', parameters, context))
            error = raised.value
            assert error.code == 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'
            assert error.failure_diagnostic == captured['diagnostic']
            assert error.failure_evidence_linked is True
            ref = error.failure_evidence_ref
            stored = fixture['env'].blobs.read_verified(ref)
            assert FailureDiagnostic(stored) == error.failure_diagnostic
            data = error.failure_diagnostic.to_dict()
            native = data['native_write']
            assert native['phase'] == 'response_wait'
            assert native['write_stdin'] == 'returned'
            assert native['acknowledged_bytes'] == native['frame_bytes'] == len(writes[0])
            assert native['frame_digest'] == 'sha256:' + hashlib.sha256(writes[0]).hexdigest()
            record = row(fixture)
            binding = decode_dispatch(record['binding_bytes'])
            assert native['operation_ref'] == binding.execution_operation_ref
            assert native['input_digest'] == 'sha256:' + binding.prompt_input_digest.hex
            assert native['unit_ref_digest'] == 'sha256:' + hashlib.sha256(
                safe_json(UNIT).encode()).hexdigest()
            assert record['dispatch_phase'] == 'unknown'
            assert record['dispatch_version'] == 2
            assert decode_json(record['result_blob_json']) == asdict(ref)
            wire = _failure(error).to_body()['details']
            assert wire['failureDiagnostic'] == data
            assert wire['failureEvidenceRef'] == asdict(ref)
            assert wire['failureEvidenceLinked'] is True
            assert wire['retryable'] is False
            assert _table_refs(fixture, 'eng_submissions', 'submission_id') == before_submissions
            assert _table_refs(fixture, 'eng_reviews', 'review_id') == before_reviews
            with fixture['factory'].begin(SCOPE, 'read') as uow:
                budget = uow.authorization.action_budget(binding.approval_ref)
            assert [slot['consumed'] for slot in budget['actions']] == [1, 1]
            assert transport.sends == len(writes) == len(clients) == 1

            # Replaying the original parent may return its pending journal
            # view; it must not invoke a second SDK request or consume again.
            asyncio.run(fixture['service'].execute('engineering.work.invoke', parameters, context))
            assert transport.sends == len(writes) == len(clients) == 1
            assert row(fixture)['binding_bytes'] == record['binding_bytes']
            with fixture['factory'].begin(SCOPE, 'read') as uow:
                assert uow.authorization.action_budget(binding.approval_ref) == budget
        finally:
            for client in clients:
                client.detach()


def test_maximum_diagnostic_and_repeated_recording_failures_stay_bounded():
    node = {'relation': 'raised', 'type': 'M' * 96, 'code': 'C' * 96,
        'frames': [{'module': 'M' * 96, 'function': 'F' * 96, 'line': 9999999}] * 3}
    record = {'contract': 'engineering-dispatch-failure/1', 'stage': 'native_send',
        'exception_chain': [node] * 6, 'chain_truncated': True, 'native_write': None,
        'recording_failure': {'exception_chain': [node] * 6, 'chain_truncated': True}}
    diagnostic = FailureDiagnostic.from_record(record)
    assert len(diagnostic.encoded) < 16384
    additional = diagnostic.with_recording_failure(OSError('private exception text'))
    assert len(additional.encoded) < 16384
    assert additional.to_dict()['recording_failure']['chain_truncated'] is True
    assert additional.to_dict()['recording_failure']['exception_chain'] == [node] * 6


def test_handoff_release_failure_is_distinguished_after_the_original_send(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        transport = fixture['transport']
        original = transport.guard_effect_handoff

        @contextmanager
        def fail_release(*args, **kwargs):
            with original(*args, **kwargs):
                yield
            raise OSError('controlled handoff release failure; no provider receipt')

        monkeypatch.setattr(transport, 'guard_effect_handoff', fail_release)
        answer = call(fixture)
        assert answer.outcome == 'unknown'
        data = answer.value['failure_diagnostic'].to_dict()
        assert data['stage'] == 'handoff_exit'
        assert data['exception_chain'][0]['type'] == 'builtins.OSError'
        assert data['native_write'] is None
        assert transport.sends == 1
        assert row(fixture)['dispatch_phase'] == 'unknown'
        binding = decode_dispatch(row(fixture)['binding_bytes'])
        with fixture['factory'].begin(SCOPE, 'read') as uow:
            budget = uow.authorization.action_budget(binding.approval_ref)
        assert [slot['consumed'] for slot in budget['actions']] == [1, 1]
        replay = call(fixture)
        assert replay.value['failure_diagnostic'].to_dict() == data
        assert transport.sends == 1


def test_capture_never_formats_hostile_exception_or_unsuppresses_private_context():
    class UnformattableError(RuntimeError):
        def __str__(self):
            raise AssertionError('exception text must never be rendered')

        def __repr__(self):
            raise AssertionError('exception args must never be rendered')

    primary = UnformattableError('private exception text')
    primary.__context__ = OSError('suppressed private context')
    primary.__suppress_context__ = True
    diagnostic = FailureDiagnostic.capture(primary, 'native_send')
    assert len(diagnostic.to_dict()['exception_chain']) == 1
    assert 'private exception text' not in diagnostic.encoded.decode()
    assert 'suppressed private context' not in diagnostic.encoded.decode()


@pytest.mark.parametrize('budget,expected', [(2.0, 'timeout'), (8.0, 'completed')])
def test_declared_work_cut_budget_covers_the_in_cut_revalidation(
        tmp_path, monkeypatch, budget, expected):
    """The cut re-validates Grant/gates/selection/scope before it may write.

    That prefix is measured at ~1.5 s. With the original 2 s transport default
    the deadline is exhausted before the write (zero bytes, UNKNOWN); the host's
    bounded 8 s budget (chosen for a frozen-package binding) completes one write.
    """
    writes, clients = [], []
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture, parameters, context, before_submissions, before_reviews = _prepare_flow(
            fixture, 'pass', f'work-sdk-cut-budget-{budget}')
        transport = fixture['transport']

        def send(binding, *, timeout):
            transport.binding = binding
            params = decode_json(fixture['env'].blobs.read_verified(binding.prompt_ref))
            process = MagicMock(spec=ProcessHandle)
            process.observe.return_value = SimpleNamespace(state='running')

            answer = {'ready': asyncio.Event(), 'line': None}

            async def read_stdout(**_kwargs):
                if not answer['ready'].is_set():
                    await answer['ready'].wait()
                line, answer['line'] = answer['line'], None
                if line is not None:
                    return line
                await asyncio.Future()

            async def read_stderr(**_kwargs):
                return b''

            async def write_stdin(data, *, timeout=None):
                frame = json.loads(data)
                if frame.get('method') == 'session/prompt' and answer['line'] is None:
                    answer['line'] = (json.dumps({
                        'jsonrpc': '2.0', 'id': frame['id'],
                        'result': {'stopReason': 'end_turn'}}) + '\n').encode()
                    answer['ready'].set()
                transport.sends += 1
                writes.append(data)
                return len(data)

            process.read_stdout = read_stdout
            process.read_stderr = read_stderr
            process.write_stdin = write_stdin
            channel = EnvironmentProcessChannel(process, name='work-cut-budget', managed=True)
            writer = channel.bind_writer(channel.acquire_writer())
            owner = object()
            client = SdkAcpClient(writer, name='work-cut-budget', connect=True,
                require_effect_write_guard=True, effect_write_owner=owner)
            clients.append(client)

            @asynccontextmanager
            async def acquire(identity, deadline):
                if budget > 2.0:
                    # The host's 8 s budget covers a 2.5 s in-cut re-validation
                    # with 5.5 s to spare; the arm is decided by construction.
                    await asyncio.sleep(2.5)
                    async with transport.dispatch.acquire_effect_write(
                            transport.ctx, binding, identity, deadline,
                            handoff=transport.handoff):
                        yield
                else:
                    # Deterministic overrun of the remaining cut budget: the
                    # production gate stack cannot finish in 0.3 s, so the cut
                    # itself raises DISPATCH_EFFECT_TIMEOUT (the real shape)
                    # while the guard's own 2 s deadline is untouched. No part
                    # of this arm depends on how fast the machine is.
                    loop = asyncio.get_running_loop()
                    async with transport.dispatch.acquire_effect_write(
                            transport.ctx, binding, identity, loop.time() + 0.3,
                            handoff=transport.handoff):
                        yield

            guard = EffectWriteGuard(UNIT, binding.execution_operation_ref,
                'sha256:' + binding.prompt_input_digest.hex, params, acquire,
                timeout=budget)
            client.request('session/prompt', params, timeout=30,
                effect_write_guard=guard, _effect_write_owner=owner)

        monkeypatch.setattr(transport, 'send', send)
        monkeypatch.setattr(
            transport, 'failure_diagnostic',
            lambda binding, error, stage: recorded_failure_diagnostic(binding, error, stage),
            raising=False)
        try:
            answer = call(fixture)
            if expected == 'timeout':
                assert answer.outcome == 'unknown'
                assert transport.sends == 0 and writes == []
                diagnostic = answer.value['failure_diagnostic'].to_dict()
                # The 2.5 s reconstruction overruns the 2 s transport budget, so
                # the guard itself cancels the acquisition; the cut's own
                # DISPATCH_EFFECT_TIMEOUT code is covered by the deterministic
                # expired-deadline case in the handoff test file.
                head = diagnostic['exception_chain'][0]
                assert head['type'] in {'builtins.TimeoutError', 'builtins.CancelledError'} \
                    or head['code'] == 'DISPATCH_EFFECT_TIMEOUT'
                # The guard cancels the acquisition at its own deadline, so the
                # transport may or may not have produced a boundary snapshot;
                # when it did, it must still be the pre-write phase.
                assert diagnostic['exception_chain'][0]['code'] == 'DISPATCH_EFFECT_TIMEOUT'
                native = diagnostic['native_write']
                assert native is not None, diagnostic
                assert native['phase'] == 'effect_guard_acquire'
                assert native['before_write'] == 'not_entered'
                assert native['write_stdin'] == 'not_entered'
                record = row(fixture)
                assert record['dispatch_phase'] == 'unknown'
                binding = decode_dispatch(record['binding_bytes'])
                with fixture['factory'].begin(SCOPE, 'read') as uow:
                    budget_view = uow.authorization.action_budget(binding.approval_ref)
                assert [slot['consumed'] for slot in budget_view['actions']] == [1, 1]
            else:
                assert answer.outcome == 'completed'
                assert transport.sends == 1 and len(writes) == 1
                assert row(fixture)['dispatch_phase'] == 'completed'
        finally:
            for client in clients:
                client.detach()

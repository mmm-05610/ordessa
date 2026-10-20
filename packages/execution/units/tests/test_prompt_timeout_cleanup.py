"""Prompt timeout retains the original Unit until SDK callback cleanup."""
import importlib.util
import json
from pathlib import Path
from threading import Event, Thread
import time
from types import SimpleNamespace

import pytest

from ordessa_environments import EnvironmentRefused
from ordessa_execution_agents.harness.transport import RequestTimeout, WriterLeaseRefused
from ordessa_units.admission.connection import ConnectionLeaseRefused
from ordessa_units.records.unit_records import UnitRecordsRefused

from test_local_owner import ACP_PEER_REVERSE_WRITE, live_owner


class _HeldRefusingApproval:
    def __init__(self):
        self.entered = Event()
        self.resume = Event()
        self.calls = []

    def authorize(self, **request):
        self.calls.append(request)
        self.entered.set()
        if not self.resume.wait(8):
            raise TimeoutError('controlled callback approval was not released')
        return False


def _close_generated_units():
    root = Path(__file__).resolve().parents[4]
    path = root / 'tooling/checks/server_product/probe-work-package-generation.py'
    spec = importlib.util.spec_from_file_location('work_package_generation_probe_for_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.close_generated_units


def _termination_rows(world, unit):
    return tuple(world.records.owner_read_termination(unit.identity['unitId'], action)
                 for action in ('stop', 'release'))


@pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True,
    'preparation_peer': ACP_PEER_REVERSE_WRITE,
    'callback_approval': _HeldRefusingApproval(),
}], indirect=True)
def test_real_prompt_timeout_pending_close_and_owner_retry(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry
    record = instance.channel_factory.owned_record
    approval = instance.callbacks.approval
    launch = record.prepared_agent.harness.launch_spec
    callback_file = Path(launch.cwd) / 'callback-proof.txt'
    lease = world.owner.authorize('interaction', unit, authorization)
    operation_ref = 'prompt-timeout-cleanup-once'
    params = {'prompt': [{'type': 'text', 'text': 'controlled timeout cleanup'}]}
    prompt_frames = []
    prompt_errors = []
    prompt_results = []
    original_write = record.process.write_stdin

    async def observe_prompt_write(data, *, timeout=None):
        try:
            raw = json.loads(data)
        except (TypeError, ValueError):
            raw = None
        if isinstance(raw, dict) and raw.get('method') == 'session/prompt':
            prompt_frames.append(raw['id'])
        return await original_write(data, timeout=timeout)

    record.process.write_stdin = observe_prompt_write

    def send_prompt():
        try:
            prompt_results.append(instance.prompt(unit.identity, lease,
                operation_ref=operation_ref, timeout=1.0, **params))
        except BaseException as error:
            prompt_errors.append(error)

    prompt_thread = Thread(target=send_prompt)
    close_pending = Event()
    close_observations = []
    original_unit_close = unit.close

    def observe_close(auth):
        result = original_unit_close(auth)
        close_observations.append(result)
        if result.get('state') == 'pending' and result.get('unresolved') is True:
            close_pending.set()
        return result

    monkeypatch.setattr(unit, 'close', observe_close)
    close_future = None
    from concurrent.futures import ThreadPoolExecutor
    close_pool = ThreadPoolExecutor(max_workers=1)
    try:
        prompt_thread.start()
        assert approval.entered.wait(5)
        assert len(prompt_frames) == 1
        prompt_thread.join(4)
        assert not prompt_thread.is_alive()
        assert len(prompt_errors) == 1 and isinstance(prompt_errors[0], RequestTimeout)
        assert prompt_results == []

        with world.journal._connect() as db:
            stored = db.execute(
                'SELECT state,body_json FROM harness_acp_turn_attempts WHERE operation_ref=?',
                (operation_ref,)).fetchone()
        assert stored is not None and stored['state'] == 'unknown'
        body = json.loads(stored['body_json'])
        assert body['state'] == 'unknown'
        assert body['request']['raw']['id'] == prompt_frames[0]
        assert body['response'] is None
        assert len(approval.calls) == 1

        # The request bridge timed out while the SDK loop was synchronously
        # held in the original callback. Keep this assertion even if it finds
        # that the channel's unknown latch was not propagated by cancellation.
        assert record.channel._unresolved is True

        with pytest.raises((UnitRecordsRefused, WriterLeaseRefused, ConnectionLeaseRefused)):
            instance.prompt(unit.identity, lease, operation_ref=operation_ref,
                            timeout=.05, **params)
        assert prompt_frames == [body['request']['raw']['id']]
        with world.journal._connect() as db:
            assert db.execute(
                'SELECT count(*) FROM harness_acp_turn_attempts WHERE operation_ref=?',
                (operation_ref,)).fetchone()[0] == 1
        assert _termination_rows(world, unit) == (None, None)
        assert world.environment.snapshot.active_uses == 1
        assert client._active_native_operations > 0
        assert record.process.observe().state == 'running'

        # Exercise the same cleanup helper used by the product probe. Its
        # repeated call is allowed only while the exact original close reports
        # pending/unresolved; authorization and Unit identity stay fixed.
        close_helper = _close_generated_units()
        runtime = SimpleNamespace(units=world.public_manager,
                                  unit_execution_owner=world.owner)
        close_future = close_pool.submit(close_helper, runtime, (), timeout=8)
        assert close_pending.wait(3)
        assert close_observations[0]['state'] == 'pending'
        assert _termination_rows(world, unit) == (None, None)
        assert world.environment.snapshot.active_uses == 1
        assert client._active_native_operations > 0
    finally:
        approval.resume.set()
        prompt_thread.join(8)
        if close_future is not None:
            try:
                close_future.result(timeout=12)
            finally:
                close_pool.shutdown(wait=True)
        else:
            close_pool.shutdown(wait=True)

    assert not prompt_thread.is_alive()
    deadline = time.monotonic() + 5
    while client._active_native_operations and time.monotonic() < deadline:
        Event().wait(.01)
    assert client._active_native_operations == 0
    states, attempts = close_future.result(timeout=1)
    assert states == ['confirmed'] and attempts[0] >= 2
    assert len(close_observations) == attempts[0]
    assert close_observations[-1]['state'] == 'confirmed'
    assert _termination_rows(world, unit)[0]['state'] == 'confirmed'
    assert _termination_rows(world, unit)[1]['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0
    with pytest.raises(EnvironmentRefused, match='environment use is released'):
        record.process.observe()
    assert prompt_frames == [body['request']['raw']['id']]
    with world.journal._connect() as db:
        after_close = db.execute(
            'SELECT state,body_json FROM harness_acp_turn_attempts WHERE operation_ref=?',
            (operation_ref,)).fetchone()
    assert after_close['state'] == stored['state'] == 'unknown'
    assert after_close['body_json'] == stored['body_json']
    assert callback_file.exists() is False

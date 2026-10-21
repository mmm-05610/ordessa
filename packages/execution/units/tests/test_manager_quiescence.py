"""Public Manager close quiesces exact original native Unit clients first."""
from threading import Event, Thread

import pytest
import os

from ordessa_agents.harness.transport import WriterLeaseRefused
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.errors import UnitApiRefused

from test_local_owner import ACP_PEER_REVERSE_WRITE, live_owner


def _termination_rows(world, unit):
    return tuple(world.records.owner_read_termination(unit.identity['unitId'], action)
                 for action in ('stop', 'release'))


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_manager_close_pending_keeps_every_unit_when_one_original_sdk_is_busy(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    units = tuple(world.public_manager.create(world.owner.spec, authorization) for _ in range(2))
    records = tuple(unit._instance.channel_factory.owned_record for unit in units)
    busy_record = records[-1]
    entered, resume = Event(), Event()
    worker_errors = []

    def hold_original_native_operation():
        try:
            with busy_record.entry.admitted_operation():
                entered.set()
                if not resume.wait(5):
                    raise TimeoutError('test gate was not released')
        except BaseException as error:
            worker_errors.append(error)

    worker = Thread(target=hold_original_native_operation)
    worker.start()
    assert entered.wait(5)
    try:
        result = world.public_manager.close(authorization)
        assert result['state'] == 'pending'
        assert result['unresolved'] is True
        assert all(item['state'] == 'pending' and item['unresolved'] is True
                   for item in result['units'])
        assert world.original_manager._draining is True
        assert world.environment.snapshot.active_uses == 2
        assert all(record.process.observe().state == 'running' for record in records)
        assert all(_termination_rows(world, unit) == (None, None) for unit in units)
        assert {entry[3] for entry in world.owner._operations.values()} == {'prepare', 'start'}

        # The idle sibling was quiesced during the all-members preflight. It
        # remains the same process/Use/record object, but cannot start a new RPC.
        with pytest.raises(WriterLeaseRefused):
            units[0].interaction(authorization).request('session/prompt', {
                'sessionId': units[0].snapshot()['sessionId'],
                'prompt': [{'type': 'text', 'text': 'after manager drain'}],
            }, timeout=5)
        assert _termination_rows(world, units[0]) == (None, None)
    finally:
        resume.set()
        worker.join(5)
    assert not worker.is_alive()
    assert worker_errors == []

    closed = world.public_manager.close(authorization)
    assert closed['state'] == 'confirmed'
    assert all(item['state'] == 'confirmed' for item in closed['units'])
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_manager_close_stays_pending_through_recorded_prompt_finish(live_owner, monkeypatch):
    from ordessa_units.records import acp_turns

    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    lease = world.owner.authorize('interaction', unit, authorization)
    client = instance.channel_factory.owned_record.entry
    original_finish = acp_turns.finish
    finish_entered, resume_finish = Event(), Event()
    prompt_results, prompt_errors = [], []

    def hold_finish(records, operation_ref, state, *args, **kwargs):
        if state == 'completed':
            finish_entered.set()
            if not resume_finish.wait(5):
                raise TimeoutError('recorded prompt finish was not released')
        return original_finish(records, operation_ref, state, *args, **kwargs)

    monkeypatch.setattr(acp_turns, 'finish', hold_finish)

    def recorded_prompt():
        try:
            prompt_results.append(instance.prompt(
                unit.identity, lease, operation_ref='quiescence-held-recorded-prompt', timeout=5,
                prompt=[{'type': 'text', 'text': 'real local ACP prompt'}]))
        except BaseException as error:
            prompt_errors.append(error)

    worker = Thread(target=recorded_prompt)
    worker.start()
    assert finish_entered.wait(5)
    try:
        # The native response already arrived, but the outer SDK admission span
        # remains live until the original durable receipt is finalized.
        assert client._active_native_operations == 1
        assert client.try_quiesce() is False
        result = world.public_manager.close(authorization)
        assert result['state'] == 'pending'
        assert result['unresolved'] is True
        assert _termination_rows(world, unit) == (None, None)
        assert world.environment.snapshot.active_uses == 1
        assert instance.channel_factory.owned_record.process.observe().state == 'running'
    finally:
        resume_finish.set()
        worker.join(5)
    assert not worker.is_alive()
    assert prompt_errors == []
    assert prompt_results and prompt_results[0]['state'] == 'completed'

    result = world.public_manager.close(authorization)
    assert result['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0


class _HeldCallbackApproval:
    def __init__(self):
        self.entered, self.resume = Event(), Event()
        self.calls = []

    def authorize(self, **request):
        self.calls.append(request)
        self.entered.set()
        if not self.resume.wait(5):
            raise TimeoutError('test callback approval was not released')
        return True


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "preparation_peer": ACP_PEER_REVERSE_WRITE,
    "callback_approval": _HeldCallbackApproval(),
}], indirect=True)
def test_manager_close_waits_for_real_local_peer_reverse_file_write(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    approval = instance.callbacks.approval
    client = instance.channel_factory.owned_record.entry
    lease = world.owner.authorize('interaction', unit, authorization)
    prompt_results, prompt_errors = [], []
    launch = instance.channel_factory.owned_record.prepared_agent.harness.launch_spec
    file_path = os.path.join(launch.cwd, 'callback-proof.txt')
    files = instance.channel_factory.environment.files
    relative = os.path.relpath(file_path, files.root())

    def send_real_prompt():
        try:
            prompt_results.append(instance.prompt(
                unit.identity, lease, operation_ref='real-peer-reverse-write', timeout=5,
                prompt=[{'type': 'text', 'text': 'request one approved file write'}]))
        except BaseException as error:
            prompt_errors.append(error)

    worker = Thread(target=send_real_prompt)
    rejected, reject_errors = Event(), []
    reject_worker = None
    worker.start()
    assert approval.entered.wait(5)
    try:
        # The real child sent fs/write_text_file over ACP. Its original
        # callback is blocked at the configured approval port before touching
        # the Environment file area.
        assert client._active_native_operations >= 2
        assert approval.calls and approval.calls[0]['method'] == 'fs/write_text_file'
        assert files.exists(relative) is False
        result = world.public_manager.close(authorization)
        assert result['state'] == 'pending'
        assert result['unresolved'] is True
        assert unit.close(authorization)['state'] == 'pending'
        assert _termination_rows(world, unit) == (None, None)
        assert world.environment.snapshot.active_uses == 1
        assert instance.channel_factory.owned_record.process.observe().state == 'running'
        operations_before = len(world.owner._operations)

        def reject_after_close_cut():
            try:
                # An external approval wait must not retain the admission
                # lock. The cut must reject a fresh public request without
                # waiting for that original callback or spending a new key.
                with world.admission.admission_lock:
                    pass
                with pytest.raises(UnitApiRefused, match='closing'):
                    world.public_manager.create(world.owner.spec, authorization)
            except BaseException as error:
                reject_errors.append(error)
            finally:
                rejected.set()

        reject_worker = Thread(target=reject_after_close_cut)
        reject_worker.start()
        assert rejected.wait(1), 'close-cut rejection waited for external callback approval'
        assert reject_errors == []
        assert approval.resume.is_set() is False
        assert len(world.owner._operations) == operations_before
        assert world.environment.snapshot.active_uses == 1
    finally:
        approval.resume.set()
        worker.join(5)
        if reject_worker is not None:
            reject_worker.join(5)
    assert not worker.is_alive()
    assert reject_worker is not None and not reject_worker.is_alive()
    assert prompt_errors == []
    assert prompt_results and prompt_results[0]['state'] == 'completed'
    assert files.exists(relative) is True
    assert files.read_text(relative) == 'written-once'
    assert len(approval.calls) == 1
    assert client._active_native_operations == 0
    assert unit.close(authorization)['state'] == 'confirmed'
    assert world.public_manager.close(authorization)['state'] == 'confirmed'


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_invalid_close_authorization_does_not_quiesce_or_drain(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    client = unit._instance.channel_factory.owned_record.entry

    with pytest.raises(InvocationAuthorityRefused):
        world.public_manager.close(object())
    assert world.original_manager._draining is False
    assert client._native_admission_open is True
    assert _termination_rows(world, unit) == (None, None)

    refused = unit.close(object())
    assert refused['state'] == 'refused'
    assert client._native_admission_open is True
    assert _termination_rows(world, unit) == (None, None)

    interaction = unit.interaction(authorization)
    response = interaction.prompt(
        {'prompt': [{'type': 'text', 'text': 'still authorized after refused close'}]}, timeout=5)
    assert response['stopReason'] == 'end_turn'
    assert unit.close(authorization)['state'] == 'confirmed'


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_manager_close_never_replays_original_unknown_release(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    original_release = instance.channel_factory.release
    attempts = []

    def lose_original_release_receipt(entry):
        attempts.append(entry)
        original_release(entry)
        raise RuntimeError('controlled lost release receipt')

    monkeypatch.setattr(instance.channel_factory, 'release', lose_original_release_receipt)
    first = world.public_manager.close(authorization)
    second = world.public_manager.close(authorization)

    assert first['state'] == 'partial'
    assert second['state'] == 'partial'
    assert len(attempts) == 1
    assert world.public_manager.get(unit.identity) is unit
    termination = world.records.owner_read_termination(unit.identity['unitId'], 'release')
    assert termination is not None and termination['state'] == 'unknown'
    assert world.environment.snapshot.active_uses == 1
    world.unknown_release_completed = True
    world.leave_unknown = True

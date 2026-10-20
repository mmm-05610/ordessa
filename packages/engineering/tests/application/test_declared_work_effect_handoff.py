"""Native handoff reads the same schema-17 Work dispatch row it will write."""
from contextlib import contextmanager
from threading import Thread

import pytest

from ordessa_engineering.adapters.native_records import (
    engineering_effect_write_guard_factory,
)
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_work_package_dispatch_v2 import call, dispatch_fixture, row, request


def test_declared_work_handoff_uses_work_dispatch_row_not_legacy_dispatch(
    tmp_path, monkeypatch,
):
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        owner = fixture['service']._execution_dispatch
        transport = fixture['transport']
        access = fixture['service']._access
        records = transport.records
        native_thread = Thread(target=lambda: None, name='controlled-work-handoff-target')
        observations = {'handoff_entered': False, 'before_write': False}

        @contextmanager
        def controlled_permission_handoff(
            context, *, invocation_key, action_instances, target_thread, expires_at,
        ):
            assert context is transport.ctx
            assert type(invocation_key) is bytes and len(invocation_key) == 32
            assert action_instances
            assert target_thread is native_thread and not target_thread.is_alive()
            assert type(expires_at) is float
            # Explicit test-only token: the original effect guard still checks
            # and consumes it around the controlled transport write.
            yield transport.handoff

        monkeypatch.setattr(
            access, 'handoff_effect_write', controlled_permission_handoff, raising=False)

        @contextmanager
        def native_handoff(context, binding, *, access, timeout):
            transport.ctx = context
            fixed = engineering_effect_write_guard_factory(
                owner, context, records, fixture['env'].blobs)
            with fixed.guard_effect_handoff(
                context, binding, access=access, timeout=timeout,
                target_thread=native_thread,
            ):
                observations['handoff_entered'] = True
                yield

        transport.guard_effect_handoff = native_handoff

        def before_write(binding):
            assert observations['handoff_entered'] is True
            assert binding.work is not None
            key = work_dispatch_key(
                binding.work['work_id'], binding.work['action_id'], binding.step_id)
            observations['legacy_run_id'] = binding.run_id
            with fixture['factory'].begin(binding.scope, 'read') as uow:
                work_row = uow.work_dispatch.get(
                    key, binding.step_id, binding.attempt, binding.scope)
                assert work_row['binding_bytes']
                assert work_row['execution_operation_ref'] == binding.execution_operation_ref
                assert work_row['dispatch_phase'] == 'possibly_written'
                with pytest.raises(ApplicationError, match='NOT_FOUND'):
                    uow.dispatch.get(
                        binding.run_id, binding.step_id, binding.attempt, binding.scope)
            observations['before_write'] = True

        transport.before_write = before_write

        result = call(fixture)

        assert result.outcome == 'completed'
        assert observations['handoff_entered'] is True
        assert observations['before_write'] is True
        assert observations['legacy_run_id']
        assert transport.sends == 1
        stored = row(fixture)
        assert stored['dispatch_phase'] == 'completed'
        assert stored['binding_bytes']
        with fixture['factory'].begin(fixture['authorization'].scope, 'read') as uow:
            with pytest.raises(ApplicationError, match='NOT_FOUND'):
                uow.dispatch.get(
                    observations['legacy_run_id'],
                    fixture['authorization'].step_id, 1,
                    fixture['authorization'].scope)


def test_declared_work_response_wait_can_exceed_the_bounded_native_write_cut(tmp_path, monkeypatch):
    from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities

    descriptor = next(item for item in owner_capabilities()
                      if item.capability_id == 'engineering.executions.dispatch')
    contract = descriptor.contract
    assert contract['limits']['timeout_max_seconds'] == (
        contract['input_schema']['properties']['dispatch']['properties']['timeout']['maximum'])
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        value = request(fixture)
        value['dispatch']['timeout'] = 1800
        result = call(fixture, value)
        assert result.outcome == 'completed'
        assert fixture['transport'].sends == 1
        assert row(fixture)['dispatch_phase'] == 'completed'


def test_frozen_package_work_selects_the_bounded_eight_second_write_budget(
        tmp_path, monkeypatch):
    """The 8 s budget is chosen from the verified binding, not from the caller."""
    from dataclasses import replace
    from ordessa_engineering.adapters.native_records.recorded_dispatch import (
        effect_write_timeout)
    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch

    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        result = call(fixture)
        assert result.outcome == 'completed'
        binding = decode_dispatch(row(fixture)['binding_bytes'])
        assert binding.binding_version == 2
        assert binding.subject['subject_kind'] == 'frozen_package'
        assert effect_write_timeout(binding) == 8.0
        # A run-based (v1) binding keeps the transport default of 2 s.
        run_based = replace(binding, binding_version=1, work=None, subject=None)
        assert effect_write_timeout(run_based) is None


def test_a_busy_effect_cut_still_exits_bounded_with_zero_writes(tmp_path, monkeypatch):
    """Lock contention beyond the deadline never writes and never hangs."""
    import time
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.application.contracts.errors import ApplicationError

    class _BusyCut:
        def __enter__(self):
            raise ApplicationError('EFFECT_WRITE_BUSY')

        def __exit__(self, *_exc):
            return False

    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        # Only the effect-cut acquisition is busy; every other UoW is real.
        monkeypatch.setattr(SQLiteUoWFactory, 'begin_effect_cut',
                            lambda _self, _scope: _BusyCut())
        started = time.monotonic()
        result = call(fixture)
        elapsed = time.monotonic() - started
        assert result.outcome == 'unknown'
        assert fixture['transport'].sends == 0
        assert elapsed < 5.0  # bounded by the controlled transport deadline
        diagnostic = result.value['failure_diagnostic'].to_dict()
        assert diagnostic['exception_chain'][0]['code'] == 'DISPATCH_EFFECT_TIMEOUT'


def test_the_real_factory_selects_the_guard_budget_from_the_binding(
        tmp_path, monkeypatch):
    """The production factory itself, not the helper, picks 8 s vs the default.

    The factory's ``__call__`` is the only construction point of the effect
    write guard. Its slot is seeded directly here because the handoff row check
    needs a ``possibly_written`` row, which the other handoff test covers; the
    budget decision, the binding validation and the guard construction below are
    all the production ones.
    """
    from dataclasses import replace
    from threading import current_thread
    from ordessa_engineering.adapters.native_records import (
        engineering_effect_write_guard_factory)
    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
    from ordessa_infrastructure.encoding import decode_json

    class _RecordsPeer:
        """Only the ACP input-digest read the factory performs; no Unit."""

        def __init__(self, digest):
            self.digest = digest

        def acp_prompt_input_digest(self, unit, params):
            return self.digest

    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        transport = fixture['transport']
        access = fixture['service']._access
        owner = fixture['service']._execution_dispatch
        assert call(fixture).outcome == 'completed'
        binding = decode_dispatch(row(fixture)['binding_bytes'])
        unit = decode_json(binding.unit_ref_bytes)
        params = decode_json(fixture['env'].blobs.read_verified(binding.prompt_ref))
        digest = 'sha256:' + binding.prompt_input_digest.hex
        records = _RecordsPeer(digest)
        monkeypatch.setattr(owner, 'records', records, raising=False)
        monkeypatch.setattr(transport, 'records', records, raising=False)
        monkeypatch.setattr(access, 'handoff_effect_write',
                            lambda *a, **k: None, raising=False)
        factory = engineering_effect_write_guard_factory(
            owner, None, records, fixture['env'].blobs)

        def guard_for(candidate):
            factory._slot = (object(), candidate, object(), current_thread(), owner)
            try:
                return factory(unit, binding.execution_operation_ref, digest, params)
            finally:
                factory._slot = None

        declared = guard_for(binding)
        assert declared.timeout == 8.0
        assert declared.release_timeout == 1.0
        run_based = replace(binding, binding_version=1, work=None, subject=None)
        default = guard_for(run_based)
        assert default.timeout == 2.0


def test_an_expired_cut_deadline_refuses_before_any_write(tmp_path, monkeypatch):
    """The cut's own deadline check is deterministic: no clock race, no write."""
    import asyncio
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.application.orchestration.steps.declared_implementation_dispatch import (
        acquire_effect_cut)
    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch

    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        # Produce a real binding, then hand the cut a deadline already in the
        # past: its first check must refuse without touching the writer.
        assert call(fixture).outcome == 'completed'
        binding = decode_dispatch(row(fixture)['binding_bytes'])
        dispatch = fixture['dispatch']
        context = fixture['transport'].ctx
        from ordessa_infrastructure.encoding import decode_json
        unit = decode_json(binding.unit_ref_bytes)
        identity = {'unitRef': unit, 'operationRef': binding.execution_operation_ref,
                    'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
                    'requestId': 'controlled-expired-cut',
                    'frameDigest': 'sha256:' + 'e' * 64}
        sends_before = fixture['transport'].sends

        async def run():
            loop = asyncio.get_running_loop()
            async with acquire_effect_cut(dispatch, context, binding, identity,
                                          loop.time() - 1.0):
                raise AssertionError('expired cut must not yield')

        with pytest.raises(ApplicationError, match='DISPATCH_EFFECT_TIMEOUT'):
            asyncio.run(run())
        assert fixture['transport'].sends == sends_before

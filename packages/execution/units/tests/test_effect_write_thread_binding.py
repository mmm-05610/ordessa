"""Public SDK effect-write target binding on the original local Unit owner."""
import threading

import pytest

pytest_plugins = ('test_local_owner',)


_GUARDED_OWNER = {
    'acp_turn_opt_in': True,
    'effect_write_guard_factory': lambda *_args: None,
}


@pytest.mark.parametrize('live_owner', [_GUARDED_OWNER], indirect=True)
def test_unit_effect_write_thread_is_the_original_sdk_loop_thread(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = world.owner.native_unit(unit, world.owner.authorization())
    entry = instance.channel_factory.owned_record.entry

    async def on_original_loop():
        return threading.current_thread()

    actual_loop_thread = entry.run_process_operation(on_original_loop(), timeout=2)
    target = instance.effect_write_thread
    assert type(target) is threading.Thread
    assert target is actual_loop_thread
    assert target.is_alive()
    assert entry.effect_write_thread is target


def test_unit_effect_write_thread_refuses_unconfigured_guard(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = world.owner.native_unit(unit, world.owner.authorization())
    from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused

    with pytest.raises(UnitLifecycleRefused, match='guarded original ACP target'):
        _ = instance.effect_write_thread


@pytest.mark.parametrize('live_owner', [_GUARDED_OWNER], indirect=True)
def test_unit_effect_write_thread_refuses_closed_native_admission(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = world.owner.native_unit(unit, world.owner.authorization())
    assert instance.try_quiesce() is True
    from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused

    with pytest.raises(UnitLifecycleRefused):
        _ = instance.effect_write_thread

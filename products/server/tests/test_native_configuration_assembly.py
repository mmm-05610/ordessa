"""Neutral product configuration authority, without native processes or models."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from ordessa_harness.server_acp.registry import NativeConfigurationObservation, NativeSessionObservation
from ordessa_server_product.composition import create_composition


def runtime_at(tmp_path, **options):
    return create_composition().native_runtime(tmp_path / 'data',
        plugin_root=Path(__file__).resolve().parents[3] / 'plugins/harness',
        harness_id='pi', adapter_command=shutil.which('node'),
        installed_artifact_root='/opt/ordessa/artifacts', **options)


def observed_owner(monkeypatch, authority):
    owner = NativeSessionObservation('connection', 'execution', 'ledger-session', 'native-session')
    channel = SimpleNamespace(ended=False, harness_id='pi', workspace_id='workspace')
    state = {'owner': owner, 'generation': 'native-generation-1'}
    monkeypatch.setattr(authority.channels, 'get', lambda connection: channel if connection == 'connection' else None)
    monkeypatch.setattr(authority.channels, 'native_session_observation', lambda connection, native: state['owner'])
    monkeypatch.setattr(authority.channels, 'query_native_configuration', lambda *args, **kwargs:
        NativeConfigurationObservation(state['owner'], state['generation'], False,
            json.dumps([{'id': 'model', 'currentValue': 'native-model'}])))
    return state


def create_controlled_service(monkeypatch, authority, target):
    from ordessa_harness_api import Installation
    from ordessa_harness.pi.configuration.runtime import PiLiveModelRuntime

    monkeypatch.setattr(authority.services, 'verify', lambda brand:
        Installation(brand, PiLiveModelRuntime.native_version, (1, 0, 0), 'controlled:publication'))
    service, native_runtime = authority.create_service(target)
    assert service.target == native_runtime.target == target
    assert service.journal.path == authority.services.journal_path
    return service


def test_without_profile_authority_registers_native_owner_without_profile_records(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, include_profile=False, pi_profile_bridge=True)
    try:
        runtime.start()
        assert runtime.plugin_host.provided_port('profile.core') is None
        authority = runtime.plugin_host.provided_port('native.configuration')
        assert authority is not None
        observed_owner(monkeypatch, authority)
        first = authority.register_native(connection_id='connection', native_session_id='native-session')
        second = authority.register_native(connection_id='connection', native_session_id='native-session')
        assert first.target == second.target
        assert first.owner is second.owner
        assert authority.services.owners is authority.owners
        assert authority.services.journal_path == tmp_path / 'data/plugins/profile/native-configuration.sqlite'
        assert not (tmp_path / 'data/plugins/profile/profile-store.sqlite').exists()
        assert runtime.plugin_host.provided_port('model_provider.catalog') is not None
        create_controlled_service(monkeypatch, authority, first.target)
    finally:
        runtime.stop()


def test_profile_reuses_neutral_uid_and_unload_cannot_dispose_shared_authority(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, pi_profile_bridge=True)
    try:
        runtime.start()
        authority = runtime.plugin_host.provided_port('native.configuration')
        assert authority is not None
        observed_owner(monkeypatch, authority)
        before = authority.register_native(connection_id='connection', native_session_id='native-session')
        core = runtime.plugin_host.provided_port('profile.core')
        with core.db.read() as conn:
            assert conn.execute('SELECT COUNT(*) FROM profile_sessions').fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM profile_profiles').fetchone()[0] == 0
        profile = core.profiles.create('selected-profile', realm='local', harness_id='pi', display_name='Selected')
        sessions = runtime.plugin_host.provided_port('profile.native-sessions')
        registered = sessions.register(connection_id='connection', native_session_id='native-session', profile_id=profile['profile_id'])
        assert registered.session_ref.session_uid == before.target.session_id
        assert registered.snapshot.target == before.target
        assert sessions.owners is authority.owners
        runtime.plugin_host.deactivate('ordessa.skills')
        runtime.plugin_host.deactivate('ordessa.profile')
        assert runtime.plugin_host.provided_port('native.configuration') is authority
        assert authority.register_native(connection_id='connection', native_session_id='native-session').target == before.target
        assert runtime.plugin_host.provided_port('model_provider.catalog') is not None
        create_controlled_service(monkeypatch, authority, before.target)
        profile_plugin = next(plugin for plugin in runtime.plugin_selection if plugin.descriptor().id == 'ordessa.profile')
        runtime.plugin_host.activate(profile_plugin)
        reactivated = runtime.plugin_host.provided_port('profile.native-sessions')
        assert reactivated.owners is authority.owners
        assert reactivated.register(connection_id='connection', native_session_id='native-session', profile_id=profile['profile_id']).session_ref == registered.session_ref
    finally:
        runtime.stop()


def test_runtime_restart_replaces_authority_and_old_consumers_fail_closed(tmp_path):
    runtime = runtime_at(tmp_path)
    try:
        runtime.start()
        first = runtime.plugin_host.provided_port('native.configuration')
        assert first is not None
        runtime.stop()
        assert runtime.plugin_host.provided_port('native.configuration') is None
        with pytest.raises(RuntimeError, match='inactive'):
            first.register_native(connection_id='connection', native_session_id='native')
        with pytest.raises(RuntimeError, match='inactive'):
            first.create_service(None)
        with pytest.raises(RuntimeError, match='inactive'):
            first.begin_restoration(None, operation_id='stopped-round')
        runtime.start()
        second = runtime.plugin_host.provided_port('native.configuration')
        assert second is not first
        assert second.owners is not first.owners
        assert runtime.plugin_host.provided_port('profile.native-sessions').owners is second.owners
    finally:
        runtime.stop()


def test_neutral_registration_refuses_owner_replacement_and_generation_drift(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        authority = runtime.plugin_host.provided_port('native.configuration')
        state = observed_owner(monkeypatch, authority)
        first = authority.register_native(connection_id='connection', native_session_id='native-session')
        state['generation'] = 'native-generation-2'
        with pytest.raises(RuntimeError):
            authority.resolve(first.target)
        state['owner'] = NativeSessionObservation('connection', 'other-execution', 'ledger-session', 'native-session')
        with pytest.raises(RuntimeError):
            authority.register_native(connection_id='connection', native_session_id='native-session')
    finally:
        runtime.stop()


def test_profile_unload_keeps_same_c4_unknown_session_fence(tmp_path, monkeypatch):
    from ordessa_harness.application import FenceObservation, OperationJournal
    from ordessa_harness_api import ErrorCode, Plan, Refused

    runtime = runtime_at(tmp_path)
    try:
        runtime.start()
        authority = runtime.plugin_host.provided_port('native.configuration')
        observed_owner(monkeypatch, authority)
        target = authority.register_native(connection_id='connection', native_session_id='native-session').target
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        before = Plan('profile-plan', target, 'a' * 64, 'before', 'native', 1,
            'authorization', 'secret', (now + timedelta(minutes=5)).isoformat())
        # Both consumers use the existing C4 journal path; no effect is run.
        profile_journal = OperationJournal(authority.services.journal_path)
        profile_journal.register_plan('profile-consumer', before)
        pending = profile_journal.reserve('profile-consumer', before.plan_id,
            'profile-unknown', FenceObservation.from_plan(before), now=now)
        assert pending.result.kind == 'unknown'
        runtime.plugin_host.deactivate('ordessa.skills')
        runtime.plugin_host.deactivate('ordessa.profile')
        current = runtime.plugin_host.provided_port('native.configuration')
        assert current is authority
        assert current.register_native(connection_id='connection', native_session_id='native-session').target == target
        model_journal = OperationJournal(current.services.journal_path)
        choice = replace(before, plan_id='model-plan')
        model_journal.register_plan('model-consumer', choice)
        refused = model_journal.reserve('model-consumer', choice.plan_id,
            'model-switch', FenceObservation.from_plan(choice), now=now)
        assert isinstance(refused, Refused) and refused.code is ErrorCode.BUSY
        assert model_journal.reconcile('profile-consumer', target, 'profile-unknown') == pending.result
    finally:
        runtime.stop()

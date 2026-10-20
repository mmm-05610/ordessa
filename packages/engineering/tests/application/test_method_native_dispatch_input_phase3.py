"""Original Unit session + transparent method recipe scope.

The task reader is an explicit controlled peer, qualified separately on real
SQLite MethodRun/package state. This file qualifies native session formation
and per-cut forwarding, not a production method, Grant or model call.
"""
from dataclasses import replace
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_local_dispatch_bindings_phase3 import (
    assembled_live_owner, _grant_dispatch_to_the_same_local_authority,
)

from ordessa_engineering.adapters.native_records import (
    build_local_dispatch_bindings, build_local_method_dispatch_inputs,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess

pytest_plugins = ('test_local_owner',)


def test_prepare_uses_returned_unit_session_and_forwards_exact_recipe(
        assembled_live_owner, monkeypatch):
    world = assembled_live_owner
    owner = world.owner
    unit = owner.manager.create(owner.spec, owner.authorization())
    creates = []
    monkeypatch.setattr(owner.manager, 'create', lambda *args, **kwargs: creates.append(1))
    from ordessa_engineering.adapters.native_records import method_inputs
    calls = []

    def read_task(context, **identity):
        calls.append(identity)
        return {'task_text': 'controlled method task',
                'actions': ['edit_repository', 'run_checks'], 'timeout': 30}

    monkeypatch.setattr(method_inputs, 'build_method_dispatch_inputs',
                        lambda *_: SimpleNamespace(read_task=read_task))
    access = EngineeringCommandAccess(world.access)
    producer = build_local_method_dispatch_inputs(object(), object(), owner, access)
    caller = world.access.authenticate('Bearer ' + __import__('test_local_owner').BEARER)
    with access.admit(caller, Scope('env', 'project'), EXECUTION_DISPATCH,
                      request_id='native-method-prepare', trace_id='native-method-prepare') as context:
        recipe = producer.prepare(context, run_id='controlled-run',
                                  step_id='dispatch', attempt=1, unit_ref=unit.identity)
        assert recipe['params'] == {
            'sessionId': unit.snapshot()['sessionId'],
            'prompt': [{'type': 'text', 'text': 'controlled method task'}]}
        assert set(recipe) == {'run_id', 'step_id', 'attempt', 'unit_ref', 'params', 'actions', 'timeout'}
        assert calls == [{'run_id': 'controlled-run', 'step_id': 'dispatch', 'attempt': 1}]
        helpers = runpy.run_path(str(Path(__file__).parents[1]
                                     / 'domain/test_implementation_package_binding.py'))
        helpers['_records'].__globals__['SCOPE'] = context.scope
        package = helpers['_records']()[2]
        package = replace(package, payload=replace(package.payload,
            execution_profile_ref=EnvironmentRef(
                owner.permission.profile_revision.environment_namespace,
                owner.permission.profile_revision.profile_id,
                Digest('sha256', owner.permission.profile_revision.digest.removeprefix('sha256:')))))
        selection, sources, _query = build_local_dispatch_bindings(
            owner, access, prompt_parameters=producer.prompt_parameters)
        with sources.guard_dispatch_input(context, package, unit.identity, recipe):
            assert producer.prompt_parameters(context, package, unit.identity, recipe) is recipe['params']
            with selection.guard_selection(context, package, unit.identity):
                pass
            with sources.guard_commit_snapshot(context, package, unit.identity):
                pass
        # Source scope is reset; it cannot silently reuse a previous run's input.
        with pytest.raises(ApplicationError, match='DISPATCH_METHOD_INPUT_SOURCE_UNAVAILABLE'):
            with sources.guard_commit_snapshot(context, package, unit.identity):
                pytest.fail('unscoped method input reused')
        assert creates == []


def test_prepare_unknown_unit_ref_refuses_before_task_read(
        assembled_live_owner, monkeypatch):
    world = assembled_live_owner
    from ordessa_engineering.adapters.native_records import method_inputs
    calls = []
    monkeypatch.setattr(method_inputs, 'build_method_dispatch_inputs',
                        lambda *_: SimpleNamespace(read_task=lambda *_args, **_kwargs: calls.append(1)))
    access = EngineeringCommandAccess(world.access)
    producer = build_local_method_dispatch_inputs(object(), object(), world.owner, access)
    caller = world.access.authenticate('Bearer ' + __import__('test_local_owner').BEARER)
    with access.admit(caller, Scope('env', 'project'), EXECUTION_DISPATCH,
                      request_id='native-method-unknown', trace_id='native-method-unknown') as context:
        with pytest.raises(ApplicationError, match='RECORDED_DISPATCH_FIXED_SESSION_UNAVAILABLE'):
            producer.prepare(context, run_id='controlled-run', step_id='dispatch',
                             attempt=1, unit_ref={'environmentNamespace': 'env', 'unitId': 'unknown',
                                 'ownerProviderRef': {'provider': 'unknown'}, 'sourceRevision': 'unknown'})
    assert calls == []

"""Real current MethodRun must pass before any native input or blob is frozen."""
from types import SimpleNamespace

import pytest
from test_method_dispatch_inputs_phase3 import dispatch_task_world, env
from test_review_usecases import _context

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch


def test_waiting_run_refuses_dispatch_before_native_input_or_blob_write(dispatch_task_world):
    world = dispatch_task_world
    e = world['env']
    calls = []
    owner = ImplementationDispatch(e['factory'], e['access'], method_runs=e['bindings'],
        execution=SimpleNamespace(freeze_input=lambda *_: calls.append('freeze')),
        selection=SimpleNamespace(guard_selection=lambda *_: calls.append('selection')),
        blobs=SimpleNamespace(authority_id=e['factory'].authority_id,
                              put_verified=lambda *_: calls.append('blob')))
    with pytest.raises(ApplicationError, match='DISPATCH_WORK_STEP_UNAVAILABLE'):
        owner.dispatch('dispatch-task-run', 'dispatch', 1,
            {'environmentNamespace': 'controlled', 'unitId': 'controlled',
             'ownerProviderRef': {'provider': 'controlled'}, 'sourceRevision': '1'},
            {'prompt': [{'type': 'text', 'text': world['task']['task_text']}],
             'sessionId': 'controlled-native-session'},
            ('edit_repository', 'run_checks'), _context(e['scope'], 'dispatch-before-wait-resume'),
            timeout=30)
    assert calls == []

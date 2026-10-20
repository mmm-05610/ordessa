"""Original running-node recipe checks with controlled external package material.

The public start and its journal are real. The start source and package backing
closure are controlled peers; no dispatch, Grant or business acceptance is
claimed by this read-only recipe check.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json

import pytest
from test_method_dispatch_inputs_phase3 import dispatch_task_world, env, _method_source
from test_method_work import call, query
from test_review_usecases import _context

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WorkSeed, WorkWaitSelection
from ordessa_engineering.application.contracts.run_waits import BoundRunWait
from ordessa_engineering.application.orchestration.dispatch_inputs import render_dispatch_task
from ordessa_engineering.application.orchestration.dispatch_recipe import check_dispatch_recipe
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import load_method, compile_method
from ordessa_engineering.methods.definitions.models import MethodSource


@pytest.fixture
def running_recipe(dispatch_task_world, tmp_path):
    world = dispatch_task_world
    e = world['env']
    root = tmp_path / 'direct-dispatch-method'
    root.mkdir()
    _unused, capabilities, _schema = _method_source(root)
    path = root / 'workflow.yaml'
    workflow = json.loads(path.read_text())
    path.write_text(json.dumps(workflow, separators=(',', ':')))
    path = root / 'method.yaml'
    manifest = json.loads(path.read_text())
    manifest['release_version'] = '1.0.1'
    resource = next(r for r in manifest['resources'] if r['kind'] == 'workflow')
    resource['sha256'] = hashlib.sha256((root / resource['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest, separators=(',', ':')))
    loaded = load_method(MethodSource(root), reader=FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, capabilities, 'controlled:direct-dispatch')
    assert compiled.ok, compiled.error
    published = freeze_method(compiled.value, e['store'], e['store'],
        capability_catalog=type('Catalog', (), {'read_current': lambda _self: capabilities})())
    assert published.ok, published.error
    ref = published.value.ref
    method = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                       Digest('sha256', ref.snapshot_digest))
    e['management'].adopt(method, _context(e['scope'], 'adopt-direct-dispatch'), expected_version=2)
    snapshot = e['store'].get(ref)
    package = replace(world['package'], package_id='direct-dispatch-package',
                      payload=replace(world['package'].payload, method_ref=method))
    with e['factory'].begin(e['scope']) as uow:
        package_ref = uow.implementation.create_package(package)
        uow.commit()
    node = next(n for n in snapshot.program.workflow.steps if n.id == 'dispatch')
    task = render_dispatch_task(snapshot, package, node,
        run_id='direct-dispatch-run', step_id='dispatch', attempt=1,
        blobs=world['blobs'], resource_reader=e['store'])
    request = {'run_id': 'direct-dispatch-run', 'step_id': 'dispatch', 'attempt': 1,
        'unit_ref': {'environmentNamespace': 'controlled', 'unitId': 'controlled',
                     'ownerProviderRef': {'provider': 'controlled'}, 'sourceRevision': '1'},
        'params': {'prompt': [{'type': 'text', 'text': task['task_text']}],
                   'sessionId': 'controlled-native-session'},
        'actions': task['actions'], 'timeout': task['timeout']}

    @contextmanager
    def start_source(context, snapshot_arg, *, run_id, selection):
        assert run_id == request['run_id'] and selection is None
        yield WorkSeed({'package_ref': asdict(package_ref), 'dispatch_input': request,
                       'work_inputs': asdict(world['work_ref'])}, e['source'].start_reads)

    e['source'].guard_start = start_source

    @contextmanager
    def condition_source(context, snapshot_arg, node_arg, view):
        condition = BoundRunWait(e['scope'], view['run_id'], view['row_digest'],
            view['next_step_ordinal'], 'object_exists', (world['work_ref'],))
        yield WorkWaitSelection(condition, {})

    e['source'].guard_condition = condition_source
    result = call(e, 'engineering.work.start', {'run_id': request['run_id']}, 'start-direct-dispatch')
    assert result.status == 'completed'
    ready = query(e, 'engineering.work.current_condition', {'run_id': request['run_id']})
    assert ready['ready'] is True
    resumed = call(e, 'engineering.runs.resume', {
        'run_id': request['run_id'], 'expected_row_digest': ready['row_digest'],
        'expected_condition_digest': ready['condition_digest'],
        'expected_next_step_ordinal': ready['next_step_ordinal']}, 'resume-direct-dispatch')
    assert resumed.status == 'completed' and resumed.result['status'] == 'RUNNING'
    return e, package, request


def test_exact_running_recipe_and_frozen_task_match(running_recipe):
    e, package, request = running_recipe
    with e['factory'].begin(e['scope'], 'read') as uow:
        assert check_dispatch_recipe(uow, e['bindings'], package, request) == request


def test_changed_native_request_is_refused(running_recipe):
    e, package, request = running_recipe
    changed = {**request, 'params': {**request['params'],
                                   'prompt': [{'type': 'text', 'text': 'caller replacement'}]}}
    with e['factory'].begin(e['scope'], 'read') as uow:
        with pytest.raises(ApplicationError, match='DISPATCH_METHOD_INPUT_CHANGED'):
            check_dispatch_recipe(uow, e['bindings'], package, changed)

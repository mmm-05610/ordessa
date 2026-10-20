"""Pinned check composition refuses source drift before any Unit or command."""
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path

import pytest
from ordessa_units.api import UnitApiRefused

PATH = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/local_library_check_runtime.py'
SPEC = importlib.util.spec_from_file_location('local_library_check_runtime', PATH)
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


@pytest.fixture
def selected(tmp_path):
    runtime = tmp_path / 'runtime'
    (runtime / 'bin').mkdir(parents=True)
    python = runtime / 'bin/python'
    python.write_text('controlled interpreter artifact')
    cfg = runtime / 'pyvenv.cfg'
    cfg.write_text('controlled isolated configuration')
    script = tmp_path / 'runner.py'
    script.write_text('controlled runner')
    project = tmp_path / 'project with spaces'
    project.mkdir()
    @contextmanager
    def scope(**request):
        yield
    return dict(python_executable=python, runner=script, project_root=project,
        pinned_files={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (python,cfg,script,Path('/usr/bin/env').resolve())},
        runtime_tree_digest=producer.catalog_runtime_digest(runtime),
        allowed_paths=(str(project/'catalog/views.py'),), scope_guard=scope)


def test_fixed_argv_is_quoted_clears_environment_and_has_no_caller_arguments(selected):
    import shlex
    command, _, verify = producer.fixed_catalog_check(**selected)
    assert shlex.split(command) == ['/usr/bin/env','-i','PATH=/usr/bin:/bin',str(selected['python_executable']),
        '-I','-B',str(selected['runner']),'--project-root',str(selected['project_root'])]
    assert verify() is True


@pytest.mark.parametrize('changed', ['runner','python_executable'])
def test_runner_or_interpreter_drift_refuses_before_factory_or_dispatch(selected, changed):
    _, callback_factory, verify = producer.fixed_catalog_check(**selected)
    selected[changed].write_text('changed artifact')
    with pytest.raises(UnitApiRefused, match='changed'):
        verify()
    with pytest.raises(UnitApiRefused, match='changed'):
        callback_factory()


def test_new_runtime_startup_source_is_also_drift(selected):
    _, _, verify = producer.fixed_catalog_check(**selected)
    (selected['python_executable'].parent.parent / 'sitecustomize.py').write_text('injected')
    with pytest.raises(UnitApiRefused, match='selection changed'):
        verify()


def test_missing_interpreter_or_runtime_pin_and_missing_scope_are_refused(selected):
    missing = dict(selected['pinned_files'])
    missing.pop(str(selected['python_executable']))
    with pytest.raises(UnitApiRefused, match='must be pinned'):
        producer.fixed_catalog_check(**{**selected,'pinned_files':missing})
    with pytest.raises(UnitApiRefused, match='original Work scope'):
        producer.fixed_catalog_check(**{**selected,'scope_guard':None})

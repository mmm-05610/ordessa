"""Recovered Local Library check runtime stays pinned, isolated and memory-only.

Environment-specific to this machine: it reads the recovery records kept in
``.nightly-cache/local-library-runtime-20261017{,-recovery}/`` (gitignored) and
the demo project at ``/home/maoqh/projects/ordessa-demo-local-library``. It is
not collected by the default suites; run it explicitly with the nightly venv:

    .venv-nightly/bin/python -m pytest \
        tooling/checks/server_product/test_local_library_runtime_recovery.py -q

Missing records are a real failure of this recovery, never a skip: the point of
the file is that the pin can be reproduced and that the same pins refuse drift.
It never starts a Unit, a model, the demo's server or a disk-backed database.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
import shlex
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[3]
PRODUCER_PATH = REPO / 'tooling/checks/server_product/local_library_check_runtime.py'
RUNNER_PATH = REPO / 'tooling/checks/server_product/local_library_catalog_check_runner.py'
RUNTIME = REPO / '.nightly-cache/local-library-runtime-20261017'
RECORDS = REPO / '.nightly-cache/local-library-runtime-20261017-recovery'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(path: Path) -> Path:
    if not path.exists():
        raise AssertionError(f'recovered runtime artifact missing: {path}; re-run the D3-runtime recovery before reusing the pin')
    return path


@pytest.fixture(scope='module')
def records():
    identity = json.loads(_require(RECORDS / 'identity.json').read_text())
    candidate = json.loads(_require(RECORDS / 'configuration-candidate.json').read_text())
    receipt = json.loads(_require(RECORDS / 'receipt.json').read_text())
    return {'identity': identity, 'candidate': candidate, 'receipt': receipt}


@pytest.fixture(scope='module')
def producer():
    return _load('local_library_check_runtime', _require(PRODUCER_PATH))


@pytest.fixture(scope='module')
def runner():
    return _load('local_library_catalog_check_runner', _require(RUNNER_PATH))


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _venv_python(*args: str) -> str:
    completed = subprocess.run(
        [str(RUNTIME / 'bin/python'), '-I', '-B', *args],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def test_runtime_is_persistent_inside_the_repository(records):
    identity = records['identity']
    assert RUNTIME.is_dir()
    assert RUNTIME.resolve().is_relative_to(REPO), 'the check runtime must persist inside the worktree, not /tmp'
    assert Path(identity['venv']['root']) == RUNTIME
    assert (RUNTIME / 'bin/python').resolve() == Path(identity['venv']['resolved_python'])
    assert _sha256(Path(identity['base_interpreter']['path'])) == identity['base_interpreter']['sha256']


def test_pinned_artifacts_still_match_the_recorded_hashes(records):
    pinned = records['candidate']['pinned_files']
    assert pinned, 'a candidate without pins proves nothing'
    for path, digest in pinned.items():
        target = Path(path)
        assert target.is_file(), f'pinned artifact disappeared: {path}'
        assert target.resolve() == target, f'pinned artifact became a symlink target or moved: {path}'
        assert _sha256(target) == digest, f'pinned artifact drifted: {path}'
    assert str(RUNNER_PATH.resolve()) in pinned
    assert str(RUNTIME / 'pyvenv.cfg') in pinned


def test_runtime_tree_digest_is_reproducible(records, producer):
    assert producer.catalog_runtime_digest(RUNTIME) == records['candidate']['runtime_tree_digest']
    assert records['candidate']['runtime_tree_digest'] == records['identity']['runtime_tree_digest']


def test_producer_accepts_the_candidate_and_refuses_broken_pins(records, producer):
    candidate = records['candidate']

    @contextmanager
    def scope(**request):
        yield

    selected = dict(
        python_executable=Path(candidate['python_executable']),
        runner=Path(candidate['runner']),
        project_root=Path(candidate['project_root']),
        pinned_files=candidate['pinned_files'],
        runtime_tree_digest=candidate['runtime_tree_digest'],
        allowed_paths=tuple(candidate['allowed_paths']),
        scope_guard=scope,
    )
    command, callback_factory, verify = producer.fixed_catalog_check(**selected)
    assert shlex.split(command) == [
        '/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', candidate['python_executable'],
        '-I', '-B', candidate['runner'], '--project-root', candidate['project_root'],
    ]
    assert verify() is True
    assert callable(callback_factory), 'the check command must still travel with its guarded callback factory'

    without_interpreter = {path: digest for path, digest in candidate['pinned_files'].items()
                           if path != records['identity']['base_interpreter']['path']}
    with pytest.raises(Exception):
        producer.fixed_catalog_check(**{**selected, 'pinned_files': without_interpreter})

    with pytest.raises(Exception):
        producer.fixed_catalog_check(**{**selected, 'pinned_files': {path: ('0' * 64) for path in candidate['pinned_files']}})

    with pytest.raises(Exception):
        producer.fixed_catalog_check(**{**selected, 'runtime_tree_digest': '0' * 64})


def test_venv_identity_matches_the_recorded_dependencies(records):
    identity = records['identity']
    cfg = (RUNTIME / 'pyvenv.cfg').read_text()
    assert 'include-system-site-packages = false' in cfg, 'the check runtime must not inherit the host site-packages'

    installed = json.loads(_venv_python(
        '-c', 'import importlib.metadata as md, json; '
              'print(json.dumps(sorted([[d.metadata["Name"], d.version] for d in md.distributions()])))'))
    assert installed == identity['installed_distributions']
    assert _venv_python('-c', 'import django; print(django.get_version())') == identity['django_version']


def test_runner_keeps_memory_only_sqlite_guards(runner):
    assert runner.sqlite_target_is_memory(':memory:') is True
    assert runner.sqlite_target_is_memory('file:memdb1?mode=memory&cache=shared', uri=True) is True
    assert runner.sqlite_target_is_memory('/tmp/catalog.sqlite3') is False
    assert runner.sqlite_target_is_memory('file:/tmp/catalog.sqlite3', uri=True) is False
    assert runner.sqlite_target_is_memory('file:memdb1?mode=memory&mode=memory', uri=True) is False
    assert runner.TEST_LABELS == ('catalog.tests',), 'the runner must stay bounded to the demo catalog tests'


def test_recorded_controlled_run_receipt_is_self_consistent(records):
    receipt = records['receipt']
    candidate = records['candidate']
    assert receipt['work_order'] == 'D3-runtime'
    assert receipt['exit_code'] == 0
    assert receipt['argv'][3] == candidate['python_executable']
    assert receipt['argv'][6] == candidate['runner']
    assert receipt['argv'][-1] == candidate['project_root']
    assert receipt['report']['testsRun'] == 40
    assert receipt['report']['failures'] == receipt['report']['errors'] == receipt['report']['skipped'] == 0
    assert receipt['report']['unittest_was_successful'] is True
    assert receipt['guard_evidence']['allowed_sqlite_targets'] == ['file:<memory>?mode=memory']
    assert receipt['guard_evidence']['product_settings_imported'] is False
    assert receipt['guard_evidence']['dotenv_imported'] is False
    assert receipt['zero_effects']['models'] == 0
    assert receipt['zero_effects']['new_units'] == 0

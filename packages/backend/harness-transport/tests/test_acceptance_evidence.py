"""Failure receipts for own-package installer; controlled faults, no native IO."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


def helper():
    path = Path(__file__).with_name('acceptance_install.py')
    spec = importlib.util.spec_from_file_location('controlled_install_acceptance', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_existing_receipt_refuses_before_any_command(tmp_path, monkeypatch):
    module = helper()
    evidence = tmp_path / 'existing.json'; evidence.write_bytes(b'original receipt\n')
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: pytest.fail('no command'))
    with pytest.raises(FileExistsError): module.exercise(evidence)
    assert evidence.read_bytes() == b'original receipt\n'


def test_real_broken_own_package_build_preserves_failure_command(tmp_path, monkeypatch):
    module = helper()
    project = tmp_path / 'broken'; project.mkdir(); (project / 'src').mkdir()
    (project / 'pyproject.toml').write_text('[build-system]\nrequires = []\nbuild-backend = "controlled_absent_backend"\n')
    monkeypatch.setattr(module, 'PROJECTS', (str(project),))
    evidence = tmp_path / 'failed.json'
    with pytest.raises(RuntimeError, match="controlled_absent_backend"): module.exercise(evidence)
    record = json.loads(evidence.read_text())
    assert record['status'] == 'failed' and record['failureType'] == 'RuntimeError'
    assert record['evidenceLevel'] == 'failedLocalDistributionAttempt'
    assert len(record['records']) == 1 and record['records'][0]['exitCode'] != 0
    assert record['temporaryEnvironmentRemoved'] and not record['productReady']
    assert record['modelCalls'] == 0 and record['wheelSha256'] == {}


def test_injected_build_timeout_records_unknown_exit_and_cleans(tmp_path, monkeypatch):
    module = helper()
    monkeypatch.setattr(module, 'PROJECTS', ('packages/backend/environment-api',))
    original_run = module.subprocess.run
    def timeout(command, **kwargs):
        if command[0] == 'git': return original_run(command, **kwargs)
        raise subprocess.TimeoutExpired(command, 90)
    monkeypatch.setattr(module.subprocess, 'run', timeout)
    evidence = tmp_path / 'timeout.json'
    with pytest.raises(subprocess.TimeoutExpired): module.exercise(evidence)
    record = json.loads(evidence.read_text())
    assert record['status'] == 'failed' and record['failureType'] == 'TimeoutExpired'
    assert len(record['records']) == 1
    assert record['records'][0]['exitCode'] is None and record['records'][0]['timedOut'] is True
    assert record['temporaryEnvironmentRemoved'] and not record['productReady']
    assert record['nativeHarnessProcesses'] == 0

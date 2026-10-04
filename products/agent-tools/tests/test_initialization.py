"""Real filesystem observations: fixture executables must never run."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from ordessa_agent_tools import cli, initialization
from ordessa_agent_tools.client import ClientError


def document():
    value = {'catalogVersion': 'harness-command-discovery/1', 'candidates': [{'familyId': 'fixture', 'commands': ['fixture-cmd']}]}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'catalog': value, 'catalogDigest': 'sha256:' + digest}


@pytest.fixture
def candidates(monkeypatch):
    monkeypatch.setattr(initialization, 'catalog', document)
    def no_service(*args, **kwargs):
        raise AssertionError('init must not contact a service')
    monkeypatch.setattr(cli, 'WireClient', no_service)


def executable(path, marker):
    path.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
    path.chmod(0o700)


def test_real_executable_without_execution_or_service(tmp_path, candidates, capsys):
    marker = tmp_path / 'must-not-exist'
    executable(tmp_path / 'fixture-cmd', marker)
    assert cli.main(['init', '--path', str(tmp_path), '--json']) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope['serviceRef'] is None
    assert envelope['evidence']['executedBinaries'] is False
    item = envelope['data']['harnesses'][0]
    assert item['status'] == 'executableFound'
    assert item['runtimeReady'] == 'unknown'
    assert item['providerAdmission'] == 'notChecked'
    assert item['commands'][0]['matches'][0]['resolvedPath'] == str(tmp_path / 'fixture-cmd')
    assert not marker.exists()


def test_no_resource_not_green(tmp_path, candidates, capsys):
    assert cli.main(['init', '--path', str(tmp_path), '--json']) == 4
    envelope = json.loads(capsys.readouterr().out)
    assert envelope['data']['foundFamilies'] == []
    assert envelope['error']['code'] == 'HARNESS_EXECUTABLES_NOT_FOUND'


def test_relative_and_empty_path_dont_search_cwd(tmp_path, candidates, monkeypatch):
    executable(tmp_path / 'fixture-cmd', tmp_path / 'marker')
    monkeypatch.chdir(tmp_path)
    result = initialization.discover(os.pathsep.join(['', '.', 'relative']))
    assert result['ignoredRelativeOrEmptyPathEntries'] == 3
    assert result['foundFamilies'] == []


def test_shadowing_paths_preserved(tmp_path, candidates):
    first, second = tmp_path / 'one', tmp_path / 'two'
    first.mkdir(); second.mkdir()
    for directory in (first, second):
        executable(directory / 'fixture-cmd', tmp_path / 'marker')
    result = initialization.discover(os.pathsep.join([str(first), str(second), str(first)]))
    assert [x['path'] for x in result['harnesses'][0]['commands'][0]['matches']] == [str(first / 'fixture-cmd'), str(second / 'fixture-cmd')]


@pytest.mark.parametrize('kind', ['directory', 'fifo', 'no-execute', 'broken-link', 'loop-link'])
def test_invalid_binary_not_usable(tmp_path, candidates, kind):
    path = tmp_path / 'fixture-cmd'
    if kind == 'directory': path.mkdir()
    elif kind == 'fifo': os.mkfifo(path)
    elif kind == 'no-execute': path.write_text('data'); path.chmod(0o600)
    elif kind == 'broken-link': path.symlink_to(tmp_path / 'absent')
    else: path.symlink_to(path)
    result = initialization.discover(str(tmp_path))
    observed = result['harnesses'][0]['commands'][0]
    assert not observed['matches']
    assert observed['issues']
    assert not result['foundFamilies']


def test_valid_symlink_is_only_observation(tmp_path, candidates):
    executable(tmp_path / 'real', tmp_path / 'marker')
    (tmp_path / 'fixture-cmd').symlink_to(tmp_path / 'real')
    observed = initialization.discover(str(tmp_path))['harnesses'][0]['commands'][0]['matches'][0]
    assert observed['isSymlink'] and observed['resolvedPath'] == str(tmp_path / 'real')


def test_permission_error_is_unknown_not_absence(tmp_path, candidates, monkeypatch):
    original = Path.stat
    def denied(path, *args, **kwargs):
        if path.name == 'fixture-cmd': raise PermissionError('private detail')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', denied)
    result = initialization.discover(str(tmp_path))
    assert result['harnesses'][0]['status'] == 'scanUnavailable'
    assert 'private detail' not in json.dumps(result)


def test_report_explicit_new_file_only(tmp_path, candidates, capsys):
    executable(tmp_path / 'fixture-cmd', tmp_path / 'marker')
    report = tmp_path / 'report.json'
    args = ['init', '--path', str(tmp_path), '--json', '--output', str(report)]
    assert cli.main(args) == 0
    first = report.read_bytes()
    assert json.loads(first)['data']['scanScope'] == 'clientMachine'
    assert report.stat().st_mode & 0o777 == 0o600
    capsys.readouterr()
    assert cli.main(args) == 2
    assert report.read_bytes() == first
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'INIT_REPORT_REFUSED'


def test_oversized_path_refused(candidates):
    with pytest.raises(ClientError): initialization.discover('x' * 32769)


@pytest.mark.parametrize('corruption', ['missing', 'digest', 'duplicate', 'extra', 'unsafe-command'])
def test_catalog_no_fallback(tmp_path, monkeypatch, corruption):
    data = document()
    if corruption == 'digest': data['catalogDigest'] = 'sha256:' + '0' * 64
    elif corruption == 'duplicate': data['catalog']['candidates'] *= 2
    elif corruption == 'extra': data['catalog']['candidates'][0]['unknown'] = True
    elif corruption == 'unsafe-command': data['catalog']['candidates'][0]['commands'] = ['x;touch marker']
    if corruption not in {'digest', 'missing'}:
        encoded = json.dumps(data['catalog'], sort_keys=True, separators=(',', ':')).encode()
        data['catalogDigest'] = 'sha256:' + hashlib.sha256(encoded).hexdigest()
    if corruption != 'missing': (tmp_path / 'harness_commands.json').write_text(json.dumps(data))
    monkeypatch.setattr(initialization.resources, 'files', lambda name: tmp_path)
    with pytest.raises(ClientError) as error: initialization.catalog()
    assert error.value.code == 'HARNESS_CATALOG_UNAVAILABLE'


def test_found_path_does_not_hide_inaccessible_shadow(tmp_path, candidates, monkeypatch):
    first, blocked = tmp_path / 'first', tmp_path / 'blocked'
    first.mkdir(); blocked.mkdir()
    executable(first / 'fixture-cmd', tmp_path / 'marker')
    original = Path.stat
    def denied(path, *args, **kwargs):
        if path.parent == blocked: raise PermissionError('private detail')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', denied)
    result = initialization.discover(os.pathsep.join([str(first), str(blocked)]))
    assert result['foundFamilies'] == ['fixture']
    assert result['scanCompleteForSearchedEntries'] is False


def test_lstat_permission_change_is_typed_diagnostic(tmp_path, candidates, monkeypatch, capsys):
    original = Path.is_symlink
    def denied(path):
        if path.name == 'fixture-cmd': raise PermissionError('private detail')
        return original(path)
    monkeypatch.setattr(Path, 'is_symlink', denied)
    assert cli.main(['init', '--path', str(tmp_path), '--json']) == 4
    envelope = json.loads(capsys.readouterr().out)
    assert envelope['error']['code'] == 'HARNESS_DISCOVERY_INCOMPLETE'
    assert envelope['data']['harnesses'][0]['status'] == 'scanUnavailable'
    assert 'private detail' not in json.dumps(envelope)

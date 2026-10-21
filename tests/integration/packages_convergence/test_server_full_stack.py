"""One Server process, three capability groups, one client (source+installed assembly).

This is the durable form of the manual full-stack smoke: it starts the real
`ordessa-server` console script from the environment running the tests, waits for
the listening handshake, then drives `agents` / `environments` / `decisions`
through the real `ordessa` client. No model is called and no fixture owner is
injected: the Server composes itself from zero configuration.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _server_script(name: str) -> Path:
    candidate = Path(sys.executable).with_name(name)
    if not candidate.is_file():
        pytest.skip(f"{name} console script is not installed in this interpreter")
    return candidate


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _run(args, *, timeout=120):
    return subprocess.run([str(item) for item in args], capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, 'PYTHONNOUSERSITE': '1'})


def _envelope(result):
    assert result.returncode == 0, (result.stdout, result.stderr)
    value = json.loads(result.stdout)
    assert value['status'] == 'completed', value
    return value['data']


@pytest.fixture()
def server(tmp_path):
    root = tmp_path / 'root'
    port = _free_port()
    process = subprocess.Popen(
        [str(_server_script('ordessa-server')), '--data-root', str(root), '--port', str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.time() + 30
        handshake = None
        while time.time() < deadline:
            line = process.stdout.readline()
            if '"listening"' in line:
                handshake = json.loads(line)
                break
        assert handshake is not None, process.stderr.read()
        token = root / 'secrets' / 'http-token'
        assert token.is_file() and (token.stat().st_mode & 0o777) == 0o600
        config = tmp_path / 'client.json'
        config.write_text(json.dumps({'services': {'local': {
            'endpoint': handshake['origin'], 'tokenFile': str(token)}}}))
        config.chmod(0o600)
        yield tmp_path, ['--config', str(config), '--service', 'local'], Path(handshake['origin'])
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_three_capability_groups_serve_one_process(server):
    workspace, mode, origin = server
    ordessa = _server_script('ordessa')

    harnesses = _envelope(_run([ordessa, *mode, 'agents', 'harness', 'list', '--json']))['harnesses']
    assert {item['providerId'] for item in harnesses} >= {'kilo', 'pi'}

    manifest = workspace / 'manifest.json'
    manifest.write_text(json.dumps({
        'schemaVersion': 'profile-content/1',
        'harnessDefinitionRef': {'environmentNamespace': 'server',
                                 'definitionId': harnesses[0]['providerId'],
                                 'revision': harnesses[0]['definitionRef']['revision']},
        'declarations': []}))
    created = _envelope(_run([ordessa, *mode, 'agents', 'profiles', 'create', 'demo',
                              '--name', 'Demo', '--manifest', str(manifest), '--json']))
    assert created['catalogRevision'] == 1

    work = workspace / 'work'
    environment = _envelope(_run([ordessa, *mode, 'environments', 'create', 'local',
                                  '--root', str(work), '--json']))
    request = workspace / 'exec.json'
    request.write_text(json.dumps({'reference': environment['identity'],
                                   'argv': ['echo', 'full-stack-ok']}))
    executed = _envelope(_run([ordessa, *mode, 'call', 'environments.exec',
                               '--input', str(request), '--json']))
    assert executed['stdout'] == 'full-stack-ok\n' and executed['exitCode'] == 0

    job = workspace / 'job.json'
    job.write_text(json.dumps({
        'spec_version': 'decision-job/1', 'job_id': 'full-stack', 'version': 1,
        'input': {'score': 7},
        'limits': {'max_model_calls': 0, 'max_steps': 4,
                   'max_value_bytes': 4096, 'timeout_seconds': 5.0},
        'steps': [{'id': 'gate', 'type': 'rules', 'engine': None,
                   'when': {'fact': 'input.score', 'op': 'gte', 'value': 1},
                   'payload': {'checks': [{'id': 'high', 'when': 'input.score >= 5'}],
                               'default': {'answer': 'accept'}}}],
        'result': {'from': 'gate', 'path': ['values', 'default']}}))
    decided = _envelope(_run([ordessa, *mode, 'decisions', 'run', '--job', str(job),
                              '--request-id', 'full-stack-1', '--json']))
    assert decided['result'] == {'answer': 'accept'}

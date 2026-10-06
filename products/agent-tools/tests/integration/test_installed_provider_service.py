"""Fresh client wheel + actual isolated Server process, no native/model calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from test_profile_service import IsolatedService


def test_installed_cli_observes_three_independent_server_providers(tmp_path):
    product = Path(__file__).resolve().parents[2]
    source = tmp_path / 'client-source'; source.mkdir()
    shutil.copy2(product / 'pyproject.toml', source / 'pyproject.toml')
    shutil.copytree(product / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
    wheels = tmp_path / 'wheels'
    build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation',
        '--no-deps', '--wheel-dir', str(wheels), str(source)], capture_output=True, text=True, timeout=60)
    assert build.returncode == 0, build.stdout + build.stderr
    artifacts = list(wheels.glob('ordessa_agent_tools-*.whl')); assert len(artifacts) == 1
    isolated = tmp_path / 'client'
    created = subprocess.run([sys.executable, '-m', 'venv', str(isolated)], capture_output=True, text=True, timeout=60)
    assert created.returncode == 0, created.stderr
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    python = isolated / 'bin/python'
    install = subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(artifacts[0])],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert install.returncode == 0, install.stdout + install.stderr
    missing = subprocess.run([str(python), '-I', '-c', '''import importlib.util
assert all(importlib.util.find_spec(name) is None for name in (
    'pacthold', 'ordessa_server', 'ordessa_harness', 'ordessa_harness_codex',
    'ordessa_harness_pi', 'ordessa_harness_claude_code', 'server_plugin_api', 'claude_agent_sdk'))'''],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert missing.returncode == 0, missing.stdout + missing.stderr
    service = IsolatedService(tmp_path, version='agent-assembly/3', providers=True,
        cli_executable=isolated / 'bin/ordessa-agent')
    try:
        service.start()
        listed = service.cli(['providers', 'list'])
        assert listed['evidence'] == {'level': 'providerRegistryObserved', 'runtimeVerified': False}
        views = listed['data']['providers']
        assert {row['providerRef']['providerId'] for row in views} == {'codex', 'pi', 'claude'}
        assert len(views) == 3
        for row in views:
            assert 'start' not in row['descriptor']['supportedMethods']
            assert row['providerRef']['ownerActivationRef']['pluginId'] in {'codex', 'pi', 'claude-code'}
            ref = row['descriptor']['definitionRef']
            assert ref['environmentNamespace'] == service.identity
            described = service.cli(['providers', 'describe', json.dumps(ref)])
            assert described['data'] == row
            assert described['evidence']['runtimeVerified'] is False
        denied = service.cli(['providers', 'list'], expected=3, token='invalid-test-token')
        assert denied['error']['code'] == 'AUTHORIZATION_REFUSED'
        foreign = dict(views[0]['descriptor']['definitionRef'], environmentNamespace='foreign')
        refused = service.cli(['providers', 'describe', json.dumps(foreign)], expected=2)
        assert refused['error']['code'] == 'PARAMETER_INVALID'
        capabilities = service.cli(['capabilities'])['data']['coreAgent']
        assert capabilities['supports']['nodePreparation'] is False
        assert capabilities['supports']['configurationManagement'] is False
    finally:
        service.stop()
    assert service.process is None
    offline = service.cli(['providers', 'list'], expected=4)
    assert offline['status'] == 'refused' and offline['evidence'] == {'level': 'unobserved'}

"""Actual wheel metadata: no old automatic registration for migrated families.

Explicit legacy factories/Server composition remain separate migration work.
This gate does not claim removal of those consumers or native product readiness.
"""
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[5]
MIGRATED = {'codex', 'claude', 'claude-code', 'pi'}
FACTORIES = ('create_codex', 'create_claude', 'create_pi')


def retired_discovery_is_absent(metadata):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(metadata)
    return all(name not in MIGRATED and not any(
        value.split('[', 1)[0].strip().endswith(':' + factory) for factory in FACTORIES)
        for section in parser.sections() for name, value in parser.items(section))


def test_registration_guard_detects_name_and_factory_alias_bypasses():
    assert retired_discovery_is_absent('[agent_box.plugins]\nopencode = pacthold.harness_kit.entrypoints:create_opencode\n')
    for factory in FACTORIES:
        assert not retired_discovery_is_absent('[agent_box.plugins]\nrenamed = pacthold.harness_kit.entrypoints:' + factory + '\n')
    assert not retired_discovery_is_absent('[alternate.discovery]\ncodex = renamed.module:other_factory\n')


def test_actual_legacy_wheel_retires_only_three_auto_discovery_entries(tmp_path):
    project = tmp_path / 'source'
    project.mkdir()
    source = ROOT / 'plugins/harness'
    shutil.copyfile(source / 'pyproject.toml', project / 'pyproject.toml')
    shutil.copytree(source / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    wheels = tmp_path / 'wheels'
    home = tmp_path / 'isolated-home'
    home.mkdir()
    environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT'}}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
        PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    built = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-index',
        '--no-build-isolation', '--no-deps', '--wheel-dir', str(wheels), str(project)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    files = list(wheels.glob('pacthold.harness_kit-*.whl'))
    assert len(files) == 1
    with zipfile.ZipFile(files[0]) as wheel:
        entry_files = [name for name in wheel.namelist() if name.endswith('.dist-info/entry_points.txt')]
        assert len(entry_files) == 1
        metadata = wheel.read(entry_files[0]).decode('utf-8')
        assert retired_discovery_is_absent(metadata)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(metadata)
        assert dict(parser['agent_box.plugins']) == {
            'harness-profile-store': 'pacthold.harness_kit.entrypoints:create_profile_store',
            'opencode': 'pacthold.harness_kit.entrypoints:create_opencode',
            'hermes': 'pacthold.harness_kit.entrypoints:create_hermes',
        }
        # Declaration resources and historical source are retained, rather than
        # physically deleting unreviewed implementations or persisted IDs.
        for name in ('harnesses.toml', 'launch-descriptors.json'):
            assert 'pacthold.harness_kit/' + name in wheel.namelist()
    created = subprocess.run([sys.executable, '-m', 'venv', str(tmp_path / 'venv')],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert created.returncode == 0, created.stdout + created.stderr
    python = tmp_path / 'venv/bin/python'
    installed = subprocess.run([str(python), '-m', 'pip', 'install', '--no-index',
        '--no-deps', str(files[0])], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=90)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    inspected = subprocess.run([str(python), '-I', '-c',
        "from importlib.metadata import distribution; "
        "points = distribution('ordessa-harness').entry_points; "
        "assert {p.name for p in points} == {'harness-profile-store', 'opencode', 'hermes'}; "
        "assert all(not p.value.endswith((':create_codex', ':create_claude', ':create_pi')) for p in points)"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr

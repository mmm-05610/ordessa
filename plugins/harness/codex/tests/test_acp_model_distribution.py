"""Fresh own-wheel closure for pure Codex ACP planning, no native/model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]

def _acp_wheelhouse():
    """Explicit offline official ACP SDK closure; no test download or fallback."""
    configured = os.environ.get('ORDESSA_ACP_WHEELHOUSE')
    if not configured:
        raise AssertionError('set ORDESSA_ACP_WHEELHOUSE to the verified official ACP SDK closure')
    path = Path(configured)
    if not path.is_dir() or not any(path.glob('agent_client_protocol-0.12.1-*.whl')):
        raise AssertionError('verified ACP SDK 0.12.1 offline wheelhouse unavailable')
    return str(path)


def _brand_wheelhouse():
    """Offline wheelhouse for third-party brand deps, prepared from the configured trusted source."""
    configured = os.environ.get('ORDESSA_BRAND_WHEELHOUSE')
    candidates = ([Path(configured)] if configured else []) + [ROOT / '.nightly-cache' / 'brand-yaml-wheel-root']
    for path in candidates:
        if path.is_dir() and any(path.glob('pyyaml-*.whl')):
            return str(path)
    raise AssertionError('offline brand wheelhouse (PyYAML) unavailable; prepare it from the configured trusted source')


def test_independent_codex_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/interfaces/execution/c1-api', 'packages/execution/kernel',
                'packages/execution/agents', 'packages/execution/units', 'packages/execution/environments',
                'packages/infrastructure', 'plugins/harness/codex')
    sources = []
    for index, relative in enumerate(packages):
        source = ROOT / relative; clean = tmp_path / ('source-' + str(index)); clean.mkdir()
        shutil.copy2(source / 'pyproject.toml', clean / 'pyproject.toml')
        if (source / 'README.md').exists(): shutil.copy2(source / 'README.md', clean / 'README.md')
        shutil.copytree(source / 'src', clean / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
        sources.append(str(clean))
    wheels = tmp_path / 'wheels'
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    home = tmp_path / 'home'; home.mkdir()
    env.update(HOME=str(home), PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    def run(command):
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return result
    run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation', '--no-deps',
         '--wheel-dir', str(wheels), *sources])
    own = sorted(wheels.glob('*.whl'))
    assert [p.name.split('-')[0] for p in own] == ['ordessa_environments', 'ordessa_execution_agents', 'ordessa_execution_api', 'ordessa_harness_codex', 'ordessa_infrastructure', 'ordessa_units', 'pacthold']
    assert len(list(wheels.glob('*.whl'))) == len(packages)
    isolated = tmp_path / 'isolated'; run([sys.executable, '-m', 'venv', str(isolated)])
    python = str(isolated / 'bin/python')
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), '--find-links', _brand_wheelhouse(), '--find-links', _acp_wheelhouse(), *map(str, sorted(wheels.glob('*.whl')))])
    run([python, '-m', 'pip', 'check'])
    program = '''
import importlib.util,tomllib
assert importlib.util.find_spec('pydantic_graph') is None
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_pi', 'ordessa_harness_claude_code'))
from ordessa_execution_agents.harness.definitions.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,BindSecret,MountContent
from ordessa_harness_codex.acp_model_configuration import CodexAdapter
from ordessa_harness_codex.acp_model_facts import render_codex_provider_section
from ordessa_harness_codex import CodexRuntimeProvider,CodexCapabilityUnsupported
context = AdapterContext(TargetHandle('codex','instance','fixture'),'1.1.14',{'native_session_id':'original-thread'})
choice = ChoiceRequest('provider','new-model','https://fixture.test','openai-responses','ref://fixture','acme.dev',
                       {'before_provider':'acme.dev','endpoint_changed':True})
plan = CodexAdapter().compile(context,{},choice)
assert plan.reconfiguration=='restart-resume' and plan.resume_expectation=={'native_session_id':'original-thread'}
assert any(isinstance(item,MountContent) for item in plan.intents)
assert any(isinstance(item,BindSecret) and item.secret_ref=='ref://fixture' for item in plan.intents)
assert list(tomllib.loads(render_codex_provider_section(provider='acme.dev',base_url='https://fixture.test',
                                                       protocol='openai-responses'))['model_providers'])==['acme.dev']
provider = CodexRuntimeProvider(definition_ref={'environmentNamespace':'fixture','definitionId':'codex','revision':'1'},
                               implementation_digest='sha256:'+'a'*64)
assert 'start' not in provider.descriptor.supported_methods
assert 'apply_configuration' not in provider.descriptor.supported_methods
try: provider.start({},None)
except CodexCapabilityUnsupported: pass
else: raise AssertionError('pure compilation must not grant native start')
'''
    run([python, '-I', '-c', program])

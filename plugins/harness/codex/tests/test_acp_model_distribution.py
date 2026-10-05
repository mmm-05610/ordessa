"""Fresh own-wheel closure for pure Codex ACP planning, no native/model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]


def test_independent_codex_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/backend/environment-api', 'packages/backend/pacthold',
                'packages/backend/harness-transport', 'plugins/harness/api', 'plugins/harness/codex')
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
    artifacts = sorted(wheels.glob('*.whl')); assert len(artifacts) == len(packages)
    isolated = tmp_path / 'isolated'; run([sys.executable, '-m', 'venv', str(isolated)])
    python = str(isolated / 'bin/python')
    run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', *map(str, artifacts)])
    run([python, '-m', 'pip', 'check'])
    program = '''
import importlib.util,tomllib
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_pi', 'ordessa_harness_claude_code'))
from ordessa_harness_api.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,BindSecret,MountContent
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

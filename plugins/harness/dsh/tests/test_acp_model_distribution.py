"""Fresh own-wheel closure for pure dsh ACP planning, no native/model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]

def _brand_wheelhouse():
    """Offline wheelhouse for third-party brand deps, prepared from the configured trusted source."""
    configured = os.environ.get('ORDESSA_BRAND_WHEELHOUSE')
    candidates = ([Path(configured)] if configured else []) + [ROOT / '.nightly-cache' / 'brand-yaml-wheel-root']
    for path in candidates:
        if path.is_dir() and any(path.glob('pyyaml-*.whl')):
            return str(path)
    raise AssertionError('offline brand wheelhouse (PyYAML) unavailable; prepare it from the configured trusted source')


def _acp_wheelhouse():
    configured = os.environ.get('ORDESSA_ACP_WHEELHOUSE')
    assert configured, 'official ACP SDK offline wheelhouse must be explicitly supplied'
    directory = Path(configured)
    wheel = directory / 'agent_client_protocol-0.12.1-py3-none-any.whl'
    import hashlib
    assert wheel.is_file() and hashlib.sha256(wheel.read_bytes()).hexdigest() == 'aaf3cc301ed87d9e2c4ccb91adfe1cd58784355f6ce7e513f50e7ca2391862ef'
    return str(directory)


def test_independent_dsh_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/interfaces/execution/c1-api',
                'packages/execution/agents', 'packages/execution/environments', 'packages/execution/units',
                'packages/infrastructure', 'plugins/harness/dsh')
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
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), '--find-links', _brand_wheelhouse(), '--find-links', _acp_wheelhouse(), *map(str, artifacts)])
    run([python, '-m', 'pip', 'check'])
    program = '''
import importlib.util
from importlib.metadata import requires, distributions
own_requirements = requires('ordessa-harness-dsh')
assert any(r.startswith('ordessa-execution-api==0.1.0') for r in own_requirements), own_requirements
assert any(r.startswith('ordessa-units==0.1.0') for r in own_requirements), own_requirements
retired = {'ordessa-environment-api', 'ordessa-harness-transport'}
assert not any(any(r.startswith(name) for name in retired) for r in own_requirements), own_requirements
assert retired.isdisjoint({d.metadata['Name'] for d in distributions()})
assert importlib.util.find_spec('ordessa_environment_api') is None
assert importlib.util.find_spec('pacthold') is None
assert importlib.util.find_spec('ordessa_harness_transport') is None
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_pi', 'ordessa_harness_claude_code',
    'ordessa_harness_codex'))
from ordessa_harness_dsh.acp_model_configuration import DshAdapter, DSH_MODEL_KIND, ADAPTER_ID
from ordessa_harness_dsh import DshRuntimeProvider, DshCapabilityUnsupported
from ordessa_harness_dsh.client import describe
from ordessa_harness_dsh.production import settings_document
assert isinstance(settings_document(), dict)
from ordessa_execution_agents.harness.definitions.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,Refusal,Verdict
manifest = DshAdapter().registration_manifest()
assert manifest['adapter_id'] == 'assets.model-provider.dsh' and manifest['kind'] == 'dsh.model'
assert manifest['native_target'] is None and manifest['claims'] == {}
assert manifest['supported_native_versions'] == ''
context = AdapterContext(TargetHandle('dsh','instance','fixture'),'0.1.5-rc.1',{'native_session_id':'ses-1'})
choice = ChoiceRequest('provider','new-model','https://fixture.test','openai-responses','ref://fixture','acme.dev',
                       {'before_provider':'acme.dev'})
assessment = DshAdapter().assess(context, choice)
assert assessment.verdict == 'unsupported' and assessment.harness_id == 'dsh'
refusal = DshAdapter().compile(context, {}, choice)
assert isinstance(refusal, Refusal) and refusal.code == 'capability-unsupported'
verdict = DshAdapter().verify(context, {'desired_model':'new-model','readback':{'model':'new-model'},
                                        'native_session_id':'ses-1'})
assert isinstance(verdict, Verdict) and verdict.verdict == 'unknown'
facts = describe()
assert 'session/load' not in facts['knownMethods'] and facts['absentMethods'] == ['session/load']
assert facts['protocol'] == 'dsh-acp/1'
provider = DshRuntimeProvider(definition_ref={'environmentNamespace':'fixture','definitionId':'dsh','revision':'1'},
                               implementation_digest='sha256:'+'a'*64)
methods = provider.descriptor.supported_methods
assert 'start' not in methods
for name in ('apply_configuration','query_change','describe_configuration','inspect_configuration'):
    assert name not in methods
for name, args in (('apply_configuration',({},None,None)), ('recover',({},None))):
    try: getattr(provider, name)(*args)
    except DshCapabilityUnsupported: pass
    else: raise AssertionError('dsh configuration/recovery must stay typed-refused')
assert 'recover' not in methods
'''
    run([python, '-I', '-c', program])

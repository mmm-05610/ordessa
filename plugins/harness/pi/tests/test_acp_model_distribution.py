"""Fresh own-wheel closure for pure Pi ACP planning, no native/model calls."""
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[4]

KERNEL_DEP_DIST_TO_PACKAGE = {
    'pydantic-graph': 'pydantic_graph', 'pydantic': 'pydantic', 'pydantic-core': 'pydantic_core',
    'annotated-types': 'annotated_types', 'typing-inspection': 'typing_inspection',
    'typing-extensions': 'typing_extensions', 'anyio': 'anyio', 'idna': 'idna',
    'logfire-api': 'logfire_api',
}


def _repack_kernel_wheels(wheel_dir: Path) -> set:
    """Repack the pinned third-party kernel dependency chain from the running
    environment: pacthold declares pydantic-graph (032 revision), so the
    own-wheel closure needs its fixed chain present without network access."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    generated = set()
    for dist_name, package in KERNEL_DEP_DIST_TO_PACKAGE.items():
        dist = importlib.metadata.distribution(dist_name)
        package_dir = Path(dist.locate_file(package))
        wheel_path = wheel_dir / f'{package}-{dist.version}-py3-none-any.whl'
        generated.add(wheel_path.name)
        with zipfile.ZipFile(wheel_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(package_dir.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    zf.write(path, path.relative_to(package_dir.parent))
            dist_info = Path(dist._path)
            for path in sorted(dist_info.rglob('*')):
                if path.is_file():
                    zf.write(path, path.relative_to(package_dir.parent))
    return generated


def test_independent_pi_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/backend/environment-api', 'packages/backend/pacthold',
                'packages/backend/harness-transport', 'plugins/harness/pi')
    sources = []
    for index, relative in enumerate(packages):
        source = ROOT / relative; clean = tmp_path / ('source-' + str(index)); clean.mkdir()
        shutil.copy2(source / 'pyproject.toml', clean / 'pyproject.toml')
        if (source / 'README.md').exists(): shutil.copy2(source / 'README.md', clean / 'README.md')
        shutil.copytree(source / 'src', clean / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
        sources.append(str(clean))
    wheels = tmp_path / 'wheels'
    kernel_wheels = _repack_kernel_wheels(wheels)
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
    own = [p for p in own if p.name not in kernel_wheels]
    assert [p.name.split('-')[0] for p in own] == ['ordessa_environment_api',
        'ordessa_harness_pi', 'ordessa_harness_transport', 'pacthold']
    artifacts = sorted(wheels.glob('*.whl')); assert len(artifacts) == len(packages) + len(KERNEL_DEP_DIST_TO_PACKAGE)
    isolated = tmp_path / 'isolated'; run([sys.executable, '-m', 'venv', str(isolated)])
    python = str(isolated / 'bin/python')
    run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', *map(str, artifacts)])
    run([python, '-m', 'pip', 'check'])
    program = """
import importlib.util
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_codex', 'ordessa_harness_claude_code'))
from dataclasses import replace
from pacthold.harness_contracts.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,BindSecret,CompileIntent,RequestParams
from ordessa_harness_pi.acp_model_configuration import PiAdapter
from ordessa_harness_pi import PiRuntimeProvider,PiProviderRefused
context = AdapterContext(TargetHandle('pi','instance','fixture'),'0.5.1',{'native_session_id':'original-session'})
choice = ChoiceRequest('provider','new-model','https://fixture.test','openai-chat','ref://fixture','acme',
                       {'provider_in_instance':True,'credential_changed':True})
plan = PiAdapter().compile(context,{},choice)
assert plan.reconfiguration=='restart-resume' and plan.resume_expectation=={'native_session_id':'original-session'}
assert any(isinstance(item,CompileIntent) and item.field_path==('session','model') and item.typed_value=='new-model' for item in plan.intents)
assert any(isinstance(item,BindSecret) and item.secret_ref=='ref://fixture' for item in plan.intents)
assert not any(isinstance(item,CompileIntent) and item.field_path==('providers','acme') for item in plan.intents)
before={'providers':{'acme':{'baseUrl':'https://fixture.test','models':[{'id':'new-model','maxTokens':4096},{'id':'sibling','maxTokens':2}]}}}
budget=PiAdapter().compile(context,before,replace(choice,params=RequestParams(max_tokens=1024)))
golden=next(item.typed_value for item in budget.intents if isinstance(item,CompileIntent) and item.field_path==('providers','acme'))
assert golden['models']==[{'id':'new-model','maxTokens':1024},{'id':'sibling','maxTokens':2}]
retry=RequestParams.from_record({'retry':{'enabled':True,'maxRetries':2,'provider':{'maxRetries':1,'maxRetryDelayMs':1000}}})
retry_plan=PiAdapter().compile(context,before,replace(choice,params=retry))
assert any(isinstance(item,CompileIntent) and item.field_path==('retry',) for item in retry_plan.intents)
assert not any(isinstance(item,CompileIntent) and item.field_path==('providers','acme') for item in retry_plan.intents)
provider = PiRuntimeProvider(definition_ref={'environmentNamespace':'fixture','definitionId':'pi','revision':'1'},
                            implementation_digest='sha256:'+'a'*64)
assert 'start' not in provider.descriptor.supported_methods
assert 'apply_configuration' not in provider.descriptor.supported_methods
try: provider.start({},None)
except PiProviderRefused: pass
else: raise AssertionError('pure compilation must not grant native start')
"""
    run([python, '-I', '-c', program])

"""Fresh own-wheel closure for pure Codex ACP planning, no native/model calls."""
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
    """Repack the pinned third-party kernel dependency chain from the running env.

    Pacthold declares pydantic-graph as a kernel dependency (032 revision), so
    the own-wheel closure needs its full fixed chain present without network
    access. Versions come from the running environment, which pins the
    toolchain recorded in docs/baseline.md.
    """
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


def test_independent_codex_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/backend/environment-api', 'packages/backend/pacthold',
                'packages/backend/harness-transport', 'plugins/harness/codex')
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
    own = sorted(p for p in wheels.glob('*.whl') if p.name not in kernel_wheels)
    assert [p.name.split('-')[0] for p in own] == ['ordessa_environment_api',
        'ordessa_harness_codex', 'ordessa_harness_transport', 'pacthold']
    assert len(list(wheels.glob('*.whl'))) == len(packages) + len(KERNEL_DEP_DIST_TO_PACKAGE)
    isolated = tmp_path / 'isolated'; run([sys.executable, '-m', 'venv', str(isolated)])
    python = str(isolated / 'bin/python')
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), *map(str, sorted(wheels.glob('*.whl')))])
    run([python, '-m', 'pip', 'check'])
    program = '''
import importlib.util,tomllib
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_pi', 'ordessa_harness_claude_code'))
from pacthold.harness_contracts.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,BindSecret,MountContent
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

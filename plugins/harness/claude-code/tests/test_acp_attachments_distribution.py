"""Fresh own-package wheel closure; conversion only, no native/model process."""
import importlib.metadata
import json
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


def test_independent_attachment_wheel_without_monolith_product_server_or_sdk(tmp_path):
    packages = ('packages/backend/environment-api', 'packages/backend/pacthold',
                'packages/backend/harness-transport', 'plugins/harness/claude-code')
    wheels = tmp_path / 'wheels'
    kernel_wheels = _repack_kernel_wheels(wheels)
    clean_sources = []
    for index, relative in enumerate(packages):
        source = ROOT / relative
        destination = tmp_path / ('source-' + str(index)); destination.mkdir()
        shutil.copy2(source / 'pyproject.toml', destination / 'pyproject.toml')
        if (source / 'README.md').is_file(): shutil.copy2(source / 'README.md', destination / 'README.md')
        shutil.copytree(source / 'src', destination / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
        clean_sources.append(str(destination))
    build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation',
        '--no-deps', '--wheel-dir', str(wheels), *clean_sources], capture_output=True, text=True, timeout=60)
    assert build.returncode == 0, build.stdout + build.stderr
    own = [p for p in wheels.glob('*.whl') if p.name not in kernel_wheels]
    assert [p.name.split('-')[0] for p in sorted(own)] == ['ordessa_environment_api',
        'ordessa_harness_claude_code', 'ordessa_harness_transport', 'pacthold']
    artifacts = sorted(wheels.glob('*.whl')); assert len(artifacts) == len(packages) + len(KERNEL_DEP_DIST_TO_PACKAGE)
    claude = list(wheels.glob('ordessa_harness_claude_code-*.whl')); assert len(claude) == 1
    with zipfile.ZipFile(claude[0]) as archive:
        assert 'ordessa_harness_claude_code/acp_attachments.py' in archive.namelist()
        assert 'ordessa_harness_claude_code/acp_model_configuration.py' in archive.namelist()
        assert not any(name.startswith(('pacthold.harness_kit/', 'ordessa_agent_tools/', 'ordessa_server/')) for name in archive.namelist())
    environment = tmp_path / 'isolated'
    created = subprocess.run([sys.executable, '-m', 'venv', str(environment)], capture_output=True, text=True, timeout=60)
    assert created.returncode == 0, created.stderr
    python = environment / 'bin/python'
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    install = subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps',
        *map(str, artifacts)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert install.returncode == 0, install.stdout + install.stderr
    checked = subprocess.run([str(python), "-m", "pip", "check"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    program = '''
import base64, hashlib, importlib.util, json
assert all(importlib.util.find_spec(name) is None for name in
    ('ordessa_harness', 'ordessa_agent_tools', 'ordessa_server', 'claude_agent_sdk', 'server_plugin_api'))
import ordessa_harness_claude_code.server_plugin
from ordessa_harness_claude_code.acp_model_configuration import ClaudeAdapter
from pacthold.harness_contracts.model_compilation import AdapterContext, ChoiceRequest, TargetHandle
context = AdapterContext(TargetHandle("claude-code", "instance", "fixture"), "0.81.2", {"native_session_id": "fixture-session"})
choice = ChoiceRequest("fixture-provider", "fixture-model", "https://fixture.test", "anthropic-messages", None, "fixture")
compiled = ClaudeAdapter().compile(context, {}, choice)
assert compiled.reconfiguration == "session-local"
assert compiled.intents[0].typed_value == "fixture-model"
assert ClaudeAdapter().assess(AdapterContext(context.target_handle, "0.2.163"), choice).verdict == "unsupported"
from ordessa_harness_claude_code.acp_attachments import (
    ClaudePreparedAttachment, ClaudeAttachmentRefused, assemble_attachment_blocks,
    CLAUDE_ATTACHMENT_UNSUPPORTED, CLAUDE_ATTACHMENT_HASH_MISMATCH)
from ordessa_harness_claude_code import ClaudeCodeRuntimeProvider, ClaudeProviderUnavailable
runtime = ClaudeCodeRuntimeProvider(definition_ref={'environmentNamespace': 'fixture',
    'definitionId': 'claude', 'revision': '1'}, implementation_digest='sha256:' + 'a' * 64)
assert set(runtime.descriptor.supported_methods) == {
    'describe_definition', 'inspect_installation', 'assess_configuration', 'plan_preparation'}
try: runtime.start({}, None)
except ClaudeProviderUnavailable: pass
else: raise AssertionError('attachments must not grant native start')
data = b'controlled-content'
ref = ClaudePreparedAttachment('image', 'image.png', 'https://ordessa.example/image',
    'image/png', hashlib.sha256(data).hexdigest(), len(data))
block = assemble_attachment_blocks({'image': ref}, attach_declared=True, data_by_prepared_id={'image': data})[0]
assert base64.b64decode(block['data']) == data
try: assemble_attachment_blocks({'image': ref}, attach_declared=True, data_by_prepared_id={'image': b'changed---content-'})
except ClaudeAttachmentRefused as error: assert error.code == CLAUDE_ATTACHMENT_HASH_MISMATCH
else: raise AssertionError('changed bytes accepted')
audio = ClaudePreparedAttachment('audio', 'audio.wav', 'https://ordessa.example/audio', 'audio/wav', 'a' * 64, 1)
try: assemble_attachment_blocks({'audio': audio}, attach_declared=True)
except ClaudeAttachmentRefused as error: assert error.code == CLAUDE_ATTACHMENT_UNSUPPORTED
else: raise AssertionError('audio silently accepted')
print(json.dumps({'converted': True, 'nativeStarted': False, 'modelsCalled': 0}))
'''
    run = subprocess.run([str(python), '-I', '-c', program], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout) == {'converted': True, 'nativeStarted': False, 'modelsCalled': 0}

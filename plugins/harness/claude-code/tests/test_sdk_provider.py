"""Offline SDK migration gates, separate from unavailable native bootstrap.

All historical tests/assertions remain. Their retired execution imports must be
migrated by the integration owner, not satisfied by compatibility aliases.
"""
import ast
import asyncio
from dataclasses import replace
from pathlib import Path
import pytest

from ordessa_agents.sdk import BoundPath, PrepareContext, SessionBootstrap, HarnessError
from ordessa_agents.profiles import decode_content
from ordessa_harness_claude_code import factory, PROTOCOL

PIN = {'environmentNamespace': 'test', 'definitionId': 'claude', 'revision': '1'}
DIGEST = 'sha256:' + 'a' * 64


def content(payload=None):
    return decode_content({
        'schemaVersion': '1', 'harnessDefinitionRef': PIN,
        'declarations': [] if payload is None else [{
            'declarationId': 'native', 'configurationKind': 'claude.configuration',
            'schemaVersion': '1', 'action': 'value', 'requirement': 'required', 'payload': payload,
        }],
    }, 'test')


def context():
    roots = {key: BoundPath(key, '.') for key in ('work', 'home', 'config', 'data', 'state', 'cache', 'tmp')}
    environment = {
        'HOME': '/approved/home', 'PATH': '/approved/bin', 'TMPDIR': '/approved/tmp',
        'XDG_CONFIG_HOME': '/approved/config', 'XDG_DATA_HOME': '/approved/data',
        'XDG_STATE_HOME': '/approved/state', 'XDG_CACHE_HOME': '/approved/cache',
        'CLAUDE_CONFIG_DIR': '/approved/private-claude',
    }
    return PrepareContext({'members': ['launcher', 'communicate']}, roots,
        ('/approved/claude',), environment, (), (), (), SessionBootstrap('fresh', 'original-bootstrap'))


def provider():
    return factory.build({'definition_ref': PIN, 'implementation_digest': DIGEST})


def test_native_plan_is_pure_pinned_immutable_and_never_acp(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no direct spawn')))
    current = provider()
    profile = content({'model': 'explicit-native-model', 'permission_mode': 'default', 'system_prompt': 'explicit instruction'})
    current.validate_profile(profile)
    plan = current.prepare(profile, context())
    assert current.descriptor.provider_id == 'claude'
    assert current.descriptor.protocol_id == PROTOCOL == 'claude-stream-json/1'
    assert plan.argv == (
        '/approved/claude', '-p', '--output-format', 'stream-json', '--input-format', 'stream-json',
        '--verbose', '--permission-prompt-tool', 'stdio', '--model', 'explicit-native-model',
        '--permission-mode', 'default', '--append-system-prompt', 'explicit instruction',
    )
    assert plan.cwd_ref == BoundPath('work', '.')
    assert plan.session_bootstrap == context().session_bootstrap
    assert not plan.configuration_artifacts
    with pytest.raises(TypeError):
        plan.environment_values['HOME'] = '/changed'
    with pytest.raises(HarnessError, match='PROFILE_HARNESS_PIN_MISMATCH'):
        current.validate_profile(replace(profile, harness_definition_ref={**PIN, 'revision': '2'}))


def test_native_bootstrap_has_no_acp_or_old_sdk_fallback():
    class Process:
        async def open_acp_session(self, *args):
            raise AssertionError('Claude native control is not ACP')
    with pytest.raises(HarnessError, match='NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(provider().open_session(Process(), context()))
    for mode in ('resume', 'none'):
        bootstrap = SessionBootstrap(mode, None if mode == 'none' else 'native-session')
        with pytest.raises(HarnessError, match='SESSION_MODE_UNSUPPORTED'):
            provider().prepare(content(), replace(context(), session_bootstrap=bootstrap))


@pytest.mark.parametrize('payload', [
    {'permission_mode': 'bypassPermissions'}, {'permission_mode': 'acceptEdits'},
    {'allowed_tools': 'Bash'}, {'mcp_config': '/unbound/mcp.json'},
    {'resume': 'session'}, {'continue_': True}, {'subscriptionToken': 'refused'},
    {'model': True}, {'system_prompt': ['invalid']}, {'unknown': 1},
])
def test_unbound_configuration_continuation_and_permission_overrides_refuse(payload):
    with pytest.raises(HarnessError):
        provider().validate_profile(content(payload))


@pytest.mark.parametrize('flag', [
    '--dangerously-skip-permissions', '--permission-mode=acceptEdits', '--allowedTools=Bash',
    '--resume=session', '--continue', '--input-format=stream-json', '--mcp-config=/unbound/mcp.json',
])
def test_command_prefix_cannot_restore_a_retired_input_or_permission_path(flag):
    with pytest.raises(HarnessError, match='NATIVE_LAUNCH_FLAGS_UNSUPPORTED'):
        provider().prepare(content(), replace(context(), command_prefix=('/approved/claude', flag)))


def test_approved_environment_is_explicit_and_never_merges_credentials(monkeypatch):
    monkeypatch.setenv('UNAPPROVED_PROCESS_VALUE', 'must-not-enter-plan')
    current = provider()
    plan = current.prepare(content(), context())
    assert 'UNAPPROVED_PROCESS_VALUE' not in plan.environment_values
    with pytest.raises(HarnessError, match='EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED'):
        current.prepare(content(), replace(context(), launch_environment={}))
    with pytest.raises(HarnessError, match='CREDENTIAL_REFERENCE_REQUIRED'):
        current.prepare(content(), replace(context(), launch_environment={
            **dict(context().launch_environment), 'ANTHROPIC_AUTH_TOKEN': 'not-permitted',
        }))


def test_runtime_source_imports_sdk_only_and_old_execution_modules_are_absent():
    import ordessa_harness_claude_code.client as module
    root = Path(module.__file__).parent
    assert not hasattr(module, 'ClaudeCodeClient')
    for name in ('provider.py', 'sdk.py', 'stream_json.py', 'server_plugin.py', 'owner_projection.py',
                 'runtime_channel.py', 'unit_lifecycle.py', 'profile.py', 'launch.py', 'assembly.py'):
        assert not (root / name).exists(), name
    for path in root.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
                assert node.module == 'ordessa_agents.sdk', (path, node.module)


def test_factory_metadata_retains_identifier_and_has_only_sdk_dependency():
    import tomllib
    with pytest.raises(HarnessError, match='HARNESS_BINDINGS_INVALID'):
        factory.build({})
    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert metadata['project']['dependencies'] == ['ordessa-execution-agents==0.1.0']
    assert metadata['project']['entry-points']['ordessa.harness_providers']['claude'] == 'ordessa_harness_claude_code.client:factory'

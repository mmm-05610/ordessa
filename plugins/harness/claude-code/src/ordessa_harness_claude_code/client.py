"""Pure SDK provider for claude-stream-json/1, including its native bootstrap.

No Unit, direct process/SDK transport, permission issuer or ACP substitution.
Composition explicitly supplies approved native launch inputs. Preserved ACP
artifacts are historical resources, never a fallback for this native provider.
"""
import json
import uuid

from ordessa_agents.sdk import (
    HarnessDescriptor, HarnessError, PrepareContext, ProfileContent, LaunchPlan,
)
from .native_channel import ConfigRefusal, FAMILY_ID, PROTOCOL, compile_config


def _credential_binding(declaration):
    if (declaration.schema_version != '1' or declaration.action != 'value'
            or declaration.resource_refs):
        raise HarnessError('CONFIGURATION_UNSUPPORTED')
    try:
        payload = dict(declaration.payload)
    except (TypeError, ValueError):
        raise HarnessError('CONFIGURATION_INVALID') from None
    if set(payload) != {'sourcePath', 'rootKey', 'relativePath'}:
        raise HarnessError('CONFIGURATION_INVALID')
    for key in ('sourcePath', 'rootKey', 'relativePath'):
        value = payload[key]
        if type(value) is not str or not value or len(value) > 4096 or '\x00' in value:
            raise HarnessError('CONFIGURATION_INVALID')
    import pathlib as _pathlib
    if not _pathlib.PurePosixPath(payload['sourcePath']).is_absolute():
        raise HarnessError('CONFIGURATION_INVALID')
    return payload


class ClaudeHarnessProvider:
    def __init__(self, definition_ref, implementation_digest):
        self.descriptor = HarnessDescriptor(
            FAMILY_ID, definition_ref, implementation_digest, PROTOCOL,
            ('work', 'home', 'config', 'data', 'state', 'cache', 'tmp'),
            ('claude.configuration/1', 'credentials.file/1'),
        )

    def _options(self, content):
        if (type(content) is not ProfileContent
                or dict(content.harness_definition_ref) != dict(self.descriptor.definition_ref)):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options = {}
        for declaration in content.declarations:
            if declaration.configuration_kind == 'credentials.file':
                # Host-materialized credential binding: visible in the Profile,
                # never carrying the secret itself. This provider ignores it.
                _credential_binding(declaration)
                continue
            if (declaration.configuration_kind != 'claude.configuration'
                    or declaration.schema_version != '1'
                    or declaration.action != 'value' or declaration.resource_refs):
                raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:
                values = dict(declaration.payload)
            except (TypeError, ValueError):
                raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options) & set(values):
                raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        if options.get('resume') is not None or options.get('continue_') not in (None, False):
            raise HarnessError('NATIVE_CONTINUATION_UNAVAILABLE')
        for key in ('model', 'system_prompt'):
            if key in options and (type(options[key]) is not str or not options[key]
                    or len(options[key].encode('utf-8')) > 65536 or '\x00' in options[key]):
                raise HarnessError('CONFIGURATION_INVALID')
        if 'permission_mode' in options and options['permission_mode'] != 'default':
            raise HarnessError('PERMISSION_CONFIGURATION_UNAVAILABLE')
        # Raw paths are not prepared configuration/material references.
        if 'mcp_config' in options:
            raise HarnessError('PREPARED_MCP_CONFIGURATION_UNAVAILABLE')
        try:
            return compile_config(options, bidirectional=True)
        except (ConfigRefusal, TypeError, ValueError, OverflowError):
            raise HarnessError('CONFIGURATION_UNSUPPORTED') from None

    def validate_profile(self, content):
        self._options(content)

    def prepare(self, content, context):
        compiled = self._options(content)
        if type(context) is not PrepareContext:
            raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots) <= set(context.private_dirs):
            raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher', 'communicate'} <= set(context.endpoint_facts.get('members', ())):
            raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.credential_refs:
            raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        if context.session_bootstrap.mode != 'fresh':
            raise HarnessError('SESSION_MODE_UNSUPPORTED')
        forbidden = {
            '-p', '--print', '--input-format', '--output-format', '--permission-prompt-tool',
            '--verbose', '--dangerously-skip-permissions', '--allow-dangerously-skip-permissions',
            '--permission-mode', '--allowedTools', '--allowed-tools', '--settings',
            '--setting-sources', '--resume', '-r', '--continue', '-c', '--session-id',
            '--model', '--append-system-prompt', '--mcp-config',
        }
        if any(token.split('=', 1)[0] in forbidden for token in context.command_prefix):
            raise HarnessError('NATIVE_LAUNCH_FLAGS_UNSUPPORTED')
        environment = dict(context.launch_environment)
        required = ('HOME', 'PATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME',
                    'XDG_CACHE_HOME', 'TMPDIR', 'CLAUDE_CONFIG_DIR')
        if any(not environment.get(key) for key in required):
            raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in
                ('TOKEN', 'SECRET', 'PASSWORD', 'APIKEY', 'API_KEY', 'CREDENTIAL'))
                for key in environment):
            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        environment.update({'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TERM': 'dumb', 'NO_COLOR': '1'})
        # Claude only announces its session with the first user message, so pin a
        # fresh native id at launch; a reused id is refused by the CLI, hence one
        # id per preparation attempt.
        session_id = str(uuid.uuid4())
        argv = context.command_prefix + (
            '-p', '--output-format', 'stream-json', '--input-format', 'stream-json',
            '--verbose', '--permission-prompt-tool', 'stdio', '--session-id', session_id,
        ) + tuple(compiled['args'])
        return LaunchPlan(
            argv, context.private_dirs['work'], environment, (), (),
            context.prepared_configuration_refs, context.materials,
            context.session_bootstrap, ('launcher', 'communicate'),
        )

    def prompt_handler(self):
        return ClaudePromptHandler()

    async def open_session(self, process, context):
        if type(context) is not PrepareContext:
            raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        # Native control_request/control_response must never receive ACP frames.
        raise HarnessError('NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE')

    async def open_native_session(self, process, context, plan=None):
        """Bootstrap claude-stream-json/1.

        Claude announces its session only with the first user message, so the
        launch pins the native id with ``--session-id`` (chosen by ``prepare``)
        and this bootstrap proves the process answers the control handshake.
        The pinned id is echoed back by Claude in ``system/init`` on the first
        prompt; it is never fabricated after launch.
        """
        if type(context) is not PrepareContext:
            raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        channel = getattr(process, 'native_channel', None)
        if channel is None or not callable(getattr(channel, 'exchange', None)):
            raise HarnessError('NATIVE_BOOTSTRAP_UNAVAILABLE')
        session_id = _pinned_session_id(plan)
        if session_id is None:
            raise HarnessError('NATIVE_SESSION_INVALID')

        def is_control_response(value):
            return (type(value) is dict and value.get('type') == 'control_response'
                    and isinstance(value.get('response'), dict)
                    and value['response'].get('subtype') == 'success')

        await channel.exchange('control/initialize',
            lambda rid: _encode_control_request(rid, 'initialize'), is_control_response)
        return ClaudeSession(session_id)


from dataclasses import dataclass


def _pinned_session_id(plan):
    argv = getattr(plan, 'argv', None)
    if not isinstance(argv, (tuple, list)):
        return None
    for index, item in enumerate(argv[:-1]):
        if item == '--session-id':
            value = argv[index + 1]
            if (type(value) is not str or not value or len(value) > 512
                    or any(ord(char) < 32 for char in value)):
                return None
            return value
    return None


def _encode_control_request(request_id, subtype):
    """One stream-json control frame; the CLI answers with control_response."""
    if (type(request_id) is not str or not request_id or len(request_id) > 512
            or type(subtype) is not str or not subtype or len(subtype) > 64):
        raise HarnessError('NATIVE_FRAME_INVALID')
    value = {'type': 'control_request', 'request_id': request_id,
             'request': {'subtype': subtype}}
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n')


class ClaudePromptHandler:
    """claude-stream-json/1 prompt, completion and interrupt frames."""

    protocol_id = 'claude-stream-json/1'

    def encode_prompt(self, session_id, params_bytes, operation_ref):
        from ordessa_agents.sdk.native_prompt import prompt_text
        text = prompt_text(params_bytes)
        value = {'type': 'user',
                 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}
        return (_canonical(value) + '\n').encode()

    def accept(self, value, *, session_id=None):
        if type(value) is not dict:
            return False
        if value.get('type') == 'result':
            return value.get('session_id') in (None, session_id)
        return False

    def outcome(self, value, *, session_id=None):
        if value.get('is_error'):
            return 'failed', {'protocol': 'claude-stream-json/1', 'subtype': value.get('subtype'),
                              'sessionId': value.get('session_id'),
                              'result': str(value.get('result'))[:200]}
        return 'completed', {'protocol': 'claude-stream-json/1', 'sessionId': value.get('session_id'),
                             'numTurns': value.get('num_turns'),
                             'costUsd': value.get('total_cost_usd'),
                             'result': str(value.get('result'))[:200]}

    def encode_cancel(self, session_id, operation_ref):
        return (_canonical({'type': 'control_request', 'request_id': str(operation_ref),
                            'request': {'subtype': 'interrupt'}}) + '\n').encode()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


@dataclass(frozen=True)
class ClaudeSession:
    """Native claude-stream-json/1 session identity; no ledger, no grants."""
    session_id:str
    protocol_id:str='claude-stream-json/1'


class ClaudeProviderFactory:
    def build(self, bindings):
        if set(bindings) != {'definition_ref', 'implementation_digest'}:
            raise HarnessError('HARNESS_BINDINGS_INVALID')
        return ClaudeHarnessProvider(bindings['definition_ref'], bindings['implementation_digest'])


factory = ClaudeProviderFactory()

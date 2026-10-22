"""pi preparation plus its own ``pi-rpc/1`` native bootstrap.

No Unit/provider ledger, direct client, permission lease or ACP translation:
the harness supplies its own correlation id encoder, and the owner only guards
the physical write and observes the matching response.
"""
from ordessa_agents.sdk import HarnessDescriptor,HarnessError,PrepareContext,ProfileContent,LaunchPlan
from dataclasses import dataclass
from .native_channel import compile_config,ConfigRefusal,ISOLATION_FLAGS
from .rpc_frames import encode_request


def _credential_binding(declaration):
    if (declaration.schema_version!='1' or declaration.action!='value'
            or declaration.resource_refs):raise HarnessError('CONFIGURATION_UNSUPPORTED')
    try:payload=dict(declaration.payload)
    except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
    if set(payload)!={'sourcePath','rootKey','relativePath'}:raise HarnessError('CONFIGURATION_INVALID')
    for key in ('sourcePath','rootKey','relativePath'):
        value=payload[key]
        if type(value) is not str or not value or len(value)>4096 or '\x00' in value:
            raise HarnessError('CONFIGURATION_INVALID')
    import pathlib as _pathlib
    if not _pathlib.PurePosixPath(payload['sourcePath']).is_absolute():
        raise HarnessError('CONFIGURATION_INVALID')
    return payload


class PiHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('pi',definition_ref,implementation_digest,'pi-rpc/1',
            ('work','home','config','data','state','cache','tmp'),
            ('pi.configuration/1','credentials.file/1'))

    def _options(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options={}
        for declaration in content.declarations:
            if declaration.configuration_kind=='credentials.file':
                _credential_binding(declaration)
                continue
            if (declaration.configuration_kind!='pi.configuration' or declaration.schema_version!='1'
                    or declaration.action!='value' or declaration.resource_refs):raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:values=dict(declaration.payload)
            except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options)&set(values):raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        for key in ('provider','model','thinking'):
            if key in options and (type(options[key]) is not str or not options[key] or len(options[key])>512):
                raise HarnessError('CONFIGURATION_INVALID')
        if 'offline' in options and type(options['offline']) is not bool:raise HarnessError('CONFIGURATION_INVALID')
        if 'extensions' in options and options['extensions'] is not False:raise HarnessError('CONFIGURATION_UNSUPPORTED')
        if 'session_dir' in options:raise HarnessError('SESSION_CONFIGURATION_UNAVAILABLE')
        try:return compile_config(options)
        except (ConfigRefusal,ValueError,TypeError):raise HarnessError('CONFIGURATION_UNSUPPORTED') from None

    def validate_profile(self,content):self._options(content)

    def prepare(self,content,context):
        compiled=self._options(content)
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        forbidden={'--allow-all','--allow-all-tools','--allow-all-paths','--yolo','--auto-approve','--yes','--dangerously-bypass-approvals-and-sandbox'}
        if any(token.split('=',1)[0] in forbidden for token in context.command_prefix):raise HarnessError('AUTO_APPROVAL_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','PI_CODING_AGENT_DIR')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','APIKEY','API_KEY','CREDENTIAL')) for key in environment):raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb','NO_COLOR':'1'})
        argv=context.command_prefix+('--mode','rpc','--no-session')+ISOLATION_FLAGS
        if compiled['offline']:
            argv+=('--offline',);environment['PI_OFFLINE']='1'
        elif 'PI_OFFLINE' in environment:raise HarnessError('CONFIGURATION_CONFLICT')
        environment.update({'PI_TELEMETRY':'0','PI_SKIP_VERSION_CHECK':'1'})
        argv+=tuple(compiled['args'])
        return LaunchPlan(argv,context.private_dirs['work'],environment,(),(),context.prepared_configuration_refs,
            context.materials,context.session_bootstrap,('launcher','communicate'))

    def prompt_handler(self):
        return PiPromptHandler()

    def native_codec(self):
        return PiNativeCodec()

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        # pi-rpc/1 is not ACP; never reuse its managed bootstrap with alien frames.
        raise HarnessError('NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE')

    async def open_native_session(self,process,context,plan=None):
        """One ``pi-rpc/1`` bootstrap: request state, read the native session id.

        This is pi's own protocol. The frame comes from pi's pinned codec and the
        response is interpreted here; the owner supplies only a guarded exchange.
        """
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        channel=getattr(process,'native_channel',None)
        if channel is None or not callable(getattr(channel,'exchange',None)):
            raise HarnessError('NATIVE_BOOTSTRAP_UNAVAILABLE')
        response=await channel.exchange('get_state',
            lambda request_id:encode_request(request_id,'get_state',{}))
        if (type(response) is not dict or response.get('type')!='response'
                or response.get('command')!='get_state'):
            raise HarnessError('NATIVE_BOOTSTRAP_INVALID')
        if response.get('success') is not True:raise HarnessError('NATIVE_BOOTSTRAP_REFUSED')
        data=response.get('data')
        session_id=data.get('sessionId') if isinstance(data,dict) else None
        if (type(session_id) is not str or not session_id or len(session_id)>512
                or any(ord(char)<32 for char in session_id)):
            raise HarnessError('NATIVE_SESSION_INVALID')
        return PiSession(session_id)


class PiPromptHandler:
    """pi-rpc/1 prompt, settle observation and abort frames."""

    protocol_id = 'pi-rpc/1'

    def __init__(self):
        self._messages = {}

    def encode_prompt(self, session_id, params_bytes, operation_ref):
        from ordessa_agents.sdk.native_prompt import prompt_text
        text = prompt_text(params_bytes)
        return encode_request(str(operation_ref), 'prompt', {'message': text})

    def _capture(self, session_id, message):
        if type(message) is not dict or message.get('role') != 'assistant':
            return
        content = message.get('content')
        text = ''
        if type(content) is str:
            text = content
        elif type(content) is list:
            parts = []
            for part in content:
                if type(part) is dict and part.get('type') == 'text':
                    value = part.get('text')
                    if type(value) is str and value:
                        parts.append(value)
            text = '\n'.join(parts)
        if text.strip():
            self._messages[session_id] = text.strip()[-4096:]

    def accept(self, value, *, session_id=None):
        if type(value) is not dict:
            return False
        kind = value.get('type')
        if kind == 'message_end':
            self._capture(session_id, value.get('message'))
        elif kind in ('turn_end', 'agent_end'):
            messages = value.get('messages')
            if type(messages) is list:
                for message in messages:
                    self._capture(session_id, message)
        if kind == 'error':
            return True
        return kind == 'agent_settled'

    def outcome(self, value, *, session_id=None):
        kind = value.get('type')
        if kind == 'error':
            return 'failed', {'protocol': 'pi-rpc/1', 'event': kind,
                              'error': str(value.get('error') or value.get('message') or '')[:200]}
        observation = {'protocol': 'pi-rpc/1', 'event': kind}
        answer = self._messages.pop(session_id, None)
        if answer is not None:
            observation['answer'] = answer
        return 'completed', observation

    def encode_cancel(self, session_id, operation_ref):
        return encode_request(str(operation_ref), 'abort', {})


@dataclass(frozen=True)
class PiSession:
    """Native pi-rpc/1 session identity; no ledger, no grants."""
    session_id:str
    protocol_id:str='pi-rpc/1'


class PiProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return PiHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=PiProviderFactory()


class PiNativeCodec:
    """pi-rpc/1 dialect: type-tagged request frames and event streams."""

    protocol_id = 'pi-rpc/1'
    protocol_version = 1
    capabilities = frozenset({'request', 'events'})

    def encode_request(self, correlation_id, message):
        from ordessa_agents.sdk.native_codec import encode_frame, _object
        value = _object(message, 'native message')
        command = value.get('type')
        if type(command) is not str or not command:
            raise ValueError('pi native message needs type')
        params = {key: item for key, item in value.items() if key != 'type'}
        if 'id' in params:
            raise ValueError('pi native message must not carry its own id')
        return encode_frame({'id': str(correlation_id), 'type': command, **params})

    def classify(self, value):
        from ordessa_agents.sdk.native_codec import NativeCodecError, _object
        value = _object(value, 'native frame')
        kind = value.get('type')
        if type(kind) is not str or not kind:
            raise NativeCodecError('pi frame has no type')
        if kind == 'response':
            return 'response', str(value.get('id')), value.get('command')
        return 'notification', None, kind

    def terminal_state(self, value):
        if value.get('type') != 'response':
            raise ValueError('pi terminal classification expects a response frame')
        if value.get('success') is False:
            return 'failed'
        return 'completed'

    #: ``prompt`` returns a command ack; the turn terminal is ``agent_settled``.
    PENDING_REQUESTS = frozenset({'prompt'})

    def response_state(self, method, value):
        if method in self.PENDING_REQUESTS and value.get('success') is not False:
            return 'pending'
        return self.terminal_state(value)

    def notification_state(self, value, *, session_id=None, request=None, response=None):
        kind = value.get('type') if type(value) is dict else None
        if kind == 'agent_settled':
            return 'completed'
        if kind == 'error':
            return 'failed'
        return None


def native_codec():
    return PiNativeCodec()

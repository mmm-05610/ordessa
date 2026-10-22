"""codex preparation plus its own ``codex-app-server/1`` native bootstrap.

No Unit/provider ledger, direct client, permission lease or ACP translation:
the harness encodes its own JSON-RPC frames and the owner only guards the
physical write and observes the matching response.
"""
from ordessa_agents.sdk import HarnessDescriptor,HarnessError,PrepareContext,ProfileContent,LaunchPlan
from .native_channel import compile_config,ConfigRefusal
from .rpc import encode_request


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


class CodexHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('codex',definition_ref,implementation_digest,'codex-app-server/1',
            ('work','home','config','data','state','cache','tmp'),
            ('codex.configuration/1','credentials.file/1'))

    def _options(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options={}
        for declaration in content.declarations:
            if declaration.configuration_kind=='credentials.file':
                # Host-materialized credential binding: visible in the Profile,
                # never carrying the secret itself. This provider ignores it.
                _credential_binding(declaration)
                continue
            if (declaration.configuration_kind!='codex.configuration' or declaration.schema_version!='1'
                    or declaration.action!='value' or declaration.resource_refs):raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:values=dict(declaration.payload)
            except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options)&set(values):raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        try:compiled=compile_config(options)
        except (ConfigRefusal,ValueError,TypeError):raise HarnessError('CONFIGURATION_UNSUPPORTED') from None
        # ``model`` rides the app-server's own ``-c model=…`` override;
        # ``sandbox`` is protocol-pinned on ``thread/start`` and is accepted so a
        # sandboxed Environment (where Codex's inner bwrap has no user
        # namespaces) can choose ``danger-full-access`` — the outer environment
        # boundary stays the isolation. Everything else is still an explicit
        # refusal instead of a guessed wire key.
        unsupported=set(compiled['thread_params'])-{'model','sandbox'}
        sandbox=compiled['thread_params'].get('sandbox')
        if sandbox is not None and sandbox not in ('read-only','workspace-write','danger-full-access'):
            raise HarnessError('CONFIGURATION_INVALID')
        if unsupported or compiled['deferred']:raise HarnessError('SESSION_CONFIGURATION_UNAVAILABLE')
        return compiled

    def validate_profile(self,content):self._options(content)

    def prepare(self,content,context):
        compiled=self._options(content)
        sandbox=compiled['thread_params'].get('sandbox')
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        forbidden={'--allow-all','--allow-all-tools','--allow-all-paths','--yolo','--auto-approve','--yes','--dangerously-bypass-approvals-and-sandbox'}
        if any(token.split('=',1)[0] in forbidden for token in context.command_prefix):raise HarnessError('AUTO_APPROVAL_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','CODEX_HOME')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','APIKEY','API_KEY','CREDENTIAL')) for key in environment):raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb','NO_COLOR':'1'})
        if sandbox is not None:
            # A non-secret launch marker for this provider's own bootstrap step.
            environment['ORDESSA_CODEX_SANDBOX']=sandbox
        model=compiled['thread_params'].get('model')
        argv=context.command_prefix+('app-server',)
        if model is not None:
            if type(model) is not str or not model or len(model)>256:raise HarnessError('CONFIGURATION_INVALID')
            argv+=('-c','model="'+model+'"')
        argv+=tuple(compiled['args'])
        return LaunchPlan(argv,context.private_dirs['work'],environment,(),(),context.prepared_configuration_refs,
            context.materials,context.session_bootstrap,('launcher','communicate'))

    def prompt_handler(self):
        return CodexPromptHandler()

    def native_codec(self):
        return CodexNativeCodec()

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        # codex-app-server/1 is not ACP; never reuse its managed bootstrap with alien frames.
        raise HarnessError('NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE')

    async def open_native_session(self,process,context,plan=None):
        """Two JSON-RPC frames: initialize, then thread/start (native thread id).

        The frames come from this plugin's own codec; the owner only supplies a
        guarded exchange per frame and never parses the dialect.
        """
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        channel=getattr(process,'native_channel',None)
        if channel is None or not callable(getattr(channel,'exchange',None)):
            raise HarnessError('NATIVE_BOOTSTRAP_UNAVAILABLE')
        reply=await channel.exchange('initialize',
            lambda rid:encode_request(rid,'initialize',{'clientInfo':{'name':'ordessa-cli','version':'1'}}))
        if type(reply) is not dict or 'result' not in reply:raise HarnessError('NATIVE_BOOTSTRAP_INVALID')
        sandbox='workspace-write'
        if plan is not None:
            configured=getattr(plan,'environment_values',{}).get('ORDESSA_CODEX_SANDBOX')
            if configured in ('read-only','workspace-write','danger-full-access'):
                sandbox=configured
        reply=await channel.exchange('thread/start',
            lambda rid:encode_request(rid,'thread/start',{'approvalPolicy':'never','sandbox':sandbox}))
        if type(reply) is not dict or type(reply.get('result')) is not dict:
            raise HarnessError('NATIVE_BOOTSTRAP_INVALID')
        thread=reply['result'].get('thread')
        if type(thread) is not dict:raise HarnessError('NATIVE_BOOTSTRAP_INVALID')
        session_id=thread.get('sessionId') or thread.get('id')
        if (type(session_id) is not str or not session_id or len(session_id)>512
                or any(ord(char)<32 for char in session_id)):
            raise HarnessError('NATIVE_SESSION_INVALID')
        return CodexSession(session_id)


from dataclasses import dataclass


@dataclass(frozen=True)
class CodexSession:
    """Native codex-app-server/1 thread identity; no ledger, no grants."""
    session_id:str
    protocol_id:str='codex-app-server/1'


class CodexProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return CodexHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=CodexProviderFactory()


class CodexPromptHandler:
    """codex-app-server/1 prompt, completion and interrupt frames."""

    protocol_id = 'codex-app-server/1'

    def __init__(self):
        # Bounded per-session accumulation of completed agent messages.
        self._messages = {}

    def _remember(self, session_id, text):
        if type(text) is not str or not text:
            return
        self._messages[session_id] = text[-4096:]

    def encode_prompt(self, session_id, params_bytes, operation_ref):
        from ordessa_agents.sdk.native_prompt import prompt_text
        text = prompt_text(params_bytes)
        return encode_request(str(operation_ref), 'turn/start',
                              {'threadId': session_id, 'input': [{'type': 'text', 'text': text}]})

    def accept(self, value, *, session_id=None):
        method = value.get('method') if type(value) is dict else None
        if method == 'item/completed':
            params = value.get('params') or {}
            item = params.get('item') or {}
            if isinstance(item, dict) and item.get('type') in ('agentMessage', 'assistantMessage'):
                self._remember(params.get('threadId'), item.get('text') or item.get('content'))
            return False
        if method in ('turn/completed', 'turn/aborted'):
            params = value.get('params') or {}
            return params.get('threadId') in (None, session_id)
        if method == 'error':
            params = value.get('params') or {}
            error = params.get('error') if type(params.get('error')) is dict else {}
            # Codex reports retryable failures as an ``error`` notification
            # with ``willRetry`` set (``Reconnecting... 2/5``); the turn is not
            # terminal yet. Only a non-retryable error ends the operation.
            if error.get('willRetry') is True:
                return False
            return params.get('threadId') in (None, session_id)
        return False

    def outcome(self, value, *, session_id=None):
        method = value.get('method')
        params = value.get('params') or {}
        if method == 'error':
            error = params.get('error') or {}
            return 'failed', {'protocol': 'codex-app-server/1', 'method': method,
                              'turnId': params.get('turnId'),
                              'errorName': str(error.get('name') or error.get('type') or 'error')[:120],
                              'errorMessage': str(error.get('message') or '')[:400]}
        turn = params.get('turn') or {}
        status = turn.get('status')
        terminal = 'completed' if status in (None, 'completed') else (
            'failed' if status in ('failed', 'interrupted', 'aborted') else 'unknown')
        answer = self._messages.pop(session_id, None)
        observation = {'protocol': 'codex-app-server/1', 'method': method,
                       'turnId': turn.get('id'), 'turnStatus': status,
                       'items': len(turn.get('items') or ())}
        if answer is not None:
            observation['answer'] = answer
        return terminal, observation

    def encode_cancel(self, session_id, operation_ref):
        return encode_request(str(operation_ref), 'turn/interrupt', {'threadId': session_id})


def prompt_handler():
    return CodexPromptHandler()


class CodexNativeCodec:
    """codex-app-server/1 dialect: JSON-RPC requests, notifications, replies."""

    protocol_id = 'codex-app-server/1'
    protocol_version = 1
    capabilities = frozenset({'request', 'notify', 'events', 'reverse_requests'})

    def _params(self, message):
        from ordessa_agents.sdk.native_codec import _object
        value = _object(message, 'native message')
        if 'method' not in value:
            raise ValueError('codex native message needs method')
        params = value.get('params', {})
        if type(params) is not dict:
            raise ValueError('codex params must be an object')
        return value['method'], params, value

    def encode_request(self, correlation_id, message):
        from ordessa_agents.sdk.native_codec import encode_frame
        method, params, original = self._params(message)
        value = {'jsonrpc': '2.0', 'id': str(correlation_id),
                 'method': method, 'params': params}
        for key, item in original.items():
            if key not in ('method', 'params', 'id', 'jsonrpc'):
                value[key] = item
        return encode_frame(value)

    def encode_notify(self, message):
        from ordessa_agents.sdk.native_codec import encode_frame
        method, params, original = self._params(message)
        value = {'jsonrpc': '2.0', 'method': method, 'params': params}
        for key, item in original.items():
            if key not in ('method', 'params', 'id', 'jsonrpc'):
                value[key] = item
        return encode_frame(value)

    def classify(self, value):
        """Classify one app-server frame.

        The pinned codex app-server (0.157.1) omits ``jsonrpc`` on some responses,
        so classification is structural (method/id/result/error), not by a
        version field. Unknown shapes raise instead of being misread.
        """
        from ordessa_agents.sdk.native_codec import NativeCodecError, _object
        value = _object(value, 'native frame')
        has_method = 'method' in value
        has_id = 'id' in value
        has_result = 'result' in value
        has_error = 'error' in value
        if has_method and has_id:
            return 'reverse_request', str(value['id']), str(value['method'])
        if has_method:
            return 'notification', None, str(value['method'])
        if has_id and has_result != has_error:
            return 'response', str(value['id']), None
        raise NativeCodecError('codex frame is not a request, notification or response')

    def terminal_state(self, value):
        if 'error' in value:
            return 'failed'
        if 'result' not in value:
            raise ValueError('codex response has neither result nor error')
        return 'completed'

    #: Requests whose protocol response only acknowledges acceptance; the turn's
    #: terminal fact is a later notification (``turn/completed`` etc.).
    PENDING_REQUESTS = frozenset({'turn/start'})

    def response_state(self, method, value):
        """Protocol-level meaning of one response frame for its request method."""
        if method in self.PENDING_REQUESTS and 'error' not in value:
            return 'pending'
        return self.terminal_state(value)

    def notification_state(self, value, *, session_id=None, request=None, response=None):
        """A notification that ends an accepted operation, or None."""
        method = value.get('method') if type(value) is dict else None
        params = value.get('params') if type(value) is dict else None
        if type(params) is not dict:
            params = {}
        if request is not None:
            request_params = request.get('params', {})
            session_id = request_params.get('threadId', session_id)
        if session_id is not None and params.get('threadId') not in (None, session_id):
            return None
        if response is not None:
            accepted_turn = response.get('result', {}).get('turn', {}).get('id')
            observed_turn = params.get('turn', {}).get('id') or params.get('turnId')
            if accepted_turn is not None and observed_turn != accepted_turn:
                return None
        if method == 'error':
            error = params.get('error') if type(params.get('error')) is dict else {}
            # A retryable transport error is informational: codex reconnects by
            # itself. Treating it as terminal would fail long turns that are
            # still alive.
            if error.get('willRetry') is True:
                return None
            return 'failed'
        if method == 'turn/aborted':
            return 'failed'
        if method == 'turn/completed':
            turn = params.get('turn') if type(params.get('turn')) is dict else {}
            status = turn.get('status')
            if status in (None, 'completed'):
                return 'completed'
            if status in ('failed', 'interrupted', 'aborted'):
                return 'failed'
            return 'failed'
        return None

    def encode_reply(self, correlation_id, reply):
        from ordessa_agents.sdk.native_codec import NativeCodecError, encode_frame, _object
        reply = _object(reply, 'reply')
        has_result = 'result' in reply
        has_error = 'error' in reply
        if has_result == has_error:
            raise NativeCodecError('reply must carry exactly one of result/error')
        return encode_frame({'jsonrpc': '2.0', 'id': str(correlation_id), **reply})


def native_codec():
    return CodexNativeCodec()

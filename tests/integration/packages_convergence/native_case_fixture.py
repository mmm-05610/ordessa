"""Controlled real-process case for the ``agents.native.*`` surface (no model).

A real local pipe endpoint runs a Node peer that speaks the REAL
``codex-app-server/1`` dialect (initialize / thread/start / arbitrary requests),
so the production codex provider codec and the ONE native runtime are exercised
through the formal owner composition. Every non-bootstrap request is logged to
``native-effects.log``. No real brand binary and no model call is involved; real
Codex/Pi runs are separate evidence.
"""
from __future__ import annotations

import asyncio
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from ordessa_agents.public import InteractionService, Records
from ordessa_agents.sdk.interactions import InteractionsRefused
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from test_agent_guarded_bootstrap import setup

#: codex-app-server/1 controlled peer: the dialect the real provider codec uses.
CODEX_PEER = r'''import fs from 'node:fs';import readline from 'node:readline';
const thread='thread-1';
for await (const line of readline.createInterface({input:process.stdin})){
 const q=JSON.parse(line);let result;
 try{
  if(q.method==='initialize')result={};
  else if(q.method==='thread/start')result={thread:{id:thread,sessionId:thread}};
  else{
   fs.appendFileSync('native-effects.log',JSON.stringify({method:q.method,params:q.params})+'\n');
   result={ok:true,echo:q.params===undefined?null:q.params};
  }
  console.log(JSON.stringify({jsonrpc:'2.0',id:q.id,result}));
 }catch(error){console.log(JSON.stringify({jsonrpc:'2.0',id:q.id,error:{code:-32602,message:error.message}}));}
}
'''

NATIVE_OPERATIONS = ('agents.native.describe', 'agents.native.request',
                     'agents.native.notify', 'agents.native.query',
                     'agents.native.events', 'agents.native.respond')


class CaseAuthority:
    """Exact-grant authority over the original caller, including native ops."""

    def __init__(self, invocation, caller, issuer, scope):
        self._invocation = invocation
        self._caller = caller
        self._issuer = issuer
        self._scope = scope
        # Trusted composition reads the original instance authority here; it is
        # the SAME issuer, never a copy or a synthetic one.
        self.authority = issuer

    def _granted(self):
        principal = self._caller[0]
        self._issuer.verify(principal)
        return {capability for grant in principal.grants
                for capability in grant.capabilities}

    def _allow(self, operation):
        if operation not in self._granted():
            raise InteractionsRefused('ACTION_NOT_AUTHORIZED', operation)

    def principal_scope(self, invocation):
        if invocation is not self._invocation:
            raise InteractionsRefused('FORGED_INVOCATION')
        self._granted()
        return 'principal:' + self._caller[0].principal_id

    def check_read_binding(self, invocation, instance_ref):
        self._allow('agents.query')

    def check_read_turn(self, invocation, query):
        self._allow('agents.query')

    def check_send(self, invocation, binding):
        self._allow('agents.prompt')

    def check_native_describe(self, invocation, instance_ref):
        self._allow('agents.native.describe')

    def _write_operation(self, binding):
        from ordessa_agents.sdk.native_runtime import NativeDispatchBinding
        if type(binding) is not NativeDispatchBinding:
            raise InteractionsRefused('WRITE_BINDING_UNSUPPORTED')
        return {'request': 'agents.native.request', 'notify': 'agents.native.notify',
                'reply': 'agents.native.respond'}[binding.kind]

    def check_native_dispatch(self, invocation, binding):
        self._allow(self._write_operation(binding))

    @contextmanager
    def guard_native_dispatch(self, invocation, binding):
        self._allow(self._write_operation(binding))
        yield

    def check_read_native_operation(self, invocation, operation_ref, digest):
        self._allow('agents.native.query')

    def check_read_native_events(self, invocation, instance_ref):
        self._allow('agents.native.events')

    def check_native_respond(self, invocation, pending_ref):
        self._allow('agents.native.respond')

    @contextmanager
    def guard_write(self, binding, invocation):
        self._allow(self._write_operation(binding))
        yield


class DelegatingNativeAccess:
    """Native access that delegates the original checks and adds the native ones.

    Trusted test composition supplies the original invocation/principal/project
    mapping; this adapter creates no principal, grant or journal.
    """

    def __init__(self, base, issuer, *, caller_resolver, scope_for_agent,
                 principal_scope_for_caller, operations=NATIVE_OPERATIONS):
        self._base = base
        self._issuer = issuer
        self._caller_resolver = caller_resolver
        self._scope_for_agent = scope_for_agent
        self._principal_scope_for_caller = principal_scope_for_caller
        self._operations = frozenset(operations)
        self.authority = issuer

    def _caller(self, invocation):
        caller = self._caller_resolver(invocation)
        if caller is None:
            raise InteractionsRefused('AUTHORITY_UNAVAILABLE')
        self._issuer.verify(caller)
        return caller

    def _allow(self, operation):
        if operation not in self._operations:
            raise InteractionsRefused('ACTION_NOT_AUTHORIZED', operation)

    def principal_scope(self, invocation):
        self._caller(invocation)
        return self._base.principal_scope(invocation)

    def check_send(self, *args):
        return self._base.check_send(*args)

    def check_read_turn(self, *args):
        return self._base.check_read_turn(*args)

    def check_read_binding(self, *args):
        return self._base.check_read_binding(*args)

    def _write_operation(self, binding):
        from ordessa_agents.sdk.native_runtime import NativeDispatchBinding
        if type(binding) is not NativeDispatchBinding:
            raise InteractionsRefused('WRITE_BINDING_UNSUPPORTED')
        return {'request': 'agents.native.request', 'notify': 'agents.native.notify',
                'reply': 'agents.native.respond'}[binding.kind]

    def check_native_describe(self, invocation, instance_ref):
        self._caller(invocation)
        self._allow('agents.native.describe')

    def check_native_dispatch(self, invocation, binding):
        self._caller(invocation)
        self._allow(self._write_operation(binding))

    @contextmanager
    def guard_native_dispatch(self, invocation, binding):
        self._caller(invocation)
        self._allow(self._write_operation(binding))
        yield

    def check_read_native_operation(self, invocation, operation_ref, digest):
        self._caller(invocation)
        self._allow('agents.native.query')

    def check_read_native_events(self, invocation, instance_ref):
        self._caller(invocation)
        self._allow('agents.native.events')

    def check_native_respond(self, invocation, pending_ref):
        self._caller(invocation)
        self._allow('agents.native.respond')

    @contextmanager
    def guard_write(self, binding, invocation):
        self._caller(invocation)
        self._allow(self._write_operation(binding))
        yield


@dataclass(frozen=True)
class NativeCall:
    """One submit input plus the digest the registry derives from it."""

    instance_ref: object
    session_id: str
    request_id: str
    message: dict

    def projection(self):
        return {'instanceRef': self.instance_ref.projection(),
                'requestId': self.request_id, 'nativeMessage': self.message}

    @property
    def input_digest(self):
        from ordessa_agents.sdk.native_envelope import input_digest
        return input_digest(kind='request', protocol_id='codex-app-server/1',
                            session_id=self.session_id, message=self.message)


async def native_case(tmp_path, *, grants=True, start=True):
    """Prepare (and by default start) a controlled codex-app-server/1 instance.

    ``start=False`` leaves the instance to the consumer's own product manager.
    """
    case = await setup(tmp_path, CODEX_PEER, runner=(shutil.which('node'),),
                       peer_name='peer.mjs', brand='codex')
    started = None
    if start:
        started = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
        assert started.state == 'running'
    scope = Scope('fixture-realm', 'fixture-project')
    caps = (('agents.operations.read', 'agents.query', 'agents.prompt',
             *NATIVE_OPERATIONS) if grants else ())
    issuer = InstanceAccessAuthority(lambda: 'synthetic-native-token',
                                     principal_id='existing-test-caller',
                                     grants=(AccessGrant(scope, caps),) if caps else (),
                                     legacy_principal=None)
    caller = [issuer.authenticate('Bearer synthetic-native-token')]
    authority = CaseAuthority(case.fixture.invocation, caller, issuer, scope)
    catalog = case.manager.harness_resolver
    service = InteractionService(case.records, authority, case.fixture.resolver,
                                 native_prompts=catalog.prompt_handlers(),
                                 native_codecs=catalog.native_codecs())
    case.native = service
    case.native_access = authority
    case.issuer = issuer
    case.caller = caller
    case.scope = scope
    case.started = started
    case.effects = Path(case.prepared.native_working_directory) / 'native-effects.log'
    return case


def request(case, *, value='m2', purpose='apply', native_id='native-protocol-1'):
    """A new-surface request call; ``value`` keeps the effect-log vocabulary."""
    return NativeCall(case.started.instance_ref, case.started.session_id, native_id,
                      {'method': 'ordessa/probe',
                       'params': {'value': value, 'purpose': purpose}})


async def close(case):
    if case.native is not None:
        case.native.close()
    case.records.close()
    case.owner.close()
    await case.fixture.cleanup()


async def wait_completed(case, invoke, acceptance, *, timeout=5.0):
    """Poll the SAME public surface until the accepted operation is terminal."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    value = None
    while loop.time() < deadline:
        value = await invoke('agents.native.query',
                             {'operationRef': acceptance['operationRef']},
                             'native-query')
        if not isinstance(value, dict):
            value = {'status': value.status, 'data': value.data}
        if value['status'] == 'completed' and value['data']['state'] in (
                'completed', 'failed', 'refused'):
            return value['data']
        await asyncio.sleep(0.05)
    raise AssertionError('native operation did not reach a terminal state: %r' % (value,))


__all__ = ['CaseAuthority', 'DelegatingNativeAccess', 'NativeCall', 'native_case', 'request', 'close',
           'wait_completed', 'NATIVE_OPERATIONS', 'CODEX_PEER']

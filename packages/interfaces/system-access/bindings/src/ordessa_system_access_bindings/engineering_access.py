"""Bind a verified machine caller to the original Engineering access port.

The admission guard is acquired before SQLite and held through the use case's
commit and synchronous response construction. This adapter owns no ACL or
journal. Project grants must be explicitly configured by trusted composition;
it cannot infer a realm/project from a path or caller-supplied actor.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from dataclasses import dataclass
from threading import get_ident,current_thread
import asyncio,math,time

from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError


@dataclass
class _AdmissionLease:
    context: CommandContext
    caller: object
    operation: str
    thread_id: int
    task: object = None
    active: bool = True
    parked: bool = False
    handoff: object = None


def _task():
    try:return asyncio.current_task()
    except RuntimeError:return None


@dataclass
class _EffectHandoff:
    lease: _AdmissionLease
    context: CommandContext
    invocation_key: bytes
    action_instances: tuple
    target_thread: object
    expires_at: float
    task: object
    active: bool = True
    used: bool = False
    consuming: bool = False


class EngineeringCommandAccess:
    def __init__(self, authority):
        self.authority = authority
        self._active = ContextVar("engineering-command-admission", default=None)
        self._effect = ContextVar('engineering-effect-handoff',default=None)

    @contextmanager
    def admit(self, caller, scope, operation, *, request_id, trace_id):
        if type(scope) is not WireScope:
            raise ApplicationError("SCOPE_MISMATCH")
        with self.authority.guard(caller, scope, operation):
            # A shared instance bearer is a service caller, never a human.
            context = CommandContext(
                Scope(scope.realm_id, scope.project_id), caller.principal_id,
                ActorRef(caller.principal_id, "service", "instance-bearer"),
                request_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), trace_id,
            )
            lease = _AdmissionLease(context, caller, operation, get_ident(),_task())
            token = self._active.set(lease)
            try:
                yield context
            finally:
                # Context copies/tasks share this same lease object. Resetting
                # only the parent's ContextVar would leave their copy usable.
                lease.active = False
                self._active.reset(token)

    def require(self, context, operation):
        active = self._active.get()
        if (active is None or not active.active or active.thread_id != get_ident()
                or active.context is not context or active.operation != operation or active.task is not _task()):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        if active.parked and (active.handoff is None or self._effect.get() is not active.handoff
                or not active.handoff.consuming):
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.authority.verify(active.caller)

    @contextmanager
    def guard_current_capability(self,context,scope,capability):
        lease=self._active.get()
        if lease is None:raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.require(context,lease.operation)
        if (scope.realm_id,scope.project_id)!=(context.scope.realm_id,context.scope.project_id):
            raise ApplicationError('SCOPE_MISMATCH')
        with self.authority.guard(lease.caller,WireScope(scope.realm_id,scope.project_id),capability) as caller:
            yield caller

    @staticmethod
    def _validate_effect_binding(invocation_key,action_instances):
        if (type(invocation_key) is not bytes or len(invocation_key)!=32
                or type(action_instances) is not tuple or not action_instances
                or any(type(pair) is not tuple or len(pair)!=2
                    or any(type(value) is not str or not value or len(value)>512 for value in pair)
                    for pair in action_instances)
                or len(set(action_instances))!=len(action_instances)):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')

    @contextmanager
    def handoff_effect_write(self,context,*,invocation_key,action_instances,target_thread,expires_at,contract=None):
        if contract not in (None,'engineering.agent-effect-write/1'):
            raise ApplicationError('EFFECT_HANDOFF_CONTRACT_INVALID')
        lease=self._active.get()
        if lease is None:raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.require(context,lease.operation)
        self._validate_effect_binding(invocation_key,action_instances)
        if (lease.parked or lease.handoff is not None or target_thread is not current_thread()
                or type(expires_at) not in (int,float) or not math.isfinite(expires_at)
                or not time.monotonic()<expires_at<=time.monotonic()+60
                or not callable(getattr(self.authority,'suspend_guard',None))):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        handoff=_EffectHandoff(lease,context,invocation_key,action_instances,target_thread,expires_at,_task())
        lease.handoff=handoff
        try:
            with self.authority.suspend_guard(lease.caller,
                    WireScope(context.scope.realm_id,context.scope.project_id),lease.operation):
                lease.parked=True
                try:yield handoff
                finally:
                    handoff.active=False
                    lease.parked=False
        finally:
            handoff.active=False
            lease.handoff=None

    @contextmanager
    def consume_effect_write(self,handoff,context,*,invocation_key,action_instances):
        self._validate_effect_binding(invocation_key,action_instances)
        lease=self._active.get()
        if (type(handoff) is not _EffectHandoff or lease is None or handoff.lease is not lease
                or not lease.active or not lease.parked or lease.handoff is not handoff
                or handoff.context is not context or lease.context is not context
                or handoff.invocation_key!=invocation_key or handoff.action_instances!=action_instances
                or not handoff.active or handoff.used or handoff.target_thread is not current_thread()
                or handoff.task is not _task() or lease.task is not _task()
                or lease.thread_id!=get_ident() or time.monotonic()>=handoff.expires_at):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        handoff.used=True
        # The original authority independently checks current principal/grants
        # under the SAME lock, held only around this synchronous bounded cut.
        with self.authority.guard(lease.caller,WireScope(context.scope.realm_id,context.scope.project_id),lease.operation):
            token=self._effect.set(handoff)
            handoff.consuming=True
            try:
                self.require(context,lease.operation)
                yield
            finally:
                handoff.consuming=False
                self._effect.reset(token)


    @contextmanager
    def guard_agent_preparation_wait(self, context):
        lease=self._active.get()
        self.require(context,'engineering.executions.dispatch')
        if (lease is None or lease.task is not _task() or lease.parked or lease.handoff is not None):
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        with self.authority.suspend_guard(lease.caller,
                WireScope(context.scope.realm_id,context.scope.project_id),lease.operation):
            lease.parked=True
            try:yield
            finally:lease.parked=False
        self.require(context,lease.operation)

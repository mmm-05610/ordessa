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
import math
import time
from threading import RLock, Thread, current_thread, get_ident

from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_interfaces.system_access.access_control.authentication import AccessError
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_units.assembly import UnitRunPermission


@dataclass
class _AdmissionLease:
    context: CommandContext
    caller: object
    operation: str
    thread_id: int
    active: bool = True
    guard: object = None
    suspended: bool = False
    nested: bool = False
    capability_guards: int = 0
    parent: object = None
    work_parent: object = None
    expires_at: float = math.inf
    issued_task: object = None
    agent_task: object = None


@dataclass(eq=False)
class _EffectWriteHandoff:
    access: object
    lease: _AdmissionLease
    invocation_key: bytes
    action_instances: tuple
    target_thread: Thread
    expires_at: float
    credential_epoch: int
    active: bool = True
    consumed: bool = False



def _agent_task():
    import asyncio
    try:return asyncio.current_task()
    except RuntimeError:return None


@dataclass(eq=False)
class _AgentEffectWriteHandoff(_EffectWriteHandoff):
    task: object = None
    contract: str = 'engineering.agent-effect-write/1'


_DISPATCH = "engineering.executions.dispatch"
_WORK_INVOKE = "engineering.work.invoke"
_WORK_GET = "engineering.work.get"
_REVIEW_REQUEST = "engineering.reviews.request"
_REVIEW_ASSIGN = "engineering.reviews.assign_reviewer"
_NATIVE_PROMPT_OPERATIONS = frozenset({_DISPATCH, _REVIEW_REQUEST})
_WORK_PARENT_OPERATIONS = frozenset({_WORK_INVOKE, _WORK_GET})
_WORK_STEP_OPERATIONS = frozenset({
    _WORK_GET,
    "engineering.reviews.request",
    "engineering.reviews.record",
    "engineering.submissions.record_report",
    "engineering.proposals.associate_review",
    _DISPATCH,
})


class EngineeringCommandAccess:
    def __init__(self, authority):
        self.authority = authority
        self._active = ContextVar("engineering-command-admission", default=None)
        self._lease_lock = RLock()
        self._handoffs = {}

    @staticmethod
    def owner_scope(scope):
        """Use the same native scope conversion as original command admission."""
        if type(scope) is not WireScope:
            raise ApplicationError("SCOPE_MISMATCH")
        return Scope(scope.realm_id, scope.project_id)

    @contextmanager
    def admit(self, caller, scope, operation, *, request_id, trace_id):
        inherited = self._active.get()
        if inherited is not None and (inherited.suspended or inherited.parent is not None):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        if (inherited is not None and inherited.operation == _WORK_INVOKE
                and operation in _WORK_STEP_OPERATIONS):
            # Native Work children must pass through admit_work_step, which
            # releases/revalidates the parent authority lease. A generic
            # nested admit would retain the parent guard across child effects.
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        native_scope = self.owner_scope(scope)
        guard = self.authority.guard(caller, scope, operation)
        guard.__enter__()
        lease = None
        try:
            # A shared instance bearer is a service caller, never a human.
            context = CommandContext(
                native_scope, caller.principal_id,
                ActorRef(caller.principal_id, "service", "instance-bearer"),
                request_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), trace_id,
            )
            lease = _AdmissionLease(context, caller, operation, get_ident(),
                guard=guard, nested=self._active.get() is not None, issued_task=_agent_task())
            token = self._active.set(lease)
            try:
                yield context
            finally:
                # Context copies/tasks share this same lease object. Resetting
                # only the parent's ContextVar would leave their copy usable.
                with self._lease_lock:
                    lease.active = False
                self._active.reset(token)
        finally:
            # A handoff temporarily exits this exact guard and replaces it
            # only after original-authority revalidation, never during wait.
            held = guard if lease is None else lease.guard
            if held is not None:
                held.__exit__(None, None, None)

    def _current(self, context, operation=None):
        if (getattr(self._active.get(), 'agent_task', None) is not None
                and self._active.get().agent_task is not _agent_task()):
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        active = self._active.get()
        if (active is None or not active.active or active.suspended
                or active.thread_id != get_ident() or active.context is not context
                or operation is not None and active.operation != operation
                or active.parent is not None and (
                    not active.parent.active or not active.parent.suspended
                    or time.monotonic() >= active.expires_at)):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        return active

    def require(self, context, operation):
        active = self._current(context, operation)
        self.authority.verify(active.caller)

    def current_context(self):
        """Return this thread's actual issued request, never reconstruct one."""
        active = self._active.get()
        if active is None:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        self.require(active.context, active.operation)
        return active.context

    def check_work_capability(self, context, operation):
        """Check a capability against the exact active Work request identity.

        This read-only check uses the same issued caller and exact scope as the
        enclosing Work command. It never creates a grant or substitutes a
        caller-provided actor/principal.
        """
        active = self._current(context)
        if (active.operation not in _WORK_PARENT_OPERATIONS
                or active.nested or active.parent is not None
                or type(operation) is not str or not operation):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        scope = WireScope(context.scope.realm_id, context.scope.project_id)
        try:
            with self.authority.guard(active.caller, scope, operation):
                return True
        except AccessError:
            raise ApplicationError("ACCESS_DENIED") from None

    @contextmanager
    def admit_work_step(self, context, operation, *, request_id):
        """Run one native dispatch as an original-authority child of Work.invoke.

        The parent lease and its authority guard are suspended while the child
        goes through ordinary ``admit``. The parent is resumed only after a
        successful child exit and a fresh check of its exact original grant.
        """
        active = self._current(context)
        # The declared review runner may issue only its original reviewer
        # assignment command. It remains a child of the suspended Work lease.
        review_child = (active.operation == _REVIEW_REQUEST
            and operation == _REVIEW_ASSIGN
            and active.work_parent is not None
            and active.work_parent.operation == _WORK_INVOKE
            and active.work_parent.active and active.work_parent.suspended)
        work_child = active.operation == _WORK_INVOKE and operation in _WORK_STEP_OPERATIONS
        if (not (work_child or review_child)
                or active.parent is not None or active.nested
                or active.capability_guards or active.guard is None
                or active.suspended or type(request_id) is not str
                or not request_id or len(request_id) > 512
                or any(ord(char) < 32 for char in request_id)):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        with self._lease_lock:
            if any(token.active and token.lease is active for token in self._handoffs.values()):
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
            active.suspended = True
            parent_guard, active.guard = active.guard, None
        parent_token = self._active.set(None)
        child_succeeded = False
        resumed_guard = None
        try:
            try:
                parent_guard.__exit__(None, None, None)
            except BaseException as error:
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE") from error
            try:
                with self.admit(
                    active.caller,
                    WireScope(context.scope.realm_id, context.scope.project_id),
                    operation,
                    request_id=request_id,
                    trace_id=context.trace_id,
                ) as child_context:
                    child = self._current(child_context, operation)
                    child.work_parent = active
                    yield child_context
                    # A child may catch a failed bootstrap/handoff inside its
                    # body. Revalidate before treating that normal return as
                    # success, so an invalidated child cannot revive Work.
                    self.require(child_context, operation)
                child_succeeded = True
            except BaseException:
                # A failed step cannot continue under the suspended parent.
                raise
            if child_succeeded:
                try:
                    resumed_guard = self.authority.guard(
                        active.caller,
                        WireScope(context.scope.realm_id, context.scope.project_id),
                        active.operation,
                    )
                    resumed_guard.__enter__()
                except AccessError:
                    raise ApplicationError("ACCESS_DENIED") from None
                except BaseException as error:
                    raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE") from error
        except AccessError:
            with self._lease_lock:
                active.active = False
                active.suspended = False
                active.guard = None
            raise ApplicationError("ACCESS_DENIED") from None
        except BaseException:
            with self._lease_lock:
                active.active = False
                active.suspended = False
                active.guard = None
            raise
        else:
            with self._lease_lock:
                active.suspended = False
                active.guard = resumed_guard
        finally:
            self._active.reset(parent_token)

    @contextmanager
    def guard_unit_bootstrap(self, context, *, permission):
        """Temporarily yield authority-lock ownership to the original Unit owner.

        Unit bootstrap can perform SDK writes on another thread whose real
        UnitRunPermission must revalidate through this same InstanceAccessAuthority.
        Release only this dispatch lease while the Unit owner runs; the parent
        Work lease and every Unit effect guard retain their ordinary semantics.
        """
        active = self._current(context)
        scope = WireScope(context.scope.realm_id, context.scope.project_id)
        work_parent = active.work_parent
        if (active.operation not in _NATIVE_PROMPT_OPERATIONS
                or type(permission) is not UnitRunPermission
                or permission.access_authority is not self.authority
                or type(permission.scope) is not WireScope
                or permission.scope != scope
                or getattr(permission.principal, 'principal_id', None) != active.caller.principal_id
                or getattr(permission.principal, 'credential_epoch', None) != active.caller.credential_epoch
                or work_parent is None or not work_parent.active
                or not work_parent.suspended
                or work_parent.operation != _WORK_INVOKE
                or work_parent.thread_id != active.thread_id
                or work_parent.caller is not active.caller
                or work_parent.context.scope != context.scope
                or active.parent is not None or active.nested
                or active.capability_guards or active.guard is None
                or active.suspended):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        try:
            self.authority.verify(active.caller)
            self.authority.verify(permission.principal)
        except AccessError:
            raise ApplicationError("ACCESS_DENIED") from None
        except BaseException as error:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE") from error

        with self._lease_lock:
            if (active.suspended or active.guard is None
                    or any(token.active and token.lease is active
                           for token in self._handoffs.values())):
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
            active.suspended = True
            parent_guard, active.guard = active.guard, None
        resumed_guard = None
        try:
            try:
                parent_guard.__exit__(None, None, None)
            except BaseException as error:
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE") from error
            yield permission
            # UnitRunPermission performs its own action/expiry checks with its
            # original owner's clock at every native operation. Do not invent
            # a second expiry clock in this bridge.
            resumed_guard = self.authority.guard(
                active.caller, scope, active.operation)
            resumed_guard.__enter__()
        except AccessError:
            with self._lease_lock:
                active.active = False
                active.suspended = False
                active.guard = None
            raise ApplicationError("ACCESS_DENIED") from None
        except BaseException:
            with self._lease_lock:
                active.active = False
                active.suspended = False
                active.guard = None
            raise
        else:
            with self._lease_lock:
                active.guard = resumed_guard
                active.suspended = False

    @staticmethod
    def _effect_binding(invocation_key, action_instances, *, operation=_DISPATCH):
        if (type(invocation_key) is not bytes or len(invocation_key) != 32
                or type(action_instances) is not tuple
                or operation not in _NATIVE_PROMPT_OPERATIONS
                or (len(action_instances) != 0 if operation == _REVIEW_REQUEST
                    else not 1 <= len(action_instances) <= 4096)
                or any(type(pair) is not tuple or len(pair) != 2
                    or any(type(item) is not str or not item or len(item) > 512
                        or any(ord(c) < 32 for c in item) for item in pair)
                    for pair in action_instances)
                or len(set(action_instances)) != len(action_instances)):
            raise ApplicationError("EFFECT_HANDOFF_BINDING_INVALID")

    @contextmanager
    def handoff_effect_write(self, context, *, invocation_key, action_instances,
            target_thread, expires_at, contract=None):
        """Suspend only this dispatch guard while its original send waits.

        The opaque token permits one bounded ACP prompt byte-write cut on the
        selected original SDK Thread. Engineering owns the binding digest and
        actions; no business policy or new permission is interpreted here.
        """
        if contract is not None:
            if contract != 'engineering.agent-effect-write/1':
                raise ApplicationError('EFFECT_HANDOFF_CONTRACT_INVALID')
            with self._handoff_agent_effect_write(context, invocation_key=invocation_key,
                    action_instances=action_instances, target_thread=target_thread,
                    expires_at=expires_at) as handoff:
                yield handoff
            return
        active = self._current(context)
        self._effect_binding(invocation_key, action_instances, operation=active.operation)
        if (not isinstance(target_thread, Thread) or target_thread is current_thread()
                or not target_thread.is_alive() or type(expires_at) not in (int, float)
                or not math.isfinite(expires_at)
                or not time.monotonic() < expires_at <= time.monotonic() + 60):
            raise ApplicationError("EFFECT_HANDOFF_TARGET_INVALID")
        self.authority.verify(active.caller)
        with self._lease_lock:
            if (active.parent is not None or active.nested
                    or active.capability_guards or active.guard is None):
                raise ApplicationError("EFFECT_HANDOFF_NESTED_ADMISSION")
            handoff = _EffectWriteHandoff(self, active, invocation_key,
                action_instances, target_thread, expires_at,
                active.caller.credential_epoch)
            self._handoffs[id(handoff)] = handoff
            active.suspended = True
            guard, active.guard = active.guard, None
        guard.__exit__(None, None, None)
        try:
            yield handoff
        finally:
            with self._lease_lock:
                handoff.active = False
                self._handoffs.pop(id(handoff), None)
            # Wait only for a current bounded byte cut; no response/model wait
            # owns this lock. Do not revive a revoked principal on resumption.
            resumed = self.authority.guard(active.caller,
                WireScope(context.scope.realm_id, context.scope.project_id), active.operation)
            try:
                resumed.__enter__()
            except AccessError:
                with self._lease_lock:
                    active.active = False
                raise ApplicationError("ACCESS_DENIED") from None
            else:
                active.guard = resumed
            finally:
                with self._lease_lock:
                    active.suspended = False

    def _pending_effect_write(self, handoff):
        parent = handoff.lease
        inherited = self._active.get()
        if (self._handoffs.get(id(handoff)) is not handoff
                or not handoff.active or handoff.consumed
                or not parent.active or not parent.suspended
                or parent.operation not in _NATIVE_PROMPT_OPERATIONS
                or parent.caller.credential_epoch != handoff.credential_epoch
                or time.monotonic() >= handoff.expires_at
                or inherited is not None and inherited is not parent):
            raise ApplicationError("EFFECT_HANDOFF_UNAVAILABLE")

    @contextmanager
    def consume_effect_write(self, handoff, context, *, invocation_key,
            action_instances):
        """Revalidate and consume once around the original bounded byte cut.

        Consumers must leave this manager before waiting for a model response;
        the original Engineering/SDK deadline bounds the native write itself.
        """
        if type(handoff) is _AgentEffectWriteHandoff:
            with self._consume_agent_effect_write(handoff, context,
                    invocation_key=invocation_key, action_instances=action_instances):
                yield
            return
        if type(handoff) is not _EffectWriteHandoff:
            raise ApplicationError("EFFECT_HANDOFF_MISMATCH")
        self._effect_binding(invocation_key, action_instances, operation=handoff.lease.operation)
        if (handoff.access is not self
                or handoff.target_thread is not current_thread()
                or handoff.lease.context is not context
                or invocation_key != handoff.invocation_key
                or action_instances != handoff.action_instances):
            raise ApplicationError("EFFECT_HANDOFF_MISMATCH")
        parent = handoff.lease
        scope = WireScope(context.scope.realm_id, context.scope.project_id)
        # Retired/used tokens fail before trying the original authority lock;
        # they must not wait behind an unrelated resumed caller operation.
        with self._lease_lock:
            self._pending_effect_write(handoff)
        try:
            with self.authority.guard(parent.caller, scope, parent.operation):
                with self._lease_lock:
                    self._pending_effect_write(handoff)
                    handoff.consumed = True
                    delegated = _AdmissionLease(context, parent.caller, parent.operation,
                        get_ident(), parent=parent, expires_at=handoff.expires_at)
                    token = self._active.set(delegated)
                try:
                    yield
                finally:
                    delegated.active = False
                    try:
                        self._active.reset(token)
                    except ValueError:
                        # The original SDK enters with wait_for (one Task)
                        # and exits in its bounded cleanup Task, on this same
                        # SDK Thread. Reset tokens cannot cross Contexts. The
                        # shared inactive lease already revokes every captured
                        # child; clear only our own value in this exit Context.
                        if (current_thread() is not handoff.target_thread
                                or token.var is not self._active):
                            raise
                        if self._active.get() is delegated:
                            self._active.set(None)
        except AccessError:
            raise ApplicationError("ACCESS_DENIED") from None

    @contextmanager
    def guard_current_capability(self, context, scope, capability):
        """Hold an extra original-authority capability for this issued context.

        Trusted composition chooses the capability; no ActorRef or principal
        string can substitute for the caller issued to the active admission.
        """
        active = self._current(context)
        if (type(scope) is not WireScope
                or (context.scope.realm_id, context.scope.project_id) !=
                   (scope.realm_id, scope.project_id)):
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        if active.parent is not None:
            # A bounded native dispatch revalidates its already captured
            # confirmation source before bytes are written. Only that source
            # read is allowed under the consumed original handoff; this is not
            # admission to another command or a transfer of dispatch rights.
            with self._lease_lock:
                source_cut = (active.operation == _DISPATCH
                    and capability == 'engineering.conversation.attest'
                    and not active.nested
                    and active.caller is active.parent.caller
                    and active.parent.context is context
                    and any(token.active and token.consumed
                        and token.lease is active.parent
                        and token.target_thread is current_thread()
                        and token.credential_epoch == active.caller.credential_epoch
                        and time.monotonic() < token.expires_at
                        for token in self._handoffs.values()))
            if not source_cut:
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        try:
            with self.authority.guard(active.caller, scope, capability):
                active.capability_guards += 1
                try:
                    yield active.caller
                finally:
                    active.capability_guards -= 1
        except AccessError:
            raise ApplicationError("ACCESS_DENIED") from None


    @contextmanager
    def _handoff_agent_effect_write(self, context, *, invocation_key, action_instances,
                                    target_thread, expires_at):
        active = self._current(context, _DISPATCH)
        self._effect_binding(invocation_key, action_instances, operation=active.operation)
        task = _agent_task()
        if (task is None or active.issued_task is not task or target_thread is not current_thread()
                or type(expires_at) not in (int,float) or not math.isfinite(expires_at)
                or not time.monotonic() < expires_at <= time.monotonic()+60):
            raise ApplicationError('EFFECT_HANDOFF_TARGET_INVALID')
        self.authority.verify(active.caller)
        with self._lease_lock:
            if (active.parent is not None or active.nested or active.capability_guards
                    or active.guard is None or any(t.active and t.lease is active for t in self._handoffs.values())):
                raise ApplicationError('EFFECT_HANDOFF_NESTED_ADMISSION')
            handoff = _AgentEffectWriteHandoff(self,active,invocation_key,action_instances,
                target_thread,expires_at,active.caller.credential_epoch,task=task)
            self._handoffs[id(handoff)] = handoff
            active.suspended = True
            guard, active.guard = active.guard, None
        # Exit the original exact authority guard before yielding to SDK await.
        guard.__exit__(None,None,None)
        try:
            yield handoff
        finally:
            with self._lease_lock:
                handoff.active=False
                self._handoffs.pop(id(handoff),None)
            resumed=self.authority.guard(active.caller,
                WireScope(context.scope.realm_id,context.scope.project_id),active.operation)
            try:
                resumed.__enter__()
            except AccessError:
                with self._lease_lock:active.active=False
                raise ApplicationError('ACCESS_DENIED') from None
            else:active.guard=resumed
            finally:
                with self._lease_lock:active.suspended=False

    @contextmanager
    def _consume_agent_effect_write(self, handoff, context, *, invocation_key, action_instances):
        if (handoff.contract != 'engineering.agent-effect-write/1'
                or handoff.access is not self or handoff.target_thread is not current_thread()
                or handoff.task is None or handoff.task is not _agent_task()
                or handoff.lease.issued_task is not handoff.task
                or handoff.lease.context is not context
                or invocation_key != handoff.invocation_key or action_instances != handoff.action_instances):
            raise ApplicationError('EFFECT_HANDOFF_MISMATCH')
        self._effect_binding(invocation_key,action_instances,operation=handoff.lease.operation)
        parent=handoff.lease
        with self._lease_lock:self._pending_effect_write(handoff)
        try:
            with self.authority.guard(parent.caller,
                    WireScope(context.scope.realm_id,context.scope.project_id),parent.operation):
                with self._lease_lock:
                    self._pending_effect_write(handoff)
                    handoff.consumed=True
                    delegated=_AdmissionLease(context,parent.caller,parent.operation,get_ident(),
                        parent=parent,expires_at=handoff.expires_at,
                        issued_task=handoff.task,agent_task=handoff.task)
                    token=self._active.set(delegated)
                try:yield
                finally:
                    delegated.active=False
                    self._active.reset(token)
        except AccessError:
            raise ApplicationError('ACCESS_DENIED') from None


    @contextmanager
    def guard_agent_preparation_wait(self, context):
        """Release only this original same-task lease during endpoint lookup.

        This is not a send handoff or business grant. Source reservation remains
        original SDK state; return revalidates the same principal/operation.
        """
        active=self._current(context,_DISPATCH)
        task=_agent_task()
        if (task is None or active.issued_task is not task or active.parent is not None
                or active.nested or active.capability_guards or active.guard is None):
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.authority.verify(active.caller)
        with self._lease_lock:
            if any(t.active and t.lease is active for t in self._handoffs.values()):
                raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
            active.suspended=True
            guard,active.guard=active.guard,None
        guard.__exit__(None,None,None)
        try:yield
        finally:
            resumed=self.authority.guard(active.caller,
                WireScope(context.scope.realm_id,context.scope.project_id),active.operation)
            try:resumed.__enter__()
            except AccessError:
                active.active=False
                raise ApplicationError('ACCESS_DENIED') from None
            else:active.guard=resumed
            finally:active.suspended=False

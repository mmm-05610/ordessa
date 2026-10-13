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
    expires_at: float = math.inf


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


_DISPATCH = "engineering.executions.dispatch"


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
                guard=guard, nested=self._active.get() is not None)
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

    @staticmethod
    def _effect_binding(invocation_key, action_instances):
        if (type(invocation_key) is not bytes or len(invocation_key) != 32
                or type(action_instances) is not tuple
                or not 1 <= len(action_instances) <= 4096
                or any(type(pair) is not tuple or len(pair) != 2
                    or any(type(item) is not str or not item or len(item) > 512
                        or any(ord(c) < 32 for c in item) for item in pair)
                    for pair in action_instances)
                or len(set(action_instances)) != len(action_instances)):
            raise ApplicationError("EFFECT_HANDOFF_BINDING_INVALID")

    @contextmanager
    def handoff_effect_write(self, context, *, invocation_key, action_instances,
            target_thread, expires_at):
        """Suspend only this dispatch guard while its original send waits.

        The opaque token permits one bounded ACP prompt byte-write cut on the
        selected original SDK Thread. Engineering owns the binding digest and
        actions; no business policy or new permission is interpreted here.
        """
        self._effect_binding(invocation_key, action_instances)
        if (not isinstance(target_thread, Thread) or target_thread is current_thread()
                or not target_thread.is_alive() or type(expires_at) not in (int, float)
                or not math.isfinite(expires_at)
                or not time.monotonic() < expires_at <= time.monotonic() + 60):
            raise ApplicationError("EFFECT_HANDOFF_TARGET_INVALID")
        active = self._current(context, _DISPATCH)
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
                WireScope(context.scope.realm_id, context.scope.project_id), _DISPATCH)
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
                or parent.operation != _DISPATCH
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
        self._effect_binding(invocation_key, action_instances)
        if (type(handoff) is not _EffectWriteHandoff or handoff.access is not self
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
            with self.authority.guard(parent.caller, scope, _DISPATCH):
                with self._lease_lock:
                    self._pending_effect_write(handoff)
                    handoff.consumed = True
                    delegated = _AdmissionLease(context, parent.caller, _DISPATCH,
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
        if (active.parent is not None or type(scope) is not WireScope
                or (context.scope.realm_id, context.scope.project_id) !=
                   (scope.realm_id, scope.project_id)):
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

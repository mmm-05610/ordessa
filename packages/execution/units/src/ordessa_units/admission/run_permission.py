"""Finite execution permission backed by the host's current access authority.

This narrows an existing authenticated capability. It authenticates no human,
creates no host access grant, and cannot confer Engineering acceptance rights.
The handle protects against accidental copying/serialization in this process;
it is not a security boundary against arbitrary trusted Python code.
"""
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from threading import RLock
import time

from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from .invocation import InvocationAuthorityRefused, InvocationGrant

RUN_ACTIONS = frozenset({'prepare', 'start', 'interaction', 'stop', 'release'})


@dataclass(frozen=True)
class UnitRunPermission:
    """Trusted host selection narrowing a real, already granted access scope.

    ``access_authority`` is the host's existing identity owner (guard/verify);
    ``principal`` is its authenticated principal, not a caller-supplied name.
    Its exact scope must grant each ``execution.units.<action>`` explicitly.
    No default action, principal, expiry, directory or environment is supplied.
    """
    access_authority: object
    principal: object
    scope: object
    agent_id: str
    profile_revision: ProfileRevisionRef
    environment_identity: str
    root_directory: str
    actions: frozenset[str]
    expires_at: float

    def __post_init__(self):
        if (any(not callable(getattr(self.access_authority, name, None)) for name in ('guard', 'verify'))
                or not isinstance(getattr(self.principal, 'principal_id', None), str)
                or not self.principal.principal_id
                or type(self.profile_revision) is not ProfileRevisionRef
                or getattr(self.scope, 'realm_id', None) != self.profile_revision.environment_namespace
                or not isinstance(getattr(self.scope, 'project_id', None), str)
                or not self.scope.project_id
                or not isinstance(self.agent_id, str) or not self.agent_id
                or not isinstance(self.environment_identity, str) or not self.environment_identity
                or type(self.actions) is not frozenset or not self.actions or not self.actions <= RUN_ACTIONS
                or type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at)
                or not isinstance(self.root_directory, str) or not Path(self.root_directory).is_absolute()):
            raise InvocationAuthorityRefused('Explicit bounded authenticated Unit permission required')
        root = Path(self.root_directory)
        if root.resolve() != root or any(p.is_symlink() for p in (root, *root.parents)):
            raise InvocationAuthorityRefused('Unit permission directory must be canonical and non-symlink')
        # The real identity owner rejects fabricated/stale principal objects.
        self.access_authority.verify(self.principal)

    @property
    def principal_scope(self):
        return self.principal.principal_id

    @property
    def identity(self):
        facts = {'principalScope': self.principal_scope,
                 'scope': {'realmId': self.scope.realm_id, 'projectId': self.scope.project_id},
                 'credentialEpoch': getattr(self.principal, 'credential_epoch', None),
                 'agentId': self.agent_id, 'profileRevision': encode_revision_ref(self.profile_revision),
                 'environmentIdentity': self.environment_identity, 'rootDirectory': self.root_directory,
                 'actions': sorted(self.actions), 'expiresAt': self.expires_at}
        return 'sha256:' + hashlib.sha256(safe_json(facts).encode()).hexdigest()

    @contextmanager
    def guard(self, action, *, clock=time.time):
        if action not in self.actions or clock() >= self.expires_at:
            raise InvocationAuthorityRefused('Unit permission is expired or lacks this action')
        # This is the existing host access guard, with an exact capability.
        with self.access_authority.guard(self.principal, self.scope, 'execution.units.' + action):
            if clock() >= self.expires_at:
                raise InvocationAuthorityRefused('Unit permission expired during admission')
            yield self


class UnitRunAuthorization:
    """Identity-only, live owner handle; facts do not reproduce permission."""
    __slots__ = ()
    def __init__(self, *args, **kwargs):
        raise TypeError('Unit authorization is issued by its selected owner')
    def __copy__(self):
        raise TypeError('Unit authorization cannot be copied')
    def __deepcopy__(self, memo):
        return self.__copy__()
    def __reduce__(self):
        raise TypeError('Unit authorization cannot be serialized')


class LocalUnitInvocationAuthority:
    """Concrete invocation authority over one original store and permission."""
    def __init__(self, store, permission, *, owner_id, clock=time.time):
        if type(permission) is not UnitRunPermission:
            raise InvocationAuthorityRefused('Explicit UnitRunPermission required')
        self.store, self.permission, self.owner_id, self.clock = store, permission, owner_id, clock
        self.issuer_ref = sealed_mapping({'environmentNamespace': permission.profile_revision.environment_namespace,
                                         'issuerId': owner_id, 'permissionId': permission.identity})
        self._lock, self._closed = RLock(), False
        self._handle = object.__new__(UnitRunAuthorization)
        self._grants = {}
        self._revoke_connections = []

    def authorization(self):
        with self._lock:
            if self._closed:
                raise InvocationAuthorityRefused('Unit owner is closed')
            return self._handle

    @contextmanager
    def guard(self, action, authorization):
        with self._lock:
            if self._closed or authorization is not self._handle:
                raise InvocationAuthorityRefused('Original live Unit authorization required')
        with self.permission.guard(action, clock=self.clock):
            with self._lock:
                if self._closed:
                    raise InvocationAuthorityRefused('Unit owner was revoked')
            yield

    def _operation(self, request, actions, target_ref, delegation_ref):
        query = tuple(actions) == ('query',)
        if (len(actions) != 1 or (actions[0] not in RUN_ACTIONS and not query) or delegation_ref is not None
                or request.principal_scope != self.permission.principal_scope
                or request.environment_namespace != self.permission.profile_revision.environment_namespace):
            raise InvocationAuthorityRefused('Unit request differs from its bounded permission')
        operation = self.store.read_operation(request)
        expected_kind = 'unit-acp-query' if query else 'unit-public-' + actions[0]
        if operation is None or operation.intent.kind != expected_kind:
            raise InvocationAuthorityRefused('Original execution operation required')
        context = operation.intent.context_ref
        run = context.get('localUnitRun', {})
        if (run.get('ownerId') != self.owner_id or run.get('permissionId') != self.permission.identity
                or run.get('agentId') != self.permission.agent_id
                or run.get('environmentIdentity') != self.permission.environment_identity
                or safe_json(run.get('profileRevision')) != safe_json(encode_revision_ref(self.permission.profile_revision))
                or safe_json(context.get('nodeRef')) != safe_json(target_ref)):
            raise InvocationAuthorityRefused('Original operation scope differs from permission')
        if query:
            read = context.get('acpTurnRead')
            binding = context.get('invocationBindings', {}).get('read')
            # OperationIntent recursively seals JSON objects as MappingProxyType.
            # Validate the public mapping contract rather than requiring the
            # mutable dict representation used before persistence.
            if (not isinstance(read, Mapping)
                    or set(read) != {'unitRef', 'operationRef', 'expectedPromptInputDigest'}
                    or not isinstance(read.get('unitRef'), Mapping)
                    or not isinstance(read.get('operationRef'), str) or not read['operationRef']
                    or not isinstance(read.get('expectedPromptInputDigest'), str)
                    or not read['expectedPromptInputDigest'].startswith('sha256:')
                    or len(read['expectedPromptInputDigest']) != 71
                    or any(char not in '0123456789abcdef' for char in read['expectedPromptInputDigest'][7:])
                    or not isinstance(binding, Mapping)
                    or set(binding) != {'action', 'targetRef', 'delegationRef', 'cleanup'}
                    or binding.get('action') != 'query'
                    or safe_json(binding.get('targetRef')) != safe_json(target_ref)
                    or binding.get('delegationRef') is not None
                    or binding.get('cleanup') is not True):
                raise InvocationAuthorityRefused('Exact original Unit receipt query required')
        return operation

    def authorize(self, request, actions, target_ref, delegation_ref):
        action = actions[0] if len(actions) == 1 else ''
        # A query is a read-only receipt view within the existing interaction
        # permission. It does not add a host grant or UnitRunPermission action.
        permission_action = 'interaction' if action == 'query' else action
        with self.guard(permission_action, self._handle):
            self._operation(request, actions, target_ref, delegation_ref)
            grant = InvocationGrant(request.principal_scope, None, actions, target_ref,
                                    self.permission.identity, self.permission.expires_at, self.issuer_ref)
            self._grants[id(grant)] = grant
            return grant

    def revalidate(self, grant, request, actions, target_ref):
        action = actions[0] if len(actions) == 1 else ''
        permission_action = 'interaction' if action == 'query' else action
        with self.guard(permission_action, self._handle):
            if self._grants.get(id(grant)) is not grant:
                raise InvocationAuthorityRefused('Original authority-issued grant required')
            self._operation(request, actions, target_ref, grant.delegation_ref)
            return grant

    def revoke(self):
        with self._lock:
            self._closed = True
            self._grants.clear()
            callbacks = tuple(self._revoke_connections)
        for callback in callbacks:
            callback()


__all__ = ['UnitRunPermission', 'UnitRunAuthorization', 'LocalUnitInvocationAuthority']

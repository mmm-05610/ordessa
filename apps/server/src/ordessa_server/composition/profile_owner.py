"""Server-owned Profile owner on the original store, admission and key material.

Identity semantics belong here, not in a copied app helper: the admission policy is
bound to the configured instance principal scope and the namespace is the explicit
Profile environment, while authorization is the original instance authority
(`OriginalProfileAccess`). The store, request ledger and revision CAS stay with
`ProfileService`; this module only assembles and closes them in order.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from ordessa_agents.profiles import (
    ProfileAccessRefused,
    ProfileService,
    ProfileValidationError,
    SqliteProfileStore,
)
from ordessa_infrastructure.security.fingerprints import HmacKeyRing
from ordessa_infrastructure.security.keys import ensure_private_key
from ordessa_interfaces.system_access.access_control.authentication import VerifiedPrincipal
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_server.composition.agent_owner import AgentOwnerUnavailable


class ServerProfileFingerprint:
    """HMAC fingerprints over the same frame derivation the local CLI uses."""

    def __init__(self, material: bytes, *, scope: str) -> None:
        if type(material) is not bytes or len(material) != 32:
            raise AgentOwnerUnavailable('32-byte Profile fingerprint material required')
        self._ring = HmacKeyRing({'server-1': material}, active_key_id='server-1')
        self._scope = scope

    def describe(self):
        return self._ring.describe(comparison_scope='profile:' + self._scope)

    def fingerprint(self, request, surface, digest):
        frame = '|'.join((request.environment_namespace, request.principal_scope,
                          request.request_id, surface, digest)).encode('utf-8')
        return self._ring.sign(frame)


class ServerProfilePolicy:
    """Principal-bound, namespace-bound admission; no anonymous allow."""

    def __init__(self, principal_scope: str, namespace: str) -> None:
        self._principal = principal_scope
        self._prefix = f'{namespace}:agents.profile:'

    def admit_invoke(self, principal, method, mode):
        return (principal == self._principal and mode == 'reliable'
                and type(method) is str and method.startswith('pacthold.agents.profiles.'))

    def admit_object_access(self, principal, target, mode):
        return (principal == self._principal and mode in ('read', 'write')
                and type(target) is str and target.startswith(self._prefix))


class ServerProfileAdmission:
    """One open Profile namespace with its own lock, policy and fingerprint key."""

    def __init__(self, *, namespace: str, principal_scope: str, key_material: bytes) -> None:
        if type(namespace) is not str or not namespace:
            raise AgentOwnerUnavailable('explicit Profile namespace required')
        if type(principal_scope) is not str or not principal_scope:
            raise AgentOwnerUnavailable('explicit Profile principal scope required')
        self.namespace = namespace
        self.principal_scope = principal_scope
        self.admission_lock = RLock()
        self.policy = ServerProfilePolicy(principal_scope, namespace)
        self.fingerprint_port = ServerProfileFingerprint(key_material, scope=namespace)
        self._closed = False

    def check_open(self) -> None:
        if self._closed:
            raise ProfileValidationError('server Profile owner closed')

    def check_namespace(self, namespace: str) -> None:
        if namespace != self.namespace:
            raise ProfileValidationError('foreign Profile namespace')

    def close(self) -> None:
        self._closed = True


@dataclass
class ServerProfileOwner:
    """The single server-side Profile owner retained for the runtime's lifetime."""

    store: SqliteProfileStore
    admission: ServerProfileAdmission
    service: ProfileService
    guard: OriginalProfileAccess
    key_path: Path

    def close(self) -> None:
        self.admission.close()
        self.store.close()


def _caller_from_invocation(invocation):
    from ordessa_server.composition.invocation import principal_from_invocation
    try:
        return principal_from_invocation(invocation)
    except Exception:
        raise ProfileAccessRefused('verified instance caller required') from None


def build_server_profile_owner(
    root: Path,
    *,
    namespace: str,
    principal_scope: str,
    authority,
    scope: Scope,
    validator,
) -> ServerProfileOwner:
    """Assemble the Profile owner *inside an already owned root*.

    The fingerprint key is created 0600 on first use; the store and admission are
    closed in reverse order if any later construction step refuses.
    """
    if not isinstance(root, Path) or not root.is_absolute():
        raise AgentOwnerUnavailable('explicit absolute product root required')
    if type(scope) is not Scope:
        raise AgentOwnerUnavailable('explicit Profile authorization scope required')
    state = root / 'state'
    key_path = state / 'profile-fingerprint.key'
    key_material = ensure_private_key(key_path)
    store = SqliteProfileStore(state / 'profiles.sqlite')
    admission = ServerProfileAdmission(namespace=namespace, principal_scope=principal_scope,
                                       key_material=key_material)
    try:
        service = ProfileService(store, admission, validator)
    except BaseException:
        admission.close()
        store.close()
        raise
    guard = OriginalProfileAccess(
        authority,
        caller_resolver=_caller_from_invocation,
        scope_for_service=lambda _service: scope,
        principal_scope_for_caller=lambda caller: 'principal:' + caller.principal_id,
    )
    return ServerProfileOwner(store=store, admission=admission, service=service,
                              guard=guard, key_path=key_path)


__all__ = [
    "ServerProfileAdmission", "ServerProfileFingerprint", "ServerProfileOwner",
    "ServerProfilePolicy", "build_server_profile_owner",
]

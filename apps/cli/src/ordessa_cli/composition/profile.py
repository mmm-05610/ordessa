"""Local Profile admission and fingerprint provision on the ORIGINAL store/service.

The same OS-user principal, namespace, lock and key are used for every Profile
write. The fingerprint key is provisioned in the explicit state directory; no
fixture constant or allow-all policy is used.
"""
from __future__ import annotations

from contextlib import contextmanager
from threading import RLock

from ordessa_agents.profiles import (
    ProfileService, ProfileValidationError, ProfileAccessRefused, SqliteProfileStore,
)
from ordessa_infrastructure.security.fingerprints import HmacKeyRing

from .state import ensure_private_key


class LocalFingerprint:
    def __init__(self, material: bytes, *, scope: str):
        self._ring = HmacKeyRing({'local-1': material}, active_key_id='local-1')
        self._scope = scope

    def describe(self):
        return self._ring.describe(comparison_scope='profile:' + self._scope)

    def fingerprint(self, request, surface, digest):
        frame = '|'.join((request.environment_namespace, request.principal_scope,
                          request.request_id, surface, digest)).encode('utf-8')
        return self._ring.sign(frame)


class LocalProfilePolicy:
    """Principal-bound, namespace-bound local policy; no anonymous allow."""

    def __init__(self, principal_scope: str, namespace: str):
        self._principal = principal_scope
        self._prefix = f'{namespace}:agents.profile:'

    def admit_invoke(self, principal, method, mode):
        return (principal == self._principal and mode == 'reliable'
                and type(method) is str and method.startswith('pacthold.agents.profiles.'))

    def admit_object_access(self, principal, target, mode):
        return (principal == self._principal and mode in ('read', 'write')
                and type(target) is str and target.startswith(self._prefix))


class LocalProfileAdmission:
    def __init__(self, *, namespace: str, principal_scope: str, key_material: bytes):
        self.namespace = namespace
        self.principal_scope = principal_scope
        self.admission_lock = RLock()
        self.policy = LocalProfilePolicy(principal_scope, namespace)
        self.fingerprint_port = LocalFingerprint(key_material, scope=namespace)
        self._closed = False

    def check_open(self):
        if self._closed:
            raise ProfileValidationError('local Profile owner closed')

    def check_namespace(self, namespace):
        if namespace != self.namespace:
            raise ProfileValidationError('foreign Profile namespace')

    def close(self):
        self._closed = True


class LocalProfileGuard:
    """Synchronous scope check around one capability operation.

    Authorization is the local OS-user mapping; the Profile service still owns
    its own admission lock, revision CAS and request ledger.
    """

    def __init__(self, authority):
        self._authority = authority

    @contextmanager
    def guard(self, operation, invocation, service):
        if operation != 'agents.profiles.capabilities' and not operation.startswith('agents.profiles.'):
            raise ProfileAccessRefused('foreign operation')
        if invocation is None:
            raise ProfileAccessRefused('original invocation required')
        try:
            self._authority.verify(invocation)
        except Exception:
            raise ProfileAccessRefused('local principal unavailable') from None
        yield


class LocalProfileOwner:
    def __init__(self, *, store: SqliteProfileStore, admission: LocalProfileAdmission,
                 service: ProfileService, catalog, guard: LocalProfileGuard):
        self.store, self.admission, self.service = store, admission, service
        self.catalog, self.guard = catalog, guard

    def close(self):
        self.admission.close()
        self.store.close()


def build_profile_owner(*, store_path, namespace: str, principal_scope: str,
                        key_material: bytes, catalog, authority) -> LocalProfileOwner:
    store = SqliteProfileStore(store_path)
    admission = LocalProfileAdmission(namespace=namespace, principal_scope=principal_scope,
                                      key_material=key_material)
    guard = LocalProfileGuard(authority)
    try:
        service = ProfileService(store, admission, catalog)
    except BaseException:
        admission.close()
        store.close()
        raise
    return LocalProfileOwner(store=store, admission=admission, service=service,
                             catalog=catalog, guard=guard)


__all__ = ['LocalFingerprint', 'LocalProfileAdmission', 'LocalProfileGuard',
           'LocalProfileOwner', 'LocalProfilePolicy', 'ensure_private_key',
           'build_profile_owner']

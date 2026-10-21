"""Local foreground identity: the OS user's existing authority, no new grant.

This is process-local mapping for a local CLI. It is not a network credential,
policy store or portable authority value. Every owner adapter binds the same
principal scope to the same invocation object.
"""
from dataclasses import dataclass, field
import os

from ordessa_environments import EnvironmentRefused, OwnerScope


@dataclass(frozen=True)
class LocalInvocation:
    owner_scope: OwnerScope
    request_id: str
    _issuer: object = field(repr=False, compare=False)


class LocalForegroundAuthority:
    def __init__(self, *, actions):
        self._issuer = object()
        self._uid = os.getuid()
        self.scope = OwnerScope('principal', 'os-user:' + str(self._uid))
        self.actions = frozenset(actions)
        self._revoked = False

    @property
    def principal_scope(self):
        return f'{self.scope.kind}:{self.scope.ref}'

    def revoke(self):
        self._revoked = True

    def authenticate(self, command):
        if self._revoked or os.getuid() != self._uid:
            raise EnvironmentRefused('local OS subject changed or authority revoked')
        return {'kind': 'local-os-user', 'id': self.scope.ref}

    def resolve(self, context):
        if self._revoked or dict(context.principal) != self.authenticate(''):
            raise EnvironmentRefused('local foreground principal differs')
        return LocalInvocation(self.scope, context.request_id, self._issuer)

    def authorize(self, scope, action, target, invocation):
        return (type(invocation) is LocalInvocation and invocation._issuer is self._issuer
                and invocation.owner_scope == self.scope == scope
                and not self._revoked and os.getuid() == self._uid
                and action in self.actions)

    def verify(self, invocation):
        """Recheck the current local principal; return its stable scope string."""
        if (type(invocation) is not LocalInvocation or invocation._issuer is not self._issuer
                or invocation.owner_scope != self.scope or self._revoked
                or os.getuid() != self._uid):
            raise EnvironmentRefused('local invocation authority unavailable')
        return self.principal_scope


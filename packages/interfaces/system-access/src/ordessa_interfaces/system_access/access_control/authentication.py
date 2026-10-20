"""Single-process bearer identity and exact-scope access checks.

This is a composition mechanism, not a credential store or an OS security
boundary. The provider must quickly return the existing instance token. The
private issuer marker prevents accidental construction/serialization of a
verified principal; it cannot defend against arbitrary trusted Python code in
the same process.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import re
import threading
from typing import Callable, Iterator

from ..contracts.refs import Scope


_MAX_AUTHORIZATION_BYTES = 8192
_MAX_TOKEN_BYTES = 4096
_MAX_ITEMS = 4096
_MAX_EPOCH = (1 << 63) - 1
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,511}$")
_FORBIDDEN_CAPABILITIES = frozenset({
    "approval.grant", "record_consent",
    "engineering.approvals.grant", "engineering.approvals.record_consent",
})


class AccessError(RuntimeError):
    """Stable authorization failure; messages never contain credential data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _operation(value: object) -> str:
    if (type(value) is not str or not _IDENTIFIER.fullmatch(value)
            or "*" in value or value in _FORBIDDEN_CAPABILITIES
            or value.endswith(".approval.grant") or value.endswith(".record_consent")):
        raise AccessError("INVALID_CAPABILITY")
    return value


def _strict_tuple(value: object, *, code: str) -> tuple:
    if type(value) is not tuple or len(value) > _MAX_ITEMS:
        raise AccessError(code)
    return value


@dataclass(frozen=True)
class AccessGrant:
    """An immutable allow-list for one exact realm/project scope."""

    scope: Scope
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.scope) is not Scope:
            raise AccessError("INVALID_GRANT")
        capabilities = _strict_tuple(self.capabilities, code="INVALID_GRANT")
        normalized = tuple(_operation(item) for item in capabilities)
        if len(set(normalized)) != len(normalized):
            raise AccessError("INVALID_GRANT")
        object.__setattr__(self, "capabilities", normalized)


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Identity minted by one InstanceAccessAuthority after bearer checking."""

    principal_id: str
    kind: str
    grants: tuple[AccessGrant, ...]
    credential_epoch: int
    assurance: str = "instance-bearer"
    legacy_principal: str | None = None
    _issuer: object = field(default=None, repr=False, compare=False)
    _token_fingerprint: bytes = field(default=b"", repr=False, compare=False)

    def __post_init__(self) -> None:
        if (type(self.principal_id) is not str or not _IDENTIFIER.fullmatch(self.principal_id)
                or type(self.kind) is not str or self.kind != "machine"
                or type(self.assurance) is not str or self.assurance != "instance-bearer"):
            raise AccessError("INVALID_PRINCIPAL")
        grants = _strict_tuple(self.grants, code="INVALID_PRINCIPAL")
        if any(type(grant) is not AccessGrant for grant in grants):
            raise AccessError("INVALID_PRINCIPAL")
        if len({grant.scope for grant in grants}) != len(grants):
            raise AccessError("INVALID_PRINCIPAL")
        if (type(self.credential_epoch) is not int or not 0 <= self.credential_epoch <= _MAX_EPOCH
                or self.legacy_principal not in (None, "local")
                or type(self._token_fingerprint) is not bytes):
            raise AccessError("INVALID_PRINCIPAL")


class InstanceAccessAuthority:
    """One instance bearer credential with finite, exact-scope capabilities.

    ``token_provider`` supplies the current existing instance token and must
    be a fast in-process read (for example, a runtime value or process
    environment lookup). It must not perform network or blocking I/O. A
    verified request guard holds the authority lock through its caller's
    operation, so trusted revocation or grant replacement from another thread
    waits until that operation exits.
    """

    def __init__(self, token_provider: Callable[[], str], *, principal_id: str = "local",
                 grants: tuple[AccessGrant, ...], legacy_principal: str | None = "local"):
        if not callable(token_provider):
            raise AccessError("INVALID_AUTHORITY")
        if type(principal_id) is not str or not _IDENTIFIER.fullmatch(principal_id):
            raise AccessError("INVALID_PRINCIPAL")
        if legacy_principal not in (None, "local"):
            raise AccessError("INVALID_LEGACY_BINDING")
        if legacy_principal == "local" and principal_id != "local":
            raise AccessError("INVALID_LEGACY_BINDING")
        self._token_provider = token_provider
        self._principal_id = principal_id
        self._legacy_principal = legacy_principal
        self._issuer = object()
        self._lock = threading.RLock()
        self._guard_owner: int | None = None
        self._guard_depth = 0
        self._guard_bindings = []
        self._credential_epoch = 0
        self._revoked_fingerprint: bytes | None = None
        self._grants = self._validate_grants(grants)
        token = self._read_token()
        self._token_fingerprint = self._fingerprint(token)

    @staticmethod
    def _validate_grants(grants: object) -> tuple[AccessGrant, ...]:
        result = _strict_tuple(grants, code="INVALID_GRANT")
        if any(type(grant) is not AccessGrant for grant in result):
            raise AccessError("INVALID_GRANT")
        if len({grant.scope for grant in result}) != len(result):
            raise AccessError("INVALID_GRANT")
        return result

    def _read_token(self) -> str:
        try:
            token = self._token_provider()
        except Exception:
            raise AccessError("AUTHORITY_UNAVAILABLE") from None
        if type(token) is not str:
            raise AccessError("AUTHORITY_UNAVAILABLE")
        try:
            encoded = token.encode("ascii")
        except UnicodeEncodeError:
            raise AccessError("AUTHORITY_UNAVAILABLE") from None
        if not encoded or len(encoded) > _MAX_TOKEN_BYTES or any(byte <= 32 or byte >= 127 for byte in encoded):
            raise AccessError("AUTHORITY_UNAVAILABLE")
        return token

    @staticmethod
    def _fingerprint(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def _refresh_credential_locked(self) -> tuple[str, bytes]:
        token = self._read_token()
        fingerprint = self._fingerprint(token)
        if not hmac.compare_digest(fingerprint, self._token_fingerprint):
            self._advance_epoch_locked()
            self._token_fingerprint = fingerprint
        return token, fingerprint

    def _advance_epoch_locked(self) -> None:
        if self._credential_epoch >= _MAX_EPOCH:
            raise AccessError("AUTHORITY_EXHAUSTED")
        self._credential_epoch += 1

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def credential_epoch(self) -> int:
        with self._lock:
            return self._credential_epoch

    def authenticate(self, authorization: str) -> VerifiedPrincipal:
        """Verify an exact ``Bearer <instance-token>`` Authorization value."""
        if type(authorization) is not str:
            raise AccessError("AUTHENTICATION_REQUIRED")
        try:
            supplied = authorization.encode("utf-8")
        except UnicodeEncodeError:
            raise AccessError("AUTHENTICATION_REQUIRED") from None
        if not supplied or len(supplied) > _MAX_AUTHORIZATION_BYTES:
            raise AccessError("INVALID_AUTHORIZATION")
        with self._lock:
            token, fingerprint = self._refresh_credential_locked()
            expected = b"Bearer " + token.encode("ascii")
            if not hmac.compare_digest(supplied, expected):
                raise AccessError("AUTHENTICATION_REQUIRED")
            if self._revoked_fingerprint is not None and hmac.compare_digest(
                    fingerprint, self._revoked_fingerprint):
                raise AccessError("AUTHENTICATION_REQUIRED")
            return VerifiedPrincipal(
                principal_id=self._principal_id,
                kind="machine",
                grants=self._grants,
                credential_epoch=self._credential_epoch,
                assurance="instance-bearer",
                legacy_principal=self._legacy_principal,
                _issuer=self._issuer,
                _token_fingerprint=fingerprint,
            )

    def _verify_locked(self, principal: VerifiedPrincipal) -> None:
        if type(principal) is not VerifiedPrincipal or principal._issuer is not self._issuer:
            raise AccessError("INVALID_PRINCIPAL")
        _token, fingerprint = self._refresh_credential_locked()
        if (principal.principal_id != self._principal_id
                or principal.legacy_principal != self._legacy_principal
                or principal.credential_epoch != self._credential_epoch
                or self._revoked_fingerprint == fingerprint
                or not hmac.compare_digest(principal._token_fingerprint, fingerprint)):
            raise AccessError("AUTHORIZATION_STALE")

    def verify(self, principal: VerifiedPrincipal) -> None:
        """Recheck an observation lease; do not hold a lock across async waits."""
        with self._lock:
            self._verify_locked(principal)

    @contextmanager
    def guard(self, principal: VerifiedPrincipal, scope: Scope,
              operation: str) -> Iterator[VerifiedPrincipal]:
        """Validate exact scope/capability and hold the lock through caller work."""
        self._lock.acquire()
        owner = threading.get_ident()
        if self._guard_owner not in (None, owner):
            # RLock acquisition cannot pass an active other-thread guard; this
            # branch is defensive if lock mechanics are ever changed.
            self._lock.release()
            raise AccessError("AUTHORIZATION_BUSY")
        try:
            self._verify_locked(principal)
            if type(scope) is not Scope:
                raise AccessError("INVALID_SCOPE")
            capability = _operation(operation)
            grant = next((item for item in self._grants if item.scope == scope), None)
            principal_grant = next((item for item in principal.grants if item.scope == scope), None)
            if (grant is None or principal_grant is None
                    or capability not in grant.capabilities
                    or capability not in principal_grant.capabilities):
                raise AccessError("ACCESS_DENIED")
            if self._guard_owner == owner:
                self._guard_depth += 1
            else:
                self._guard_owner = owner
                self._guard_depth = 1
            binding=(principal,scope,capability)
            self._guard_bindings.append(binding)
            try:
                yield principal
            finally:
                if not self._guard_bindings or self._guard_bindings[-1] is not binding:
                    raise AccessError('AUTHORIZATION_GUARD_INVALID')
                self._guard_bindings.pop()
                self._guard_depth -= 1
                if self._guard_depth == 0:
                    self._guard_owner = None
        finally:
            self._lock.release()

    @contextmanager
    def suspend_guard(self,principal,scope,operation):
        """Park exactly one current typed guard across an external response wait.

        This transfers no grant. The SAME authority lock is reacquired and the
        original principal/grant rechecked before original guarded work resumes.
        Nested/legacy guards cannot be parked. Caller enforces its task binding.
        """
        owner=threading.get_ident();capability=_operation(operation)
        if (self._guard_owner!=owner or self._guard_depth!=1 or len(self._guard_bindings)!=1):
            raise AccessError('AUTHORIZATION_GUARD_INVALID')
        original=self._guard_bindings[0]
        if original[0] is not principal or original[1]!=scope or original[2]!=capability:
            raise AccessError('AUTHORIZATION_GUARD_INVALID')
        self._verify_locked(principal)
        self._guard_bindings.pop();self._guard_owner=None;self._guard_depth=0
        self._lock.release()
        try:yield
        finally:
            self._lock.acquire()
            # Balance the original outer context even if another same-thread
            # task holds a reentrant guard: refuse resumption rather than claim
            # its authority, and let each original context release its own lock.
            busy=self._guard_depth!=0
            self._guard_bindings.append(original);self._guard_owner=owner;self._guard_depth+=1
            if busy:raise AccessError('AUTHORIZATION_BUSY')
            self._verify_locked(principal)
            grant=next((item for item in self._grants if item.scope==scope),None)
            observed=next((item for item in principal.grants if item.scope==scope),None)
            if (grant is None or observed is None or capability not in grant.capabilities
                    or capability not in observed.capabilities):raise AccessError('ACCESS_DENIED')

    @contextmanager
    def guard_legacy(self, principal: VerifiedPrincipal) -> Iterator[VerifiedPrincipal]:
        """Hold identity validity for the legacy local principal, not ACL."""
        with self._lock:
            self._verify_locked(principal)
            if principal.legacy_principal != "local" or self._legacy_principal != "local":
                raise AccessError("LEGACY_IDENTITY_UNAVAILABLE")
            owner = threading.get_ident()
            if self._guard_owner == owner:
                self._guard_depth += 1
            else:
                self._guard_owner = owner
                self._guard_depth = 1
            try:
                yield principal
            finally:
                self._guard_depth -= 1
                if self._guard_depth == 0:
                    self._guard_owner = None

    def _refuse_reentrant_mutation_locked(self) -> None:
        if self._guard_owner == threading.get_ident() and self._guard_depth:
            raise AccessError("AUTHORIZATION_GUARD_ACTIVE")

    def revoke(self) -> int:
        """Disable this credential until the trusted provider rotates its token."""
        with self._lock:
            self._refuse_reentrant_mutation_locked()
            _token, fingerprint = self._refresh_credential_locked()
            self._advance_epoch_locked()
            self._revoked_fingerprint = fingerprint
            return self._credential_epoch

    def invalidate(self) -> int:
        """Retire issued leases at a runtime-round boundary, keeping the token."""
        with self._lock:
            self._refuse_reentrant_mutation_locked()
            self._advance_epoch_locked()
            return self._credential_epoch

    def replace_grants(self, grants: tuple[AccessGrant, ...]) -> int:
        """Atomically replace exact grants and invalidate old principals."""
        with self._lock:
            self._refuse_reentrant_mutation_locked()
            validated = self._validate_grants(grants)
            self._advance_epoch_locked()
            self._grants = validated
            return self._credential_epoch

"""Protected fingerprint port over HMAC-SHA256 (spec 026/005 T005-04).

The MAC encoding frozen in 002 (guarantee-levels.md §request-key): the key
material comes from an injected opaque byte string (a platform secret port
supplies it in production); a TEMPORARY TEST KEY is legitimate only in
fixtures. Rotation retires a key id: comparisons against retired keys raise
``ComparisonUnavailableError`` while the spent tombstones (stored in the
SqliteStorePort) still block re-dispatch — the tombstone is never dropped to
make a retry possible.
"""
from __future__ import annotations

import hashlib
import hmac

from ordessa_environment_api import (
    ComparisonUnavailableError,
    FingerprintDescriptor,
    RequestKey,
)
from ordessa_environment_api.errors import EnvironmentError


class ProtectedFingerprintHmac:
    """Implements ProtectedFingerprintPort with domain-separated HMAC keys."""

    ALGORITHM = "hmac-sha256"

    def __init__(self, keys: dict[str, bytes], *, active_key_id: str,
                 tombstone_check=None) -> None:
        if active_key_id not in keys:
            raise EnvironmentError(f"active key id {active_key_id!r} has no material")
        self._keys = dict(keys)
        self._active = active_key_id
        self._tombstone_check = tombstone_check or (lambda key_id: False)

    def rotate(self, new_key_id: str, material: bytes) -> None:
        """Rotation mints a new revision; the old id stays known-but-retired."""
        if new_key_id in self._keys:
            raise EnvironmentError(f"key id {new_key_id!r} already exists")
        self._keys[new_key_id] = material
        self._active = new_key_id

    def describe(self) -> FingerprintDescriptor:
        return FingerprintDescriptor(
            algorithm=self.ALGORITHM, key_id=self._active,
            comparison_scope="request-input",
        )

    def fingerprint(self, key: RequestKey, binding_digest: str, content_digest: str) -> str:
        material = self._keys.get(self._active)
        if material is None:
            raise ComparisonUnavailableError(
                f"key {self._active!r} has no material; refusing before dispatch"
            )
        message = "|".join((
            key.environment_namespace, key.principal_scope, key.request_id,
            binding_digest, content_digest,
        )).encode("utf-8")
        return hmac.new(material, message, hashlib.sha256).hexdigest()

    def verify(self, key_id: str, mac: str, key: RequestKey, binding_digest: str,
               content_digest: str) -> bool:
        """Comparison against a possibly-retired key id (history reads)."""
        if self._tombstone_check(key_id) and key_id != self._active:
            # retired-and-tombstoned keys stay comparable only through the
            # authorized history path — the tombstone blocks re-dispatch
            # regardless of the verification outcome
            raise ComparisonUnavailableError(
                f"key {key_id!r} is retired; tombstone keeps the request spent"
            )
        material = self._keys.get(key_id)
        if material is None:
            raise ComparisonUnavailableError(f"key {key_id!r} material is gone")
        return hmac.compare_digest(mac, self._recompute(material, key, binding_digest, content_digest))

    def _recompute(self, material: bytes, key: RequestKey, binding_digest: str,
                   content_digest: str) -> str:
        message = "|".join((
            key.environment_namespace, key.principal_scope, key.request_id,
            binding_digest, content_digest,
        )).encode("utf-8")
        return hmac.new(material, message, hashlib.sha256).hexdigest()

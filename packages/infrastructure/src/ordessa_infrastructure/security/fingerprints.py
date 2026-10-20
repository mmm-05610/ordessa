"""Keyed HMAC fingerprints and explicit key-availability failures.

Callers own input framing, admission policy and persisted no-replay fences.
This mechanism never reads credentials, stores requests, or retries effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Callable, Mapping


@dataclass(frozen=True)
class FingerprintDescriptor:
    algorithm: str
    key_id: str
    comparison_scope: str

    def __post_init__(self):
        algorithm = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
        if not isinstance(self.algorithm, str) or not algorithm.match(self.algorithm):
            raise ValueError("FingerprintDescriptor.algorithm is malformed")
        if not isinstance(self.key_id, str) or not re.match(r"^[a-z0-9][a-z0-9._:-]{0,127}$", self.key_id):
            raise ValueError("key id is malformed")
        if not isinstance(self.comparison_scope, str) or not algorithm.match(
            self.comparison_scope.replace(":", "-").replace("_", "-")
        ) and ":" not in self.comparison_scope:
            raise ValueError("FingerprintDescriptor.comparison_scope is malformed")


class FingerprintUnavailable(RuntimeError):
    """The requested key cannot be used for this comparison."""


class FingerprintKeyConflict(ValueError):
    """A key ID was reused or the selected signing key is absent."""


class HmacKeyRing:
    algorithm = "hmac-sha256"

    def __init__(self, keys: Mapping[str, bytes], *, active_key_id: str,
                 retired: Callable[[str], bool] | None = None):
        if active_key_id not in keys:
            raise FingerprintKeyConflict(f"active key id {active_key_id!r} has no material")
        self._keys = dict(keys)
        self._active = active_key_id
        self._retired = retired if retired is not None else lambda key_id: False

    def describe(self, *, comparison_scope: str) -> FingerprintDescriptor:
        return FingerprintDescriptor(self.algorithm, self._active, comparison_scope)

    def rotate(self, key_id: str, material: bytes) -> None:
        if key_id in self._keys:
            raise FingerprintKeyConflict(f"key id {key_id!r} already exists")
        self._keys[key_id] = material
        self._active = key_id

    def sign(self, message: bytes) -> str:
        material = self._keys.get(self._active)
        if material is None:
            raise FingerprintUnavailable(f"key {self._active!r} material is gone")
        return hmac.new(material, message, hashlib.sha256).hexdigest()

    def verify(self, key_id: str, mac: str, message: bytes) -> bool:
        if self._retired(key_id) and key_id != self._active:
            raise FingerprintUnavailable(f"key {key_id!r} is retired")
        material = self._keys.get(key_id)
        if material is None:
            raise FingerprintUnavailable(f"key {key_id!r} material is gone")
        return hmac.compare_digest(mac, hmac.new(material, message, hashlib.sha256).hexdigest())

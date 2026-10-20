"""Unit complete-input framing over the Infrastructure HMAC mechanism.

Retired keys refuse comparison; original spent request fences remain in the
Unit store. Required comparison failures never downgrade or replay a request.
"""
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.security.fingerprints import (
    FingerprintDescriptor, FingerprintKeyConflict, FingerprintUnavailable, HmacKeyRing,
)
from ordessa_units.errors import UnitComparisonUnavailable, UnitGuaranteeUnavailable


class ProtectedFingerprintHmac:
    ALGORITHM = "hmac-sha256"

    def __init__(self, keys: dict[str, bytes], *, active_key_id: str,
                 tombstone_check=None) -> None:
        try:
            self._key_ring = HmacKeyRing(keys, active_key_id=active_key_id, retired=tombstone_check)
        except FingerprintKeyConflict as error:
            raise UnitGuaranteeUnavailable(str(error)) from error

    def rotate(self, new_key_id: str, material: bytes) -> None:
        try:
            self._key_ring.rotate(new_key_id, material)
        except FingerprintKeyConflict as error:
            raise UnitGuaranteeUnavailable(str(error)) from error

    def describe(self) -> FingerprintDescriptor:
        return self._key_ring.describe(comparison_scope="request-input")

    @staticmethod
    def _input(key: RequestKey, binding_digest: str, content_digest: str) -> bytes:
        return "|".join((key.environment_namespace, key.principal_scope,
                         key.request_id, binding_digest, content_digest)).encode("utf-8")

    def fingerprint(self, key: RequestKey, binding_digest: str, content_digest: str) -> str:
        try:
            return self._key_ring.sign(self._input(key, binding_digest, content_digest))
        except FingerprintUnavailable as error:
            raise UnitComparisonUnavailable(str(error)) from error

    def verify(self, key_id: str, mac: str, key: RequestKey, binding_digest: str,
               content_digest: str) -> bool:
        try:
            return self._key_ring.verify(key_id, mac, self._input(key, binding_digest, content_digest))
        except FingerprintUnavailable as error:
            raise UnitComparisonUnavailable(str(error)) from error

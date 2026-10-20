"""Required complete-input fingerprint port for Unit admission."""
from typing import Protocol, runtime_checkable

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.security.fingerprints import FingerprintDescriptor


@runtime_checkable
class ProtectedFingerprintPort(Protocol):
    def describe(self) -> FingerprintDescriptor: ...

    def fingerprint(self, key: RequestKey, binding_digest: str, content_digest: str) -> str:
        """Compare complete input without weakening the spent-request fence."""
        ...

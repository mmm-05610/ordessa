"""Secret-store contract; bytes and persisted locator meanings unchanged."""
from pathlib import Path
from typing import Protocol

MAX_SECRET_BYTES = 1024 * 1024


class SecretStore(Protocol):
    def import_file(self, source: Path, kind: str) -> tuple[str, str]: ...
    def read(self, locator: str) -> bytes: ...
    def delete(self, locator: str) -> None: ...


class SecretLocatorUnavailable(RuntimeError):
    """A recorded credential's locator is not resolvable in the store.

    Typed (``code = CREDENTIAL_NOT_AVAILABLE``) so ``_safe_code`` surfaces it as
    the execution reason instead of a reasonless ``EXECUTION_FAILED``. The
    message carries only the non-sensitive locator id and why it cannot be read;
    no secret bytes are ever included.
    """

    code = "CREDENTIAL_NOT_AVAILABLE"

    def __init__(self, locator: str) -> None:
        self.locator = locator
        super().__init__(
            f"credential locator {locator!r} is not available on this machine "
            "(the credential was never imported here, or was removed); "
            "select a profile whose credential is present")



__all__ = ["SecretStore", "MAX_SECRET_BYTES", "SecretLocatorUnavailable"]

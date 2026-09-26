"""Windows current-user DPAPI store for explicitly imported credential bytes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import csv
import io
import os
from pathlib import Path
import subprocess
from typing import Protocol
from uuid import uuid4


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


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(content: bytes) -> tuple[_Blob, object]:
    buffer = ctypes.create_string_buffer(content)
    return _Blob(len(content), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_functions():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    arguments = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    crypt32.CryptProtectData.argtypes = arguments
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


class WindowsDpapiSecretStore:
    def __init__(self, data_root: Path | str) -> None:
        if os.name != "nt":
            raise RuntimeError("SECRET_STORE_WINDOWS_REQUIRED")
        self.root = Path(data_root).resolve() / "secrets" / "credentials"

    def import_file(self, source: Path, kind: str) -> tuple[str, str]:
        del kind
        if source.is_symlink() or not source.is_file():
            raise ValueError("CREDENTIAL_SOURCE_INVALID")
        source = source.resolve(strict=True)
        size = source.stat().st_size
        if size <= 0 or size > MAX_SECRET_BYTES:
            raise ValueError("CREDENTIAL_SOURCE_OUTSIDE_BOUND")
        content = source.read_bytes()
        try:
            protected = self._protect(content)
        finally:
            content = b""
        credential_id = f"credential_{uuid4().hex}"
        locator = f"{credential_id}.dpapi"
        self.root.mkdir(parents=True, exist_ok=True)
        self._protect_acl(self.root)
        target = self.root / locator
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(protected)
            stream.flush()
            os.fsync(stream.fileno())
        self._protect_acl(target)
        return credential_id, locator

    def read(self, locator: str) -> bytes:
        if not locator.endswith(".dpapi") or Path(locator).name != locator:
            raise ValueError("CREDENTIAL_LOCATOR_INVALID")
        path = self.root / locator
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SECRET_BYTES * 2:
            raise ValueError("CREDENTIAL_UNAVAILABLE")
        return self._unprotect(path.read_bytes())

    def delete(self, locator: str) -> None:
        if not locator.endswith(".dpapi") or Path(locator).name != locator:
            raise ValueError("CREDENTIAL_LOCATOR_INVALID")
        path = self.root / locator
        if path.exists():
            path.unlink()

    @staticmethod
    def _protect(content: bytes) -> bytes:
        source, source_buffer = _blob(content)
        output = _Blob()
        crypt32, kernel32 = _dpapi_functions()
        if not crypt32.CryptProtectData(
            ctypes.byref(source), "AgentBox Server credential", None, None, None,
            0x01, ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
            del source_buffer

    @staticmethod
    def _unprotect(content: bytes) -> bytes:
        source, source_buffer = _blob(content)
        output = _Blob()
        crypt32, kernel32 = _dpapi_functions()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
            del source_buffer

    @staticmethod
    def _protect_acl(path: Path) -> None:
        identity = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout
        fields = next(csv.reader(io.StringIO(identity)))
        if len(fields) < 2 or not fields[1].startswith("S-"):
            raise RuntimeError("WINDOWS_IDENTITY_UNAVAILABLE")
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{fields[1]}:(F)"],
            check=True, capture_output=True, text=True, timeout=5,
        )


@dataclass
class MemorySecretStore:
    """Explicitly injected deterministic store for tests; never default composition."""
    values: dict[str, bytes]

    def import_file(self, source: Path, kind: str) -> tuple[str, str]:
        del kind
        credential_id = f"credential_{uuid4().hex}"
        self.values[credential_id] = source.read_bytes()
        return credential_id, credential_id

    def read(self, locator: str) -> bytes:
        # Order 120: a locator that is not in the store is a decidable
        # configuration fact, not a Python bookkeeping accident. Raising the raw
        # ``KeyError`` let it collapse into a reasonless ``EXECUTION_FAILED`` far
        # from where the cause is known; name the (non-sensitive) locator so the
        # failure stays typed and actionable. The value is never in the message.
        try:
            return self.values[locator]
        except KeyError:
            raise SecretLocatorUnavailable(locator) from None

    def delete(self, locator: str) -> None:
        self.values.pop(locator, None)

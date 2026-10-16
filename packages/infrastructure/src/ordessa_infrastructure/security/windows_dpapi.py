"""Windows current-user DPAPI store for explicitly imported credential bytes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import csv
import io
import os
from pathlib import Path
import subprocess
from uuid import uuid4


from .secrets import MAX_SECRET_BYTES


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
    """Native current-user DPAPI; root and description are supplied by caller.

    Construction does not provision directories. Import/read/delete retain the
    original .dpapi bytes, credential_ locator, bounds, ACL and error behavior.
    No Linux backend, product layout or plaintext fallback is selected here.
    """

    def __init__(self, storage_root: Path | str, *, protect_description: str) -> None:
        if os.name != "nt":
            raise RuntimeError("SECRET_STORE_WINDOWS_REQUIRED")
        self.root = Path(storage_root).resolve()
        self._protect_description = protect_description

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

    def _protect(self, content: bytes) -> bytes:
        source, source_buffer = _blob(content)
        output = _Blob()
        crypt32, kernel32 = _dpapi_functions()
        if not crypt32.CryptProtectData(
            ctypes.byref(source), self._protect_description, None, None, None,
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

__all__ = ["WindowsDpapiSecretStore"]

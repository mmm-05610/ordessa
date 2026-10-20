"""Read an explicit request-integrity key reference from original owners.

This module never creates or imports secrets, database rows, stores, Units, or
authorities. A missing configuration means reliable-request fingerprinting is
not configured; malformed configuration or unavailable key material refuses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from ordessa_units.definitions.fingerprints import ProtectedFingerprintPort
from ordessa_units.public import ProtectedFingerprintHmac, SqliteUnitStore

from ordessa_server.bootstrap.storage.product_database import Database
from ordessa_server.configuration.credentials import CredentialRecords


_CONFIG_NAME = Path("state/request-integrity.json")
_KIND = "ordessa-request-integrity"
_MAX_CONFIG_BYTES = 4096
_CREDENTIAL_ID = re.compile(r"credential_[0-9a-f]{32}\Z")


class RequestIntegrityConfigurationUnavailable(ValueError):
    """Request-integrity key reference is invalid or its owner is unavailable."""


def _root_path(data_root) -> Path:
    try:
        root = Path(data_root)
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise RequestIntegrityConfigurationUnavailable("canonical data root required")
        if root.is_symlink():
            raise RequestIntegrityConfigurationUnavailable("canonical data root required")
        return root
    except RequestIntegrityConfigurationUnavailable:
        raise
    except (OSError, TypeError, ValueError):
        raise RequestIntegrityConfigurationUnavailable("canonical data root required") from None


def _read_configuration(root: Path) -> dict | None:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = state_fd = fd = None
    try:
        root_fd = os.open(root, directory_flags)
        root_before = os.fstat(root_fd)
        root_path_before = os.stat(root, follow_symlinks=False)
        if not _same_directory(root_before, root_path_before):
            raise RequestIntegrityConfigurationUnavailable("request-integrity data root changed")
        try:
            state_fd = os.open("state", directory_flags, dir_fd=root_fd)
        except FileNotFoundError:
            return None
        state_before = os.fstat(state_fd)
        state_path_before = os.stat("state", dir_fd=root_fd, follow_symlinks=False)
        if not _same_directory(state_before, state_path_before):
            raise RequestIntegrityConfigurationUnavailable("request-integrity state directory changed")
        try:
            before = os.stat("request-integrity.json", dir_fd=state_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or not 0 < before.st_size <= _MAX_CONFIG_BYTES):
            raise RequestIntegrityConfigurationUnavailable("request-integrity configuration is unsafe")
        fd = os.open("request-integrity.json",
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     dir_fd=state_fd)
        try:
            opened = os.fstat(fd)
            if not _same_file(before, opened):
                raise RequestIntegrityConfigurationUnavailable("request-integrity configuration changed")
            chunks, size = [], 0
            while size <= _MAX_CONFIG_BYTES:
                chunk = os.read(fd, min(4096, _MAX_CONFIG_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            after = os.fstat(fd)
            if (size != before.st_size or size > _MAX_CONFIG_BYTES
                    or not _same_file(before, after)
                    or not _same_file(before, os.stat(
                        "request-integrity.json", dir_fd=state_fd, follow_symlinks=False))
                    or not _same_directory(state_before, os.fstat(state_fd))
                    or not _same_directory(state_before, os.stat(
                        "state", dir_fd=root_fd, follow_symlinks=False))
                    or not _same_directory(root_before, os.fstat(root_fd))
                    or not _same_directory(root_before, os.stat(root, follow_symlinks=False))):
                raise RequestIntegrityConfigurationUnavailable("request-integrity configuration changed")
        finally:
            os.close(fd)
            fd = None
        document = json.loads(b"".join(chunks).decode("utf-8", errors="strict"),
                              object_pairs_hook=_unique_object)
    except RequestIntegrityConfigurationUnavailable:
        raise
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise RequestIntegrityConfigurationUnavailable("request-integrity configuration is invalid") from None
    finally:
        for descriptor in (fd, state_fd, root_fd):
            if descriptor is not None:
                os.close(descriptor)
    if (type(document) is not dict or set(document) != {"schemaVersion", "credentialId"}
            or type(document.get("schemaVersion")) is not int or document["schemaVersion"] != 1
            or type(document.get("credentialId")) is not str
            or _CREDENTIAL_ID.fullmatch(document["credentialId"]) is None):
        raise RequestIntegrityConfigurationUnavailable("request-integrity configuration is invalid")
    return document


def _same_directory(left, right) -> bool:
    return (stat.S_ISDIR(left.st_mode) and stat.S_ISDIR(right.st_mode)
            and (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino))


def _same_file(left, right) -> bool:
    return (stat.S_ISREG(left.st_mode) and stat.S_ISREG(right.st_mode)
            and (left.st_dev, left.st_ino, left.st_size, left.st_mtime_ns, left.st_ctime_ns,
                 left.st_uid, stat.S_IMODE(left.st_mode))
            == (right.st_dev, right.st_ino, right.st_size, right.st_mtime_ns, right.st_ctime_ns,
                right.st_uid, stat.S_IMODE(right.st_mode)))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_request_integrity_port(
    *, data_root, records: CredentialRecords, secret_store,
    unit_store: SqliteUnitStore,
) -> ProtectedFingerprintPort | None:
    """Resolve the configured key through the exact selected Server owners.

    The caller supplies the original records, SecretStore and UnitStore from
    this runtime. SecretStore has no public root identity; its own read checks
    that the opaque locator belongs to its namespace. No fallback key or
    tombstone predicate is synthesized here.
    """
    root = _root_path(data_root)
    if type(records) is not CredentialRecords:
        raise RequestIntegrityConfigurationUnavailable("original CredentialRecords required")
    database = records.database
    try:
        if type(database) is not Database:
            raise RequestIntegrityConfigurationUnavailable("original Server Database required")
        database_root = Path(database.data_root)
        if database_root.resolve(strict=True) != root or database_root != root:
            raise RequestIntegrityConfigurationUnavailable("credential records belong to another data root")
    except RequestIntegrityConfigurationUnavailable:
        raise
    except (OSError, TypeError, ValueError, AttributeError):
        raise RequestIntegrityConfigurationUnavailable("original same-root credential records required") from None

    document = _read_configuration(root)
    if document is None:
        return None
    if not callable(getattr(secret_store, "read", None)):
        raise RequestIntegrityConfigurationUnavailable("original SecretStore read port required")
    if type(unit_store) is not SqliteUnitStore:
        raise RequestIntegrityConfigurationUnavailable("original SqliteUnitStore required for tombstones")

    credential_id = document["credentialId"]
    if not callable(getattr(unit_store, "has_key_tombstone", None)):
        raise RequestIntegrityConfigurationUnavailable("original UnitStore tombstone query required")
    try:
        active_key_is_retired = unit_store.has_key_tombstone(credential_id)
    except Exception:
        raise RequestIntegrityConfigurationUnavailable(
            "configured integrity key retirement status is unavailable"
        ) from None
    if active_key_is_retired is not False:
        raise RequestIntegrityConfigurationUnavailable(
            "configured integrity key is tombstoned or its retirement status is invalid"
        )
    try:
        row = records.get(credential_id, kind=_KIND)
        if (type(row) is not dict or row.get("id") != credential_id
                or row.get("kind") != _KIND or type(row.get("secret_locator")) is not str):
            raise RequestIntegrityConfigurationUnavailable("registered integrity key reference is invalid")
        key = secret_store.read(row["secret_locator"])
    except RequestIntegrityConfigurationUnavailable:
        raise
    except Exception:
        raise RequestIntegrityConfigurationUnavailable("registered integrity key is unavailable") from None
    if type(key) is not bytes or len(key) != 32:
        raise RequestIntegrityConfigurationUnavailable("integrity key must contain exactly 32 bytes")
    try:
        return ProtectedFingerprintHmac(
            {credential_id: key}, active_key_id=credential_id,
            tombstone_check=unit_store.has_key_tombstone,
        )
    except Exception:
        raise RequestIntegrityConfigurationUnavailable("original fingerprint port could not be constructed") from None


__all__ = ["RequestIntegrityConfigurationUnavailable", "load_request_integrity_port"]

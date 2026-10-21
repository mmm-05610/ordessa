"""C-01 data-root lifecycle for the Server: creation, owner marker and lock.

The shared contract (layout constants, resolution order, root-owned paths) now
lives in :mod:`ordessa_infrastructure.layout`; it is re-exported here so the
Server's module surface, error codes and data-compatibility identifiers are
unchanged. Only the Server may create a root or take the single-instance lock.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

from ordessa_infrastructure.layout import (  # re-exported contract
    BACKUPS_DIR, DATA_ROOT_ENV, DATA_ROOT_ERROR_CODES, DEFAULT_DATA_ROOT_DIRNAME,
    DESKTOP_LOG_FILE, DIR_MODE, ERRORS_BY_CODE, INSTANCE_LOCK, LAYOUT,
    LAYOUT_CONSTANTS_PATH, LAUNCH_ERROR_CODES, LOGS_DIR, LOG_KEEP, LOG_ROTATE_BYTES,
    SECRET_FILE_MODE, SECRETS_DIR, SERVER_LOG_FILE, TOKEN_FILE,
    DataRootError, DataRootInvalidError, DataRootLockedError,
    DataRootMigrationRefusedError, DataRootNotWritableError, DataRootSpec,
    DataRootSymlinkError, backups_dir, desktop_log_file, launch_env, logs_dir,
    resolve_data_root, secrets_dir, server_log_file, token_file,
)

#: The owner marker: name and content are data-compatibility identifiers
#: (docs/archive/pre-restructure/source/docs/server-host-baseline.md). A pre-existing directory WITHOUT this
#: marker is a foreign root — `composition.runtime.DataRootOwner` refuses it
#: (DATA_ROOT_UNOWNED) rather than adopting it. Whoever CREATES a root must
#: write the marker in the same breath: `ensure_data_root` here for the
#: Server/CLI path, and `apps/desktop/electron/data-root.ts` for the root the
#: desktop host creates before it spawns the Server.
OWNER_MARKER_NAME = ".agentbox-server-root"
OWNER_MARKER_CONTENT = "agentbox-server-r1\n"


def write_owner_marker(root: Path) -> Path:
    """Write the owner marker for a root THIS call created (C-01 §3).

    Only a creator may call this. Writing the marker onto a pre-existing
    unmarked directory is exactly the silent adoption the runtime refuses,
    so this helper is not a "repair" for foreign roots.
    """
    marker = root / OWNER_MARKER_NAME
    marker.write_text(OWNER_MARKER_CONTENT, encoding="utf-8")
    return marker

# -- creation and validation (C-01 §3) --------------------------------------


@dataclass(frozen=True)
class DataRoot:
    """A data root that passed every C-01 §3 check."""

    path: Path
    source: str
    created: bool
    writable: bool
    locked: bool


def _refuse_symlinks(root: Path) -> None:
    """Ask the symlink question with no-follow semantics, before any read.

    `os.lstat` is the whole point: it describes the directory entry itself.
    A `stat`/`is_dir()` pair would already have followed the link and
    answered "yes it is a directory" about the TARGET — which is the leak
    this check exists to prevent.
    """
    candidates: "Sequence[tuple[str, Path]]" = [
        ("data root", root),
        (SECRETS_DIR, root / SECRETS_DIR),
        (LOGS_DIR, root / LOGS_DIR),
        (BACKUPS_DIR, root / BACKUPS_DIR),
        (INSTANCE_LOCK, root / INSTANCE_LOCK),
        (TOKEN_FILE, root / TOKEN_FILE),
    ]
    for label, path in candidates:
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DataRootInvalidError(
                f"the {label} path cannot be inspected: {exc.strerror or 'unknown error'}",
                "check the permissions on the data root and its parents",
            ) from exc
        import stat as stat_module
        if stat_module.S_ISLNK(entry.st_mode):
            raise DataRootSymlinkError(
                f"the {label} path is a symbolic link",
                "point ORDESSA_DATA_ROOT at a real directory; links are refused before "
                "their target is read",
            )


def _require_writable(root: Path) -> None:
    """Prove writability by writing, not by asking `os.access`.

    An access check is advisory and lies under several real conditions
    (read-only mounts, ACLs, a root uid). One create/unlink of a uniquely
    named file answers the question the contract actually asks.
    """
    probe = root / f".write-probe-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise DataRootNotWritableError(
            f"the data root is not writable: {exc.strerror or 'unknown error'}",
            "check the ownership and mode of the data root; the Server needs to write "
            "its state, logs and secrets",
        ) from exc
    os.close(descriptor)
    try:
        os.unlink(probe)
    except OSError:  # pragma: no cover - the root is proven writable above
        pass


def ensure_data_root(
    spec: DataRootSpec,
    *,
    lock: bool = False,
    require_migration_provider: bool = False,
) -> DataRoot:
    """Create or reuse the root, enforcing C-01 §3 in a fixed order.

    The order matters and is not incidental: symlink → shape → writability
    → lock. A symlinked root is refused *before* the writability probe,
    because the probe would otherwise create a file inside the link target.
    """
    root = spec.path
    _refuse_symlinks(root)
    created = False
    if not os.path.lexists(root):
        try:
            root.mkdir(parents=True, mode=DIR_MODE)
        except OSError as exc:
            raise DataRootInvalidError(
                f"the data root cannot be created: {exc.strerror or 'unknown error'}",
                "check the permissions on the parent directory",
            ) from exc
        created = True
    import stat as stat_module
    if not stat_module.S_ISDIR(os.lstat(root).st_mode):
        raise DataRootInvalidError(
            f"the data root {root.name!r} is not a directory",
            "remove or rename the file, or point ORDESSA_DATA_ROOT elsewhere",
        )
    # Writability is proved BEFORE the layout directories are created, so a
    # read-only root produces the typed refusal instead of a raw EACCES from
    # the first mkdir. Order, not luck, decides which error a caller sees.
    _require_writable(root)
    # Modes are applied ONLY to what this call created. An existing root is
    # reused as it stands: chmod-ing it to 0700 here would silently "repair"
    # a root the user made read-only on purpose, and the contract says such
    # a root is REFUSED, not corrected.
    if created:
        os.chmod(root, DIR_MODE)
        # C-01 §3: the creator claims the root it just made. Without this the
        # Server's own bootstrap (DataRootOwner.acquire) would see a root that
        # exists without a marker and refuse it as foreign — a fresh CLI/desktop
        # first start could never succeed (DATA_ROOT_UNOWNED).
        write_owner_marker(root)
    for name in (SECRETS_DIR, LOGS_DIR, BACKUPS_DIR):
        child = root / name
        if not os.path.lexists(child):
            child.mkdir(mode=DIR_MODE)
        if created:
            os.chmod(child, DIR_MODE)
    if require_migration_provider:
        require_migration_provider_for_historical_root(root)
    held = _lock_instance(root) if lock else False
    return DataRoot(
        path=root, source=spec.source, created=created, writable=True, locked=held,
    )

# -- the single-instance lock (C-01 §3, data-model §3) -----------------------


class InstanceLock:
    """An `flock` on `$DATA_ROOT/instance.lock`, held for the process lifetime.

    The lock file is a new name (the Server's own `server.lock` is
    untouched — data compatibility rule 5), and it identifies an instance,
    not a port or a pid.
    """

    def __init__(self, root: Path, owner: str | None = None) -> None:
        self.path = root / INSTANCE_LOCK
        self.owner = owner or f"instance_{uuid.uuid4().hex}"
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> "InstanceLock":
        if self._descriptor is not None:
            return self
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, SECRET_FILE_MODE)
        try:
            _lock_descriptor(descriptor, blocking=False)
        except OSError as exc:
            os.close(descriptor)
            raise DataRootLockedError(
                f"another instance already holds the data root (lock file {self.path.name!r})",
                "quit the running instance, or start this one against a different "
                "ORDESSA_DATA_ROOT",
            ) from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, (self.owner + "\n").encode("ascii"))
        os.fsync(descriptor)
        self._descriptor = descriptor
        return self

    def release(self) -> None:
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            _unlock_descriptor(descriptor)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _lock_descriptor(descriptor: int, *, blocking: bool) -> None:
    if os.name == "nt":  # pragma: no cover - the product is Linux-only
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(descriptor, mode, 1)
        return
    import fcntl
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    fcntl.flock(descriptor, flags)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":  # pragma: no cover - the product is Linux-only
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _lock_instance(root: Path) -> bool:
    """Probe-and-release: is another instance already holding this root?"""
    probe = InstanceLock(root)
    try:
        probe.acquire()
    except DataRootLockedError:
        return True
    probe.release()
    return False


def instance_lock(root: Path, owner: str | None = None) -> InstanceLock:
    """The caller's own long-lived lock on the data root."""
    return InstanceLock(root, owner)

# -- the historical-root preflight (C-01 §4) --------------------------------


def require_migration_provider_for_historical_root(root: Path) -> None:
    """Refuse a historical root that has no registered migration provider.

    The shared historical preflight owns this decision. Both runtime
    construction and this data-root surface call that same implementation. This wraps the one existing refusal so the data-root
    surface spells it `DATA_ROOT_MIGRATION_REFUSED` (C-01 §6) and keeps the
    original code on the exception as `legacy_code`.

    The refusal happens before any marker, lock, token or schema write, so
    a rejected root keeps its original bytes (C-01 §4, counterexample 6).
    """
    from ordessa_server.bootstrap.migrations.historical_preflight import LegacyMigrationProviderMissingError
    from ordessa_server.bootstrap.migrations.historical_preflight import _require_legacy_provider_for_historical_root

    try:
        _require_legacy_provider_for_historical_root(root)
    except LegacyMigrationProviderMissingError as exc:
        refused = DataRootMigrationRefusedError(
            "this data root is historical and its migration provider is not installed",
            "install the distribution that registers the sealed migration source, or "
            "start against a different ORDESSA_DATA_ROOT; the existing data is left "
            "untouched",
        )
        # The sealed-legacy code stays reachable on the typed refusal: the
        # data-root surface and the composition root can name the same
        # refusal two ways without inventing a third meaning for it.
        refused.legacy_code = getattr(exc, "code", None)
        raise refused from exc
    except Exception as exc:
        if getattr(exc, "code", None) == "DATA_ROOT_PATH_UNSAFE":
            raise DataRootSymlinkError(
                f"a Server-owned path under {root.name!r} is a symbolic link",
                "replace the link with a real file or directory before starting",
            ) from exc
        raise

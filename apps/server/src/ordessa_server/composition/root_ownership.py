"""Sole Server root-proof issuer and provenance/current-owner validation."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Callable
from server_plugin_api.root_ownership import OwnedRootBinding, RootOwnershipError

def _lexical(path: Path | str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise RootOwnershipError("owned root paths must be absolute")
    return Path(os.path.normpath(str(value)))


_ISSUED_IDENTITY = object()


class _IssuedOwnedRootBinding(OwnedRootBinding):
    """Implementation detail: instances are made only by the private bridge."""


    def validate_for(self, *, root_path: Path | str, store_path: Path | str, child_path: Path | str) -> None:
        validate_owned_root_binding(self, root_path=root_path, store_path=store_path, child_path=child_path)


def _issue_owned_root_binding(
    *, root_path: Path | str, store_path: Path | str, child_path: Path | str,
    validate_current: Callable[[], bool],
) -> OwnedRootBinding:
    """Private host bridge. Called after the existing DataRootOwner is acquired."""
    root = _lexical(root_path)
    store = _lexical(store_path)
    child = _lexical(child_path)
    if not callable(validate_current):
        raise TypeError("owned root proof requires a host validator")
    if store == root or root not in store.parents:
        raise RootOwnershipError("store path is outside the owned root")
    if child == root or root not in child.parents:
        raise RootOwnershipError("child path is outside the owned root")
    if child == store or child in {
        store.with_name(store.name + "-wal"),
        store.with_name(store.name + "-shm"),
    }:
        raise RootOwnershipError("owned child path aliases the core store")
    binding = object.__new__(_IssuedOwnedRootBinding)
    object.__setattr__(binding, "root_path", root)
    object.__setattr__(binding, "store_path", store)
    object.__setattr__(binding, "child_path", child)
    object.__setattr__(binding, "_validate_current", validate_current)
    object.__setattr__(binding, "_issued_identity", _ISSUED_IDENTITY)
    return binding


def _is_issued_owned_root_binding(value: object) -> bool:
    """Read-only provenance check; structural lookalikes are never accepted."""
    return (type(value) is _IssuedOwnedRootBinding
            and getattr(value, "_issued_identity", None) is _ISSUED_IDENTITY)


def validate_owned_root_binding(
    self, *, root_path: Path | str, store_path: Path | str, child_path: Path | str,
) -> None:
    """Validate exact lexical bindings and re-check current host ownership."""
    if not _is_issued_owned_root_binding(self):
        raise RootOwnershipError("owned root proof was not issued by the Server host")
    if (_lexical(root_path) != self.root_path
            or _lexical(store_path) != self.store_path
            or _lexical(child_path) != self.child_path):
        raise RootOwnershipError("owned root proof does not match requested paths")
    try:
        current = self._validate_current()
    except Exception as exc:
        raise RootOwnershipError("owned root proof could not be revalidated") from exc
    if current is not True:
        raise RootOwnershipError("owned root proof is no longer current")


import stat
from threading import RLock
from uuid import uuid4
from ordessa_server.bootstrap.data_root import OWNER_MARKER_CONTENT, OWNER_MARKER_NAME, write_owner_marker

class DataRootPathUnsafeError(RuntimeError):
    """A Server-owned database path must not traverse a symbolic link."""

    code = "DATA_ROOT_PATH_UNSAFE"


class RuntimeCompositionUnavailable(RuntimeError):
    """The selected Server runtime lacks its required assembly capability."""
    code = "GUARANTEE_UNAVAILABLE"


class DataRootOwner:
    """Exclusive process lock and identity marker for one data root."""

    # Retains the ORIGINAL owner after a failed construction cleanup. This is
    # only an OS-lock lifetime anchor, never a second Environment/Store owner.
    _pending_builds: dict[Path, "_FailedBuildCleanup"] = {}
    _pending_builds_lock = RLock()

    @classmethod
    def retry_pending_build(cls, root: Path | str) -> None:
        """Retry exact original cleanup; never acquire a replacement writer."""
        with cls._pending_builds_lock:
            pending = cls._pending_builds.get(Path(root).resolve())
        if pending is None:
            raise RuntimeCompositionUnavailable("no failed construction owns this root")
        pending.retry()

    @classmethod
    def _retain_failed_build(cls, pending: "_FailedBuildCleanup") -> None:
        with cls._pending_builds_lock:
            if pending.owner.root in cls._pending_builds:
                raise RuntimeCompositionUnavailable("failed construction already retained")
            cls._pending_builds[pending.owner.root] = pending

    def __init__(self, root: Path) -> None:
        self.root = root
        self.instance_id = f"server_{uuid4().hex}"
        self._stream = None
        self._root_identity = None
        self._marker_identity = None
        self._lock_identity = None

    def acquire(self) -> None:
        with self._pending_builds_lock:
            if self.root in self._pending_builds:
                raise RuntimeError("DATA_ROOT_IN_USE: failed construction cleanup pending")
        # The marker's name and content live in `.data_root` with the rest of
        # the data-root contract (one spelling, read by both entry points).
        marker = self.root / OWNER_MARKER_NAME
        try:
            root_info = self.root.lstat()
        except FileNotFoundError:
            root_info = None
        if root_info is not None and stat.S_ISLNK(root_info.st_mode):
            raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: data root cannot be a symlink")
        if root_info is not None and not marker.exists():
            raise RuntimeError("DATA_ROOT_UNOWNED: existing directory has no AgentBox owner marker")
        if marker.is_symlink():
            raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: owner marker cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            write_owner_marker(self.root)
        else:
            marker_info = marker.lstat()
            if stat.S_ISLNK(marker_info.st_mode) or not stat.S_ISREG(marker_info.st_mode):
                raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: owner marker must be a regular file")
            marker_fd = os.open(marker, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(marker_fd)
                marker_bytes = os.read(marker_fd, len(OWNER_MARKER_CONTENT.encode("utf-8")) + 1)
            finally:
                os.close(marker_fd)
            if ((opened.st_dev, opened.st_ino) != (marker_info.st_dev, marker_info.st_ino)
                    or marker_bytes != OWNER_MARKER_CONTENT.encode("utf-8")):
                raise RuntimeError("DATA_ROOT_MARKER_INVALID")
        lock_path = self.root / "server.lock"
        try:
            lock_info = lock_path.lstat()
            if stat.S_ISLNK(lock_info.st_mode) or not stat.S_ISREG(lock_info.st_mode):
                raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: server lock must be a regular file")
        except FileNotFoundError:
            pass
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            stream = os.fdopen(descriptor, "r+b", buffering=0)
        except BaseException:
            os.close(descriptor)
            raise
        self._stream = stream
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("DATA_ROOT_IN_USE") from exc
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, (self.instance_id + "\n").encode("ascii"))
            os.fsync(descriptor)
            self._root_identity = self._identity(self.root)
            self._marker_identity = self._identity(marker)
            self._lock_identity = self._identity(lock_path)
            if not self._validate_current_identity():
                raise RootOwnershipError("newly acquired data-root identity changed")
        except BaseException as acquisition_failure:
            try:
                self.release()
            except BaseException as close_failure:
                try:
                    acquisition_failure.cleanup_errors = (
                        *getattr(acquisition_failure, "cleanup_errors", ()), close_failure)
                except (AttributeError, TypeError):
                    pass
            raise

    @staticmethod
    def _identity(path: Path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: owned root paths cannot be symlinks")
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))

    def _validate_current_identity(self) -> bool:
        if self._stream is None:
            return False
        marker = self.root / OWNER_MARKER_NAME
        lock_path = self.root / "server.lock"
        try:
            ancestor = self.root
            while True:
                if stat.S_ISLNK(ancestor.lstat().st_mode):
                    return False
                if ancestor.parent == ancestor:
                    break
                ancestor = ancestor.parent
            if (self._identity(self.root) != self._root_identity
                    or self._identity(marker) != self._marker_identity
                    or self._identity(lock_path) != self._lock_identity):
                return False
            descriptor_identity = os.fstat(self._stream.fileno())
            if (descriptor_identity.st_dev, descriptor_identity.st_ino,
                    stat.S_IFMT(descriptor_identity.st_mode)) != self._lock_identity:
                return False
            descriptor = os.open(marker, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                marker_bytes = os.read(descriptor, len(OWNER_MARKER_CONTENT.encode("utf-8")) + 1)
            finally:
                os.close(descriptor)
            return marker_bytes == OWNER_MARKER_CONTENT.encode("utf-8")
        except (OSError, DataRootPathUnsafeError):
            return False

    @property
    def root_path(self) -> Path:
        return self.root

    def bind_owned_root(self, *, root_path, store_path, child_path) -> OwnedRootBinding:
        """Issue a path-bound proof backed by this held host owner."""
        try:
            store = Path(store_path)
            child = Path(child_path)
            def validate_bound_paths() -> bool:
                if not self._validate_current_identity():
                    return False
                for target in (store, child):
                    relative = target.relative_to(self.root)
                    current = self.root
                    for part in relative.parts:
                        current = current / part
                        try:
                            info = current.lstat()
                        except FileNotFoundError:
                            continue
                        if stat.S_ISLNK(info.st_mode):
                            return False
                        if current != target and not stat.S_ISDIR(info.st_mode):
                            return False
                return True
            if not self.acquired:
                raise RootOwnershipError("data root owner has not acquired its lock")
            binding = _issue_owned_root_binding(
                root_path=Path(root_path), store_path=store,
                child_path=child, validate_current=validate_bound_paths,
            )
            binding.validate_for(root_path=self.root, store_path=store_path,
                                 child_path=child_path)
        except (TypeError, ValueError, RootOwnershipError) as exc:
            raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: requested paths are not bound to this owner") from exc
        if Path(root_path) != self.root:
            raise DataRootPathUnsafeError("DATA_ROOT_PATH_UNSAFE: requested root differs from held owner")
        return binding

    def validate_owned_root(
        self, binding: OwnedRootBinding, *, root_path, store_path, child_path,
    ) -> None:
        """Validate host issuance and current ownership without caller dispatch."""
        validate_owned_root_binding(
            binding, root_path=root_path, store_path=store_path, child_path=child_path,
        )
        if Path(root_path) != self.root:
            raise RootOwnershipError("owned root proof does not match requested paths")
        if not self._validate_current_identity():
            raise RootOwnershipError("owned root proof is no longer current")

    def release(self) -> None:
        if self._stream is None:
            return
        # This is the final cleanup step, after Environment detach and the
        # original SQL writer release have both succeeded. Closing this
        # unbuffered descriptor releases its OS lock; never unlock it first
        # and then report a failed close as if the lock were still held.
        stream = self._stream
        try:
            stream.close()
        finally:
            if stream.closed:
                self._stream = None

    @property
    def acquired(self) -> bool:
        return self._validate_current_identity()

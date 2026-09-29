"""C-01 — the data-root specification, in one place, for both entry points.

The Server CLI (`python -m ordessa_server`) and the Desktop host (the
TypeScript side reads `data_root_layout.json` — the very file this module
loads) resolve a data root through the SAME two-step order and the SAME
layout literals. There is no second spelling of `.ordessa`, `secrets/
http-token`, `logs/`, `backups/` or `instance.lock` anywhere in this
repository: this module is the only Python reader of that file and the only
writer of the layout paths below.

Three properties of the contract are load-bearing and are implemented as
such, not as documentation:

* **The symlink question is asked before anything is read.** Every check
  uses `os.lstat` / `O_NOFOLLOW` semantics. `Path.resolve()` is never
  called on the candidate root, because resolving first would answer the
  question by following the link — the very thing the contract refuses.
* **A refusal is typed and actionable.** Each error carries a stable
  `code`, a human `reason` and a `remedy`; none of them ever carries token
  bytes, and a locator is reduced to its basename (contracts README §4).
* **Reuse is reuse.** An existing root is opened, never rebuilt: the token
  file keeps its bytes across a second start, and only the permissions the
  contract names are enforced.

`build_runtime` keeps its own historical-root preflight
(`bootstrap.runtime._require_legacy_provider_for_historical_root`); this
module does not re-implement it. `require_migration_provider_for_historical_root`
translates that one refusal into `DATA_ROOT_MIGRATION_REFUSED` so the
data-root surface has exactly one spelling of "this old root needs a
migration provider it does not have" (C-01 §4).
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

#: The layout constants file, shipped inside the package. The TypeScript host
#: reads the same file; neither side restates these literals.
LAYOUT_CONSTANTS_PATH = Path(__file__).with_name("data_root_layout.json")

with open(LAYOUT_CONSTANTS_PATH, "r", encoding="utf-8") as _handle:
    LAYOUT: "dict[str, Any]" = json.load(_handle)

#: C-01 §1 resolution order, step 1: the explicit override.
DATA_ROOT_ENV: str = LAYOUT["dataRoot"]["envVar"]
#: C-01 §1 resolution order, step 2: the default, relative to the home dir.
DEFAULT_DATA_ROOT_DIRNAME: str = LAYOUT["dataRoot"]["defaultDirname"]

SECRETS_DIR: str = LAYOUT["layout"]["secretsDir"]
TOKEN_FILE: str = LAYOUT["layout"]["tokenFile"]
LOGS_DIR: str = LAYOUT["layout"]["logsDir"]
BACKUPS_DIR: str = LAYOUT["layout"]["backupsDir"]
INSTANCE_LOCK: str = LAYOUT["layout"]["instanceLock"]

DIR_MODE: int = int(LAYOUT["permissions"]["dirMode"], 8)
SECRET_FILE_MODE: int = int(LAYOUT["permissions"]["secretFileMode"], 8)

LOG_ROTATE_BYTES: int = int(LAYOUT["logs"]["rotateBytes"])
LOG_KEEP: int = int(LAYOUT["logs"]["keep"])
SERVER_LOG_FILE: str = f"{LOGS_DIR}/{LAYOUT['logs']['serverFile']}"
DESKTOP_LOG_FILE: str = f"{LOGS_DIR}/{LAYOUT['logs']['desktopFile']}"

DATA_ROOT_ERROR_CODES: "tuple[str, ...]" = tuple(LAYOUT["dataRootErrors"])
LAUNCH_ERROR_CODES: "tuple[str, ...]" = tuple(LAYOUT["launchErrors"])


# -- typed refusals (C-01 §6) ------------------------------------------------


class DataRootError(RuntimeError):
    """A data root that cannot be used, named by its stable code.

    `reason` says what was observed, `remedy` says who can fix it. Neither
    half ever carries a token byte, and a path is reduced to its basename.
    """

    code = "DATA_ROOT_INVALID"

    def __init__(self, reason: str, remedy: str, *, detail: str | None = None) -> None:
        self.reason = reason
        self.remedy = remedy
        self.detail = detail
        super().__init__(f"{self.code}: {reason}; {remedy}")


class DataRootInvalidError(DataRootError):
    """The resolved root is not an absolute, `..`-free path."""

    code = "DATA_ROOT_INVALID"


class DataRootSymlinkError(DataRootError):
    """The root (or a path the layout owns under it) is a symbolic link."""

    code = "DATA_ROOT_SYMLINK"


class DataRootNotWritableError(DataRootError):
    """The root exists but this process cannot write into it."""

    code = "DATA_ROOT_NOT_WRITABLE"


class DataRootLockedError(DataRootError):
    """Another live instance holds the data root.

    This is deliberately NOT a disk error: the data is fine, a second
    instance is already running.
    """

    code = "DATA_ROOT_LOCKED"


class DataRootMigrationRefusedError(DataRootError):
    """A historical root with no registered migration provider."""

    code = "DATA_ROOT_MIGRATION_REFUSED"


#: Code → class, so a caller may branch on the code without importing five
#: names, and so the JSON's `dataRootErrors` list stays the single truth.
ERRORS_BY_CODE: "Mapping[str, type[DataRootError]]" = {
    DataRootInvalidError.code: DataRootInvalidError,
    DataRootSymlinkError.code: DataRootSymlinkError,
    DataRootNotWritableError.code: DataRootNotWritableError,
    DataRootLockedError.code: DataRootLockedError,
    DataRootMigrationRefusedError.code: DataRootMigrationRefusedError,
}


# -- resolution (C-01 §1) ---------------------------------------------------


@dataclass(frozen=True)
class DataRootSpec:
    """A resolved-but-not-yet-created data root (data-model §2.1, `source`)."""

    path: Path
    source: str  # 'env' | 'default' | 'explicit'


def _reject_traversal(raw: str) -> None:
    """Refuse a relative path or one carrying `..` — BEFORE normalising.

    Normalising first would silently collapse `..` into a plausible
    absolute path, and the caller would never learn the value it was given
    was not usable as written.
    """
    if not raw:
        raise DataRootInvalidError(
            "the data root is empty",
            "set ORDESSA_DATA_ROOT to an absolute directory, or unset it to use the default",
        )
    if not os.path.isabs(raw):
        raise DataRootInvalidError(
            f"the data root {os.path.basename(raw)!r} is not absolute",
            "pass an absolute path; relative data roots are never resolved against the cwd",
        )
    parts = Path(raw).parts
    if ".." in parts:
        raise DataRootInvalidError(
            "the data root contains a '..' segment",
            "pass a normalised absolute path; '..' is never resolved",
        )


def resolve_data_root(
    env: "Mapping[str, str] | None" = None,
    *,
    home: str | None = None,
    explicit: str | os.PathLike[str] | None = None,
) -> DataRootSpec:
    """Resolve the data root through the one documented order.

    `explicit` is the Server CLI's `--data-root`. It is checked with the
    same rules as the environment override, because a flag is just another
    spelling of "the caller named a root" — not a way around the contract.
    """
    environment = os.environ if env is None else env
    if explicit is not None:
        raw = os.fspath(explicit)
        _reject_traversal(raw)
        return DataRootSpec(Path(raw), "explicit")
    override = environment.get(DATA_ROOT_ENV)
    if override:
        _reject_traversal(override)
        return DataRootSpec(Path(override), "env")
    base = home if home is not None else os.path.expanduser("~")
    if not base:
        raise DataRootInvalidError(
            "no home directory is available for the default data root",
            "set ORDESSA_DATA_ROOT to an absolute directory",
        )
    return DataRootSpec(Path(base) / DEFAULT_DATA_ROOT_DIRNAME, "default")


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

    The decision itself is NOT re-implemented here: `build_runtime` already
    owns the sealed-legacy preflight, and two copies of that rule would be
    two answers. This wraps the one existing refusal so the data-root
    surface spells it `DATA_ROOT_MIGRATION_REFUSED` (C-01 §6) and keeps the
    original code on the exception as `legacy_code`.

    The refusal happens before any marker, lock, token or schema write, so
    a rejected root keeps its original bytes (C-01 §4, counterexample 6).
    """
    from .runtime import LegacyMigrationProviderMissingError
    from .runtime import _require_legacy_provider_for_historical_root

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



# -- the paths the rest of the tree asks for by name -------------------------

def secrets_dir(root: Path) -> Path:
    return root / SECRETS_DIR


def token_file(root: Path) -> Path:
    """`$DATA_ROOT/secrets/http-token` — the locator, never the token bytes."""
    return root / TOKEN_FILE


def logs_dir(root: Path) -> Path:
    return root / LOGS_DIR


def server_log_file(root: Path) -> Path:
    return root / SERVER_LOG_FILE


def desktop_log_file(root: Path) -> Path:
    return root / DESKTOP_LOG_FILE


def backups_dir(root: Path) -> Path:
    return root / BACKUPS_DIR


def launch_env(data_root: Path, origin: str) -> "dict[str, str]":
    """The three C-02 §2 variables, spelled exactly as the connectors read them.

    `plugins/connectors/ordessa/src/target.ts` refuses `ORDESSA_SERVER_ORIGIN`
    and `ORDESSA_SERVER_TOKEN_FILE` when they are absent, naming the host as
    the party that must supply them. The values here are the host's side of
    that contract: the origin is an origin and nothing else, and only a
    locator crosses the process boundary — never the token.
    """
    return {
        LAYOUT["launch"]["dataRootEnv"]: str(data_root),
        LAYOUT["launch"]["originEnv"]: origin,
        LAYOUT["launch"]["tokenFileEnv"]: str(token_file(data_root)),
    }

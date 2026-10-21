"""C-01 data-root contract: layout constants, resolution order and root-owned paths.

This is the shared, dependency-free source. The same `data_root_layout.json` is
read by the TypeScript desktop host, so the literals live in exactly one file and
neither side restates a path, a variable name or a permission.

Creation, the ownership marker and the single-instance lock stay with the
Server's lifecycle (`ordessa_server.bootstrap.data_root`); this module is
read-only with respect to a root.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

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

#: Zero-config CLI default port. `--port 0` still means "the system assigns one";
#: a host that spawns the Server reads the real port from the listening handshake.
DEFAULT_CLIENT_PORT: int = int(LAYOUT["launch"]["defaultClientPort"])

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

    `plugins/agents/connectors/ordessa/src/target.ts` refuses `ORDESSA_SERVER_ORIGIN`
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

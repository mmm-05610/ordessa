"""This machine, as an environment a Workspace can live in.

The `local` placement needs the same two things every other placement needs - a
validated location and a truthful answer about what can be done with it - and
nothing else. There is no connector here because there is no other machine to
ask, and there is no new deployment field because the document already says how
a room runs, on whichever machine it runs.

What stays in this module is the part that is genuinely local: turning a
caller-supplied path into a location, listing one directory honestly, and
refusing - in typed terms - when the path is not a location this Server may
open. Nothing here stages bytes, composes a room, or starts a process; that is
the channel's job and it is the same channel for any host.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from ordessa_server.errors import ServerError

#: One workspace file, as the Worker channel bounds it too.
MAX_WORKSPACE_FILE_BYTES = 8 * 1024 * 1024

#: The one path that can never be a Workspace. A room binds its workspace
#: writable, so accepting `/` would hand the whole host filesystem to the guest
#: at the workspace mount - a placement that is never a product intent and is
#: cheap to refuse by name.
FORBIDDEN_ROOTS = frozenset({"/"})

#: Directory entries this listing reports. Anything else is a non-directory
#: entry with a reason, never a silent omission.
_DIRECTORY = "directory"
_FILE = "file"

#: The explicit Server-composition modes this placement knows. `isolated` is
#: the default and the historic one: opening a Workspace requires that this
#: host can run the sandbox room. `native` is chosen once at Server startup by
#: the composition, where the room does not run at all - so the open asks the
#: project's own validity and nothing else. The mode is never derived from a
#: probe answer and never from an environment variable: a sandbox failure
#: must not silently become a native run.
EXECUTION_MODES = frozenset({"isolated", "native"})


def _refuse(code: str, message: str, status: int, *, retryable: bool = False) -> ServerError:
    return ServerError(code, message, status=status, retryable=retryable)


class LocalEnvironmentProvider:
    """Validate and list paths on the machine this Server runs on.

    `sandbox_probe` answers whether this host can run the room the sandbox layer
    composes. It is injectable so the refusal can be exercised without a host
    that genuinely lacks it, and it is asked only where it matters: browsing a
    directory needs no sandbox, and opening a Workspace does - but only in the
    `isolated` composition. A `native` Server chose that mode at startup and
    never asks the probe, so a sandbox failure can only ever refuse the old
    path, never flip the mode.
    """

    def __init__(self, *, sandbox_probe: Callable[[], Mapping[str, Any]] | None = None,
                 execution_mode: str = "isolated") -> None:
        if execution_mode not in EXECUTION_MODES:
            # A composition that names no known mode is a programming error at
            # the assembly boundary, refused loudly rather than defaulted.
            raise ValueError(f"local execution mode is not supported: {execution_mode!r}")
        self.execution_mode = execution_mode
        self._sandbox_probe = sandbox_probe or _host_sandbox_probe
        self._sandbox_answer: bool | None = None

    # -- capability --------------------------------------------------------

    def sandbox_available(self) -> bool:
        """Whether this host can run the composed room, asked of the sandbox layer.

        Answered once per Server: the host's ability to run the room does not
        change while the process lives, and `server.hello` asks this on every
        connect - it must not cost a subprocess each time.
        """
        if self._sandbox_answer is None:
            try:
                self._sandbox_answer = self._sandbox_probe().get("status") == "available"
            except Exception:
                # An unavailable probe is an unavailable sandbox: pretending a
                # room could run here is the one answer that must never be guessed.
                self._sandbox_answer = False
        return self._sandbox_answer

    def readiness_blockers(self) -> list[dict[str, Any]]:
        """Why this Server could not open a local Workspace, if that is so.

        A native composition honestly declares it needs no Ordessa sandbox;
        that is not a claim that the Agent's own permissions or the backend
        execution gates have passed - those answer through their own faces.
        """
        if self.execution_mode == "native":
            return []
        if self.sandbox_available():
            return []
        return [{"code": "LOCAL_SANDBOX_UNAVAILABLE", "retryable": True}]

    # -- locations ---------------------------------------------------------

    def validate(self, path: Any) -> str:
        """Return the location's normalized form, or refuse in typed terms.

        The returned value is what the Workspace record stores, so two spellings
        of one directory are one Workspace rather than two.
        """
        if not isinstance(path, str) or not path or "\x00" in path:
            raise _refuse("LOCAL_PATH_INVALID", "a local workspace path must be a non-empty string", 422)
        if not path.startswith("/"):
            # A relative path would mean "relative to wherever the Server was
            # started", which is not a location a product can reopen later.
            raise _refuse("LOCAL_PATH_INVALID", "a local workspace path must be absolute", 422)
        if str(PurePosixPath(path)) != path or "//" in path:
            raise _refuse("LOCAL_PATH_INVALID", "a local workspace path must be normalized", 422)
        if any(part in {".", ".."} for part in path.split("/")):
            raise _refuse("LOCAL_PATH_INVALID", "a local workspace path must not traverse", 422)
        if path in FORBIDDEN_ROOTS:
            raise _refuse("LOCAL_PATH_FORBIDDEN", "this root may not be opened as a workspace", 403)
        try:
            info = os.stat(path)
        except FileNotFoundError as exc:
            raise _refuse("LOCAL_PATH_MISSING", "the local path does not exist", 404) from exc
        except PermissionError as exc:
            raise _refuse("LOCAL_PATH_NOT_READABLE", "the local path is not readable", 403) from exc
        except OSError as exc:
            raise _refuse("LOCAL_PATH_UNAVAILABLE", "the local path could not be inspected", 503) from exc
        if not os.path.isdir(path):
            raise _refuse("LOCAL_PATH_NOT_DIRECTORY", "the local path is not a directory", 422)
        if not os.access(path, os.R_OK):
            raise _refuse("LOCAL_PATH_NOT_READABLE", "the local path is not readable", 403)
        # Symlinks are resolved into the stored identity: the record must name
        # the directory the room will actually bind, not one of its aliases.
        return os.path.realpath(path)

    def open_workspace(self, path: Any) -> dict[str, Any]:
        """Validate one location for opening; the caller records the result.

        Project validity is every mode's own requirement - native weakens none
        of it. Only the sandbox demand is mode-keyed, and only `isolated`
        keeps the historic refusal.
        """
        normalized = self.validate(path)
        if self.execution_mode == "isolated":
            self.require_sandbox()
        return {"path": normalized}

    def require_sandbox(self) -> None:
        """Refuse an open this host cannot actually run, rather than half-open it."""
        if not self.sandbox_available():
            raise _refuse(
                "LOCAL_SANDBOX_UNAVAILABLE",
                "this host cannot run the sandbox room a local workspace needs",
                503, retryable=True,
            )

    # -- browsing ----------------------------------------------------------

    def browse(self, path: Any) -> dict[str, Any]:
        """List one directory: readable and writable are separate facts.

        A directory is never refused for being read-only, and a non-directory is
        listed with its reason instead of being dropped - the client should not
        have to guess why an entry it can see on disk is missing from a listing.
        """
        normalized = self.validate(path)
        try:
            entries = sorted(os.scandir(normalized), key=lambda item: item.name)
        except PermissionError as exc:
            raise _refuse("LOCAL_PATH_NOT_READABLE", "the local path is not readable", 403) from exc
        except OSError as exc:
            raise _refuse("LOCAL_PATH_UNAVAILABLE", "the local path could not be listed", 503) from exc
        items = []
        for entry in entries:
            try:
                is_directory = entry.is_dir()
            except OSError:
                is_directory = False
            if is_directory:
                items.append({
                    "name": entry.name, "kind": _DIRECTORY, "canOpen": True,
                    "canWrite": os.access(entry.path, os.W_OK), "reason": None,
                })
            else:
                items.append({
                    "name": entry.name, "kind": _FILE, "canOpen": False,
                    "canWrite": False, "reason": "not_a_directory",
                })
        return {"path": normalized, "entries": items}


    # -- workspace files ---------------------------------------------------

    def read_workspace_file(self, *, normalized_path: str, relative_path: str,
                            ) -> tuple[bytes, str]:
        """Read one bounded file from an opened local workspace.

        The Server owns this machine, so no Worker round trip is needed - but the
        boundary is the same one the Worker channel enforces elsewhere: the path
        stays inside the recorded workspace, links are not followed, and only a
        regular file is ever read.
        """
        if not isinstance(relative_path, str) or not relative_path:
            raise _refuse("LOCAL_PATH_INVALID", "a workspace file must be named", 422)
        parts = relative_path.split("/")
        if (relative_path.startswith("/") or "\\" in relative_path or "\x00" in relative_path
                or any(part in {"", ".", ".."} for part in parts)):
            raise _refuse("LOCAL_PATH_INVALID", "a workspace file path must be normalized", 422)
        target = Path(normalized_path).joinpath(*parts)
        try:
            info = os.lstat(target)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise _refuse("LOCAL_PATH_MISSING", "the workspace file does not exist", 404) from exc
        except OSError as exc:
            raise _refuse("LOCAL_PATH_UNAVAILABLE", "the workspace file could not be read", 503) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise _refuse("LOCAL_PATH_NOT_READABLE",
                          "only a regular file inside the workspace may be read", 403)
        if info.st_size > MAX_WORKSPACE_FILE_BYTES:
            raise _refuse("LOCAL_PATH_UNAVAILABLE", "the workspace file is too large", 503)
        try:
            handle = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            # The name was a regular file when inspected and a link when opened:
            # that race is a refusal, never a read of whatever replaced it.
            raise _refuse("LOCAL_PATH_NOT_READABLE", "the workspace file changed while opening", 403) from exc
        with os.fdopen(handle, "rb") as stream:
            content = stream.read(MAX_WORKSPACE_FILE_BYTES + 1)
        if len(content) > MAX_WORKSPACE_FILE_BYTES:
            raise _refuse("LOCAL_PATH_UNAVAILABLE", "the workspace file is too large", 503)
        return content, "sha256:" + hashlib.sha256(content).hexdigest()


def _host_sandbox_probe() -> Mapping[str, Any]:
    """Ask the resolved sandbox provider whether a room can run here.

    The probe is the provider's own: it checks its binary and runs the
    production read-only system root, so "available" means the room's argv
    would really start on this host, not that a file happens to be on PATH.
    The provider is resolved by name (never imported here); an unresolvable
    provider reports unavailable rather than guessing another sandbox.
    """
    from pacthold.extensions.runtime_composition.sandbox_port import (
        SandboxPortError, resolve_sandbox_port,
    )
    try:
        port = resolve_sandbox_port(
            os.environ.get("AGENT_BOX_SANDBOX_PROVIDER") or "sandbox-bwrap"
        )
        return port.probe()
    except SandboxPortError:
        return {"status": "unavailable", "code": "sandbox_provider_unresolved"}


__all__ = ["EXECUTION_MODES", "FORBIDDEN_ROOTS", "LocalEnvironmentProvider"]

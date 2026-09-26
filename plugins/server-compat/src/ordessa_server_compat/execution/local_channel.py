"""The same room, run on this machine instead of through a Worker.

This is the second implementation of one channel shape: stage the bytes, ask
the sandbox layer for the room's command, run it, hand its stdio up, audit the
declared home subtree, and leave nothing behind. It shares the audit rules
with the Worker-hosted channel (`state_capture`) rather than restating them.

The Profile's native home on this machine is `<home root>/<locator>`, created
and marker-verified here exactly as the Worker does on a remote machine - the
marker is the one fact that says which product identity owns the directory.
What it is *not*: an isolation mechanism. The command it runs is the room's,
so the isolation is the room's too - this launcher only decides where the
bytes land and how the process is started and stopped.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .state_capture import (
    MAX_AUDIT_FILES,
    MAX_AUDIT_FILE_BYTES,
    MAX_AUDIT_TOTAL_BYTES,
    StateCaptureError, audit_snapshot,
)

#: One bundled file may not exceed this many bytes, nor the bundle this many.
MAX_BUNDLE_FILES = 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def _safe_bundle_path(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or "\x00" in value or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or str(PurePosixPath(value)) != value):
        raise ValueError("LOCAL_CHANNEL_PATH_INVALID")
    return value


class LocalChannelError(RuntimeError):
    """A typed channel refusal; ``code`` names the boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _safe_relative(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or "\x00" in value or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or str(PurePosixPath(value)) != value):
        raise StateCaptureError("SIDECAR_STATE_PATH_INVALID", "state path is not a bounded relative path")
    return value


#: Order 56: one subscription working copy may not exceed these bounds (the
#: asset module's caps; restated here because this layer enforces them before
#: the file ever reaches a home).
MAX_SUBSCRIPTION_FILE_BYTES = 256 * 1024
MAX_SUBSCRIPTION_FILES = 8


def _subscription_target(role_dir: Path, name: str) -> Path:
    """The host path of one declared guest-relative subscription file.

    The guest path minus `/runtime/home/` is exactly the role-relative path:
    both the native-home bind and the state window bind map that way, so the
    declared name is the whole mapping rule - no guessing from the harness.
    """
    relative = _safe_relative(name)
    target = role_dir.joinpath(*relative.split("/"))
    resolved_parent = target.parent.resolve()
    if not resolved_parent.is_relative_to(role_dir.resolve()):
        raise LocalChannelError("ACCOUNT_MATERIALIZE_INVALID", "a subscription path escapes the home")
    return target


def write_subscription_files(
    role_dir: Path, files: Mapping[str, bytes], *, declared: Sequence[str],
) -> list[str]:
    """Materialise the working copy: exactly the declared names, bounded.

    Parents are created inside the role directory; the leaf is written with
    O_NOFOLLOW so a planted link can never redirect the write, and the mode is
    0600 - a login state is credential material even though it is not the
    injected secret.
    """
    written: list[str] = []
    if len(files) > MAX_SUBSCRIPTION_FILES:
        raise LocalChannelError("ACCOUNT_MATERIALIZE_INVALID", "too many subscription files")
    for name in declared:
        payload = files.get(name)
        if payload is None:
            continue
        if not payload or len(payload) > MAX_SUBSCRIPTION_FILE_BYTES:
            raise LocalChannelError(
                "ACCOUNT_MATERIALIZE_INVALID", "a subscription file is empty or oversized")
        target = _subscription_target(role_dir, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(target):
            info = os.lstat(target)
            if not stat.S_ISREG(info.st_mode):
                raise LocalChannelError(
                    "ACCOUNT_MATERIALIZE_INVALID", "a subscription target is not a regular file")
        handle = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        written.append(name)
    return written


def read_subscription_files(
    role_dir: Path, *, declared: Sequence[str],
) -> dict[str, bytes]:
    """Read the working copy back for reclamation: declared names only."""
    files: dict[str, bytes] = {}
    for name in declared:
        target = _subscription_target(role_dir, name)
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            raise LocalChannelError(
                "ACCOUNT_RECLAIM_INVALID", "a subscription working file is not a regular file")
        if info.st_size <= 0 or info.st_size > MAX_SUBSCRIPTION_FILE_BYTES:
            raise LocalChannelError(
                "ACCOUNT_RECLAIM_INVALID", "a subscription working file is empty or oversized")
        handle = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(handle, "rb") as stream:
            files[name] = stream.read(MAX_SUBSCRIPTION_FILE_BYTES + 1)
    return files


def _seed_store_entries(store: Path, entries: Sequence[tuple[str, str]]) -> None:
    """Order 66: create the declared shared entries in the family library.

    A room can only bind a name that exists; the library is ours, so seeding
    it creates empty mount points (a zero-byte file or an empty directory) and
    never moves data. A name that already exists must be the declared kind and
    a real file/directory - a link or a foreign type is refused, not bound.
    """
    for name, kind in entries:
        relative = _safe_relative(name)
        target = store.joinpath(*relative.split("/"))
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
            if not stat.S_ISDIR(os.lstat(target).st_mode):
                raise LocalChannelError(
                    "SESSION_STORE_INVALID", f"{name} is not a directory")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            handle = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(handle)
            continue
        if not stat.S_ISREG(info.st_mode):
            raise LocalChannelError(
                "SESSION_STORE_INVALID", f"{name} is not a regular file")


def home_locator_segments(locator: str) -> list[str]:
    """`<role>` plus the registry's native home, each a short safe name.

    The same rule the Worker enforces for its own homes: one role segment plus
    a native home that may itself be nested (`.config/opencode`), so up to six
    segments are well-formed, and `.` / `..` are refused even though the
    character class alone would admit them.
    """
    segments = locator.split("/") if isinstance(locator, str) else []
    if not segments or len(segments) > 6 or any(not segment for segment in segments):
        raise LocalChannelError("HOME_LOCATOR_INVALID", "home locator is invalid")
    for segment in segments:
        if (len(segment) > 64 or segment in {".", ".."}
                or any(not (character.isascii() and (
                    character.isalnum() or character in "._-"))
                       for character in segment)):
            raise LocalChannelError("HOME_LOCATOR_INVALID", "home locator is invalid")
    return segments


class LocalHome:
    """One Profile's durable home directory on this machine."""

    def __init__(self, home_root: str | Path, locator: str, *,
                 profile_id: str, harness_type: str, native_home: str,
                 window: str = "", store: str | None = None) -> None:
        segments = home_locator_segments(locator)
        self.root = Path(home_root)
        self.role_dir = self.root.joinpath(*segments[:1])
        self.dir = self.root.joinpath(*segments)
        self.locator = "/".join(segments)
        self.profile_id = profile_id
        self.harness_type = harness_type
        self.native_home = native_home
        self.marker = self.role_dir / ".agentbox-profile.json"
        self.window = _safe_relative(window) if window else ""
        #: §14: the per-harness session library (host side). When present it is
        #: the audited tree - the store root itself, not a role-relative window.
        self.store = (self.root / "_sessions" / store) if store else None

    def prepare(self) -> Path:
        """Create the home, write or verify the marker, open the window.

        Returns the resolved home directory for the room's mount. A marker
        that names another product identity is a typed refusal: two Profiles
        never share one home.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        resolved = self.dir.resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise LocalChannelError("HOME_OUTSIDE_ROOT", "home escapes the home root")
        if self.store is not None:
            self.store.mkdir(parents=True, exist_ok=True)
            resolved_store = self.store.resolve()
            if not resolved_store.is_relative_to(self.root.resolve()):
                raise LocalChannelError(
                    "HOME_OUTSIDE_ROOT", "session store escapes the home root",
                )
        facts = {"profileId": self.profile_id, "harnessType": self.harness_type,
                 "nativeHome": self.native_home}
        if self.marker.exists():
            try:
                import json

                existing = json.loads(self.marker.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LocalChannelError("HOME_MARKER_CONFLICT", "home marker is not a valid marker") from exc
            if any(existing.get(key) != value for key, value in facts.items()):
                raise LocalChannelError(
                    "HOME_MARKER_CONFLICT", "the home belongs to another profile identity",
                )
        else:
            import json
            import time

            self.marker.parent.mkdir(parents=True, exist_ok=True)
            self.marker.write_text(json.dumps({**facts, "createdAt": int(time.time())}),
                                   encoding="utf-8")
            os.chmod(self.marker, 0o600)
        if self.window:
            # The window is role-relative: it may name a subtree outside the
            # native home, and prepare must create exactly the directory the
            # declared guest target binds to.
            (self.role_dir / self.window).mkdir(parents=True, exist_ok=True)
        return resolved

    # -- audit -------------------------------------------------------------

    def _relative_entries(self, base: Path, prefix: str, audit: dict) -> None:
        """One bounded, link-free walk of the window, as audit facts."""
        try:
            entries = sorted(os.scandir(base), key=lambda item: item.name)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise LocalChannelError("HOME_IO", "home listing failed") from exc
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                # The entry vanished between listing and stat: churn, reported
                # as a truncation fact by the audit accounting below.
                audit["visited"] += 1
                audit["truncated"]["entries"] += 1
                continue
            audit["visited"] += 1
            if audit["visited"] > 4096:
                # The walk is cut here: at least this entry was not audited.
                audit["truncated"]["entries"] += 1
                return
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if stat.S_ISLNK(info.st_mode):
                audit["skipped"] += 1
                continue
            if stat.S_ISDIR(info.st_mode):
                self._relative_entries(Path(entry.path), relative, audit)
                continue
            if not stat.S_ISREG(info.st_mode):
                audit["truncated"]["entries"] += 1
                continue
            if (len(audit["files"]) >= MAX_AUDIT_FILES
                    or info.st_size > MAX_AUDIT_FILE_BYTES
                    or audit["bytes"] + info.st_size > MAX_AUDIT_TOTAL_BYTES):
                audit["truncated"]["entries"] += 1
                audit["truncated"]["bytes"] += info.st_size
                if info.st_size > MAX_AUDIT_FILE_BYTES:
                    audit["truncated"]["oversize"] += 1
                continue
            audit["files"].append({"path": relative, "size": info.st_size})
            audit["bytes"] += info.st_size

    def _audit_base(self) -> Path:
        """The audited tree: the session store when declared, else the window."""
        if self.store is not None:
            return self.store
        return self.role_dir / self.window if self.window else self.dir

    def audit_facts(self) -> tuple[list[dict[str, Any]], dict[str, int], int]:
        facts: dict[str, Any] = {
            "files": [], "bytes": 0, "skipped": 0, "visited": 0,
            "truncated": {"entries": 0, "bytes": 0, "oversize": 0},
        }
        base = self._audit_base()
        self._relative_entries(base, "", facts)
        return facts["files"], facts["truncated"], facts["skipped"]

    def read(self, relative: str) -> tuple[bytes, str]:
        relative = _safe_relative(relative)
        base = self._audit_base()
        target = (base / relative).resolve()
        if not target.is_relative_to(base.resolve()):
            raise StateCaptureError("SIDECAR_STATE_PATH_INVALID", "state path escapes the window")
        try:
            info = os.lstat(target)
        except FileNotFoundError as exc:
            raise StateCaptureError("VIEW_MISSING", "the home file is gone") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise StateCaptureError("VIEW_SPECIAL_FILE", "home file is not a regular file")
        if info.st_size > MAX_AUDIT_FILE_BYTES:
            raise StateCaptureError("SIDECAR_STATE_OUTSIDE_BOUNDS", "home file exceeds the audit bound")
        handle = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(handle, "rb") as stream:
            content = stream.read(MAX_AUDIT_FILE_BYTES + 1)
        if len(content) > MAX_AUDIT_FILE_BYTES:
            raise StateCaptureError("SIDECAR_STATE_OUTSIDE_BOUNDS", "home file exceeds the audit bound")
        return content, "sha256:" + hashlib.sha256(content).hexdigest()

    def delete(self, relative: str) -> None:
        relative = _safe_relative(relative)
        base = self._audit_base()
        target = base / relative
        info = os.lstat(target)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise LocalChannelError("HOME_IO", "only a regular file may be removed from a home")
        os.unlink(target)


class LocalSidecarLauncher:
    """Run one execution-local room on this machine."""

    def __init__(
        self, *, workspace_path: str, bundle: Mapping[str, bytes],
        credential: bytes, projection_mounts: Sequence[tuple[str, str]] = (),
        runtime_artifact_mounts: Sequence[tuple[str, str]] = (),
        executable_mounts: Sequence[tuple[str, str]] = (),
        home_root: str | None = None, home_locator: str | None = None,
        profile_id: str | None = None, harness_type: str | None = None,
        native_home: str | None = None, state_target: str | None = None,
        state_ephemeral_paths: Sequence[str] = (),
        protected_state_paths: Sequence[str] = (),
        sandbox_port: "object | None" = None,
        session_store_harness: str | None = None,
        session_store_target: str | None = None,
        session_store_shared: Sequence[str] = (),
        subscription_files: Sequence[str] = (),
        subscription_asset: Mapping[str, bytes] | None = None,
        asset_files: Mapping[str, bytes] | None = None,
        usage_probe: Mapping[str, str] | None = None,
    ) -> None:
        if len(bundle) > MAX_BUNDLE_FILES or sum(map(len, bundle.values())) > MAX_BUNDLE_BYTES:
            raise ValueError("LOCAL_CHANNEL_BUNDLE_OUTSIDE_BOUNDS")
        for path in bundle:
            _safe_bundle_path(path)
        self.workspace_path = workspace_path
        self.bundle = dict(bundle)
        self.credential = credential
        self.projection_mounts = tuple(projection_mounts)
        self.runtime_artifact_mounts = tuple(runtime_artifact_mounts)
        self.executable_mounts = tuple(executable_mounts)
        # The home is this machine's own directory: prepare is done here, in
        # Python, exactly as the Worker does it remotely - same marker rule,
        # same window rule, no second authority.
        segments = home_locator_segments(home_locator) if home_locator else []
        self.native_home = native_home or (segments[-1] if len(segments) > 1 else "")
        self.home = (
            LocalHome(home_root, home_locator, profile_id=profile_id,
                      harness_type=harness_type, native_home=self.native_home,
                      window=_window_of(state_target, self.native_home),
                      store=session_store_harness)
            if home_root is not None and home_locator else None
        )
        self.session_store_harness = session_store_harness
        self.session_store_target = session_store_target
        #: Order 66's whole-db names and kinds (see the Worker-hosted launcher).
        self.session_store_shared = tuple(
            (str(name), str(kind)) for name, kind in session_store_shared)
        #: Order 56: the declared subscription working-copy names and the
        #: account asset bytes this turn materialises (empty when unbound).
        self.subscription_files = tuple(str(name) for name in subscription_files)
        self.subscription_asset = dict(subscription_asset or {})
        #: Order 58: rendered asset files, written once and never read back.
        self.asset_files = {str(name): bytes(text) for name, text in (asset_files or {}).items()}
        #: Order 55's probe rides the port (the backend reads it from here) and
        #: the read itself happens through the channels below; a deployment
        #: without a probe leaves every usage column NULL.
        self.usage_probe = dict(usage_probe) if usage_probe else None
        self.state_target = state_target
        self.state_ephemeral_paths = tuple(state_ephemeral_paths)
        self.protected_state_paths = tuple(protected_state_paths)
        #: The resolved sandbox, injected by the assembly boundary; a missing
        #: port is a typed refusal at launch, never a silent run.
        self.sandbox_port = sandbox_port

    def launch(self, environment: Mapping[str, str]):
        from pacthold.extensions.runtime_composition.sandbox_port import (
            SandboxPortUnavailable, SidecarRoomRequest,
        )

        if self.sandbox_port is None:
            raise LocalChannelError(
                "SANDBOX_PORT_UNAVAILABLE",
                "no sandbox provider was resolved for this execution",
            )
        root = Path(tempfile.mkdtemp(prefix="agentbox-local-channel-"))
        view = root / "view"
        view.mkdir()
        for path, content in sorted(self.bundle.items()):
            target = view.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        secret_path = None
        if self.credential:
            secret_file = root / "secret"
            fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(self.credential)
            secret_path = str(secret_file)
        home_dir = None
        native_bind_target = None
        window_host = None
        store_overlays: tuple[tuple[str, str], ...] = ()
        if self.home is not None:
            home_dir = str(self.home.prepare())
            if (self.session_store_shared and self.home.store is not None):
                _seed_store_entries(self.home.store, self.session_store_shared)
            if self.subscription_files:
                # Order 56: the working copy lands before the room exists, and
                # only the declared names are ever written.
                write_subscription_files(
                    self.home.role_dir, self.subscription_asset,
                    declared=self.subscription_files,
                )
            if self.asset_files:
                # Order 58: the rendered asset files take the same path.
                write_subscription_files(
                    self.home.role_dir, self.asset_files,
                    declared=tuple(sorted(self.asset_files)),
                )
            # Two read-write binds: the native home at its guest target, and —
            # when the deployment declared a window elsewhere — the window at
            # its own guest target.
            native_bind_target = f"/runtime/home/{self.native_home}"
            if self.session_store_harness is not None and self.home.store is not None:
                if self.session_store_shared:
                    # Order 66's whole-db: the library owns the named entries
                    # only; the profile's own data directory stays the window
                    # and each shared name is bound from the library over it.
                    if not self.home.window:
                        raise LocalChannelError(
                            "SESSION_STORE_INVALID",
                            "a whole-db session store needs a state target "
                            "outside the native home",
                        )
                    window_host = str(self.home.role_dir / self.home.window)
                    store_overlays = tuple(
                        (str(self.home.store.joinpath(*name.split("/"))),
                         f"{self.session_store_target}/{name}")
                        for name, _kind in self.session_store_shared
                    )
                else:
                    # §14: the session library replaces the in-home session
                    # subtree; the profile home still binds whole, and the
                    # deeper store bind wins by the existing depth ordering.
                    window_host = str(self.home.store)
            elif self.home.window and self.home.window != self.native_home:
                window_host = str(self.home.role_dir / self.home.window)
        window_target = (
            self.session_store_target if self.session_store_harness is not None
            else (self.state_target if window_host else None)
        )
        room = self.sandbox_port.compose_sidecar_room(SidecarRoomRequest(
            workspace=self.workspace_path, staged_view=str(view), secret=secret_path,
            base_environment=environment, executable_mounts=tuple(self.executable_mounts),
            projection_mounts=tuple(self.projection_mounts),
            runtime_artifact_mounts=tuple(self.runtime_artifact_mounts),
            state_home_source=home_dir, state_target=native_bind_target,
            native_home=self.native_home,
            state_window_source=window_host,
            state_window_target=window_target,
            state_overlays=store_overlays,
            state_ephemeral_paths=tuple(self.state_ephemeral_paths),
        ))
        # stderr goes to a file, not a pipe: a pipe nobody drains would block
        # the child, and the tail is what a failure needs to report.
        stderr_path = root / "stderr.log"
        stderr_file = stderr_path.open("wb")
        # Windows has no session/process-group with kill-on-close semantics:
        # the child joins a Job Object right after creation, and the Job is the
        # one thing that kills the whole tree (Order 48, D3). On POSIX the
        # session + killpg path stays exactly as it was.
        job = _new_process_job() if os.name == "nt" else None
        # Order 54: the before-snapshot of the declared workspace (bounded,
        # with content copies for the later line diff). Taken before the room
        # starts; the after-walk happens when the channels are audited.
        from ordessa_server_compat.execution.change_set import snapshot_with_copies

        before_snapshot = snapshot_with_copies(self.workspace_path, root / "before-copy")
        try:
            process = subprocess.Popen(  # noqa: S603 - the argv is the reviewed room
                list(room.argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=stderr_file, start_new_session=(os.name != "nt"),
            )
            if job is not None:
                job.assign_pid(process.pid)
        except BaseException:
            stderr_file.close()
            if job is not None:
                job.close()
            shutil.rmtree(root, ignore_errors=True)
            raise
        stderr_file.close()
        return _LocalChannels(
            process, root=root, view=view, stderr_path=stderr_path,
            credential=(self.credential or b'').strip(),
            home=self.home, before_snapshot=before_snapshot, job=job,
            protected_state_paths=self.protected_state_paths,
            state_ephemeral_paths=self.state_ephemeral_paths,
            subscription_files=self.subscription_files,
        )


class _LocalChannels:
    """One local child process, presented as the channel the harness port uses."""

    def __init__(
        self, process: subprocess.Popen, *, root: Path, view: Path, stderr_path: Path,
        credential: bytes, home: LocalHome | None,
        protected_state_paths: Sequence[str], state_ephemeral_paths: Sequence[str],
        job: "object | None" = None,
        before_snapshot: dict | None = None,
        workspace_root: "Path | None" = None,
        subscription_files: Sequence[str] = (),
    ) -> None:
        self.process = process
        #: Order 54: the attempt's before-snapshot of the declared workspace;
        #: the after-walk and the diff happen at the audit boundary.
        self.before_snapshot = before_snapshot
        self.workspace_root = workspace_root
        #: The Job Object that owns this child's tree on Windows; None on POSIX
        #: (there the session + killpg pair does the same work).
        self.job = job
        self.root = root
        self.view = view
        self.stderr_path = stderr_path
        self._credential = credential
        self.home = home
        self.protected_state_paths = tuple(protected_state_paths)
        self.state_ephemeral_paths = tuple(state_ephemeral_paths)
        self._subscription_files = tuple(subscription_files)
        self._lock = threading.RLock()
        self._closed = False

    # -- transport ---------------------------------------------------------
    def write_line(self, value: str) -> None:
        with self._lock:
            if self._closed or self.process.stdin is None or self.process.poll() is not None:
                raise RuntimeError("LOCAL_CHANNEL_CLOSED")
            self.process.stdin.write((value + "\n").encode("utf-8"))
            self.process.stdin.flush()

    def iter_chunks(self):
        """Decoded lines, as the envelope's reader expects its channel to speak."""
        assert self.process.stdout is not None
        return iter(lambda: self.process.stdout.readline().decode("utf-8", "replace"), "")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self.job is not None:
                # The whole tree, one call; KILL_ON_JOB_CLOSE reaps whatever
                # the kill raced with when the handle closes below.
                if self.process.poll() is None:
                    self.job.kill()
                    deadline = time.monotonic() + 5
                    while self.process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.05)
            else:
                if self.process.poll() is None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    deadline = time.monotonic() + 5
                    while self.process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.05)
                if self.process.poll() is None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            if self.job is not None:
                # Closing the last handle is the backstop: KILL_ON_JOB_CLOSE
                # reaps anything the explicit kill raced with.
                try:
                    self.job.close()
                except Exception:
                    pass
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            if os.environ.get("AGENTBOX_LOCAL_CHANNEL_KEEP") != "1":
                # A debug switch: keeping the root is how a failed launch's
                # stderr survives the close that a failure triggers. The home
                # is deliberately not part of this cleanup: it is the Profile's
                # durable directory, not this attempt's scratch.
                shutil.rmtree(self.root, ignore_errors=True)

    # -- audit -------------------------------------------------------------
    def workspace_change_set(self) -> dict[str, Any] | None:
        """Order 54: the per-turn change set of the declared workspace.

        The after-walk uses the same bounds as the before-walk; the diff is
        the neutral per-turn fact (added/modified/removed with honest line
        accounting). None when the workspace root is not a directory.
        """
        from ordessa_server_compat.execution.change_set import diff_snapshots, snapshot_with_copies

        if self.workspace_root is None or not Path(self.workspace_root).is_dir():
            return None
        after = snapshot_with_copies(
            Path(self.workspace_root), Path(self.root) / "after-copy")
        before = self.before_snapshot or {"files": {}, "skipped": 0,
                                          "truncated_entries": 0, "truncated_bytes": 0,
                                          "oversize_files": 0, "symlinks": 0, "special": 0}
        return diff_snapshots(before, after)

    def audit_state(self) -> dict[str, Any]:
        """Audit the declared home window under the shared audit rules."""
        if self.home is None:
            return {"files": [], "audited": {"files": 0, "bytes": 0,
                                             "truncated": {"entries": 0, "bytes": 0, "oversize": 0}},
                    "truncated": {"entries": 0, "bytes": 0, "oversize": 0}, "skipped": 0}
        files, truncated, skipped = self.home.audit_facts()
        return audit_snapshot(
            files, self.home.read,
            protected_state_paths=self.protected_state_paths,
            state_ephemeral_paths=self.state_ephemeral_paths,
            forbidden_content=self._credential,
            truncated=truncated,
            skipped=skipped,
        )

    def delete_state_file(self, relative: str) -> None:
        if self.home is not None:
            self.home.delete(relative)

    # -- subscription working copy (Order 56) ------------------------------
    def read_subscription(self) -> dict[str, bytes]:
        """Read the declared subscription working files back for reclaim."""
        if self.home is None or not self._subscription_files:
            return {}
        return read_subscription_files(
            self.home.role_dir, declared=self._subscription_files)

    # -- usage (Order 55) --------------------------------------------------
    def read_usage(self, usage_probe: Mapping[str, str] | None) -> dict[str, int] | None:
        """Read the declared journal from the local home and parse the fact.

        The same rule as the Worker-hosted channel: the journal is one of the
        files the audit already lists (same window, same bounds), the newest
        name wins, and the parse copies the family's own numbers - nothing
        here estimates and a family that reports nothing stays NULL.
        """
        from ordessa_server_compat.execution.usage import parse_usage

        if not usage_probe or self.home is None:
            return None
        suffix = usage_probe.get("journalSuffix")
        usage_format = usage_probe.get("format")
        if not suffix or not usage_format:
            return None
        try:
            files, _truncated, _skipped = self.home.audit_facts()
        except LocalChannelError:
            return None
        candidates = [
            str(entry.get("path", "")) for entry in files
            if str(entry.get("path", "")).endswith(suffix)
        ]
        if not candidates:
            return None
        path = max(candidates)  # journal names carry the newest timestamp last
        try:
            content, _digest = self.home.read(path)
        except (LocalChannelError, StateCaptureError, OSError):
            return None
        # A live SQLite carrier keeps recently committed rows in its -wal
        # sidecar; without it the parse reads a stale database and reports
        # "no usage" for a family that did report it.
        listed = {str(entry.get("path", "")) for entry in files}
        sidecars: dict[str, bytes] = {}
        for suffix_name in ("-wal", "-shm"):
            relative = f"{path}{suffix_name}"
            if relative in listed:
                try:
                    payload, _sidecar_digest = self.home.read(relative)
                except (LocalChannelError, StateCaptureError, OSError):
                    continue
                sidecars[suffix_name] = payload
        return parse_usage(usage_format, content, sidecars=sidecars or None)

    # -- diagnostics -------------------------------------------------------
    def stderr_tail(self, maximum: int = 2000) -> str:
        try:
            return self.stderr_path.read_text(errors="replace")[-maximum:]
        except OSError:
            return ""


def _new_process_job():
    """The Windows Job Object for one attempt's process tree (D3)."""
    import sys as _sys

    if _sys.platform != "win32":
        return None
    package_root = os.environ.get("AGENT_BOX_SANDBOX_WINDOWS_PATH")
    if package_root and package_root not in _sys.path:
        _sys.path.insert(0, package_root)
    try:
        from agent_box_sandbox_windows.job import Job
    except ImportError:
        raise LocalChannelError(
            "WINDOWS_JOB_UNAVAILABLE",
            "the Windows host stack needs the agent-box-sandbox-windows package",
        ) from None
    return Job(f"agentbox-attempt-{os.getpid()}-{time.monotonic_ns()}")


def _window_of(state_target: str | None, native_home: str) -> str:
    """The audit window relative to the role directory: `state_target` minus
    the guest home prefix. `.pi/agent/sessions` and `.local/share/opencode`
    are both role-relative windows; a target outside the guest home cannot be
    served by a home bind and is refused."""
    del native_home
    if not state_target:
        return ""
    prefix = "/runtime/home/"
    if not state_target.startswith(prefix) or state_target == prefix:
        raise ValueError("SIDECAR_STATE_PROJECTION_INVALID")
    window = state_target[len(prefix):]
    if (not window or window.startswith("/")
            or any(part in {"", ".", ".."} for part in window.split("/"))):
        raise ValueError("SIDECAR_STATE_PROJECTION_INVALID")
    return window


__all__ = ["LocalSidecarLauncher", "LocalChannelError", "LocalHome", "home_locator_segments"]

"""AgentBox-side client for the Harness sidecar envelope (Work Order 40 glue).

The sidecar owns ACP; this module only speaks the generic NDJSON envelope. It
never interprets a native protocol, never decides product state, and never sees
credential content: the Worker materializes credentials into the isolated
projection and the sidecar inherits nothing from this process's environment.

A launcher is injected so the same client runs over a local process (tests and
Linux acceptance) or over the Worker's interactive channel (WSL deployment).
"""
from __future__ import annotations

import json
import base64
import hashlib
from pathlib import Path, PurePosixPath
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .state_capture import StateCaptureError, audit_snapshot

from pacthold.resource_contracts.harness_capabilities import (
    CapabilityDeclaration, capability_view, merge_capabilities, validate_claims,
)


#: How often a blocked channel reader re-checks its keepalive. Small enough that
#: a failed lease ends the turn promptly, large enough not to spin.
LEASE_POLL_SECONDS = 0.25

#: Failures while reading a state subtree that mean "it is still moving", so the
#: capture keeps waiting (bounded) instead of accepting a mixed snapshot. The
#: list is deliberately short: everything else - a refusal, a bound violation,
#: credential material, a plain I/O fault - is reported as it happened, with the
#: code that names it. Classification reads the code alone, never the message.
#:
#: Audited Worker view sites, and what their codes mean here:
#:
#:   VIEW_CHANGED          an entry changed identity while the Worker was
#:                         reading it from an already-opened fd - churn
#:   VIEW_MISSING          an entry is not there - a refusal by the Worker
#:                         (it cannot know the caller ever saw it); this
#:                         capture converts it to its identity conflict
#:                         because it just listed the path
#:   VIEW_SPECIAL_FILE     a FIFO, socket or device, or a path resolving
#:                         through a symlink - a refusal, never churn
#:   VIEW_TRAVERSAL_LIMIT  more than 4096 visited entries - a refusal
#:   VIEW_FILE_LIMIT       more than 1024 files, in a listing or a manifest
#:   VIEW_INVALID          malformed identity, manifest, path or fetch range
#:                         (including a first fetch past the end of a file)
#:   VIEW_IO               a real listing, metadata, read or write fault
#:   VIEW_INCOMPLETE       the view is not committed, or a file is missing
#:   VIEW_DIGEST_MISMATCH  read-back did not match what was declared
_STATE_TRANSIENT_CODES = frozenset({
    "SIDECAR_STATE_IDENTITY_CONFLICT",  # raised here: size, offset or digest moved
    "VIEW_CHANGED",                     # the Worker's own "the bytes moved" code
})


def _matches_ephemeral_prefix(relative: str, prefixes: Sequence[str]) -> bool:
    """Whether a state-relative path is (under) a declared attempt-ephemeral
    directory. Shared by the capture exclusion and the restore drop: decision A
    keeps this scratch out of the view/state/checkpoint on every path."""
    for prefix in prefixes:
        if relative == prefix or relative.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _state_error_is_transient(error: BaseException) -> bool:
    """Whether a capture may wait for this failure to go away.

    Only the code decides. The same sentence can describe churn or a refusal, so
    no message text is inspected here: an untyped or unknown failure is reported
    as it arrived.
    """
    code = getattr(error, "code", None)
    return isinstance(code, str) and code in _STATE_TRANSIENT_CODES


#: The guest's isolated home root. Every Harness home is a projection inside it:
#: read-only configuration files and one bounded writable state subtree, both
#: declared by the deployment. It is never the host home and never a Windows
#: profile root.


class SidecarError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class SidecarLauncher(Protocol):
    """Starts the sidecar and returns (write, read) byte channels plus a stopper."""

    def launch(self, environment: Mapping[str, str]) -> "SidecarChannels": ...


class SidecarChannels(Protocol):
    def write_line(self, value: str) -> None: ...
    def iter_chunks(self): ...
    def close(self) -> None: ...


class LocalProcessLauncher:
    """Launch the sidecar as a local child process (tests, Linux acceptance)."""

    def __init__(self, command: Sequence[str], *, cwd: str | None = None) -> None:
        self.command = tuple(command)
        self.cwd = cwd

    def launch(self, environment: Mapping[str, str]):
        process = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, env=dict(environment), cwd=self.cwd,
        )
        assert process.stdin and process.stdout
        return _ProcessChannels(process)


class NativeProcessLauncher(LocalProcessLauncher):
    """Explicit host process for a selected local project, without room mounts."""

    def __init__(self, command: Sequence[str], *, cwd: str) -> None:
        if not cwd:
            raise ValueError("NATIVE_PROJECT_REQUIRED")
        super().__init__(command, cwd=cwd)


class _ProcessChannels:
    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process

    def write_line(self, value: str) -> None:
        """Write one envelope line, or refuse with the same typed error as the
        Worker channels do.

        A cancelled or already-finished execution can reach this after its
        channel was closed; the caller (`SidecarHarnessPort.cancel`) treats a
        typed closed-sidecar error as "nothing left to cancel", while a bare
        ValueError from a closed file object would escape it and fail the whole
        server shutdown.
        """
        stream = self.process.stdin
        if stream is None or getattr(stream, "closed", False):
            raise SidecarError("SIDECAR_CLOSED", "sidecar channel is closed")
        try:
            stream.write((value + "\n").encode("utf-8"))
            stream.flush()
        except (ValueError, OSError) as exc:
            raise SidecarError("SIDECAR_CLOSED", "sidecar channel is closed") from exc

    def iter_chunks(self):
        assert self.process.stdout
        return iter(lambda: self.process.stdout.readline().decode("utf-8", "replace"), "")

    def close(self) -> None:
        process = self.process
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def _advertised(capability: Any) -> bool | None:
    """A native capability advertisement, read as the tri-state it really is.

    ACP marks a session capability by its presence, conventionally as an empty
    object. Treating the value as a boolean would make every such Harness look
    incapable in Python, where `{}` is falsy but an absent or explicitly false
    value is the only honest "no". A missing key (or an explicit null) is not an
    advertisement at all and stays "not observed".
    """
    if capability is None:
        return None
    if capability is False:
        return False
    return True


def _advertised_image(capability: Any) -> bool | None:
    """`promptCapabilities.image`: only an explicit truth is an observation.

    A missing or explicitly false value stays "not observed": attachment
    support is never inferred from a default policy or from a nearby ability.
    """
    if capability is None or capability is False:
        return None
    return True


def _require_matching_artifact_authorizations(
    authorizations: Sequence[Mapping[str, str]],
    mounts: Sequence[tuple[str, str]],
) -> None:
    """Every runtime artifact mount must carry its own declaration.

    A mount without a declaration would reach bwrap unverified; a declaration
    without a mount would be a claim the Server silently dropped.  Both are
    refused here, before any Worker is contacted.
    """
    declared = {(str(item.get("path")), str(item.get("target"))) for item in authorizations}
    mounted = {(str(source), str(target)) for source, target in mounts}
    if len(declared) != len(authorizations) or len(mounted) != len(mounts):
        raise ValueError("SIDECAR_RUNTIME_ARTIFACT_DECLARATION_DUPLICATED")
    if declared != mounted:
        raise ValueError("SIDECAR_RUNTIME_ARTIFACT_DECLARATION_MISMATCH")


def _safe_bundle_relative(value: str) -> bool:
    return (isinstance(value, str) and not value.startswith("/")
            and "\x00" not in value and "//" not in value
            and not any(part in {"", ".", ".."} for part in value.split("/")))


def sidecar_bundle_files(
    plugin_root: Path | str, *,
    closure: Sequence[tuple[str, str]] | None = None,
    additional_files: Mapping[str, bytes] | None = None,
) -> dict[str, bytes]:
    """Load the reviewed sidecar closure for one bounded Worker projection.

    E-INC1a (a-6): ``closure`` is the neutral seam - a pure data list of
    ``(source_relative, target_relative)`` pairs. When given, this function
    assembles exactly what the declaration says (path-safety validation and
    bounds unchanged) and touches none of the literal view layout below.
    The ``closure=None`` branch is the *frozen compatibility shell* for the
    bootstrap call site's two-positional shape: the hardcoded
    view-layout names are Harness-runtime content, owned by H (C-HARNESS,
    IFR-04), and this shell leaves with INC1b once that declaration exists -
    nothing outside it may grow these literals (pinned in the group tests).
    """
    root = Path(plugin_root).resolve()
    if closure is not None:
        files: dict[str, bytes] = {}
        for source_relative, target_relative in closure:
            if not _safe_bundle_relative(source_relative) or not _safe_bundle_relative(target_relative):
                raise ValueError("SIDECAR_BUNDLE_PATH_INVALID")
            if target_relative in files:
                raise ValueError("SIDECAR_BUNDLE_PATH_CONFLICT")
            files[target_relative] = (root / source_relative).read_bytes()
        return _finish_bundle(files, additional_files)
    runtime = root / "runtime"
    snapshot = root / "third_party" / "harness_remote"
    source = json.loads((snapshot / "SOURCE.json").read_text(encoding="utf-8"))
    files = {
        "agentbox-sidecar/package.json": (runtime / "package.json").read_bytes(),
        "agentbox-sidecar/runtime/worker-entry.mjs": (runtime / "worker-entry.mjs").read_bytes(),
        "agentbox-sidecar/runtime/native-driver.mjs": (runtime / "native-driver.mjs").read_bytes(),
        # The validated static ceiling, so the sidecar can refuse to project a
        # capability its Harness never declared instead of guessing.
        "agentbox-sidecar/runtime/capability_declarations.json": (
            runtime / "capability_declarations.json"
        ).read_bytes(),
        "agentbox-sidecar/runtime/profile_extensions.mjs": (
            runtime / "profile_extensions.mjs"
        ).read_bytes(),
        # Order 65 C: the delegation bridge - the stdio MCP server a parent
        # Harness starts when its Profile holds delegation grants.
        "agentbox-sidecar/runtime/subagent-bridge.mjs": (
            runtime / "subagent-bridge.mjs"
        ).read_bytes(),
        "agentbox-sidecar/third_party/harness_remote/SOURCE.json": (
            snapshot / "SOURCE.json"
        ).read_bytes(),
    }
    for item in source.get("files", ()):
        relative = str(item["path"])
        files[f"agentbox-sidecar/third_party/harness_remote/{relative}"] = (
            snapshot / relative
        ).read_bytes()
    return _finish_bundle(files, additional_files)


def _finish_bundle(
    files: dict[str, bytes], additional_files: Mapping[str, bytes] | None,
) -> dict[str, bytes]:
    """Shared tail: caller extras and the worker bounds, identical for both
    the declared-closure path and the frozen compatibility shell."""
    for relative, content in (additional_files or {}).items():
        if not _safe_bundle_relative(relative):
            raise ValueError("SIDECAR_BUNDLE_PATH_INVALID")
        if relative in files:
            raise ValueError("SIDECAR_BUNDLE_PATH_CONFLICT")
        files[relative] = bytes(content)
    if len(files) > 1024 or sum(map(len, files.values())) > 64 * 1024 * 1024:
        raise ValueError("SIDECAR_BUNDLE_OUTSIDE_WORKER_BOUNDS")
    return files


class WorkerSidecarLauncher:
    """Launch the reviewed sidecar through one Worker's interactive channel.

    The Worker is the host boundary, and this launcher is what it looks like from
    the product side: stage the bytes, ask the sandbox layer for the room, spawn,
    stream, capture. Which machine the Worker runs on is the connector's fact,
    not this class's - a WSL Worker and an SSH Worker take exactly this path, and
    neither one makes this layer know a host name.
    """

    def __init__(
        self, connector, *, workspace: Mapping[str, Any], bundle: Mapping[str, bytes],
        credential: bytes | None = None,
        executable_authorizations: Sequence[Mapping[str, str]] = (),
        executable_mounts: Sequence[tuple[str, str]] = (),
        runtime_artifact_authorizations: Sequence[Mapping[str, str]] = (),
        runtime_artifact_mounts: Sequence[tuple[str, str]] = (),
        projection_mounts: Sequence[tuple[str, str]] = (),
        home_locator: str = "", native_home: str = "", profile_id: str = "",
        harness_type: str = "", audit_window: str | None = None,
        state_ephemeral_paths: Sequence[str] = (),
        protected_state_paths: Sequence[str] = (),
        timeout_ms: int = 120_000,
        sandbox_port: "SandboxPort | None" = None,
        session_store_harness: str | None = None,
        session_store_target: str | None = None,
        session_store_shared: Sequence[str] = (),
        subscription_files: Sequence[str] = (),
        asset_files: Mapping[str, bytes] | None = None,
        usage_probe: dict[str, str] | None = None,
    ) -> None:
        self.connector = connector
        self.workspace = dict(workspace)
        self.bundle = {str(path): bytes(content) for path, content in bundle.items()}
        self.credential = None if credential is None else bytes(credential)
        self.executable_authorizations = tuple(dict(item) for item in executable_authorizations)
        self.executable_mounts = tuple((str(source), str(target)) for source, target in executable_mounts)
        self.runtime_artifact_authorizations = tuple(
            dict(item) for item in runtime_artifact_authorizations
        )
        self.runtime_artifact_mounts = tuple(
            (str(source), str(target)) for source, target in runtime_artifact_mounts
        )
        _require_matching_artifact_authorizations(
            self.runtime_artifact_authorizations, self.runtime_artifact_mounts,
        )
        self.projection_mounts = tuple((str(source), str(target)) for source, target in projection_mounts)
        #: The Profile's durable home on the target machine: `<role>/<native
        #: home>` under the machine's home root. The Worker creates and marker-
        #: verifies it; nothing about it is ever uploaded or restored.
        self.home_locator = str(home_locator)
        self.native_home = str(native_home)
        self.profile_id = str(profile_id)
        self.harness_type = str(harness_type)
        #: The declared audit window: the deployment's `stateProjection.target`
        #: minus the guest home prefix, relative to the role directory.
        self.audit_window = audit_window
        #: Paths (relative to the audit window) that a read-only projection
        #: owns. They are excluded from the audit by name: configuration the
        #: deployment projects read-only is not Harness state.
        self.protected_state_paths = tuple(_safe_relative_state_path(path) for path in protected_state_paths)
        self.state_ephemeral_paths = tuple(state_ephemeral_paths)
        self.timeout_ms = timeout_ms
        #: The resolved sandbox, injected by the assembly boundary. The channel
        #: states the demand; this object translates it. A missing port is a
        #: typed refusal at launch, never a silent run without isolation.
        self.sandbox_port = sandbox_port
        #: §14: when set, this Harness's session subtree lives in the per-harness
        #: session library on the target machine (shared by every profile of the
        #: family) instead of inside the profile's native home. The declared
        #: state target is then the session subtree's guest path.
        self.session_store_harness = session_store_harness
        #: The declared session-subtree guest path the store binds at (the
        #: deployment's state target when the family split its store out).
        self.session_store_target = session_store_target
        #: Order 66's whole-db names and kinds: the entries the family library
        #: owns, bound over the profile home's own copies. Empty means the
        #: store (if any) is the §14 subtree shape.
        self.session_store_shared = tuple(
            (str(name), str(kind)) for name, kind in session_store_shared)
        #: Order 58: rendered asset files (role-relative name -> text). They
        #: are written once per turn and never read back - assets have zero
        #: writeback by construction.
        self.asset_files = dict(asset_files or {})
        #: Order 56: a bound subscription account's working-copy names. The
        #: Worker-hosted channel has no home-write op yet, so a bound account
        #: on this channel is a typed refusal rather than a silent no-op.
        self.subscription_files = tuple(str(name) for name in subscription_files)
        #: Order 51: a declared usage probe turns the audited journal into the
        #: neutral usage fact after the attempt (tokens only, no estimates).
        self.usage_probe = dict(usage_probe) if usage_probe else None

    def launch(self, environment: Mapping[str, str]):
        from pacthold.extensions.runtime_composition.sandbox_port import (
            SandboxPortUnavailable, SidecarRoomRequest,
        )

        if self.sandbox_port is None:
            raise SidecarError(
                "SANDBOX_PORT_UNAVAILABLE",
                "no sandbox provider was resolved for this execution",
            )

        attempt_id = f"sidecar-{uuid4().hex}"
        view_id = f"view-{attempt_id}"
        secret_frame_id = "harness-credential"
        credential_material, self.credential = self.credential, None
        client = self.connector.client_for_workspace(
            distribution=self.workspace["distribution"],
            user=self.workspace["remote_user"],
            connection_id=self.workspace["connection_id"],
            workspace_path=self.workspace["remote_path"],
            executable_authorizations=self.executable_authorizations,
            runtime_artifact_authorizations=self.runtime_artifact_authorizations,
        )
        try:
            client.start()
        except BaseException as error:
            client.close()
            # A Worker bootstrap refusal carries a code (an unsupported control
            # protocol, or a runtime artifact tree whose digest did not match
            # its declaration). Re-raise it as this layer's typed error so the
            # reason survives into durable product state instead of a bare
            # disconnect message.
            code = getattr(error, "code", None)
            if isinstance(code, str) and code:
                raise SidecarError(code, str(error)) from error
            raise
        try:
            manifest = [
                {"path": path, "size": len(content), "digest": _sha256(content)}
                for path, content in sorted(self.bundle.items())
            ]
            client.request("view.prepare", {"viewId": view_id, "files": manifest})
            for path, content in sorted(self.bundle.items()):
                for offset in range(0, len(content), 32 * 1024):
                    client.request("view.put", {
                        "viewId": view_id, "path": path, "offset": offset,
                        "data": base64.b64encode(content[offset:offset + 32 * 1024]).decode(),
                    })
            runtime_view = client.request("view.commit", {"viewId": view_id})["path"]
            secret = None
            if credential_material is not None:
                secret = client.request("secret.put", {
                    "attemptId": attempt_id, "frameId": secret_frame_id,
                    "data": base64.b64encode(credential_material).decode(),
                })["path"]
            # Order 54: the launcher's before-snapshot of the declared
            # workspace, taken while the room's files do not exist yet — the
            # audit's after listing diffs against this. An older Worker
            # without the op (or a deployment that declared no workspace)
            # degrades to None: the change set stays honestly unknown instead
            # of failing the turn.
            before_snapshot = None
            try:
                listing = client.request("workspace.list", {}, timeout=60.0)
                before_snapshot = {
                    entry.get("path"): entry
                    for entry in listing.get("files", ())
                    if entry.get("path")
                }
            except Exception:
                before_snapshot = None
            # The home is prepared before the room exists: the Worker creates
            # (or marker-verifies) the Profile's directory and the declared
            # audit window, and answers with the host path that the room will
            # bind read-write. Nothing is uploaded; nothing is restored.
            home_path = None
            window_host = None
            store_overlays: tuple[tuple[str, str], ...] = ()
            if self.home_locator:
                home_path = client.request("home.prepare", {
                    "locator": self.home_locator,
                    "marker": {"profileId": self.profile_id, "harnessType": self.harness_type,
                               "nativeHome": self.native_home},
                    **({"window": self.audit_window} if self.audit_window else {}),
                })["path"]
                if self.subscription_files:
                    # Order 56: the working copy is written through home.put
                    # (role-relative, like every home op) before the room
                    # exists; only the declared names, only this turn's asset.
                    materialize_subscription(
                        client, locator=self.home_locator,
                        declared=self.subscription_files,
                        asset=self.subscription_asset,
                    )
                if self.asset_files:
                    # Order 58: the rendered asset files take the same path.
                    materialize_subscription(
                        client, locator=self.home_locator,
                        declared=tuple(sorted(self.asset_files)),
                        asset=self.asset_files,
                    )
                if self.session_store_harness:
                    # §14: the declared state target is the session subtree, and
                    # its host side is the per-harness library (no profile
                    # marker: the library is harness-scoped). The room binds the
                    # library at that deeper target, so it wins over the profile
                    # home's own subtree by the existing depth ordering.
                    seed = (
                        [{"name": name, "kind": kind}
                         for name, kind in self.session_store_shared]
                        if self.session_store_shared else None
                    )
                    library_host = client.request("home.prepare", {
                        "locator": self.session_store_harness,
                        "harness": self.session_store_harness,
                        "kind": "session-store",
                        **({"entries": seed} if seed else {}),
                    })["path"]
                    if self.session_store_shared:
                        # Order 66's whole-db: the library owns the named
                        # entries only. The profile's own data directory stays
                        # the window (log/, repos/, telemetry-id, auth.json
                        # live there), and each shared name is bound from the
                        # library over it.
                        if not self.audit_window:
                            raise SidecarError(
                                "SESSION_STORE_INVALID",
                                "a whole-db session store needs a state target "
                                "outside the native home",
                            )
                        suffix = f"/{self.native_home}"
                        role_dir = (
                            home_path[: -len(suffix)] if home_path.endswith(suffix) else home_path
                        )
                        window_host = f"{role_dir}/{self.audit_window}"
                        store_overlays = tuple(
                            (f"{library_host}/{name}",
                             f"{self.session_store_target}/{name}")
                            for name, _kind in self.session_store_shared
                        )
                    else:
                        window_host = library_host
                elif self.audit_window and self.audit_window != self.native_home:
                    # The prepared path ends with the locator's segments, so the
                    # role directory it belongs to is the prefix above the
                    # native home; the window hangs off that role directory.
                    suffix = f"/{self.native_home}"
                    role_dir = (
                        home_path[: -len(suffix)] if home_path.endswith(suffix) else home_path
                    )
                    window_host = f"{role_dir}/{self.audit_window}"
            # The room is the sandbox layer's product, not this channel's: the
            # guest home layout, the XDG roots, which mounts are writable and
            # which state paths are attempt-ephemeral are all decided there.
            # This layer only supplies the token bindings it just obtained and
            # the neutral demand; the resolved provider translates it.
            room = self.sandbox_port.compose_sidecar_room(SidecarRoomRequest(
                workspace=self.workspace["remote_path"], staged_view=runtime_view,
                secret=secret, base_environment=environment,
                executable_mounts=tuple(self.executable_mounts),
                projection_mounts=tuple(self.projection_mounts),
                runtime_artifact_mounts=tuple(self.runtime_artifact_mounts),
                state_home_source=home_path,
                state_target=f"/runtime/home/{self.native_home}" if home_path else None,
                native_home=self.native_home,
                state_window_source=window_host,
                state_window_target=(
                    self.session_store_target if self.session_store_harness
                    else (f"/runtime/home/{self.audit_window}" if window_host else None)
                ),
                state_overlays=store_overlays,
                state_ephemeral_paths=tuple(self.state_ephemeral_paths),
            ))
            argv = list(room.argv)
            if self.session_store_harness:
                # §14: the audited tree is the per-harness store; the credential
                # rule's delete walks the same locator.
                store_locator = f"_sessions/{self.session_store_harness}"
                channels_kwargs = {"home_locator": store_locator, "audit_window": None,
                                   "audit_whole_home": True}
            else:
                channels_kwargs = {"home_locator": self.home_locator,
                                   "audit_window": self.audit_window}
            channels = _WorkerChannels(
                client, attempt_id, 1, view_id,
                secret_frame_id if secret is not None else None,
                **channels_kwargs,
                protected_state_paths=self.protected_state_paths,
                state_ephemeral_paths=self.state_ephemeral_paths,
                forbidden_content=(credential_material or b"").strip(),
                usage_probe=self.usage_probe,
                workspace_before_snapshot=before_snapshot,
                subscription_files=self.subscription_files,
            )
            channels.subscribe()
            client.request(
                "spawn", {"argv": argv, "timeoutMs": self.timeout_ms,
                          "stdinBase64": "", "interactive": True},
                attempt_id=attempt_id, generation=1,
            )
            return channels
        except BaseException:
            if credential_material is not None:
                try:
                    client.request("secret.cleanup", {
                        "attemptId": attempt_id, "frameId": secret_frame_id,
                    }, timeout=2)
                except BaseException:
                    pass
            try:
                client.request("view.cleanup", {"viewId": view_id}, timeout=2)
            except BaseException:
                pass
            client.close()
            raise


#: The name under which this launcher was WSL-only. Every caller it had - the
#: four family gates, the Windows acceptance and the tests - still reads it; the
#: class itself has since stopped knowing which machine its Worker runs on.
WslSidecarLauncher = WorkerSidecarLauncher


def materialize_subscription(
    client, *, locator: str, declared: Sequence[str], asset: Mapping[str, bytes],
) -> list[str]:
    """Write this turn's subscription working copy through `home.put`.

    One bounded call per declared name the asset actually carries; nothing
    else is ever sent, and a name the asset does not hold is left alone (the
    Harness may create it, and the reclaim decides what that means).
    """
    written: list[str] = []
    for name in declared:
        payload = asset.get(name)
        if payload is None:
            continue
        client.request("home.put", {
            "locator": locator, "path": name,
            "data": base64.b64encode(payload).decode("ascii"),
        }, timeout=30.0)
        written.append(name)
    return written


class _WorkerChannels:
    def __init__(
        self, client, attempt_id: str, generation: int, view_id: str,
        secret_frame_id: str | None = None,
        home_locator: str = "", audit_window: str | None = None,
        audit_whole_home: bool = False,
        usage_probe: Mapping[str, str] | None = None,
        workspace_before_snapshot: Mapping[str, Any] | None = None,
        protected_state_paths: Sequence[str] = (),
        state_ephemeral_paths: Sequence[str] = (),
        forbidden_content: bytes = b"",
        subscription_files: Sequence[str] = (),
    ) -> None:
        self.client = client
        self.attempt_id = attempt_id
        self.generation = generation
        self.view_id = view_id
        self.secret_frame_id = secret_frame_id
        self.home_locator = home_locator
        self.audit_window = audit_window
        #: §14 session library: the audited tree *is* the store root (the
        #: locator already names it), so the walk starts at the root instead of
        #: at a role-relative window inside it.
        self.audit_whole_home = bool(audit_whole_home)
        #: Order 51: the declared usage probe (journal suffix + format), used
        #: after the attempt to read the family's own numbers.
        self.usage_probe = dict(usage_probe) if usage_probe else None
        #: Order 54: the launcher's before-snapshot of the declared workspace
        #: (path -> {size, digest}); the after listing comes from
        #: `workspace.list` over the same root.
        #: Order 142: distinguish a *declared empty* workspace (`{}`) from *no
        #: snapshot at all* (`None`). `{}` is falsy, so the old truthiness test
        #: folded it into `None` and `workspace_change_set` then reported the WSL
        #: channel's change set as unknown on every first turn. Keep `{}` as `{}`.
        self.workspace_before_snapshot = (
            dict(workspace_before_snapshot) if workspace_before_snapshot is not None else None
        )
        #: Read-only configuration that lives *inside* the audited window. It
        #: is not state: it must not enter the audit manifest.
        self.protected_state_paths = frozenset(protected_state_paths)
        self.state_ephemeral_paths = tuple(state_ephemeral_paths)
        self._forbidden_content = forbidden_content
        #: Order 56's declared working-copy names, read back for the reclaim.
        self._subscription_files = tuple(subscription_files)
        self._chunks: queue.Queue = queue.Queue()
        self._unsubscribe = None
        self._disconnect_unsubscribe = None
        self._closed = False
        # The Worker cancels any attempt whose client stays quiet past its
        # lease, and a sidecar prompt is exactly such a client. This owner keeps
        # the lease alive for as long as the attempt does; it is started in
        # `subscribe()` (not here) because the launcher may hand us a client
        # substitute that has no lease support at all.
        self._lease_keepalive = None

    def subscribe(self) -> None:
        self._unsubscribe = self.client.subscribe_output(self._worker_event)
        subscribe_disconnect = getattr(self.client, "subscribe_disconnect", None)
        if callable(subscribe_disconnect):
            self._disconnect_unsubscribe = subscribe_disconnect(self._worker_disconnect)
        keep_lease = getattr(self.client, "keep_lease", None)
        if callable(keep_lease):
            # Before `spawn`, so the very first silent stretch is covered too.
            self._lease_keepalive = keep_lease(label=f"channels-{self.attempt_id}")
            self._lease_keepalive.start()

    def _worker_disconnect(self, error) -> None:
        if not self._closed:
            self._chunks.put(SidecarError(
                "WORKER_DISCONNECTED", getattr(error, "message", str(error)),
            ))

    def _worker_event(self, event: Mapping[str, Any]) -> None:
        result = event.get("result") or {}
        if (result.get("attemptId") != self.attempt_id
                or int(result.get("generation", -1)) != self.generation):
            return
        if event.get("event") == "process.terminal":
            self._stop_lease()  # the attempt is over; nothing left to keep alive
            self._chunks.put(None)
            return
        if event.get("event") != "process.output" or result.get("stream") != "stdout":
            return
        if result.get("truncated"):
            self._chunks.put(SidecarError("SIDECAR_OUTPUT_TRUNCATED", "Worker stream budget exceeded"))
            return
        try:
            content = base64.b64decode(result.get("data", ""), validate=True)
        except ValueError as exc:
            self._chunks.put(SidecarError("SIDECAR_OUTPUT_INVALID", str(exc)))
            return
        if content:
            self._chunks.put(content.decode("utf-8", "replace"))

    def write_line(self, value: str) -> None:
        if self._closed:
            raise SidecarError("SIDECAR_CLOSED", "Worker sidecar is closed")
        content = (value + "\n").encode("utf-8")
        for offset in range(0, len(content), 60 * 1024):
            chunk = content[offset:offset + 60 * 1024]
            deadline = time.monotonic() + 2
            while True:
                try:
                    self.client.write_stdin(
                        self.attempt_id, self.generation, chunk, timeout=10,
                    )
                    break
                except BaseException as exc:
                    # spawn acknowledgement precedes child-pipe installation.
                    # ATTEMPT_NOT_READY is issued before any byte is written,
                    # so this one narrow retry cannot duplicate input.
                    if (getattr(exc, "code", None) != "ATTEMPT_NOT_READY"
                            or time.monotonic() >= deadline):
                        raise
                    time.sleep(0.01)

    def iter_chunks(self):
        while True:
            try:
                item = self._chunks.get(timeout=LEASE_POLL_SECONDS)
            except queue.Empty:
                # A failed keepalive must end this turn - typed, and without
                # waiting for a frame that will never arrive.
                failure = self._lease_failure()
                if failure is not None:
                    raise failure
                continue
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def _lease_failure(self) -> SidecarError | None:
        """The keepalive's typed failure, if the lease could not be kept."""
        owner = self._lease_keepalive
        failure = getattr(owner, "failure", None) if owner is not None else None
        if failure is None:
            return None
        code = getattr(failure, "code", None) or "WORKER_LEASE_HEARTBEAT_FAILED"
        message = getattr(failure, "message", None) or str(failure)
        return SidecarError(str(code), str(message))

    def _stop_lease(self) -> None:
        owner, self._lease_keepalive = self._lease_keepalive, None
        if owner is not None:
            try:
                owner.stop()
            except BaseException:  # noqa: BLE001 - stopping must never mask the turn
                pass

    def audit_state(self) -> dict[str, Any]:
        """Audit the declared home window through the shared audit rules.

        Nothing is uploaded and nothing is restored: the Worker lists its own
        durable home (`home.list`, digest included, bounded, truncation as a
        fact), and the only bytes read are the ones the fail-closed credential
        scan must look at. The manifest that comes out is a *record* of what
        the home looks like, not a copy of it.
        """
        if not self.home_locator or (self.audit_window is None and not self.audit_whole_home):
            return {
                "files": [], "skipped": 0,
                "truncated": {"entries": 0, "bytes": 0, "oversize": 0},
                "audited": {"files": 0, "bytes": 0,
                            "truncated": {"entries": 0, "bytes": 0, "oversize": 0}},
            }
        # Real homes can be large (hundreds of MB, thousands of files); the
        # walk stays bounded by the Worker's audit caps but takes longer than
        # the default RPC window, so the audit carries its own generous one.
        result = self.client.request("home.list", {
            "locator": self.home_locator,
            **({"relative": self.audit_window} if self.audit_window else {}),
        }, timeout=120.0)
        try:
            return audit_snapshot(
                result.get("files", ()), self._home_bytes,
                protected_state_paths=tuple(self.protected_state_paths),
                state_ephemeral_paths=self.state_ephemeral_paths,
                forbidden_content=self._forbidden_content,
                truncated=result.get("truncated") or {},
                skipped=int(result.get("skipped") or 0),
            )
        except StateCaptureError as error:
            # The shared rules speak their own error type; this layer's callers
            # expect the sidecar's, with the same code - and the credential
            # rule needs the offending relative path with it.
            failure = SidecarError(error.code, str(error))
            failure.path = getattr(error, "path", None)
            raise failure from error

    def read_usage(
        self, usage_probe: Mapping[str, str] | None,
    ) -> dict[str, int] | None:
        """Read the declared journal via home.get and parse the usage fact.

        Nothing here estimates: the parser copies the family's own numbers, a
        family that reports nothing leaves every column NULL, and the read
        rides the same audited, bounded home channel the capture uses.
        """
        from ordessa_server_compat.execution.usage import parse_usage

        if not usage_probe or not self.home_locator:
            return None
        suffix = usage_probe.get("journalSuffix")
        usage_format = usage_probe.get("format")
        if not suffix or not usage_format:
            return None
        listing = self.client.request("home.list", {
            "locator": self.home_locator,
            **({"relative": self.audit_window} if self.audit_window else {}),
        }, timeout=60.0)
        candidates = [
            entry["path"] for entry in listing.get("files", ())
            if str(entry.get("path", "")).endswith(suffix)
        ]
        if not candidates:
            return None
        path = max(candidates)  # journal names carry the newest timestamp last
        full = f"{self.audit_window}/{path}" if self.audit_window else path
        def fetch(relative_path: str) -> bytes | None:
            chunks = bytearray()
            while True:
                item = self.client.request("home.get", {
                    "locator": self.home_locator, "path": relative_path,
                    # The Worker's own fetch bound is 32 KiB per response; asking
                    # for more is a typed range refusal, not a shorter answer.
                    "offset": len(chunks), "maxLength": 32 * 1024,
                })
                if not isinstance(item.get("data"), str):
                    raise SidecarError("SIDECAR_STATE_INVALID", "home fetch data is invalid")
                chunks.extend(base64.b64decode(item["data"], validate=True))
                if item.get("eof") is True:
                    break
                if len(chunks) > 4 * 1024 * 1024:
                    raise SidecarError(
                        "SIDECAR_STATE_OUTSIDE_BOUNDS", "usage journal exceeds the read bound",
                    )
            return bytes(chunks)

        content = fetch(full)
        # A live SQLite carrier keeps recently committed rows in its -wal
        # sidecar; fetching only the main file would read a stale database and
        # report "no usage" for a family that did report it.
        listed = {str(entry.get("path", "")) for entry in listing.get("files", ())}
        sidecars: dict[str, bytes] = {}
        for suffix_name in ("-wal", "-shm"):
            relative = f"{path}{suffix_name}"
            if relative in listed:
                full_sidecar = f"{self.audit_window}/{relative}" if self.audit_window else relative
                try:
                    sidecars[suffix_name] = fetch(full_sidecar)
                except (SidecarError, KeyError):
                    sidecars.pop(suffix_name, None)
        return parse_usage(usage_format, content, sidecars=sidecars or None)

    def read_subscription(self) -> dict[str, bytes]:
        """Read the declared subscription working files back (order 56).

        Role-relative, like every home op: the declared name is the path.
        A missing file is simply absent; one unreadable name does not hide the
        others, and the reclaim treats the result as "no working copy".
        """
        files: dict[str, bytes] = {}
        for name in self._subscription_files:
            chunks = bytearray()
            try:
                while True:
                    item = self.client.request("home.get", {
                        "locator": self.home_locator, "path": name,
                        "offset": len(chunks), "maxLength": 32 * 1024,
                    })
                    if not isinstance(item.get("data"), str):
                        raise SidecarError("SIDECAR_STATE_INVALID", "home fetch data is invalid")
                    chunks.extend(base64.b64decode(item["data"], validate=True))
                    if item.get("eof") is True:
                        break
                    if len(chunks) > 512 * 1024:
                        raise SidecarError(
                            "SIDECAR_STATE_OUTSIDE_BOUNDS",
                            "subscription file exceeds the read bound",
                        )
            except (SidecarError, KeyError, ValueError):
                continue
            if chunks:
                files[name] = bytes(chunks)
        return files

    def workspace_change_set(self) -> dict[str, Any] | None:
        """Order 54: diff the workspace against the launcher's before-snapshot.

        The after listing comes from the Worker's `workspace.list` op (same
        bounded, link-free walk as the home audit). Line counts are not
        available on this channel: the Worker reports path/size/digest only,
        and no content copies cross the wire — the fact records that honestly.
        """
        if self.workspace_before_snapshot is None:
            return None
        listing = self.client.request("workspace.list", {}, timeout=120.0)
        before = self.workspace_before_snapshot
        after = {}
        for entry in listing.get("files", ()):
            path = entry.get("path")
            if path:
                after[path] = {"size": entry.get("size"), "digest": entry.get("digest")}
        added, modified, removed = [], [], []
        for path in sorted(set(before) | set(after)):
            b, a = before.get(path), after.get(path)
            bd = b.get("digest") if isinstance(b, dict) else None
            ad = a.get("digest") if isinstance(a, dict) else None
            entry = {"path": path,
                     "sizeBefore": b.get("size") if isinstance(b, dict) else None,
                     "sizeAfter": a.get("size") if isinstance(a, dict) else None}
            if b is None and a is not None:
                added.append({**entry, "kind": "added"})
            elif b is not None and a is None:
                removed.append({**entry, "kind": "removed"})
            elif isinstance(b, dict) and isinstance(a, dict) and bd != ad:
                modified.append({**entry, "kind": "modified"})
        return {"added": added, "modified": modified, "removed": removed,
                "addedLines": None, "removedLines": None,
                "facts": {"truncatedEntries": (after.get("truncated") or {}).get("entries", 0)
                          + (before.get("truncated") or {}).get("entries", 0)},
                "note": "line counts require content copies; the Worker channel "
                        "reports file-level changes with digests"}

    def delete_state_file(self, relative: str) -> None:
        """Remove exactly one home file - the credential rule's clean-up."""
        self.client.request("home.delete", {
            "locator": self.home_locator,
            "path": f"{self.audit_window}/{relative}" if self.audit_window else relative,
        }, timeout=10)

    def _home_bytes(self, path: str) -> tuple[bytes, str]:
        chunks = bytearray()
        expected = None
        full = f"{self.audit_window}/{path}" if self.audit_window else path
        while True:
            item = self.client.request("home.get", {
                "locator": self.home_locator, "path": full,
                "offset": len(chunks), "maxLength": 32 * 1024,
            })
            if expected is None:
                expected = item.get("digest")
            if (item.get("digest") != expected or item.get("offset") != len(chunks)
                    or not isinstance(item.get("data"), str)):
                raise SidecarError("SIDECAR_STATE_IDENTITY_CONFLICT", "home fetch identity changed")
            try:
                chunks.extend(base64.b64decode(item["data"], validate=True))
            except ValueError as exc:
                raise SidecarError("SIDECAR_STATE_INVALID", "home chunk is invalid") from exc
            if item.get("nextOffset") != len(chunks):
                raise SidecarError("SIDECAR_STATE_IDENTITY_CONFLICT", "home fetch offset changed")
            if item.get("eof") is True:
                break
            if item.get("nextOffset") == item.get("offset"):
                raise SidecarError("SIDECAR_STATE_INVALID", "home fetch made no progress")
        content = bytes(chunks)
        if expected != _sha256(content):
            raise SidecarError("SIDECAR_STATE_DIGEST_MISMATCH", "home digest did not match")
        return content, str(expected)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self.client.close_stdin(self.attempt_id, self.generation, timeout=3)
            except BaseException:
                self.client.request(
                    "cancel", attempt_id=self.attempt_id, generation=self.generation, timeout=3,
                )
            try:
                self.client.wait_terminal(self.attempt_id, self.generation, timeout=10)
            finally:
                operations = [("result.ack", {}, True)]
                if self.secret_frame_id is not None:
                    operations.append(("secret.cleanup", {
                        "attemptId": self.attempt_id, "frameId": self.secret_frame_id,
                    }, False))
                operations.extend((
                    ("view.cleanup", {"viewId": self.view_id}, False),
                    ("attempt.cleanup", {}, True),
                ))
                for op, arguments, identified in operations:
                    try:
                        self.client.request(
                            op, arguments,
                            **({"attempt_id": self.attempt_id, "generation": self.generation}
                               if identified else {}), timeout=3,
                        )
                    except BaseException:
                        pass
        finally:
            self._stop_lease()
            self._forbidden_content = b""
            if self._unsubscribe:
                self._unsubscribe()
            if self._disconnect_unsubscribe:
                self._disconnect_unsubscribe()
            self.client.close()
            self._chunks.put(None)


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _safe_relative_state_path(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or "\x00" in value or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or str(PurePosixPath(value)) != value):
        raise ValueError("SIDECAR_STATE_PATH_INVALID")
    return value


class SidecarEnvelope:
    """One sidecar session: request/response plus typed upward events."""

    def __init__(self, channels: SidecarChannels, *, on_event: Callable[[dict[str, Any]], None]) -> None:
        self._channels = channels
        self._on_event = on_event
        self._responses: dict[str, dict[str, Any]] = {}
        self._fatal: dict[str, Any] | None = None
        self._condition = threading.Condition()
        self._stderr: list[str] = []
        # Set when the channel reader itself failed (for example a keepalive
        # that could not keep the lease). The pending request must see that
        # reason and its code, not a generic "sidecar exited".
        self._reader_error: BaseException | None = None
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # -- request helper ----------------------------------------------------

    def request(self, payload: Mapping[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        request_id = f"sc-{uuid4().hex}"
        body = {**payload, "id": request_id}
        with self._condition:
            self._channels.write_line(json.dumps(body, ensure_ascii=False, separators=(",", ":")))
            deadline = time.monotonic() + timeout
            while request_id not in self._responses:
                if self._fatal is not None:
                    fatal, self._fatal = self._fatal, None
                    error = fatal.get("error") or {}
                    raise SidecarError(
                        str(error.get("code", "SIDECAR_ERROR")),
                        str(error.get("message", "")),
                    )
                if self._closed.is_set():
                    raise self._closed_error()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SidecarError("SIDECAR_TIMEOUT", f"no answer for {payload.get('op')}")
                self._condition.wait(min(remaining, 1.0))
            answer = self._responses.pop(request_id)
        if not answer.get("ok"):
            error = answer.get("error") or {}
            raise SidecarError(str(error.get("code", "SIDECAR_ERROR")), str(error.get("message", "")))
        return answer.get("result") or {}

    def _closed_error(self) -> "SidecarError":
        """The reason the channel ended: the reader's own typed failure first.

        A keepalive failure is a real cause and must reach the caller with its
        code; "sidecar exited before answering" stays the fallback for every
        ordinary close.
        """
        reader_error = self._reader_error
        if isinstance(reader_error, SidecarError):
            return reader_error
        if reader_error is not None and getattr(reader_error, "code", None):
            return SidecarError(str(reader_error.code), str(getattr(reader_error, "message", reader_error)))
        return SidecarError("SIDECAR_CLOSED", "sidecar exited before answering")

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        try:
            self._channels.close()
        finally:
            self._closed.set()
            with self._condition:
                self._condition.notify_all()

    def audit_state(self) -> dict[str, Any]:
        """Audit the declared home window, whichever channel supplies the walk."""
        audit = getattr(self._channels, "audit_state", None)
        return audit() if callable(audit) else {
            "files": [], "skipped": 0,
            "truncated": {"entries": 0, "bytes": 0, "oversize": 0},
            "audited": {"files": 0, "bytes": 0,
                        "truncated": {"entries": 0, "bytes": 0, "oversize": 0}},
        }

    def read_usage(self, usage_probe: Mapping[str, str] | None) -> dict[str, int] | None:
        """Read and parse the declared journal into the neutral usage fact.

        The journal is one of the files the audit already listed (same
        locator, same bounds, same refusal rules); the parse is the only
        place a family's field names appear.
        """
        read = getattr(self._channels, "read_usage", None)
        if not callable(read):
            return None
        return read(usage_probe)

    def delete_state_file(self, relative: str) -> None:
        delete = getattr(self._channels, "delete_state_file", None)
        if callable(delete):
            delete(relative)

    def read_subscription(self) -> dict[str, bytes]:
        """Read the declared subscription working files back (order 56)."""
        read = getattr(self._channels, "read_subscription", None)
        return read() if callable(read) else {}

    # -- reader ------------------------------------------------------------

    def _read_loop(self) -> None:
        buffer = ""
        stream = getattr(self._channels, "stdout", None)
        try:
            for chunk in self._iter_chunks():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._line(line)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the caller
            self._reader_error = exc
            self._stderr.append(str(exc))
        finally:
            del stream
            self._closed.set()
            with self._condition:
                self._condition.notify_all()

    def _iter_chunks(self):
        iterator = getattr(self._channels, "iter_chunks", None)
        if callable(iterator):
            return iterator()
        process = getattr(self._channels, "process", None)
        if process is None or process.stdout is None:
            return iter(())
        return iter(lambda: process.stdout.readline().decode("utf-8", "replace"), "")

    def _line(self, line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            return
        if "event" in message:
            try:
                self._on_event(dict(message))
            except Exception:  # noqa: BLE001 - an event consumer must not kill the reader
                pass
            return
        with self._condition:
            if message.get("id") is None and not message.get("ok", True):
                # A startup refusal (for example missing isolation) answers no
                # request; surface it to whoever is waiting.
                self._fatal = message
            else:
                self._responses[str(message.get("id"))] = message
            self._condition.notify_all()


class SidecarHarnessPort:
    """TurnExecutionPort implemented over one sidecar per execution.

    The native session id is kept per execution on the instance; nothing here
    is class-level state, so two ports in one process cannot share or overwrite
    each other's identity.

    The port also owns the *effective* capability view of each execution: the
    deployment's static declaration intersected with what the native side really
    demonstrated during that execution. Downstream behaviour (checkpoint
    resumability, attachment dispatch) reads that view, so a declared ability
    never becomes a product promise on its own, and an observed ability never
    exceeds what was declared.
    """

    def __init__(
        self, launcher: SidecarLauncher, *, environment: Mapping[str, str],
        profile: str = "", adapter: Mapping[str, Any] | None = None,
        model: str | None = None, credential_environment: str | None = None,
        preferred_auth_method: str | None = None,
        resume_native_id: str | None = None,
        state_directory: str = "/tmp/agentbox-sidecar",
        directory: str = "/workspace", on_event=None,
        declared_capabilities: Mapping[str, bool] | None = None,
        native_platform: str | None = None,
        home_locator: str | None = None,
        capability_documents: "tuple[Any, ...] | None" = None,
        capability_grants: "tuple[Any, ...] | None" = None,
        capability_authorized_providers: "tuple[str, ...] | None" = None,
        capability_binding: str | None = None,
        usage_probe: dict[str, str] | None = None,
        subscription: Mapping[str, Any] | None = None,
        account_plumbing: Any = None,
    ) -> None:
        self.launcher = launcher
        #: Order 56: this turn's subscription binding (account id, the digest
        #: it materialised, and the declared working-copy names) plus the
        #: records/assets pair the reclaim path needs. All None/empty when the
        #: profile is not bound to an account.
        self.subscription = dict(subscription) if subscription else None
        self.account_plumbing = account_plumbing
        self.environment = dict(environment)
        # 调用方必须给出部署声明的 harness 类型；空值会在 register 时被 sidecar
        # 以 HARNESS_PROFILE_UNREGISTERED 拒绝，这里不替任何一家猜一个默认名字。
        self.profile = profile
        self.adapter = dict(adapter or {})
        self.model = model
        self.credential_environment = credential_environment
        self.preferred_auth_method = preferred_auth_method
        self.resume_native_id = resume_native_id
        self.state_directory = state_directory
        self.directory = directory
        #: Which machine family owns this Profile's home, and where it sits on
        #: that machine (relative to the machine's home root). Both go into the
        #: audit manifest as the *reference*; the absolute host path the
        #: channel resolved never leaves this process.
        self.native_platform = native_platform
        self.home_locator = home_locator
        self.on_event = on_event or (lambda *_: None)
        # 静态上限：只能来自部署/插件声明（经 canonical 校验）；缺省按“全部 false”
        # 处理——不猜、不默认 true。
        if declared_capabilities is None:
            self.declared_capabilities: dict[str, bool] = {}
        else:
            self.declared_capabilities = validate_claims(declared_capabilities)
        self._sessions: dict[str, SidecarEnvelope] = {}
        self._native_sessions: dict[str, str] = {}
        self._approvals: dict[str, tuple[str, str]] = {}
        self._native_closed: set[str] = set()
        # 中立能力材料：由装配边界（bootstrap port_factory）逐执行注入——声明文档、
        # 锁定政策 grant、授权提供者集与本次执行的环境绑定。业务层只消费，不解释
        # deployment、不按品牌分支；缺失即 fail-closed（门在 _start_run 内联）。
        self.capability_documents: tuple[Any, ...] = tuple(capability_documents or ())
        self.capability_grants: tuple[Any, ...] = tuple(capability_grants or ())
        self.capability_authorized_providers: tuple[str, ...] = tuple(
            capability_authorized_providers or ()
        )
        self.capability_binding: str | None = capability_binding
        #: Order 51: the declared usage probe; the completion boundary reads
        #: the journal through the audited channel and records the tokens.
        self.usage_probe = dict(usage_probe) if usage_probe else None
        # 本次执行的原生观测与观测来源；observed 只反映这一次执行，绝不回写静态声明。
        self._observed: dict[str, dict[str, bool | None]] = {}
        self._evidence: dict[str, dict[str, str]] = {}
        self._current: str = ""
        # 已经发出过 prompt 的执行。原生在重开一个已存在的会话时可能先把存下来的
        # 历史回放一遍（Pi 的 session/load 就是这样），那些块是历史，不是这一轮的
        # 答复；prompt 之前到达的增量一律不计入本轮。规则与 harness 品牌无关。
        self._prompted: set[str] = set()
        # 被排除掉的历史回放字符数：不进本轮答复，但要记得住，便于事后核对。
        self._replayed: dict[str, int] = {}
        self._lock = threading.RLock()

    def open_execution(self, execution_id: str) -> str:
        """Open a sidecar, register the profile, and open one native session.

        Returns the opaque native session id. Credentials are never passed here:
        the Worker materializes them inside the isolated projection.
        """
        with self._lock:
            if execution_id in self._sessions:
                return self._native_sessions[execution_id]
            # 早于 start/create 设置：原生在打开会话时播发的事件也属于这次执行。
            self._current = execution_id
        envelope = SidecarEnvelope(self.launcher.launch(self.environment), on_event=self._forward)
        try:
            registered = envelope.request({
                "op": "register", "profile": self.profile, "launch": self.adapter,
                "credentialEnvironment": self.credential_environment,
                "preferredAuthMethod": self.preferred_auth_method,
                "stateDirectory": self.state_directory, "directory": self.directory,
                "permissionRoundTrip": True, "permissionTimeoutMs": 60_000,
            })
            started = envelope.request({"op": "start"})
            if self.resume_native_id is None:
                session = envelope.request({
                    "op": "create", "title": execution_id, "model": self.model,
                })
                session_operation = "create"
            else:
                session = envelope.request({"op": "open", "sessionId": self.resume_native_id})
                session_operation = "open"
        except BaseException:
            envelope.close()
            raise
        native = str(session.get("sessionId") or "")
        if not native:
            envelope.close()
            raise SidecarError("NATIVE_SESSION_MISSING", "sidecar did not report a native session id")
        with self._lock:
            self._sessions[execution_id] = envelope
            self._native_sessions[execution_id] = native
            self._current = execution_id
            # 运行时观测只记录原生真正给出的事实，且只属于本次执行：
            # - start 操作合同已注册且被真实调用，这就是 start 的观测来源；
            # - create/open 返回了原生会话身份，这就是 observe 的观测来源；
            # - 会话/提示能力按原生播发读取（空对象算播发，null/缺失是“未观测”）。
            self._record_observation(execution_id, "start", True, "sidecar.operation.start")
            self._record_observation(
                execution_id, "observe", True, f"sidecar.operation.{session_operation}",
            )
            self._record_observation(
                execution_id, "native_continuation",
                _advertised((started.get("sessionCapabilities") or {}).get("resume")),
                "sessionCapabilities.resume",
            )
            self._record_observation(
                execution_id, "attach",
                _advertised_image((started.get("promptCapabilities") or {}).get("image")),
                "promptCapabilities.image",
            )
        self.on_event(execution_id, "started", {
            "nativeSessionId": native, "provenance": registered.get("provenance"),
        })
        return native

    def workspace_change_set(self, execution_id: str) -> dict[str, Any] | None:
        """Order 54: the declared workspace's per-turn change set.

        Delegates to the execution's own channel; a channel without the
        capability answers None (honest unknown).
        """
        envelope = self._require(execution_id)
        read = getattr(envelope, "workspace_change_set", None)
        return read() if callable(read) else None

    def read_usage(
        self, execution_id: str, usage_probe: Mapping[str, str] | None,
    ) -> dict[str, int] | None:
        """Read and parse the declared journal into the neutral usage fact.

        The completion boundary calls this once the audit is done; the read
        rides the execution's own audited channel and the parse is the only
        place a family's field names appear.
        """
        envelope = self._require(execution_id)
        return envelope.read_usage(usage_probe)

    def capture_execution(self, execution_id: str) -> tuple[dict[str, Any], bool]:
        """Flush the adapter, then audit the declared home window.

        The audit is a record, not a copy: what comes back are facts about the
        home directory the Harness owns on this machine (per-file digests,
        counts, truncation), never bytes to store.
        """
        envelope = self._require(execution_id)
        with self._lock:
            already_closed = execution_id in self._native_closed
        if not already_closed:
            envelope.request({"op": "close"}, timeout=10)
            with self._lock:
                self._native_closed.add(execution_id)
        audit = envelope.audit_state()
        # resumable 的算法不变：静态声明了 native_continuation 且本次执行真的
        # 被原生播发过，才允许声明 resumable。
        resumable = self._effective_supported(execution_id, "native_continuation")
        return {
            "nativePlatform": self.native_platform,
            "homeLocator": self.home_locator,
            **audit,
        }, resumable


    @property
    def shared_store(self) -> bool:
        """Whether this execution's audited tree is the shared family library.

        Order 66 §2.5: a credential hit in the shared library is a typed
        failure that must NOT delete the file - deleting there would destroy
        other Profiles' sessions. The launcher is the only object that knows
        which tree the audit covers.
        """
        return bool(getattr(self.launcher, "session_store_harness", None))

    @property
    def whole_db_store(self) -> bool:
        """Whether this execution opens one shared *whole* library (order 80).

        `shared_store` is true for sessions-subtree as well, where every
        session has its own files and no harness initialises a shared database;
        only a whole-db store carries `shared` entries, and only there does the
        first run need the exclusive lock.
        """
        return self.shared_store and bool(
            getattr(self.launcher, "session_store_shared", ()))

    def delete_home_file(self, execution_id: str, relative: str) -> None:
        """Remove one leaked file from the home (the credential rule)."""
        envelope = self._require(execution_id)
        envelope.delete_state_file(relative)

    def pid(self, execution_id: str) -> int | None:
        """The execution-side pid, or None when this side has not reported one.

        Only the local channel's process object is readable here; a
        Worker-hosted run has no pid on this machine, and the order's rule is
        that the field stays null rather than being guessed.
        """
        envelope = self._require(execution_id)
        process = getattr(envelope, "process", None)
        pid = getattr(process, "pid", None)
        return pid if isinstance(pid, int) and not isinstance(pid, bool) else None

    def read_subscription(self, execution_id: str) -> dict[str, bytes]:
        """Read the declared subscription working files back (order 56)."""
        envelope = self._require(execution_id)
        read = getattr(envelope, "read_subscription", None)
        return read() if callable(read) else {}

    def accept(self, execution_id: str) -> None:
        """Open the execution; the prompt is issued by `prompt`."""
        self.open_execution(execution_id)

    def prompt(
        self, execution_id: str, text: str,
        attachments: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        envelope = self._require(execution_id)
        items = [dict(item) for item in attachments]
        if items and not self._effective_supported(execution_id, "attach"):
            # 有效 attach=false 时在派发前类型化拒绝：附件要么被原生真正支持，
            # 要么带着明确错误失败，绝不静默丢弃。
            raise SidecarError(
                "ATTACHMENT_UNSUPPORTED",
                "this execution has no effective 'attach' capability",
            )
        with self._lock:
            self._current = execution_id
            # 标记在请求发出之前：prompt 一发出，随后到达的块就是这一轮的输出。
            self._prompted.add(execution_id)
        result = envelope.request(
            {"op": "prompt", "sessionId": self._native_sessions[execution_id], "text": text,
             "model": self.model, "attachments": items},
            timeout=600,
        )
        # prompt 返回即完成合同被真实调用，这是 finish 的观测来源。
        self._record_observation(execution_id, "finish", True, "sidecar.operation.prompt")
        return result

    def cancel(self, execution_id: str) -> bool:
        with self._lock:
            envelope = self._sessions.get(execution_id)
            native = self._native_sessions.get(execution_id)
        if envelope is None or native is None:
            return False
        try:
            envelope.request({"op": "abort", "sessionId": native}, timeout=10)
            return True
        except SidecarError:
            return False

    def close_execution(self, execution_id: str) -> None:
        with self._lock:
            envelope = self._sessions.pop(execution_id, None)
            self._native_sessions.pop(execution_id, None)
            self._observed.pop(execution_id, None)
            self._evidence.pop(execution_id, None)
            self._prompted.discard(execution_id)
            self._replayed.pop(execution_id, None)
            native_closed = execution_id in self._native_closed
            self._native_closed.discard(execution_id)
            self._approvals = {
                key: value for key, value in self._approvals.items() if value[0] != execution_id
            }
        if envelope is not None:
            try:
                if not native_closed:
                    envelope.request({"op": "close"}, timeout=5)
            except BaseException:
                pass
            envelope.close()

    def stop(self) -> bool:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._native_sessions.clear()
            self._observed.clear()
            self._evidence.clear()
            self._prompted.clear()
            self._replayed.clear()
            self._native_closed.clear()
            self._approvals.clear()
        for envelope in sessions:
            try:
                envelope.close()
            except BaseException:
                pass
        return True

    def register_approval(
        self, approval_id: str, execution_id: str, sidecar_request_id: str,
    ) -> None:
        with self._lock:
            if execution_id not in self._sessions:
                raise SidecarError("EXECUTION_UNKNOWN", "approval execution is no longer active")
            self._approvals[approval_id] = (execution_id, sidecar_request_id)

    def decide_approval(
        self, approval_id: str, decision: str, scope: Mapping[str, Any],
    ) -> None:
        with self._lock:
            route = self._approvals.pop(approval_id, None)
        if route is None:
            raise SidecarError("PERMISSION_REQUEST_UNKNOWN", "approval route is no longer active")
        execution_id, request_id = route
        self._require(execution_id).request({
            "op": "permission_decision", "requestId": request_id,
            "decision": decision, "scope": dict(scope),
        }, timeout=10)

    def effective_capabilities(self, execution_id: str) -> dict:
        """该 execution 的 canonical 能力视图（静态声明 ∩ 本次运行时观测）。

        形状与 ``harness_capabilities.capability_view`` 一致：``declared`` 永远是静态
        上限，``observed`` 三态且随执行过程更新（例如首条 delta 到达后
        ``stream.observed=true``），``supported`` 是两者合并后的结论。未知 execution
        抛出与 `_native`/`_require` 一致的 ``EXECUTION_UNKNOWN``。
        """
        with self._lock:
            if execution_id not in self._sessions:
                raise SidecarError("EXECUTION_UNKNOWN", "no sidecar for this execution")
        return capability_view(self.profile, self._effective(execution_id))

    def _effective(self, execution_id: str) -> tuple[CapabilityDeclaration, ...]:
        with self._lock:
            observed = dict(self._observed.get(execution_id) or {})
            evidence = dict(self._evidence.get(execution_id) or {})
        return merge_capabilities(self.declared_capabilities, observed, evidence=evidence)

    def _effective_supported(self, execution_id: str, capability_id: str) -> bool:
        for declaration in self._effective(execution_id):
            if declaration.id == capability_id:
                return declaration.supported
        return False

    def _record_observation(
        self, execution_id: str, capability_id: str, value: bool | None,
        evidence: str | None = None,
    ) -> None:
        """记录一条本次执行的原生事实。

        ``None`` 表示"没有观测到"，既不写观测也不覆盖已有观测——观测是单调事实，
        而且它只影响本次执行的合并结果，不会回写任何静态声明。
        """
        if value is None:
            return
        with self._lock:
            self._observed.setdefault(execution_id, {})[capability_id] = value
            if evidence is not None:
                self._evidence.setdefault(execution_id, {})[capability_id] = evidence

    def replayed_history_chars(self, execution_id: str) -> int:
        """原生在 prompt 之前回放的历史字符数：排除在本轮答复之外，只作记账。"""
        with self._lock:
            return self._replayed.get(execution_id, 0)

    def _native(self, execution_id: str) -> str:
        native = self._native_sessions.get(execution_id)
        if native is None:
            raise SidecarError("EXECUTION_UNKNOWN", "no native session for this execution")
        return native

    def _require(self, execution_id: str) -> SidecarEnvelope:
        with self._lock:
            envelope = self._sessions.get(execution_id)
        if envelope is None:
            raise SidecarError("EXECUTION_UNKNOWN", "no sidecar for this execution")
        return envelope

    def _forward(self, message: Mapping[str, Any]) -> None:
        """Project upward sidecar events onto product-neutral callback facts."""
        event = message.get("event")
        data = message.get("data") or {}
        with self._lock:
            execution_id = self._current
        if event == "acp_notification":
            update = ((data.get("params") or {}).get("update") or {})
            if update.get("sessionUpdate") == "agent_message_chunk":
                text = ((update.get("content") or {}).get("text") or "")
                # 只有 prompt 已经发出之后到达的块才是这一轮的答复；重开会话时
                # 回放的历史在这里被排除，否则它会成为答复的前缀（真实复现：
                # 每一轮都把上一轮的全文重复一遍）。
                live = bool(text) and execution_id in self._prompted
                if text and not live:
                    with self._lock:
                        self._replayed[execution_id] = self._replayed.get(execution_id, 0) + len(text)
                if live:
                    # 收到一条流式增量，就是 stream 被真实观测到的证据；两条传输
                    # （ACP 与 deployment-declared driver）在这里汇成同一个产品事实。
                    self._record_observation(
                        execution_id, "stream", True, "sidecar.event.message.delta",
                    )
                    self.on_event(execution_id, "message.delta", {"text": text})
            elif update.get("sessionUpdate") == "agent_thought_chunk":
                # Order 52: the harness's own reasoning, as a neutral fact. The
                # live/replay exclusion matches the message chunk above.
                text = ((update.get("content") or {}).get("text") or "")
                if text and execution_id in self._prompted:
                    self.on_event(execution_id, "thought.delta", {"text": text})
            elif update.get("sessionUpdate") in {"tool_call", "tool_call_update"}:
                status = str(update.get("status") or "in_progress")
                tool_name = update.get("_meta", {}).get("toolName") if isinstance(update.get("_meta"), dict) else None
                output = update.get("rawOutput")
                if output is None and isinstance(update.get("content"), list):
                    output = "\n".join(
                        item["content"]["text"] for item in update["content"]
                        if isinstance(item, dict) and item.get("type") == "content"
                        and isinstance(item.get("content"), dict)
                        and isinstance(item["content"].get("text"), str)
                    )
                if output is not None and not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, default=str)
                self.on_event(execution_id, "tool.update", {
                    "tool_call_id": str(update.get("toolCallId") or "tool"),
                    "tool": tool_name if tool_name is not None else update.get("title"),
                    "state": {"in_progress": "running", "failed": "failed"}.get(status, status),
                    **({"summary": str(update["title"])} if update.get("title") else {}),
                    **({"result_excerpt": output[:4096]} if output else {}),
                })
            elif update.get("sessionUpdate") == "plan":
                entries = update.get("entries")
                self.on_event(execution_id, "plan.updated", {
                    "entries": entries if isinstance(entries, list) else [],
                })
            elif update.get("sessionUpdate") == "current_mode_update":
                self.on_event(execution_id, "mode.updated", {
                    "currentModeId": str(update.get("currentModeId") or ""),
                })
        elif event == "message_delta":
            # A deployment-declared native driver reports the same product fact
            # as an ACP message chunk. The event name is the driver contract's,
            # never a Harness's, so this mapping stays brand-free.
            text = str(data.get("text") or "")
            if text:
                self._record_observation(
                    execution_id, "stream", True, "sidecar.event.message.delta",
                )
                self.on_event(execution_id, "message.delta", {"text": text})
        elif event == "driver_exit":
            self.on_event(execution_id, "failed", {"code": "ADAPTER_EXIT"})
        elif event == "adapter_exit":
            self.on_event(execution_id, "failed", {"code": "ADAPTER_EXIT"})
        elif event == "permission_request":
            # 只有真实发生了 permission round-trip、并且插件静态声明了
            # permissions 时，才把它算作观测；否则保持“未观测”，绝不因为一次
            # 原生请求或某种 deny 默认就宣称支持审批。请求本身仍然如实上报。
            if self.declared_capabilities.get("permissions"):
                self._record_observation(
                    execution_id, "permissions", True,
                    "sidecar.operation.permission_request",
                )
            self.on_event(execution_id, "approval.requested", {"request": data})


class NativeHarnessPort(SidecarHarnessPort):
    """Native Agent port: retain its opaque session id, never inspect its home."""

    native_mode = True

    def open_execution(self, execution_id: str) -> str:
        # A Server session may contain many turns.  Rebind each new turn to the
        # same live ACP channel instead of issuing session/new every time.
        with self._lock:
            live = getattr(self, "_live_envelope", None)
            native = getattr(self, "_live_native_id", None)
            if live is not None:
                if live.closed:
                    raise SidecarError("NATIVE_SESSION_LOST", "native ACP channel exited")
                self._sessions[execution_id] = live
                self._native_sessions[execution_id] = native
                self._current = execution_id
                self._record_observation(execution_id, "start", True, "sidecar.channel.live")
                self._record_observation(execution_id, "observe", True, "sidecar.session.live")
                for capability_id, (value, evidence) in getattr(
                    self, "_live_session_capabilities", {},
                ).items():
                    self._record_observation(execution_id, capability_id, value, evidence)
                return native
        native = super().open_execution(execution_id)
        with self._lock:
            self._live_envelope = self._sessions[execution_id]
            self._live_native_id = native
            self._live_session_capabilities = {
                key: (self._observed[execution_id][key], self._evidence[execution_id].get(key))
                for key in ("native_continuation", "attach")
                if key in self._observed.get(execution_id, {})
            }
        return native

    def capture_execution(self, execution_id: str) -> tuple[dict[str, Any], bool]:
        self._require(execution_id)
        # session/close would destroy the live conversation.  Native homes are
        # agent-owned; this checkpoint records identity, not a copied home.
        return {
            "nativePlatform": "local",
            "homeLocator": "agent-native",
            "audited": False,
            "truncated": False,
            "files": [],
        }, self._effective_supported(execution_id, "native_continuation")

    def close_execution(self, execution_id: str) -> None:
        # End the Server turn, not its ACP session.  The channel is closed only
        # when the Server backend shuts down or the native process exits.
        with self._lock:
            self._sessions.pop(execution_id, None)
            self._native_sessions.pop(execution_id, None)
            self._observed.pop(execution_id, None)
            self._evidence.pop(execution_id, None)
            self._prompted.discard(execution_id)
            self._replayed.pop(execution_id, None)
            self._native_closed.discard(execution_id)
            self._approvals = {
                key: value for key, value in self._approvals.items() if value[0] != execution_id
            }

    def stop(self) -> bool:
        with self._lock:
            live = getattr(self, "_live_envelope", None)
            self._live_envelope = None
            self._live_native_id = None
        stopped = super().stop()
        if live is not None and not live.closed:
            live.close()
        return stopped

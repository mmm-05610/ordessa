"""SSH connector: the same Worker control plane, reached over ssh.

The WSL connector's shape is deliberate and is kept here: probe a target,
answer the remote user's identity, browse and canonicalize one path, then hand
the channel a client that speaks the Worker control protocol. What changes is
only the transport the client is given - `ssh` instead of `wsl.exe` - and the
fact that the remote host is reached by name rather than through the Windows
subsystem.

Two boundaries are worth stating because they are the ones a reader will check:

* the private key is used as a **locator**, never as material. This module reads
  the locator's path from its caller and writes it into a 0600 ssh config inside
  a private directory it owns; the key file itself is opened by `ssh`, is never
  copied, and its bytes never reach an argument vector, a log line or a report;
* the connector knows nothing about rooms, sandboxes or Harnesses. It answers
  where a process runs, not what it runs.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence
from uuid import uuid4

try:
    # The SSH/WSL remote execution legs need the agent-box-runtime-wsl
    # distribution, which is not part of the monorepo baseline (see
    # MIGRATION-TABLE.md). Connector construction (manifest, path and identity
    # validation) stays available; building a Worker client or raising a typed
    # remote refusal fails honestly and names the missing package.
    from agent_box_runtime_wsl import WorkerClient, WorkerError
except ModuleNotFoundError as _wsl_missing:
    if _wsl_missing.name != "agent_box_runtime_wsl":
        raise
    WorkerClient = None

    class WorkerError(RuntimeError):
        """Same shape as agent_box_runtime_wsl.WorkerError, for when the
        SSH/WSL remote distribution is not installed. Typed refusals keep
        working; building an actual Worker client (WorkerClient is None) is
        what refuses honestly when the legs are absent."""

        def __init__(self, code: str, message: str) -> None:
            super().__init__(message)
            self.code = code
            self.message = message

PROBE_TTL_SECONDS = 60
SUBPROCESS_TIMEOUT_SECONDS = 30

#: A target may be a hostname, an IPv4/IPv6 literal or an ssh config alias. It
#: may not contain whitespace, quotes or a leading dash: the first two would let
#: a caller reshape the remote command, and the last would be read by ssh as an
#: option rather than as the destination.
_SAFE_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,254}\Z")
_SAFE_USER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class SshConnector:
    """One SSH environment, resolved per call from the manifest and locator."""

    def __init__(
        self, *, manifest_path: Path | str, remote_worker_path: str,
        identity_file: Path | str, server_instance_id: str, port: int = 22,
        connect_timeout: int = 15,
    ) -> None:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != 1 or manifest.get("wireVersion") != 1:
            raise RuntimeError("WORKER_MANIFEST_INCOMPATIBLE")
        digest = str(manifest.get("sha256", ""))
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise RuntimeError("WORKER_MANIFEST_INVALID")
        if not remote_worker_path.startswith("/") or re.fullmatch(
            r"/[A-Za-z0-9._/-]{0,255}", remote_worker_path,
        ) is None:
            raise RuntimeError("SSH_WORKER_PATH_INVALID")
        identity = Path(identity_file)
        if not identity.is_file():
            raise RuntimeError("SSH_IDENTITY_MISSING")
        if not 1 <= int(port) <= 65535:
            raise RuntimeError("SSH_PORT_INVALID")
        self.manifest = manifest
        self.remote_worker_path = remote_worker_path
        self.identity_file = identity
        self.server_instance_id = server_instance_id
        self.port = int(port)
        self.connect_timeout = int(connect_timeout)
        self._probes: dict[str, Probe] = {}
        #: Everything this connector writes lives here: the per-target ssh
        #: configuration that names the locator, and the known-hosts file the
        #: first connection is trusted into. The directory is 0700 and private
        #: to this process; it never holds key material.
        self._runtime_dir = Path(tempfile.mkdtemp(prefix="agentbox-ssh-connector-"))
        self._runtime_dir.chmod(0o700)
        self._configs: dict[str, Path] = {}
        self._closed = False
        atexit.register(self.close)

    # -- probes ------------------------------------------------------------

    def probe(self, target: str, user: str | None):
        """Reach the target, name its user, and verify the Worker it will run.

        The digest is read from the remote host and compared with the manifest
        before any handshake: a Worker whose bytes differ from the pinned build
        is refused here rather than discovered halfway through a turn.
        """
        location = _location(target, user)
        observed_user, remote_digest = self._identify(location)
        if remote_digest != self.manifest["sha256"]:
            raise WorkerError(
                "SSH_WORKER_DIGEST_MISMATCH",
                "the remote Worker does not match the pinned build",
            )
        probe_id = f"probe-{uuid4().hex}"
        probe = Probe(probe_id, location.target, observed_user, time.monotonic() + PROBE_TTL_SECONDS)
        client = self._client(probe, project_id=probe_id)
        try:
            handshake = client.start()
            client.request("handshake")
        finally:
            client.close()
        self._probes[probe_id] = probe
        return {
            "probe_id": probe_id, "host": probe.target, "user": probe.user,
            "expires_in": PROBE_TTL_SECONDS, "worker_version": handshake["workerVersion"],
            "worker_digest": handshake["workerDigest"],
        }

    def browse(self, probe_id: str, path: str):
        probe = self._probe(probe_id)
        client = self._client(probe, project_id=probe_id)
        try:
            client.start()
            result = client.request("browse", {"path": path})
        finally:
            client.close()
        return {"probe_id": probe_id, **result}

    def open_workspace(self, probe_id: str, path: str):
        probe = self._probe(probe_id)
        client = self._client(probe, project_id=probe_id)
        try:
            client.start()
            result = client.request("canonicalize", {"path": path})
        finally:
            client.close()
        return {
            "connection_id": f"connection-{uuid4().hex}",
            "host": probe.target, "user": probe.user, "path": result["path"],
        }

    # -- the channel's client ---------------------------------------------

    def client_for_workspace(
        self, *, distribution: str, user: str, connection_id: str,
        workspace_path: str,
        executable_authorizations: Sequence[Mapping[str, str]] = (),
        runtime_artifact_authorizations: Sequence[Mapping[str, str]] = (),
    ) -> WorkerClient:
        """One Worker client for a stored Workspace.

        `distribution` is the workspace record's environment identity - the same
        field a WSL record uses for its distribution. An SSH environment's
        identity is its host, so that is what the record holds and what arrives
        here; nothing else about this call is SSH-shaped.
        """
        probe = Probe("execution", distribution, user, float("inf"))
        return self._client(
            probe, project_id=connection_id, workspace=workspace_path,
            connection_id=connection_id,
            executable_authorizations=executable_authorizations,
            runtime_artifact_authorizations=runtime_artifact_authorizations,
        )

    def read_workspace_file(
        self, *, distribution: str, user: str, connection_id: str,
        workspace_path: str, relative_path: str,
    ) -> tuple[bytes, str]:
        """Read one bounded, Worker-authorized file for an attachment."""
        client = self.client_for_workspace(
            distribution=distribution, user=user, connection_id=connection_id,
            workspace_path=workspace_path,
        )
        chunks = bytearray()
        expected = None
        client.start()
        try:
            while True:
                item = client.request("workspace.get", {
                    "path": relative_path, "offset": len(chunks), "maxLength": 32 * 1024,
                })
                expected = expected or item["digest"]
                if item["digest"] != expected or int(item["offset"]) != len(chunks):
                    raise WorkerError(
                        "ATTACHMENT_IDENTITY_CONFLICT", "workspace file changed during delivery",
                    )
                chunks.extend(base64.b64decode(item["data"], validate=True))
                if item["eof"]:
                    break
        finally:
            client.close()
        content = bytes(chunks)
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise WorkerError("ATTACHMENT_DIGEST_MISMATCH", "workspace attachment digest changed")
        return content, actual

    # -- internals ---------------------------------------------------------

    def _probe(self, probe_id: str) -> "Probe":
        probe = self._probes.get(probe_id)
        if probe is None or time.monotonic() >= probe.expires_at:
            self._probes.pop(probe_id, None)
            raise WorkerError("PROBE_EXPIRED", "SSH probe is unknown or expired")
        return probe

    def _identify(self, location: "_Location") -> tuple[str, str]:
        """Read the remote user and the Worker's digest in one round trip."""
        script = (
            "id -un && sha256sum -- " + _shell_quote(self.remote_worker_path)
        )
        result = self._run(location, script)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            raise WorkerError("SSH_IDENTITY_INVALID", "the remote host reported no identity")
        observed_user, digest_line = lines[0], lines[1]
        if _SAFE_USER.fullmatch(observed_user) is None:
            raise WorkerError("SSH_IDENTITY_INVALID", "the remote effective user was invalid")
        digest = digest_line.split(" ", 1)[0]
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise WorkerError("SSH_WORKER_UNAVAILABLE", "the remote Worker could not be hashed")
        return observed_user, "sha256:" + digest

    def _client(
        self, probe: "Probe", *, project_id: str, workspace: str | None = None,
        connection_id: str | None = None,
        executable_authorizations: Sequence[Mapping[str, str]] = (),
        runtime_artifact_authorizations: Sequence[Mapping[str, str]] = (),
    ) -> WorkerClient:
        command = [
            *self._ssh_prefix(_location(probe.target, probe.user)),
            self.remote_worker_path, "--root",
            f"/tmp/agentbox-worker-r1/{self.server_instance_id}/{project_id}",
        ]
        if workspace:
            command += ["--workspace", workspace]
        return WorkerClient(
            command, worker_digest=self.manifest["sha256"],
            worker_version=self.manifest["workerVersion"],
            connection_id=connection_id or probe.probe_id, project_id=project_id,
            effective_user=probe.user, server_instance_id=self.server_instance_id,
            executable_authorizations=tuple(executable_authorizations),
            runtime_artifact_authorizations=tuple(runtime_artifact_authorizations),
        )

    def _ssh_prefix(self, location: "_Location") -> list[str]:
        return ["ssh", "-F", str(self._config_for(location)), location.alias]

    def _config_for(self, location: "_Location") -> Path:
        """Write (once per target) the ssh configuration that names the locator.

        The configuration file is what keeps the locator out of every argument
        vector this connector builds: `ssh` reads the path from a 0600 file in
        the connector's own directory, so neither the key nor its location is
        ever spelled on a command line.
        """
        path = self._configs.get(location.alias)
        if path is not None:
            return path
        path = self._runtime_dir / f"{location.alias}.conf"
        known_hosts = self._runtime_dir / "known_hosts"
        path.write_text(
            f"Host {location.alias}\n"
            f"    HostName {location.target}\n"
            f"    User {location.user}\n"
            f"    Port {self.port}\n"
            f"    IdentityFile {self.identity_file}\n"
            "    IdentitiesOnly yes\n"
            "    BatchMode yes\n"
            "    StrictHostKeyChecking accept-new\n"
            f"    UserKnownHostsFile {known_hosts}\n"
            f"    ConnectTimeout {self.connect_timeout}\n"
            "    ServerAliveInterval 15\n"
            "    ServerAliveCountMax 4\n"
            "    LogLevel ERROR\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        self._configs[location.alias] = path
        return path

    def _run(self, location: "_Location", script: str):
        try:
            result = subprocess.run(
                [*self._ssh_prefix(location), script],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkerError("SSH_UNREACHABLE", "the SSH target could not be reached") from exc
        if result.returncode != 0:
            raise WorkerError("SSH_UNREACHABLE", "the SSH target returned a failure")
        return SimpleNamespace(
            returncode=result.returncode,
            stdout=result.stdout.decode("utf-8", "replace"),
            stderr=result.stderr.decode("utf-8", "replace"),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._configs.clear()
        shutil.rmtree(self._runtime_dir, ignore_errors=True)


class Probe:
    __slots__ = ("probe_id", "target", "user", "expires_at")

    def __init__(self, probe_id: str, target: str, user: str, expires_at: float) -> None:
        self.probe_id = probe_id
        self.target = target
        self.user = user
        self.expires_at = expires_at


class _Location:
    __slots__ = ("target", "user", "alias")

    def __init__(self, target: str, user: str) -> None:
        self.target = target
        self.user = user
        self.alias = "agentbox-" + hashlib.sha256(f"{target}\n{user}".encode()).hexdigest()[:16]


def _location(target: Any, user: Any) -> _Location:
    if not isinstance(target, str) or _SAFE_TARGET.fullmatch(target) is None:
        raise WorkerError("SSH_TARGET_INVALID", "the SSH target is not a usable host or address")
    if user is None:
        # An unnamed user is ssh's own default, which the target decides; the
        # configuration still needs a concrete one, so the probe resolves it
        # from the remote side and every later call reuses that answer.
        user = "root"
    elif not isinstance(user, str) or _SAFE_USER.fullmatch(user) is None:
        raise WorkerError("SSH_TARGET_INVALID", "the SSH user is not a usable login name")
    return _Location(target, user)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def ssh_identity_permissions(path: Path | str) -> str:
    """The locator's permission bits, as the one fact a report may carry."""
    return oct(stat.S_IMODE(os.stat(path).st_mode))


__all__ = ["SshConnector", "ssh_identity_permissions"]

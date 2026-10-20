"""Workspace use cases: probe environments, browse, and open workspaces."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from server_plugin_api import ServerError, unavailable
from server_plugin_api import digest
from ordessa_workspace.local_environment import LocalEnvironmentProvider
from ordessa_workspace.records import WorkspaceRecords


class WslConnectionPort(Protocol):
    def distributions(self) -> list[dict[str, Any]]: ...
    def probe(self, distribution: str, user: str | None) -> dict[str, Any]: ...
    def browse(self, probe_id: str, path: str) -> dict[str, Any]: ...
    def open_workspace(self, probe_id: str, path: str) -> dict[str, Any]: ...


class SshConnectionPort(Protocol):
    def probe(self, target: str, user: str | None) -> dict[str, Any]: ...
    def browse(self, probe_id: str, path: str) -> dict[str, Any]: ...
    def open_workspace(self, probe_id: str, path: str) -> dict[str, Any]: ...


class WorkspaceService:
    def __init__(self, records: WorkspaceRecords, idempotency, *,
                 connector: WslConnectionPort | None = None,
                 ssh_connector: SshConnectionPort | None = None,
                 local: LocalEnvironmentProvider | None = None) -> None:
        self.records = records
        self.idempotency = idempotency
        self.connector = connector
        self.ssh_connector = ssh_connector
        #: Local locations need no remote peer, so this defaults to the real
        #: provider; a caller that wants the refusal without the probe injects
        #: a stub instead of pretending the placement is unimplemented.
        self.local = local if local is not None else LocalEnvironmentProvider()

    def readiness_blockers(self) -> list[dict[str, Any]]:
        """Why this Server could not open a Workspace at all, if that is so.

        Environments are answered per request; this is the composition-level
        fact only - whether *any* placement can be served here.
        """
        if self.connector is not None or self.ssh_connector is not None:
            return []
        return self.local.readiness_blockers()

    def distributions(self):
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        return self.connector.distributions()

    def probe(self, key: str, distribution: str, user: str | None):
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        body = {"kind": "wsl", "distribution": distribution, "user": user}
        request_digest = digest(body)
        prior = self.idempotency.get("POST:/connections/probe", key, request_digest)
        if prior:
            return prior
        result = self._connector_call(self.connector.probe, distribution, user)
        return self.idempotency.save("POST:/connections/probe", key, request_digest, 201, result)

    def archive(self, *, workspace_id: str, expected_version: int) -> dict[str, Any]:
        return self.records.archive(workspace_id=workspace_id, expected_version=expected_version)

    def list(self, *, include_archived: bool) -> list[dict[str, Any]]:
        return self.records.list_active(include_archived=include_archived)

    def browse(self, key: str, probe_id: str, path: str):
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        body = {"probe_id": probe_id, "path": path}
        request_digest = digest(body)
        prior = self.idempotency.get("POST:/connections/browse", key, request_digest)
        if prior:
            return prior
        result = self._connector_call(self.connector.browse, probe_id, path)
        return self.idempotency.save("POST:/connections/browse", key, request_digest, 200, result)

    def create(self, key: str, body: dict[str, Any]):
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        request_digest = digest(body)
        prior = self.idempotency.get("POST:/workspaces", key, request_digest)
        if prior:
            return prior
        verified = self._connector_call(self.connector.open_workspace, body["probe_id"], body["path"])
        return self.records.create(
            key=key, request_digest=request_digest, distribution=verified["distribution"],
            remote_user=verified.get("user"), remote_path=verified["path"],
            connection_id=verified["connection_id"],
        )

    # -- wire/1 environment-addressed use cases --------------------------

    @staticmethod
    def _validate_environment(environment: Any) -> tuple[str, str | None, str | None]:
        if not isinstance(environment, Mapping):
            raise ServerError("ENVIRONMENT_INVALID", "environment must be an object", status=422)
        if set(environment) != {"kind", "host", "user"}:
            raise ServerError("ENVIRONMENT_INVALID", "environment shape is invalid", status=422)
        kind = environment.get("kind")
        if kind not in {"local", "wsl", "ssh"}:
            raise ServerError("ENVIRONMENT_INVALID", "environment.kind is not supported", status=422)
        if any(
            value is not None and not isinstance(value, str)
            for value in (environment.get("host"), environment.get("user"))
        ):
            raise ServerError("ENVIRONMENT_INVALID", "environment identity is invalid", status=422)
        return kind, environment.get("host"), environment.get("user")

    def _wsl_probe(self, host: str | None, user: str | None) -> dict[str, Any]:
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        if not host:
            raise ServerError("ENVIRONMENT_INVALID", "wsl environment needs a host", status=422)
        return self._connector_call(self.connector.probe, host, user)

    def browse_environment(self, *, environment: Any, path: str) -> dict[str, Any]:
        """Browse one environment's directory without opening a Session.

        Readable and writable are reported separately and a directory is never
        refused merely for being read-only (core-semantics/1 §4).
        """
        kind, host, user = self._validate_environment(environment)
        if kind == "local":
            return self.local.browse(path)
        if kind == "ssh":
            probe = self._ssh_probe(host, user)
            result = self._ssh_call(self.ssh_connector.browse, probe["probe_id"], path)
        else:
            probe = self._wsl_probe(host, user)
            result = self._connector_call(self.connector.browse, probe["probe_id"], path)
        entries = []
        for item in result.get("directories", ()):
            name = item if isinstance(item, str) else str(item.get("name", ""))
            entries.append({
                "name": name, "kind": "directory", "canOpen": True, "canWrite": True,
                "reason": None,
            })
        for item in result.get("files", ()):
            name = item if isinstance(item, str) else str(item.get("name", ""))
            entries.append({
                "name": name, "kind": "file", "canOpen": False, "canWrite": False,
                "reason": "not_a_directory",
            })
        return {"path": result.get("path", path), "entries": entries}

    def open_environment(
        self, *, environment: Any, path: str, expected_version: int | None,
    ) -> tuple[bool, dict[str, Any]]:
        kind, host, user = self._validate_environment(environment)
        if kind == "local":
            # A local location is this machine's own fact: the provider
            # validates it and answers the path the room will actually bind.
            # The record names no host and no remote user, because there is
            # neither - inventing either would be a workspace that claims to
            # live somewhere it does not.
            verified = self.local.open_workspace(path)
            return self.records.upsert_by_location(
                env_kind="local", env_host=None, remote_user=None,
                normalized_path=verified["path"], connection_id=None,
            )
        if kind == "ssh":
            probe = self._ssh_probe(host, user)
            verified = self._ssh_call(self.ssh_connector.open_workspace, probe["probe_id"], path)
            return self.records.upsert_by_location(
                env_kind="ssh", env_host=verified["host"], remote_user=verified.get("user") or user,
                normalized_path=verified["path"], connection_id=verified["connection_id"],
            )
        probe = self._wsl_probe(host, user)
        verified = self._connector_call(self.connector.open_workspace, probe["probe_id"], path)
        return self.records.upsert_by_location(
            env_kind=kind, env_host=host, remote_user=verified.get("user") or user,
            normalized_path=verified["path"], connection_id=verified["connection_id"],
        )

    def _ssh_probe(self, host: str | None, user: str | None) -> dict[str, Any]:
        if self.ssh_connector is None:
            raise unavailable("SSH_CONNECTOR_UNAVAILABLE", "SSH connector is not configured")
        if not host:
            raise ServerError("ENVIRONMENT_INVALID", "ssh environment needs a host", status=422)
        return self._ssh_call(self.ssh_connector.probe, host, user)

    def read_workspace_file(self, workspace: Any, relative_path: str) -> tuple[bytes, str]:
        """Read one workspace file from wherever this workspace actually lives.

        The caller supplies the stored record; which machine serves the bytes is
        the record's placement, not the caller's guess. A local workspace is
        served by this Server, a remote one by the connector that reached it.
        """
        kind = workspace.get("env_kind") or "wsl"
        if kind == "local":
            return self.local.read_workspace_file(
                normalized_path=workspace["normalized_path"], relative_path=relative_path,
            )
        if kind == "ssh":
            if self.ssh_connector is None:
                raise unavailable("SSH_CONNECTOR_UNAVAILABLE", "SSH connector is not configured")
            return self._ssh_call(
                self.ssh_connector.read_workspace_file,
                distribution=workspace.get("env_host"),
                user=workspace.get("remote_user"),
                connection_id=workspace["connection_id"],
                workspace_path=workspace["remote_path"],
                relative_path=relative_path,
            )
        if self.connector is None:
            raise unavailable("WSL_CONNECTOR_UNAVAILABLE", "WSL connector is not configured")
        reader = getattr(self.connector, "read_workspace_file", None)
        if not callable(reader):
            raise unavailable(
                "WSL_CONNECTOR_UNAVAILABLE", "workspace attachment reading is unavailable",
            )
        return self._connector_call(
            reader,
            distribution=workspace["distribution"], user=workspace.get("remote_user"),
            connection_id=workspace["connection_id"],
            workspace_path=workspace["remote_path"], relative_path=relative_path,
        )

    @staticmethod
    def _ssh_call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ServerError:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", "SSH_OPERATION_FAILED"))
            status = 409 if code == "PROBE_EXPIRED" else (
                422 if code in {"SSH_TARGET_INVALID", "SSH_IDENTITY_INVALID"} else 503
            )
            raise ServerError(
                code, str(getattr(exc, "message", "SSH operation failed")), status=status,
            ) from exc

    @staticmethod
    def _connector_call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ServerError:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", "WSL_OPERATION_FAILED"))
            status = 409 if code == "PROBE_EXPIRED" else (404 if code == "WSL_DISTRIBUTION_UNKNOWN" else 422)
            raise ServerError(code, str(getattr(exc, "message", "WSL operation failed")), status=status) from exc

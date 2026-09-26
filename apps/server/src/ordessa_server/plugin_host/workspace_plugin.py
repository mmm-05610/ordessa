"""The Workspace domain plugin — the first business domain behind the host boundary.

Owns the five `workspaces.*` wire methods, their shape, their availability
(readiness blockers) and the `WorkspaceService` instance, registered through
`server_plugin_api` and activated by the plugin host. When this plugin is not
composed, those five methods are honestly absent: not advertised by
`server.hello`, refused by dispatch as unknown — never silently kept alive by
a second table.

Transition note (batch 1, to be retired by later domain migrations): the
module still lives inside `ordessa_server` and the records facade it receives
is constructed by the bootstrap composition. The *interface* is fully
plugin-shaped (activation, disposal, honest absence, provided ports); the
physical extraction of the code and the record ownership into a separate
distribution is deliberately not part of this batch.

Port contract:

- consumes: `workspaces.records` (WorkspaceRecords facade), `idempotency`,
  `workspace.wsl_connector`, `workspace.ssh_connector`,
  `workspace.local_provider` (optional; defaults to the real local provider)
- provides: `workspace.service` — the resolution surface the transitional
  core adapter consumes for session/ACP/history workspace facts.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.errors import ServerError
from ordessa_server.wire.projection import workspace_record
from ordessa_server.workspaces.service import WorkspaceService

PLUGIN_ID = "ordessa.workspace"

_METHOD_IDS = (
    "workspaces.browse", "workspaces.open", "workspaces.list",
    "workspaces.archive", "workspaces.gitStatus",
)


class WorkspaceServerPlugin:
    """Workspace domain: records-backed environment authority."""

    def __init__(self) -> None:
        self._service: WorkspaceService | None = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Workspace domain", version="1",
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        records = ports["workspaces.records"]
        idempotency = ports["idempotency"]
        local = ports.get("workspace.local_provider")
        service = WorkspaceService(
            records, idempotency,
            connector=ports.get("workspace.wsl_connector"),
            ssh_connector=ports.get("workspace.ssh_connector"),
            **({"local": local} if local is not None else {}),
        )
        self._service = service

        def readiness() -> "tuple[bool, str | None]":
            blockers = service.readiness_blockers()
            if blockers:
                return False, str(blockers[0]["code"])
            return True, None

        def workspaces_browse(params: Mapping[str, Any]) -> dict[str, Any]:
            from ordessa_server.wire.handlers import _bounded, _require

            _require(params, "requestId", "environment", "path")
            return service.browse_environment(
                environment=params["environment"], path=_bounded(params["path"], "path"),
            )

        def workspaces_open(params: Mapping[str, Any]) -> dict[str, Any]:
            from ordessa_server.wire.handlers import _bounded, _require, _version

            _require(params, "requestId", "environment", "path")
            expected = params.get("expectedVersion")
            if expected is not None:
                expected = _version(expected)
            created, row = service.open_environment(
                environment=params["environment"], path=_bounded(params["path"], "path"),
                expected_version=expected,
            )
            return {"created": created, "workspace": workspace_record(row)}

        def workspaces_list(params: Mapping[str, Any]) -> dict[str, Any]:
            from ordessa_server.wire.errors import WireError

            include = params.get("includeArchived", False)
            if not isinstance(include, bool):
                raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
            return {"items": [workspace_record(row) for row in service.list(
                include_archived=include)], "nextCursor": None}

        def workspaces_archive(params: Mapping[str, Any]) -> dict[str, Any]:
            from ordessa_server.wire.handlers import _bounded, _require, _version
            from ordessa_server.wire.errors import WireError

            _require(params, "requestId", "workspaceId", "expectedVersion")
            try:
                row = service.archive(
                    workspace_id=_bounded(params["workspaceId"], "workspaceId"),
                    expected_version=_version(params["expectedVersion"]),
                )
            except ServerError as exc:
                current = getattr(exc, "current", None)
                error = WireError.from_server_error(exc)
                if current is not None:
                    error.current = workspace_record(current)
                raise error from exc
            return {"workspace": workspace_record(row)}

        def workspaces_git_status(params: Mapping[str, Any]) -> dict[str, Any]:
            from ordessa_server.wire.handlers import _bounded, _require
            from ordessa_server.workspaces.git_status import (
                DEFAULT_MAX_BYTES, DEFAULT_TIMEOUT_SECONDS, GitStatus,
                local_git_status, parse_porcelain_v2,
            )

            _require(params, "requestId", "workspaceId")
            row = records.get(_bounded(params["workspaceId"], "workspaceId"))
            kind = str(row.get("env_kind") or "wsl")
            connector = ports.get("workspace.wsl_connector")
            if kind == "local":
                path = row.get("normalized_path") or row.get("remote_path")
                status = local_git_status(
                    str(path), timeout=DEFAULT_TIMEOUT_SECONDS,
                    max_bytes=DEFAULT_MAX_BYTES)
                return {"git": status.as_wire()}
            if kind == "wsl" and connector is not None:
                read = getattr(connector, "read_only_git_status", None)
                if callable(read):
                    stdout, reason = read(
                        distribution=str(row["distribution"]),
                        user=row.get("remote_user"),
                        path=str(row["remote_path"]),
                        timeout=DEFAULT_TIMEOUT_SECONDS, max_bytes=DEFAULT_MAX_BYTES,
                    )
                    if reason is not None:
                        return {"git": GitStatus(reason=reason, reasons=(reason,)).as_wire()}
                    try:
                        branch, changed, ahead, behind = parse_porcelain_v2(stdout)
                    except (ValueError, TypeError):
                        return {"git": GitStatus(
                            reason="GIT_PARSE_FAILED",
                            reasons=("GIT_PARSE_FAILED",)).as_wire()}
                    return {"git": GitStatus(
                        branch=branch, changed_files=changed,
                        ahead=ahead, behind=behind).as_wire()}
            return {"git": GitStatus(
                reason="GIT_UNAVAILABLE", reasons=("GIT_UNAVAILABLE",)).as_wire()}

        methods = (
            ServerMethodDescriptor(
                method_id="workspaces.browse",
                required_params=frozenset({"requestId", "environment", "path"}),
                optional_params=frozenset(),
                handler=workspaces_browse, owner=PLUGIN_ID, availability=readiness,
            ),
            ServerMethodDescriptor(
                method_id="workspaces.open",
                required_params=frozenset({"requestId", "environment", "path"}),
                optional_params=frozenset({"expectedVersion"}),
                handler=workspaces_open, owner=PLUGIN_ID, availability=readiness,
            ),
            ServerMethodDescriptor(
                method_id="workspaces.list",
                required_params=frozenset({"includeArchived"}),
                optional_params=frozenset(),
                handler=workspaces_list, owner=PLUGIN_ID, availability=readiness,
            ),
            ServerMethodDescriptor(
                method_id="workspaces.archive",
                required_params=frozenset({"requestId", "workspaceId", "expectedVersion"}),
                optional_params=frozenset(),
                handler=workspaces_archive, owner=PLUGIN_ID, availability=readiness,
            ),
            ServerMethodDescriptor(
                method_id="workspaces.gitStatus",
                required_params=frozenset({"requestId", "workspaceId"}),
                optional_params=frozenset(),
                handler=workspaces_git_status, owner=PLUGIN_ID, availability=readiness,
            ),
        )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"workspace.service": service},
            disposal=self._dispose,
        )

    def _dispose(self) -> None:
        self._service = None

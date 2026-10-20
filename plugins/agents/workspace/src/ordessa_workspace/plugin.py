"""The Workspace domain plugin — records, environment authority, wire surface.

Owns the five `workspaces.*` wire methods, their shape, their availability
(readiness blockers), the `WorkspaceRecords` store and the `WorkspaceService`
instance, registered through `server_plugin_api` and activated by the plugin
host. When this plugin is not composed, those five methods are honestly
absent: not advertised by `server.hello`, refused by dispatch as unknown —
never silently kept alive by a second table.

Physically extracted from `ordessa_server` (core-cleanup stage 3; batch-1
retirement facts 1 and 2 closed): the plugin now constructs its own records
from the host's storage ports and is the single owner of the workspace data.

Port contract (T014-S2b: the connector builders moved out of the host's
composition root into `ordessa_workspace.connectors`, so this plugin
composes them itself and provides the ports instead of consuming them):

- consumes: `database`, `idempotency` (host storage primitives),
  `server.instance_id` (the data-root owner's process identity, the
  connector's Worker-root namespace), `workspace.local_provider`
  (optional; defaults to the real local provider)
- provides: `workspace.service` — the resolution surface every other domain
  consumes for workspace facts — `workspace.records`, and the deployment's
  machine connectors: `workspace.wsl_connector`, `workspace.ssh_connector`
  and the placement-keyed mapping `connectors` that the compatibility core
  declares this plugin for and reads at build time
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from server_plugin_api import ServerError
from server_plugin_api import (
    bounded as _bounded,
    require as _require,
    version as _version,
)
from ordessa_workspace import connectors as _connector_builders
from ordessa_workspace.wire_projection import workspace_record
from server_plugin_api import WireError
from ordessa_workspace.error_families import WORKSPACE_ERROR_FAMILIES
from ordessa_workspace.records import WorkspaceRecords
from ordessa_workspace.service import WorkspaceService

PLUGIN_ID = "ordessa.workspace"

_METHOD_IDS = (
    "workspaces.browse", "workspaces.open", "workspaces.list",
    "workspaces.archive", "workspaces.gitStatus",
)


class WorkspaceServerPlugin:
    """Workspace domain: records-backed environment authority."""

    def __init__(self, *, connector: Any | None = None,
                 ssh_connector: Any | None = None) -> None:
        self._service: WorkspaceService | None = None
        self._records: WorkspaceRecords | None = None
        # T014-S2b: the machine connectors are this plugin's composition.
        # `None` means "compose them from the deployment's machine-local
        # bindings" (the env-var builders that used to sit in the host's
        # composition root); an explicit object is the test/deployment
        # injection that replaces that build, raised by nothing else.
        self._connector_override = connector
        self._ssh_connector_override = ssh_connector

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Workspace domain", version="1",
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        records = WorkspaceRecords(ports["database"], ports["idempotency"])
        idempotency = ports["idempotency"]
        local = ports.get("workspace.local_provider")
        # T014-S2b: the host composes nothing here any more. The builders
        # are resolved as MODULE attributes (not imported symbols) so the
        # placement tests' monkeypatch surface moved with them; the
        # instance id is the data-root owner's, the same value the host's
        # former built-in fallback received.
        instance_id = str(ports.get("server.instance_id", ""))
        wsl_connector = self._connector_override
        if wsl_connector is None:
            wsl_connector = _connector_builders._builtin_connector(instance_id)
        ssh_connector = self._ssh_connector_override
        if ssh_connector is None:
            ssh_connector = _connector_builders._builtin_ssh_connector(instance_id)
        service = WorkspaceService(
            records, idempotency,
            connector=wsl_connector,
            ssh_connector=ssh_connector,
            **({"local": local} if local is not None else {}),
        )
        self._service = service
        self._records = records

        def readiness() -> "tuple[bool, str | None]":
            blockers = service.readiness_blockers()
            if blockers:
                return False, str(blockers[0]["code"])
            return True, None

        def workspaces_browse(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "requestId", "environment", "path")
            return service.browse_environment(
                environment=params["environment"], path=_bounded(params["path"], "path"),
            )

        def workspaces_open(params: Mapping[str, Any]) -> dict[str, Any]:
            expected = params.get("expectedVersion")
            if expected is not None:
                expected = _version(expected)
            created, row = service.open_environment(
                environment=params["environment"], path=_bounded(params["path"], "path"),
                expected_version=expected,
            )
            return {"created": created, "workspace": workspace_record(row)}

        def workspaces_list(params: Mapping[str, Any]) -> dict[str, Any]:
            include = params.get("includeArchived", False)
            if not isinstance(include, bool):
                raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
            return {"items": [workspace_record(row) for row in service.list(
                include_archived=include)], "nextCursor": None}

        def workspaces_archive(params: Mapping[str, Any]) -> dict[str, Any]:
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
            from ordessa_workspace.git_status import (
                DEFAULT_MAX_BYTES, DEFAULT_TIMEOUT_SECONDS, GitStatus,
                local_git_status, parse_porcelain_v2,
            )

            _require(params, "requestId", "workspaceId")
            row = records.get(_bounded(params["workspaceId"], "workspaceId"))
            kind = str(row.get("env_kind") or "wsl")
            connector = wsl_connector
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
        from ordessa_workspace.http import workspace_http_routes

        def mark_unverified() -> None:
            # Startup recovery the host's start() used to perform: every
            # stored workspace begins an unverified connection state until
            # the Server can attest access again.
            records.mark_all_unverified()

        return ServerPluginRegistration(
            methods=methods,
            http_routes=workspace_http_routes(records, service),
            provided_ports={
                "workspace.service": service,
                "workspace.records": records,
                # T014-S2b: the connectors leave the composition through
                # THIS plugin's ports, keyed by the placement that consumes
                # them — "which environments can this Server actually reach"
                # is still one fact stated once, but stated by the domain
                # that decides it. The compatibility core reads `connectors`
                # through its declared `requires` on this plugin; anything
                # outside the round resolves it through
                # `plugin_host.provided_port(...)` and gets None once this
                # plugin retires.
                "workspace.wsl_connector": wsl_connector,
                "workspace.ssh_connector": ssh_connector,
                "connectors": {"wsl": wsl_connector, "ssh": ssh_connector},
            },
            start_hooks=(mark_unverified,),
            disposal=self._dispose,
            # T014-S2a-R: the wire/1 families of the codes THIS plugin raises
            # are published as an open-point contribution, not carried in the
            # host's table. The host aggregates per composition; conflicts
            # (same code, different family) refuse the whole activation round;
            # a composition without this plugin answers these codes through
            # the documented fall-through.
            contributions=ContributionBatch((
                Contribution(
                    point_id=WIRE_ERROR_FAMILIES_POINT_ID,
                    api_version=WIRE_ERROR_FAMILIES_API_VERSION,
                    payload=WORKSPACE_ERROR_FAMILIES,
                ),
            )),
        )

    def _dispose(self) -> None:
        self._service = None
        self._records = None

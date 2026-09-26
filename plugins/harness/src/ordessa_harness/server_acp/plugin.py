"""The Harness server facet: managed ACP channels as a Server plugin.

Owns the two `acp.channel.*` wire methods and the `acp-channel` stream route
(batch-1 retirement fact 5 closed: the route is no longer registered under
the host owner). The channel registry, its transports and its release path
live in `ordessa_harness.server_acp`; this plugin is the Server-side
registration seam.

Composed in two shapes:

- default product: `launch=None` — the methods are advertised (a deployment
  fact the client can rely on) and answer the same typed
  `CAPABILITY_UNSUPPORTED` the pre-extraction composition answered when no
  channel transport was composed;
- native composition: `launch` (the access-entry transport factory) and
  `native_identity` (the composition's native identity closure) are
  injected, and the stream route is registered through the host's stream
  registry — origin, bearer and close semantics stay host-owned.

Port contract:

- consumes: `sessions.records`, `profiles.records` (declared dependency on
  the compatibility core), `workspace.service` (declared dependency on the
  Workspace plugin)
- provides: `acp.channels` (the registry, or None without a launch)
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)

from ordessa_server.errors import ServerError
from ordessa_server.wire.errors import WireError
from ordessa_server.wire.handlers import _bounded, _require

PLUGIN_ID = "ordessa.harness.acp"


class AcpChannelServerPlugin:
    """Managed ACP channels: harness-owned, host-admitted."""

    def __init__(self, *, launch: Callable | None = None,
                 native_identity: Callable[[], Mapping[str, Any]] | None = None) -> None:
        self._launch = launch
        self._native_identity = native_identity
        self._registry: Any = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Harness ACP channels", version="1",
            requires=("ordessa.workspace", "ordessa.server-compat"),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        workspaces = ports["workspace.service"]
        if self._launch is not None:
            from ordessa_harness.server_acp.registry import AcpChannelRegistry

            self._registry = AcpChannelRegistry(
                session_records=ports["sessions.records"],
                profile_records=ports["profiles.records"],
                launch=self._launch,
            )
        native_identity = self._native_identity

        def acp_channel_open(params: Mapping[str, Any]) -> dict[str, Any]:
            """Establish or re-acquire the managed bidirectional ACP channel.

            Every refusal happens before any launch: this Server's native
            identity, the Project record, and the authoritative working dir are
            all checked first, so a rejected request starts no process and writes
            no run. A pair that already holds a live channel returns that same
            connection - the binding never moves underneath a client.
            """
            _require(params, "harnessId", "projectId")
            if self._registry is None:
                raise WireError("CAPABILITY_UNSUPPORTED", "this Server composes no managed ACP channel")
            harness_id = _bounded(params["harnessId"], "harnessId", 64)
            identity = native_identity() if native_identity else None
            if (not isinstance(identity, Mapping) or identity.get("mode") != "native"
                    or identity.get("harness") != harness_id or not identity.get("profileId")):
                raise WireError(
                    "CAPABILITY_UNSUPPORTED",
                    f"{harness_id} is not the native Harness this Server answers channels for",
                )
            workspace_id = _bounded(params["projectId"], "projectId")
            row = workspaces.records.get(workspace_id)
            if str(row.get("env_kind") or "") != "local":
                raise WireError("CAPABILITY_UNSUPPORTED", "managed channels are placed on local projects only")
            selected = str(row.get("normalized_path") or "")
            if not selected:
                raise WireError("INVALID_REQUEST", "the project record carries no authoritative path")
            normalized = workspaces.local.validate(selected)
            if normalized != selected:
                raise ServerError("NATIVE_PROJECT_CHANGED", "selected project changed", status=409)
            return self._registry.acquire(
                harness_id=harness_id, workspace_id=workspace_id,
                profile_id=str(identity["profileId"]), cwd=selected,
            )

        def acp_channel_release(params: Mapping[str, Any]) -> dict[str, Any]:
            """Release one channel by ownership: its transport stops, its run
            record ends saying `released`, and no in-flight request is answered
            on anyone's behalf. Only the live holder of the id is touched."""
            _require(params, "connectionId")
            if self._registry is None:
                raise WireError("CAPABILITY_UNSUPPORTED", "this Server composes no managed ACP channel")
            result = self._registry.release(_bounded(params["connectionId"], "connectionId"))
            if result is None:
                raise WireError("NOT_FOUND", "no live managed channel carries that connectionId")
            return result

        methods = (
            ServerMethodDescriptor(
                method_id="acp.channel.open",
                required_params=frozenset({"harnessId", "projectId"}),
                optional_params=frozenset({"requestId"}),
                handler=acp_channel_open, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id="acp.channel.release",
                required_params=frozenset({"connectionId"}),
                optional_params=frozenset({"requestId"}),
                handler=acp_channel_release, owner=PLUGIN_ID,
            ),
        )
        stream_routes: "tuple[StreamRouteDescriptor, ...]" = ()
        if self._registry is not None:
            stream_routes = (StreamRouteDescriptor(
                route_id="acp-channel", resolver=self._registry.get, owner=PLUGIN_ID,
            ),)
        return ServerPluginRegistration(
            methods=methods, stream_routes=stream_routes,
            provided_ports={"acp.channels": self._registry},
            disposal=self._dispose,
        )

    def _dispose(self) -> None:
        self._registry = None

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
  Workspace plugin), `harness.directory` (the compatibility core's live
  family directory — the fact `server.hello`'s `harnesses` facet projects)
- provides: `acp.channels` (the registry, or None without a launch)
- contributes: the two `server.hello` discovery facets this domain can answer
  (`wire.discovery-facets`, T014-S3): `harnesses`, projected from the live
  directory, and `nativeExecution`, projected from the composition's native
  identity closure **with the identity rule applied here** — before this
  slice the host's transport validated a native identity, which is exactly
  the business knowledge FR-006 asks the host to stop carrying. Only the
  harness knows what a registered directory must satisfy, and only the
  harness may say so in the answer's place.
- stops: the registry's `stop_all` runs as this plugin's stop hook, so every
  managed transport ends with the `server-stop` reason and its run record
  settles through the still-live compatibility records — before any plugin is
  disposed, in reverse activation order (this plugin depends on the
  compatibility core, so it is torn down first)
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from server_plugin_api import (
    ACP_ADMISSION_PORT,
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionResult,
    AcpAttachmentReference,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
    WIRE_DISCOVERY_FACETS_API_VERSION,
    WIRE_DISCOVERY_FACETS_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)

from server_plugin_api import ServerError
from server_plugin_api import WireError
from server_plugin_api import bounded as _bounded, require as _require

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
        admission_port = ports.get(ACP_ADMISSION_PORT)

        def admission_available() -> tuple[bool, str | None]:
            # The Server installs an explicit DTO adapter. Its marker prevents
            # calling the older internal gate that shares this port name but
            # accepts mutable mappings and raises a private exception type.
            ready = (self._registry is not None and
                     type(getattr(admission_port, "public_acp_admission_port_version", None)) is int and
                     admission_port.public_acp_admission_port_version == ACP_ADMISSION_PORT_VERSION and
                     getattr(admission_port, "ready", None) is True)
            return (True, None) if ready else (False, "ACP admission authority is unavailable")

        def admission_binding(params: Mapping[str, Any], native_session_id: str) -> AcpChannelBinding | None:
            if not admission_available()[0]:
                return None
            connection_id = _bounded(params["connectionId"], "connectionId")
            channel = self._registry.get(connection_id)
            if (channel is None or channel.ended or channel.transport is None or
                    not channel.session_id or not channel.execution_id):
                return None
            # The request's nativeSessionId is only an index into facts observed
            # from this channel's correlated Agent session/new response.
            fact = self._registry.native_session_observation(connection_id, native_session_id)
            if (fact is None or fact.connection_id != channel.connection_id or
                    fact.execution_id != channel.execution_id or
                    fact.ledger_session_id != channel.session_id or
                    fact.native_session_id != native_session_id or
                    self._registry.get(connection_id) is not channel or channel.ended):
                return None
            return AcpChannelBinding(
                connection_id=channel.connection_id,
                execution_id=channel.execution_id,
                ledger_session_id=channel.session_id,
                harness_id=channel.harness_id,
                workspace_id=channel.workspace_id,
                native_session_id=fact.native_session_id,
                # Native session observation does not prove runtime generation.
                runtime_generation=None,
            )

        def admission_unknown(expected_id: str) -> dict[str, str]:
            return {"kind": "unknown", "operationId": expected_id,
                    "reason": "ACP admission outcome needs reconciliation; query before retry"}

        def wire_admission(result: AcpAdmissionResult, expected_id: str) -> dict[str, Any]:
            if type(result) is not AcpAdmissionResult:
                return admission_unknown(expected_id)
            if result.kind == "accepted":
                if result.submission_id != expected_id:
                    return admission_unknown(expected_id)
                return {"kind": "accepted", "submissionId": result.submission_id}
            if result.kind == "unknown":
                return {"kind": "unknown", "operationId": result.operation_id,
                        "reason": result.reason}
            return {"kind": "refused", "code": result.code, "reason": result.reason}

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

        def acp_submission_authorize(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "connectionId", "submission")
            if not admission_available()[0]:
                return {"kind": "refused", "code": "CAPABILITY_UNSUPPORTED",
                        "reason": "ACP channel or admission authority is unavailable"}
            raw = params["submission"]
            if not isinstance(raw, Mapping):
                raise WireError("INVALID_REQUEST", "ACP submission must be an object")
            attachments = raw.get("attachments")
            if not isinstance(attachments, list):
                raise WireError("INVALID_REQUEST", "ACP attachments must be a list")
            try:
                refs = tuple(AcpAttachmentReference(
                    name=item.get("name"), uri=item.get("uri"), sha256=item.get("sha256"),
                    mime_type=item.get("mimeType")) for item in attachments if isinstance(item, Mapping))
                if len(refs) != len(attachments):
                    raise ValueError("ACP attachment must be an object")
                request = AcpSubmissionRequest(
                    submission_id=raw.get("submissionId"), native_session_id=raw.get("nativeSessionId"),
                    text=raw.get("text"), attachments=refs,
                    configuration_digest=raw.get("configurationDigest"), command_id=raw.get("commandId"))
            except ValueError as exc:
                raise WireError("INVALID_REQUEST", str(exc)) from exc
            binding = admission_binding(params, request.native_session_id)
            if binding is None:
                return {"kind": "refused", "code": "CAPABILITY_UNSUPPORTED",
                        "reason": "ACP native session or admission authority is unavailable"}
            try:
                result = admission_port.authorize_submission(binding, request)
                return wire_admission(result, request.submission_id)
            except Exception:
                # The port may have reserved or consumed a permit before its
                # reply failed. Only its own typed result can prove refusal.
                return admission_unknown(request.submission_id)

        def acp_permission_authorize(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "connectionId", "decision")
            if not admission_available()[0]:
                return {"kind": "refused", "code": "CAPABILITY_UNSUPPORTED",
                        "reason": "ACP channel or admission authority is unavailable"}
            raw = params["decision"]
            if not isinstance(raw, Mapping):
                raise WireError("INVALID_REQUEST", "ACP permission decision must be an object")
            try:
                decision = AcpPermissionDecision(
                    native_session_id=raw.get("nativeSessionId"), interaction_id=raw.get("interactionId"),
                    run_id=raw.get("runId"), option_id=raw.get("optionId"))
            except ValueError as exc:
                raise WireError("INVALID_REQUEST", str(exc)) from exc
            binding = admission_binding(params, decision.native_session_id)
            if binding is None:
                return {"kind": "refused", "code": "CAPABILITY_UNSUPPORTED",
                        "reason": "ACP native session or admission authority is unavailable"}
            try:
                result = admission_port.authorize_permission(binding, decision)
                return wire_admission(result, decision.interaction_id)
            except Exception:
                return admission_unknown(decision.interaction_id)

        # -- discovery facets (T014-S3): what this domain lets `server.hello`
        # say about itself. Projectors, not values: the directory can gain a
        # member while the Server runs (a controlled seat is registered after
        # activation, and the next hello must advertise it), so an
        # activation-time snapshot would be a different protocol than the one
        # wire/1 froze. The host calls each one per hello and aggregates the
        # answer; it never interprets an entry and never learns the names.
        directory = ports.get("harness.directory")

        def project_harnesses() -> "list[dict[str, Any]]":
            """The families this Server can run, from the live directory.

            A deployment fact, never derived from the records: a fresh
            deployment has no records, and deriving the list from them was
            what left a client with nothing to choose. Only what a family
            *declares* is published, and a declaration that is absent stays
            absent. `registered()` is already sorted by id, so this is the
            directory's own order rather than a second sort that could later
            disagree with it.
            """
            entries: "list[dict[str, Any]]" = []
            if directory is None:
                return entries
            for harness_id in directory.registered():
                seat = directory.get(harness_id)
                entry: dict[str, Any] = {"id": harness_id}
                if seat.credential_kind is not None:
                    entry["credentialKind"] = seat.credential_kind
                if seat.model_control_id is not None:
                    entry["modelControlId"] = seat.model_control_id
                entries.append(entry)
            return entries

        def project_native_execution() -> "dict[str, Any] | None":
            """The identity a native Server runs as — or typed absence.

            A composition with no native identity answers `None`, and the
            host publishes no `nativeExecution` member at all: an absent
            fact, not a refusal. A composition that claims one has to be
            able to say it *now*: mode `native`, a harness this Server's
            directory actually registers, and a live non-empty profile id.
            A claimed identity that fails that rule is the one case where
            this hello refuses, and the refusal keeps wire/1's bytes: the
            `UNAVAILABLE` family named explicitly (it is what an
            unregistered code converged to before, so naming it changes no
            answer — only the fact that someone chose it) with the internal
            code in `details`, and the frozen message.
            """
            if native_identity is None:
                return None
            native = native_identity()
            if (not isinstance(native, Mapping) or native.get("mode") != "native"
                    or directory is None
                    or native.get("harness") not in directory.registered()
                    or not isinstance(native.get("profileId"), str) or not native["profileId"]):
                raise WireError(
                    "UNAVAILABLE", "native execution identity is unavailable",
                    {"internalCode": "SERVER_NATIVE_IDENTITY_INVALID"},
                )
            return dict(native)

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
            ServerMethodDescriptor(
                method_id="acp.submission.authorize",
                required_params=frozenset({"connectionId", "submission"}),
                optional_params=frozenset({"requestId"}),
                handler=acp_submission_authorize, owner=PLUGIN_ID,
                availability=admission_available,
            ),
            ServerMethodDescriptor(
                method_id="acp.permission.authorize",
                required_params=frozenset({"connectionId", "decision"}),
                optional_params=frozenset({"requestId"}),
                handler=acp_permission_authorize, owner=PLUGIN_ID,
                availability=admission_available,
            ),
        )
        stream_routes: "tuple[StreamRouteDescriptor, ...]" = ()
        stop_hooks: "tuple[Callable[[], None], ...]" = ()
        if self._registry is not None:
            stream_routes = (StreamRouteDescriptor(
                route_id="acp-channel", resolver=self._registry.get, owner=PLUGIN_ID,
            ),)
            # Teardown this plugin owns, and it belonged to no one else: every
            # managed transport stops with the honest `server-stop` reason and
            # its run record settles. The host guarantees only that this runs
            # in reverse activation order, before any disposal — this plugin
            # declares `ordessa.server-compat` in `requires`, so it activates
            # last and stops first, which is what keeps the session records the
            # release path writes still reachable underneath it.
            registry = self._registry
            stop_hooks = (registry.stop_all,)
        return ServerPluginRegistration(
            methods=methods, stream_routes=stream_routes,
            provided_ports={"acp.channels": self._registry},
            disposal=self._dispose,
            # T014-S3: the hello facets this domain owns, published through the
            # host's open `wire.discovery-facets` point. One batch, one owner
            # (this plugin), two facet names in the contract's own order —
            # `harnesses` then `nativeExecution` — so the aggregation stays
            # byte-identical to the answer this host used to build itself.
            # Unloading this plugin retires the batch, and hello goes back to
            # the contract's empty default instead of lying about a domain
            # that is no longer composed.
            contributions=ContributionBatch((
                Contribution(
                    point_id=WIRE_DISCOVERY_FACETS_POINT_ID,
                    api_version=WIRE_DISCOVERY_FACETS_API_VERSION,
                    payload={
                        "harnesses": project_harnesses,
                        "nativeExecution": project_native_execution,
                    },
                ),
            )),
            stop_hooks=stop_hooks,
        )

    def _dispose(self) -> None:
        self._registry = None

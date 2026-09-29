"""Q4/T09 Server-plugin registration: the ``mcp.*`` typed method face.

The MCP asset domain's ServerPlugin — the T09 Q4-side half of
``specs/011-q4-mcp/tasks.md`` (product assembly and the compat deletion are
C0). Shape follows the workspace / server-compat / ACP precedents: one
atomic ``ServerMethodDescriptor`` per wire method (params shape + handler +
availability + owner travel together), the domain service built from the
host's data root and optional facades, and the domain's error families
published through the host's open ``wire.error-families`` point — a
composition without this plugin answers these codes with the documented
fall-through, and this plugin never reads the host's aggregate.

Method set (docs/design/mcp/contracts.md §1; business plugins do not touch
``apps/server/.../wire/handlers.py`` — every row arrives here):

    mcp.list mcp.get mcp.saveRevision mcp.approveRevision mcp.archive
    mcp.probe mcp.assign mcp.unassign mcp.resolvePreview
    mcp.inspectConnection mcp.listTools mcp.planForSubmission

Port contract:

* host facades consumed (all optional, absence handled at call time):
  ``credentials`` + ``secret_store`` (wired into the fail-closed
  :func:`backend.secret.host_credential_port`),
  ``wire.error_family_resolver`` (the composition's code→family callable);
* plugin ports consumed (the explicit cross-plugin declarations of
  contracts §1 "provider 缺席类型化拒绝"): ``permission.probe_authority``
  (probe gate; absent → ``PERMISSION_AUTHORITY_ABSENT``),
  ``harness.submission_gate`` (the placeholder C4/C5 gate; absent together
  with the real port → ``APPLICATION_PORT_ABSENT`` — registered but
  availability-limited rows, never fake successes) and, since T013,
  ``harness.configuration_service`` — the REAL published
  ``ordessa_harness_api.ConfigurationService`` port (contracts §3 C4 face).
  With it composed, ``mcp.planForSubmission`` additionally requires the
  params ``submissionPermit`` (absent → ``SUBMISSION_PERMIT_REQUIRED``, and
  nothing is reconfigured or launched either way) and ``expectedRevision``
  (absent → ``EXPECTED_REVISION_REQUIRED``; drift answers the C4
  ``STALE_PLAN`` refusal as ``MCP_CAS_CONFLICT``); the placeholder gate and
  the real port together refuse ``SUBMISSION_GATE_AMBIGUOUS`` — one gate.
  Neither has a provider in this tree's default composition today, so
  ``server.hello`` honestly reports the rows unsupported while they remain
  dispatchable typed refusals (the availability predicate answers the hello
  question only and never gates dispatch, order 097);
* the native planner seam (``native_planner`` / ``lane_by_definition``
  constructor injections): the product assembly wires
  ``adapters.{codex,claude}.compile`` (with the injected destination
  descriptors and credential provenance) and the lane owner decisions in;
  the backend package never imports ``adapters`` (install boundary), and an
  unwired planner on the real-port path is the typed
  ``NATIVE_PLANNER_ABSENT`` refusal, never a fallback plan;
* provides: ``asset.mcp.v2`` — the :class:`backend.service.McpDomainService`
  (the read-only services Profile/Settings/Chat consumers resolve);
* auth: every ``mcp.*`` request carries an explicit ``principal`` param.
  The host has no request-level principal injection surface today (a
  handler receives only the params mapping), so this principal is
  caller-claimed, NOT transport-authenticated — registered as the T09 gap
  in specs/011-q4-mcp/reports/t09-service.md for the integration request;
  the domain uses it for its own isolation rules (assignment ownership,
  lease visibility, probe binding) which is exactly what makes a
  host-injected principal the honest follow-up, not a decoration.
"""
from __future__ import annotations

import logging
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
    bounded as _bounded,
    family_for as _static_family,
    require as _require,
    version as _version,
)

from .errors import McpError
from .secret import host_credential_port
from .service import McpDomainService

PLUGIN_ID = "ordessa.asset.mcp"

_LOG = logging.getLogger(__name__)

# -- the §1 shapes: exact wire/1 required/optional param sets -------------------

_PARAM_SHAPES: "dict[str, tuple[frozenset[str], frozenset[str]]]" = {
    "mcp.list": (
        frozenset({"serverScope", "principal"}),
        frozenset({"requestId"})),
    "mcp.get": (
        frozenset({"serverScope", "principal", "definitionId"}),
        frozenset({"requestId", "revision"})),
    "mcp.saveRevision": (
        frozenset({"serverScope", "principal", "definitionId", "definition",
                   "expectedVersion", "operationKey"}),
        frozenset({"requestId", "source"})),
    "mcp.approveRevision": (
        frozenset({"serverScope", "principal", "definitionId", "revision"}),
        frozenset({"requestId"})),
    "mcp.archive": (
        frozenset({"serverScope", "principal", "definitionId"}),
        frozenset({"requestId"})),
    "mcp.probe": (
        frozenset({"serverScope", "principal", "definitionId", "revision"}),
        frozenset({"requestId"})),
    "mcp.assign": (
        frozenset({"serverScope", "principal", "scopeKind", "scopeId", "definitionId",
                   "decision", "expectedRowVersion", "operationKey"}),
        frozenset({"requestId", "harness", "approvedRevision", "toolSelection"})),
    "mcp.unassign": (
        frozenset({"serverScope", "principal", "scopeKind", "scopeId", "definitionId",
                   "expectedRowVersion", "operationKey"}),
        frozenset({"requestId", "harness"})),
    "mcp.resolvePreview": (
        frozenset({"serverScope", "principal"}),
        frozenset({"requestId", "harness", "projectId", "profileRevision",
                   "sessionRef", "targetSession", "runtimeGeneration"})),
    "mcp.inspectConnection": (
        frozenset({"principal", "sessionRef", "runtimeGeneration", "leaseId"}),
        frozenset({"requestId"})),
    "mcp.listTools": (
        frozenset({"principal", "sessionRef", "runtimeGeneration", "serverScope",
                   "definitionId", "revision"}),
        frozenset({"requestId"})),
    "mcp.planForSubmission": (
        frozenset({"serverScope", "principal", "sessionRef", "runtimeGeneration"}),
        frozenset({"requestId", "harness", "projectId", "profileRevision",
                   "targetSession", "expectedRevision", "submissionPermit"})),
}

# -- error → wire mapping (the SC `_asset_refusal` style, MCP's own codes) -------

_CODE_SHAPE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")


def _mcp_refusal(exc: BaseException,
                 family_lookup: "Callable[[str], str] | None" = None) -> WireError:
    """One path for the MCP domain's refusals (``_asset_refusal`` precedent).

    A code shaped like a domain code keeps its own words: the family
    `family_lookup` assigns (the composition's resolver, the same injected
    callable the compatibility core reads), the ``"{code}: {message}"`` text
    the domain has always raised, and ``details.internalCode``. Anything
    else is a Server-side fault: ``UNAVAILABLE`` with the exception *type*
    as ``internalCode`` — the raw text (which can name a host path or a
    credential locator) goes to the log, never to the client."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _CODE_SHAPE.fullmatch(code):
        message = str(getattr(exc, "message", "") or "the MCP domain refused the request")
        family = (family_lookup or _static_family)(code)
        return WireError(family, f"{code}: {message}",
                         {"internalCode": code, "retryable": family == "UNAVAILABLE"})
    _LOG.warning("MCP domain raised %s: %s", type(exc).__name__, exc)
    return WireError("UNAVAILABLE", "the MCP domain could not complete the request",
                     {"internalCode": type(exc).__name__, "retryable": True})


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WireError("INVALID_REQUEST", f"{name} must be an object")
    return value


# -- the wire/1 families of the codes this plugin raises -------------------------
# Ownership by raise site (T014-S2a-R rule): every row here is raised by a
# backend/ module this plugin composes. Codes never raised from this
# plugin's paths are absent, and no row disagrees with the host's static
# table or the compatibility core's published rows.

MCP_ERROR_FAMILIES = MappingProxyType({
    # backend/errors.py (definition store / assignment / FR-10 vocabulary)
    "MCP_NAME_INVALID": "INVALID_REQUEST",
    "MCP_DEFINITION_INVALID": "INVALID_REQUEST",
    "MCP_TRANSPORT_UNSUPPORTED": "INVALID_REQUEST",
    "MCP_CREDENTIAL_REFERENCE_REQUIRED": "INVALID_REQUEST",
    "MCP_REVISION_EXISTS": "CONFLICT_REQUEST",
    "MCP_ASSET_MISSING": "NOT_FOUND",
    "MCP_CAS_CONFLICT": "CONFLICT_VERSION",
    "MCP_OPERATION_CONFLICT": "CONFLICT_REQUEST",
    "MCP_SERVER_SCOPE_CONFLICT": "CONFLICT_REQUEST",
    "MCP_OWNER_CONFLICT": "CONFLICT_REQUEST",
    "MCP_REVISION_NOT_APPROVED": "CONFLICT_REQUEST",
    "MCP_DEFINITION_ARCHIVED": "CONFLICT_REQUEST",
    "MCP_ASSIGNMENT_INVALID": "INVALID_REQUEST",
    "MCP_TOOL_NOT_OBSERVED": "INVALID_REQUEST",
    "MCP_CATALOG_MISSING": "NOT_FOUND",
    "AUTH_REQUIRED": "UNAUTHENTICATED",
    "SECRET_UNRESOLVED": "UNAVAILABLE",
    "PERMISSION_REFUSED": "FORBIDDEN",
    "UNKNOWN_OUTCOME": "OUTCOME_UNKNOWN",
    "CATALOG_CHANGED": "CONFLICT_REQUEST",
    "CONNECTION_FAILED": "UNAVAILABLE",
    # backend/probe.py
    "PROBE_COMMAND_INVALID": "INVALID_REQUEST",
    "PROBE_SPAWN_FAILED": "UNAVAILABLE",
    "PROBE_TIMEOUT": "UNAVAILABLE",
    "PROBE_FORMAT_INVALID": "UNAVAILABLE",
    "PROBE_RESPONSE_TOO_LARGE": "UNAVAILABLE",
    "PROBE_AUTH_REQUIRED": "UNAUTHENTICATED",
    "PROBE_CONNECTION_FAILED": "UNAVAILABLE",
    "PROBE_CANCELLED": "UNAVAILABLE",
    "PROBE_PROTOCOL_MISMATCH": "CAPABILITY_UNSUPPORTED",
    "PROBE_REDIRECT_REFUSED": "CAPABILITY_UNSUPPORTED",
    "PROBE_URL_NOT_ALLOWED": "FORBIDDEN",
    # backend/permissions.py
    "PERMISSION_AUTHORITY_ABSENT": "UNAVAILABLE",
    "PERMISSION_ENFORCEMENT_UNPROVEN": "CAPABILITY_UNSUPPORTED",
    "PERMISSION_ARGS_DIGEST_REQUIRED": "INVALID_REQUEST",
    # backend/secret.py
    "PLAN_STALE": "CONFLICT_VERSION",
    "MCP_PLAN_BINDING_INVALID": "INVALID_REQUEST",
    # backend/managed/{lease,catalog,session_manager}.py
    "MCP_STATE_TRANSITION_INVALID": "CONFLICT_REQUEST",
    "MCP_LEASE_MISSING": "NOT_FOUND",
    "MCP_LEASE_BUSY": "CONFLICT_REQUEST",
    "MCP_RECONCILE_REQUIRED": "CONFLICT_REQUEST",
    "MCP_NOT_CONNECTED": "UNAVAILABLE",
    "MCP_TOOL_NOT_APPROVED": "FORBIDDEN",
    "MCP_CATALOG_UNOBSERVABLE": "CONFLICT_REQUEST",
    "MCP_CLIENT_FACTORY_MISSING": "UNAVAILABLE",
    # backend/service.py (this plugin's own seam refusals)
    "APPLICATION_PORT_ABSENT": "CAPABILITY_UNSUPPORTED",
    "SUBMISSION_PERMIT_REQUIRED": "FORBIDDEN",
    "EXPECTED_REVISION_REQUIRED": "INVALID_REQUEST",
    "SUBMISSION_GATE_AMBIGUOUS": "CONFLICT_REQUEST",
    # backend/native_binding.py (C4 Refused/Unknown + binding seam, T013)
    "MCP_GATE_CAPABILITY_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "MCP_GATE_FRAGMENT_INVALID": "INVALID_REQUEST",
    "MCP_GATE_BUSY": "UNAVAILABLE",
    "MCP_GATE_RESUME_UNAVAILABLE": "UNAVAILABLE",
    "MCP_VERIFICATION_MISMATCH": "CONFLICT_REQUEST",
    "MCP_ISOLATION_UNPROVEN": "FORBIDDEN",
    "NATIVE_PLANNER_ABSENT": "UNAVAILABLE",
    # raised through the composition-injected native planner (adapters T04
    # codes, backend/native_intents.py vocabulary) — the submission path
    # runs them, so the rows belong to this plugin's published set
    "MCP_NATIVE_TARGET_UNSUPPORTED": "INVALID_REQUEST",
    "MCP_NATIVE_NAME_CONFLICT": "CONFLICT_REQUEST",
    "MCP_CREDENTIAL_PROVENANCE_UNPROVEN": "UNAVAILABLE",
})


class McpAssetServerPlugin:
    """The MCP asset domain: definitions, revisions, assignments, snapshots,
    managed-connection reads — registered, never hard-wired to a provider."""

    def __init__(self, *, probe_runner: Callable | None = None,
                 probe_policy: Any | None = None,
                 client_factory: Callable | None = None,
                 mcp_root: Any | None = None,
                 native_planner: Callable | None = None,
                 lane_by_definition: Any | None = None,
                 native_posture_facts: Any | None = None) -> None:
        # Composition injections for L0/L1 proofs (the ACP plugin's `launch`
        # precedent): the real probe transport, the managed client factory,
        # the store root. None keeps the production default — the real
        # credential-less probe and no client factory at all (starting a
        # managed connection then answers MCP_CLIENT_FACTORY_MISSING, the
        # honest G2/G4 absence, never a fake connection). T013: the native
        # planner and the lane owner records arrive the same way from the
        # product assembly (backend never imports adapters); unwired on the
        # real-port path is the typed NATIVE_PLANNER_ABSENT refusal.
        self._probe_runner = probe_runner
        self._probe_policy = probe_policy
        self._client_factory = client_factory
        self._mcp_root = mcp_root
        self._native_planner = native_planner
        self._lane_by_definition = lane_by_definition
        # T012: the native permission posture facts arrive the same way as
        # the planner (product assembly; the harness observation/declaration
        # plane is the only legitimate producer). Display-only labels —
        # absent keeps every native entry "unattributed".
        self._native_posture_facts = native_posture_facts
        self._service: McpDomainService | None = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="MCP asset domain (definitions, revisions, "
                                       "assignments, effective snapshots)",
            version="1",
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        root = self._mcp_root if self._mcp_root is not None \
            else context.data_root / "assets"
        kwargs: dict = {"root": root,
                        "probe_authority": ports.get("permission.probe_authority"),
                        "submission_gate": ports.get("harness.submission_gate"),
                        # T013: the real Harness C4 port (contracts §3);
                        # absent keeps the pre-T013 submission behaviour
                        "configuration_service": ports.get("harness.configuration_service"),
                        # the host's two credential layers wired into the fail-
                        # closed adapter: either absent -> SECRET_UNRESOLVED
                        # at every resolution, never a partial plan (G7)
                        "credential_port": host_credential_port(
                            credential_records=ports.get("credentials"),
                            secret_store=ports.get("secret_store"))}
        if self._native_planner is not None:
            kwargs["native_planner"] = self._native_planner
        if self._lane_by_definition is not None:
            kwargs["lane_by_definition"] = self._lane_by_definition
        if self._native_posture_facts is not None:
            kwargs["native_posture_facts"] = self._native_posture_facts
        if self._probe_runner is not None:
            kwargs["probe_runner"] = self._probe_runner
        if self._probe_policy is not None:
            kwargs["probe_policy"] = self._probe_policy
        if self._client_factory is not None:
            kwargs["client_factory"] = self._client_factory
        service = McpDomainService(**kwargs)
        self._service = service
        family_lookup = ports.get("wire.error_family_resolver")

        # -- handlers: shape-checked params → service call → camelCase view --

        def mcp_list(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal")
            return service.list_definitions(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"))

        def mcp_get(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "definitionId")
            revision = params.get("revision")
            return service.get_definition(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                revision=None if revision is None else _version(revision, "revision"))

        def mcp_save_revision(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "definitionId", "definition",
                     "expectedVersion", "operationKey")
            source = params.get("source")
            return service.save_revision(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                definition=_object(params["definition"], "definition"),
                expected_version=_version(params["expectedVersion"]),
                operation_key=_bounded(params["operationKey"], "operationKey"),
                source=None if source is None else _bounded(source, "source"))

        def mcp_approve_revision(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "definitionId", "revision")
            return service.approve_revision(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                revision=_version(params["revision"], "revision"))

        def mcp_archive(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "definitionId")
            return service.archive(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                definition_id=_bounded(params["definitionId"], "definitionId"))

        def mcp_probe(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "definitionId", "revision")
            return service.probe(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                revision=_version(params["revision"], "revision"))

        def mcp_assign(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "scopeKind", "scopeId",
                     "definitionId", "decision", "expectedRowVersion", "operationKey")
            harness = params.get("harness")
            approved = params.get("approvedRevision")
            selection = params.get("toolSelection")
            return service.assign(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                scope_kind=_bounded(params["scopeKind"], "scopeKind"),
                scope_id=_bounded(params["scopeId"], "scopeId"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                decision=_bounded(params["decision"], "decision"),
                expected_row_version=_version(params["expectedRowVersion"],
                                              "expectedRowVersion"),
                operation_key=_bounded(params["operationKey"], "operationKey"),
                harness=None if harness is None else _bounded(harness, "harness"),
                approved_revision=None if approved is None else _version(
                    approved, "approvedRevision"),
                tool_selection=None if selection is None else _object(
                    selection, "toolSelection"))

        def mcp_unassign(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "scopeKind", "scopeId",
                     "definitionId", "expectedRowVersion", "operationKey")
            harness = params.get("harness")
            return service.unassign(
                server_scope=_bounded(params["serverScope"], "serverScope"),
                principal=_bounded(params["principal"], "principal"),
                scope_kind=_bounded(params["scopeKind"], "scopeKind"),
                scope_id=_bounded(params["scopeId"], "scopeId"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                expected_row_version=_version(params["expectedRowVersion"],
                                              "expectedRowVersion"),
                operation_key=_bounded(params["operationKey"], "operationKey"),
                harness=None if harness is None else _bounded(harness, "harness"))

        def mcp_resolve_preview(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal")
            return service.resolve_preview(**_preview_params(params))

        def mcp_inspect_connection(params: Mapping[str, Any]) -> dict:
            _require(params, "principal", "sessionRef", "runtimeGeneration", "leaseId")
            return service.inspect_connection(
                principal=_bounded(params["principal"], "principal"),
                session_ref=_bounded(params["sessionRef"], "sessionRef"),
                runtime_generation=_version(params["runtimeGeneration"],
                                            "runtimeGeneration"),
                lease_id=_bounded(params["leaseId"], "leaseId"))

        def mcp_list_tools(params: Mapping[str, Any]) -> dict:
            _require(params, "principal", "sessionRef", "runtimeGeneration",
                     "serverScope", "definitionId", "revision")
            return service.list_tools(
                principal=_bounded(params["principal"], "principal"),
                session_ref=_bounded(params["sessionRef"], "sessionRef"),
                runtime_generation=_version(params["runtimeGeneration"],
                                            "runtimeGeneration"),
                server_scope=_bounded(params["serverScope"], "serverScope"),
                definition_id=_bounded(params["definitionId"], "definitionId"),
                revision=_version(params["revision"], "revision"))

        def mcp_plan_for_submission(params: Mapping[str, Any]) -> dict:
            _require(params, "serverScope", "principal", "sessionRef",
                     "runtimeGeneration")
            args = _preview_params(params)
            expected = params.get("expectedRevision")
            permit = params.get("submissionPermit")
            return service.plan_for_submission(
                server_scope=args["server_scope"], principal=args["principal"],
                session_ref=_bounded(params["sessionRef"], "sessionRef"),
                runtime_generation=_version(params["runtimeGeneration"],
                                            "runtimeGeneration"),
                harness=args["harness"], project_id=args["project_id"],
                profile_revision=args["profile_revision"],
                target_session=args["target_session"],
                expected_revision=None if expected is None else _bounded(
                    expected, "expectedRevision"),
                submission_permit=None if permit is None else _bounded(
                    permit, "submissionPermit"))

        # The unwired-port refusals ride the same mapping path as the
        # domain's own McpErrors; a WireError from the shape primitives is
        # the contract answering and passes through untouched.
        def _guard(handler: Callable[[Mapping[str, Any]], Any]) -> Callable:
            def call(params: Mapping[str, Any]) -> Any:
                try:
                    return handler(params)
                except WireError:
                    raise
                except BaseException as refusal:  # noqa: BLE001 - typed by the domain
                    raise _mcp_refusal(refusal, family_lookup) from refusal
            return call

        def probe_availability() -> "tuple[bool, str | None]":
            # The hello answer only; dispatch stays open and refuses typed
            # (order 097's two-question rule).
            if service.probe_authority is None:
                return False, "PROBE_AUTHORITY_UNWIRED"
            return True, None

        def submission_availability() -> "tuple[bool, str | None]":
            # either submission port composed -> the row can answer; the
            # permit/expectedRevision preconditions still refuse typed at
            # dispatch (availability answers the hello question only)
            if (service.configuration_service is None
                    and service.submission_gate is None):
                return False, "MCP_SUBMISSION_GATE_UNWIRED"
            return True, None

        handlers: "dict[str, tuple[Callable, Callable[[], tuple[bool, str | None]] | None]]" = {
            "mcp.list": (mcp_list, None),
            "mcp.get": (mcp_get, None),
            "mcp.saveRevision": (mcp_save_revision, None),
            "mcp.approveRevision": (mcp_approve_revision, None),
            "mcp.archive": (mcp_archive, None),
            "mcp.probe": (mcp_probe, probe_availability),
            "mcp.assign": (mcp_assign, None),
            "mcp.unassign": (mcp_unassign, None),
            "mcp.resolvePreview": (mcp_resolve_preview, None),
            "mcp.inspectConnection": (mcp_inspect_connection, None),
            "mcp.listTools": (mcp_list_tools, None),
            "mcp.planForSubmission": (mcp_plan_for_submission, submission_availability),
        }
        methods = tuple(
            ServerMethodDescriptor(
                method_id=method_id,
                required_params=_PARAM_SHAPES[method_id][0],
                optional_params=_PARAM_SHAPES[method_id][1],
                handler=_guard(handlers[method_id][0]),
                owner=PLUGIN_ID,
                availability=handlers[method_id][1],
            )
            for method_id in _PARAM_SHAPES
        )

        def load_stores() -> None:
            # Startup work this domain owns: bind the store layout under the
            # data root (legacy-compatible: <root>/assets/mcp/<id>/<rev>/
            # server.json plus the domain's own index/assignment/managed
            # tables) and read each table once, so a corrupt layout refuses
            # at start, not at first request.
            service.load()

        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"asset.mcp.v2": service},
            start_hooks=(load_stores,),
            disposal=self._dispose,
            contributions=ContributionBatch((
                Contribution(
                    point_id=WIRE_ERROR_FAMILIES_POINT_ID,
                    api_version=WIRE_ERROR_FAMILIES_API_VERSION,
                    payload=MCP_ERROR_FAMILIES,
                ),
            )),
        )

    def _dispose(self) -> None:
        self._service = None


def _preview_params(params: Mapping[str, Any]) -> dict:
    """The shared optional target params of resolvePreview / planForSubmission."""

    def opt(name: str) -> Any:
        value = params.get(name)
        return None if value is None else _bounded(value, name)

    generation = params.get("runtimeGeneration")
    return {
        "server_scope": _bounded(params["serverScope"], "serverScope"),
        "principal": _bounded(params["principal"], "principal"),
        "harness": opt("harness"),
        "project_id": opt("projectId"),
        "profile_revision": opt("profileRevision"),
        "session_ref": opt("sessionRef"),
        "target_session": opt("targetSession"),
        "runtime_generation": None if generation is None else _version(
            generation, "runtimeGeneration"),
    }

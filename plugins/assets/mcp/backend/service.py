"""Q4/T09 service layer: the MCP domain service behind the ``mcp.*`` wire face.

One object, :class:`McpDomainService`, wraps the already-delivered domain
pieces (definition store, assignment store, resolve, probe, managed
lease/catalog/session manager, permission glue, secret glue) into the
operations ``docs/design/mcp/contracts.md`` §1 lists, with the §1 inputs and
outputs (scope, principal, definitionId, expectedVersion, operationKey →
version summaries). It raises the domain's own typed refusals
(:class:`backend.errors.McpError`); the wire projection lives in
``backend/plugin.py`` — this module never imports a transport.

Auth parameters are explicit (T09 dispatch): every operation names its
``principal`` as a plain argument. The host today has NO request-level
principal injection surface (the wire/1 transport authenticates the
connection with a bearer session token, but a handler receives only the
params mapping — no caller identity), so the plugin's handlers take
``principal`` from the request params as a caller-claimed value. That is a
registered gap for the integration request, not an authentication claim: the
service's principal checks are domain-internal isolation (assignment owner,
lease visibility, probe authorisation binding), never transport
authentication.

Fail-closed ports (contracts §1 "provider 缺席类型化拒绝", FR-09):

* ``probe_authority`` (probe permission, contracts §4) — absent → every
  probe refuses ``PERMISSION_AUTHORITY_ABSENT``; a probe never runs on an
  unauthorised call path;
* ``submission_gate`` (the Harness C4/C5 sole submission gate) — absent →
  ``plan_for_submission`` refuses ``APPLICATION_PORT_ABSENT``; there is no
  second gate this domain may substitute and no fake success. T013 adds the
  real port: when ``harness.configuration_service`` (the published
  ``ordessa_harness_api.ConfigurationService``) is composed it IS that gate
  — the plan needs a presented permit and an expected revision, drift and
  refusals come back typed through ``backend.native_binding`` and never
  re-drive the gate; the placeholder and the real port together are a
  second-gate conflict. Port absent → pre-T013 behaviour unchanged;
* ``credential_port`` — the fail-closed host adapter (``credentials`` +
  ``secret_store`` host facades, possibly both absent): any resolution
  request through an unwired layer raises ``SECRET_UNRESOLVED``
  (:mod:`backend.secret`), never a partial plan.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple

from .assignment import McpAssignment, McpAssignmentStore
from .definition import McpDefinition, McpRevision
from .definition_store import McpDefinitionStore
from .errors import (
    APPLICATION_PORT_ABSENT,
    AUTH_REQUIRED,
    EXPECTED_REVISION_REQUIRED,
    PERMISSION_REFUSED,
    SUBMISSION_GATE_AMBIGUOUS,
    SUBMISSION_PERMIT_REQUIRED,
    McpError,
)
from .managed.catalog import McpToolCatalog, McpToolCatalogStore, make_catalog_provider
from .managed.lease import LeaseCaller, McpLeaseStore
from .managed.session_manager import ManagedSessionManager
from .native_binding import (
    NATIVE_PLANNER_ABSENT, facet_payload_of, plan_view, refused_to_mcp_error,
    unknown_to_mcp_error, application_target, desired_fragment,
)
from .permissions import (
    PERMISSION_AUTHORITY_ABSENT,
    native_permission_postures,
    posture_view,
)
from .probe import probe_definition
from .probe_policy import DEFAULT_PROBE_POLICY, ProbePolicy
from .resolve import McpEffectiveSnapshot, resolve_preview
from .secret import (
    CredentialPort,
    LaunchPlan,
    host_credential_port,
    resolve_for_launch,
    snapshot_credential_bindings,
)

# -- this module's seam refusals (T014: registered in backend/errors.py, ------
# imported above and re-exported here; families declared in
# backend/plugin.MCP_ERROR_FAMILIES)
# * APPLICATION_PORT_ABSENT — an application port the composition does not
#   provide (contracts §1: "所有跨插件依赖用公开端口显式声明，provider
#   缺席类型化拒绝"); plan_for_submission is the only operation that needs
#   the Harness submission gate today.
# * SUBMISSION_PERMIT_REQUIRED (T013) — the sole submission permit is an
#   input of planForSubmission (contracts §1 row 6): without it no plan is
#   produced — and nothing is reconfigured or launched either way, this
#   domain never launches.
# * EXPECTED_REVISION_REQUIRED (T013) — the plan fences on the
#   caller-observed revision; without one the C4 ``expected_revision``
#   check has no baseline and the plan would be unconditional — typed
#   refusal instead.
# * SUBMISSION_GATE_AMBIGUOUS (T013) — the Harness C4 service IS the
#   submission gate; composing the placeholder gate alongside it would be a
#   second gate (contracts §1: 同一提交闸门).


class ProbeAuthority(Protocol):
    """Consumer port for the probe permission decision (contracts §1 probe
    row "明确 probe 权限", §4). The Q5 Permission domain is the intended
    provider; until it is composed, absence is the refusal, never a default
    allow."""

    def authorize_probe(self, *, principal: str, server_scope: str,
                        definition_id: str, revision: int) -> bool: ...


class SubmissionGate(Protocol):
    """Consumer port for the Harness C4/C5 sole submission gate (contracts
    §1 last row: same gate plan/apply/reconcile pass through). The gate
    answers the decision; this domain never re-derives it."""

    def plan_submission(self, *, principal: str, server_scope: str,
                        session_ref: str, runtime_generation: int,
                        snapshot_digest: str,
                        credential_references: Tuple[Mapping[str, Any], ...]) -> Mapping[str, Any]: ...


# -- version-summary / snapshot projections (camelCase, legacy asset_view habit) --


def definition_view(definition: McpDefinition) -> dict:
    return {
        "definitionId": definition.definition_id,
        "serverScope": definition.server_scope,
        "nativeName": definition.native_name,
        "transport": definition.transport,
        "archived": definition.archived,
        "latestRevision": definition.latest_revision,
    }


def revision_view(revision: McpRevision) -> dict:
    return {
        "definitionId": revision.definition_id,
        "revision": revision.revision,
        "digest": revision.canonical_digest,
        "shape": revision.canonical_shape,
        "source": revision.source,
        "createdAt": revision.created_at,
        "approval": ({"actor": revision.approval.actor,
                      "approvedAt": revision.approval.approved_at}
                     if revision.approval else None),
    }


def assignment_view(assignment: McpAssignment) -> dict:
    selection = assignment.tool_selection
    return {
        "scopeKind": assignment.scope_kind,
        "scopeId": assignment.scope_id,
        "harness": assignment.harness,
        "definitionId": assignment.definition_id,
        "decision": assignment.decision,
        "approvedRevision": assignment.approved_revision,
        "rowVersion": assignment.row_version,
        "updatedAt": assignment.updated_at,
        "toolSelection": ({"mode": selection.mode, "names": list(selection.names),
                           "catalogDigest": selection.catalog_digest}
                          if selection else None),
    }


def snapshot_view(snapshot: McpEffectiveSnapshot) -> dict:
    return {
        "targetSession": snapshot.target_session,
        "runtimeGeneration": snapshot.runtime_generation,
        "projectId": snapshot.project_id,
        "profileRevision": snapshot.profile_revision,
        "definitionRevisions": [
            {"definitionId": entry.get("definition_id"),
             "revision": entry.get("revision"),
             "canonicalDigest": entry.get("canonical_digest"),
             "canonicalShape": entry.get("canonical_shape")}
            for entry in snapshot.definition_revisions],
        "assignmentRevisions": [
            {"definitionId": entry.get("definition_id"),
             "scopeKind": entry.get("scope_kind"),
             "scopeId": entry.get("scope_id"),
             "harness": entry.get("harness"),
             "decision": entry.get("decision"),
             "rowVersion": entry.get("row_version")}
            for entry in snapshot.assignment_revisions],
        "credentialRefRevisions": [
            {"definitionId": entry.get("definition_id"),
             "revision": entry.get("revision"),
             "slot": entry.get("slot"),
             "credentialId": entry.get("credential_id")}
            for entry in snapshot.credential_ref_revisions],
        "allowedToolNames": list(snapshot.allowed_tool_names),
        "laneByDefinition": {key: dict(value)
                             for key, value in snapshot.lane_by_definition.items()},
        "needsRevalidation": list(snapshot.needs_revalidation),
        "snapshotDigest": snapshot.snapshot_digest,
        "submissionId": snapshot.submission_id,
    }


def catalog_view(catalog: McpToolCatalog) -> dict:
    return {
        "leaseId": catalog.lease_id,
        "definitionId": catalog.definition_id,
        "revision": catalog.revision,
        "observedAt": catalog.observed_at,
        "protocolVersion": catalog.protocol_version,
        "serverInfo": dict(catalog.server_info),
        "toolNames": list(catalog.tool_names),
        "toolSchemaDigests": {name: digest for name, digest
                              in catalog.tool_names_and_schema_digests},
        "catalogDigest": catalog.catalog_digest,
        "sourceEvidence": dict(catalog.source_evidence),
        "status": catalog.status,
    }


def _result_assignment_view(raw: Mapping[str, Any]) -> dict:
    """The assignment store's own result row (snake keys) → camel summary."""
    return {
        "scopeKind": raw["scope_kind"], "scopeId": raw["scope_id"],
        "harness": raw["harness"], "definitionId": raw["definition_id"],
        "decision": raw["decision"], "approvedRevision": raw.get("approved_revision"),
        "rowVersion": raw.get("row_version"),
    }


def _require_principal(principal: Any) -> str:
    if not isinstance(principal, str) or not principal:
        raise McpError(AUTH_REQUIRED, "every MCP operation names its calling principal")
    return principal


class McpDomainService:
    """The §1 operations over the domain stores, with explicit auth inputs."""

    def __init__(self, *, root: Any, probe_authority: Optional[ProbeAuthority] = None,
                 submission_gate: Optional[SubmissionGate] = None,
                 credential_port: Optional[CredentialPort] = None,
                 client_factory: Any = None,
                 probe_runner: Callable[..., Mapping[str, Any]] = probe_definition,
                 probe_policy: ProbePolicy = DEFAULT_PROBE_POLICY,
                 configuration_service: Optional[Any] = None,
                 native_planner: Optional[Callable[[McpEffectiveSnapshot, str], Any]] = None,
                 lane_by_definition: Optional[Mapping[str, str]] = None,
                 native_posture_facts: Optional[Mapping[str, Mapping[str, Any]]] = None) -> None:
        self.root = root
        self.definitions = McpDefinitionStore(root)
        self.assignments = McpAssignmentStore(root, self.definitions)
        self.leases = McpLeaseStore(root)
        self.catalogs = McpToolCatalogStore(root)
        self.sessions = ManagedSessionManager(
            definitions=self.definitions, leases=self.leases, catalogs=self.catalogs,
            client_factory=client_factory)
        self.probe_authority = probe_authority
        self.submission_gate = submission_gate
        #: T013: the REAL Harness C4 port (``ordessa_harness_api.
        #: ConfigurationService`` — the service's plan/apply/query/reconcile
        #: face over the composed configuration adapter). When composed it
        #: IS the submission gate; the placeholder ``submission_gate`` above
        #: must then stay absent (one gate, contracts §1). Absent keeps the
        #: pre-T013 behaviour byte-for-byte (APPLICATION_PORT_ABSENT or the
        #: placeholder gate answer).
        self.configuration_service = configuration_service
        #: composition seam: ``planner(snapshot, harness) -> NativeIntentSet``
        #: (product assembly wires it to ``adapters.{codex,claude}.compile``
        #: with the injected destination descriptors and the credential
        #: provenance attestation surface — ``backend`` may not import
        #: ``adapters``; the planner is how the two meet).
        self.native_planner = native_planner
        #: which definition ids run on the native lane (owner decision
        #: records; resolve.py defaults everything else to managed).
        self.lane_by_definition = dict(lane_by_definition or {})
        #: T012 posture seam (FR-09 / contracts §4): definition_id -> native
        #: permission fact record (``source``/``scope``/``policyRef``/
        #: ``provenance``) as the harness observation/declaration plane
        #: reports it. The product assembly wires it; absent, every native
        #: entry is labelled "unattributed" — the honest default under an
        #: absent Ordessa authority, never a fabricated policy. The records
        #: are DISPLAY facts: no gate reads them and they never lift the
        #: snapshot's enforcement downgrades (backend/permissions.py T012).
        self.native_posture_facts = dict(native_posture_facts or {})
        #: None keeps the fail-closed adapter: every resolution through it
        #: raises SECRET_UNRESOLVED (backend.secret G7 convention).
        self.credential_port = credential_port if credential_port is not None \
            else host_credential_port(credential_records=None, secret_store=None)
        self._probe_runner = probe_runner
        self._probe_policy = probe_policy
        self._catalog_provider = make_catalog_provider(self.catalogs)

    # -- lifecycle -----------------------------------------------------------

    def load(self) -> dict:
        """Store warm-up for the plugin's start hook: create the domain
        layout under the data root and read each table once."""
        from pathlib import Path

        Path(str(self.root)).mkdir(parents=True, exist_ok=True)
        definitions = self.definitions.list_definitions(server_scope="")
        assignments = self.assignments.list_for(server_scope="", principal="")
        leases = self.leases.active_leases()
        return {"definitions": len(definitions), "assignments": len(assignments),
                "activeLeases": len(leases)}

    # -- definitions (contracts §1 row 1) --------------------------------------

    def list_definitions(self, *, server_scope: str, principal: str) -> dict:
        _require_principal(principal)
        rows = self.definitions.list_definitions(server_scope=server_scope)
        return {"definitions": [definition_view(row) for row in rows],
                "nextCursor": None}

    def get_definition(self, *, server_scope: str, principal: str,
                       definition_id: str, revision: Optional[int] = None) -> dict:
        _require_principal(principal)
        definition = self.definitions.get_definition(
            server_scope=server_scope, definition_id=definition_id)
        view: dict = {"definition": definition_view(definition), "latestRevision": None}
        wanted = definition.latest_revision if revision is None else int(revision)
        if wanted >= 1:
            model = self.definitions.read_revision(
                server_scope=server_scope, definition_id=definition_id, revision=wanted)
            view["latestRevision"] = revision_view(model)
        return view

    def save_revision(self, *, server_scope: str, principal: str, definition_id: str,
                      definition: Mapping[str, Any], expected_version: int,
                      operation_key: str, source: Optional[str] = None) -> dict:
        """CAS save. Zero side effects: no probe, no spawn, no connection
        (the §1 save row; the store enforces it)."""
        _require_principal(principal)
        result = self.definitions.save_revision(
            server_scope=server_scope, definition_id=definition_id,
            definition=definition, expected_version=int(expected_version),
            operation_key=operation_key, source=source)
        model = self.definitions.read_revision(
            server_scope=server_scope, definition_id=definition_id,
            revision=int(result["revision"]))
        return {"definition": definition_view(
                    self.definitions.get_definition(
                        server_scope=server_scope, definition_id=definition_id)),
                "revision": revision_view(model), "replayed": bool(result["replayed"])}

    def approve_revision(self, *, server_scope: str, principal: str,
                         definition_id: str, revision: int) -> dict:
        """The approval record's actor IS the calling principal: approval is
        attributed, never self-declared by the payload."""
        _require_principal(principal)
        result = self.definitions.approve_revision(
            server_scope=server_scope, definition_id=definition_id,
            revision=int(revision), actor=principal)
        return {"definitionId": result["definition_id"], "revision": result["revision"],
                "approval": {"actor": result["approval"]["actor"],
                             "approvedAt": result["approval"]["approved_at"]}}

    def archive(self, *, server_scope: str, principal: str, definition_id: str) -> dict:
        _require_principal(principal)
        definition = self.definitions.archive_definition(
            server_scope=server_scope, definition_id=definition_id)
        return {"definition": definition_view(definition)}

    # -- probe (contracts §1 row 2) ---------------------------------------------

    def probe(self, *, server_scope: str, principal: str, definition_id: str,
              revision: int) -> dict:
        """Permission-gated, credential-less, bounded handshake probe.

        The authority answer is required BEFORE the revision is read or any
        transport runs; the probe itself never carries credentials and
        never claims a catalog (backend/probe.py invariants, kept here)."""
        _require_principal(principal)
        authority = self.probe_authority
        if authority is None:
            raise McpError(
                PERMISSION_AUTHORITY_ABSENT,
                "no probe authority is wired for this composition; a probe is an "
                "explicit permission action and never runs unauthorised (contracts §1/§4)")
        if not authority.authorize_probe(
                principal=principal, server_scope=server_scope,
                definition_id=definition_id, revision=int(revision)):
            raise McpError(
                PERMISSION_REFUSED,
                f"the probe authority refused probing {definition_id}#{revision} "
                "for this principal before any transport ran")
        model = self.definitions.read_revision(
            server_scope=server_scope, definition_id=definition_id,
            revision=int(revision))
        facts = self._probe_runner(model.canonical, policy=self._probe_policy)
        return {"definitionId": definition_id, "revision": int(revision),
                "probe": dict(facts)}

    # -- assignments (contracts §1 row 3) -----------------------------------------

    def assign(self, *, server_scope: str, principal: str, scope_kind: str,
               scope_id: str, definition_id: str, decision: str,
               expected_row_version: int, operation_key: str,
               harness: Optional[str] = None,
               approved_revision: Optional[int] = None,
               tool_selection: Optional[Mapping[str, Any]] = None) -> dict:
        """Enable requires an approved revision plus a tool selection frozen
        against THIS server's latest catalog observation for that revision —
        never a caller-supplied catalog (the observation is read from the
        catalog store below)."""
        _require_principal(principal)
        observed = None
        if decision == "enable" and approved_revision is not None:
            observation = self._catalog_provider(definition_id, int(approved_revision))
            if observation is not None:
                observed = {"catalogDigest": observation["catalogDigest"],
                            "toolNames": list(observation["toolNames"])}
        result = self.assignments.assign(
            server_scope=server_scope, principal=principal, scope_kind=scope_kind,
            scope_id=scope_id, harness=harness, definition_id=definition_id,
            decision=decision, approved_revision=approved_revision,
            tool_selection=tool_selection, observed_catalog=observed,
            expected_row_version=int(expected_row_version), operation_key=operation_key)
        return {"assignment": _result_assignment_view(result["assignment"]),
                "replayed": bool(result["replayed"])}

    def unassign(self, *, server_scope: str, principal: str, scope_kind: str,
                 scope_id: str, definition_id: str, expected_row_version: int,
                 operation_key: str, harness: Optional[str] = None) -> dict:
        """``inherit``: delete the row so resolution falls through."""
        _require_principal(principal)
        result = self.assignments.unassign(
            server_scope=server_scope, principal=principal, scope_kind=scope_kind,
            scope_id=scope_id, harness=harness, definition_id=definition_id,
            expected_row_version=int(expected_row_version), operation_key=operation_key)
        view = _result_assignment_view(result)
        view["removed"] = bool(result["removed"])
        return {"assignment": view, "replayed": bool(result["replayed"])}

    # -- resolution (contracts §1 row 4) -------------------------------------------

    def _preview_model(self, *, server_scope: str, principal: str,
                       harness: Optional[str] = None, project_id: Optional[str] = None,
                       profile_revision: Optional[str] = None,
                       session_ref: Optional[str] = None,
                       target_session: Optional[str] = None,
                       runtime_generation: Optional[int] = None,
                       lane_by_definition: Optional[Mapping[str, str]] = None) -> McpEffectiveSnapshot:
        return resolve_preview(
            server_scope=server_scope, principal=principal,
            assignments=self.assignments, definitions=self.definitions,
            harness=harness, project_id=project_id, profile_revision=profile_revision,
            session_ref=session_ref, target_session=target_session,
            runtime_generation=runtime_generation,
            catalog_provider=self._catalog_provider,
            lane_by_definition=(self.lane_by_definition if lane_by_definition is None
                                else lane_by_definition))

    def resolve_preview(self, *, server_scope: str, principal: str,
                        harness: Optional[str] = None, project_id: Optional[str] = None,
                        profile_revision: Optional[str] = None,
                        session_ref: Optional[str] = None,
                        target_session: Optional[str] = None,
                        runtime_generation: Optional[int] = None) -> dict:
        """Read-only effective snapshot preview: no connection, no model
        call, no native write (backend/resolve.py).

        T012: alongside the snapshot the preview exposes
        ``nativePermissionPostures`` — one honest display row per native
        lane entry of the snapshot (backend/permissions.py). The rows label
        what the harness-native mechanism is while the Ordessa authority is
        absent; they never authorize and never replace the snapshot's
        ``enforcement`` words."""
        _require_principal(principal)
        snapshot = self._preview_model(
            server_scope=server_scope, principal=principal, harness=harness,
            project_id=project_id, profile_revision=profile_revision,
            session_ref=session_ref, target_session=target_session,
            runtime_generation=runtime_generation)
        return {
            "snapshot": snapshot_view(snapshot),
            "nativePermissionPostures": [
                posture_view(posture) for posture in native_permission_postures(
                    snapshot, self.native_posture_facts)],
        }

    # -- managed connection reads (contracts §1 row 5) -------------------------------

    def _caller(self, *, principal: str, session_ref: str,
                runtime_generation: int) -> LeaseCaller:
        return LeaseCaller(principal=principal, session_ref=session_ref,
                           runtime_generation=int(runtime_generation))

    def inspect_connection(self, *, principal: str, session_ref: str,
                           runtime_generation: int, lease_id: str) -> dict:
        _require_principal(principal)
        return {"connection": self.sessions.inspect_connection(
            caller=self._caller(principal=principal, session_ref=session_ref,
                                runtime_generation=runtime_generation),
            lease_id=lease_id)}

    def list_tools(self, *, principal: str, session_ref: str, runtime_generation: int,
                   server_scope: str, definition_id: str, revision: int) -> dict:
        """Live-lease catalog facts only; a stored definition entry is never
        dressed up as a connection (the manager raises MCP_CATALOG_MISSING)."""
        _require_principal(principal)
        found = self.sessions.list_tools_for_definition(
            caller=self._caller(principal=principal, session_ref=session_ref,
                                runtime_generation=runtime_generation),
            server_scope=server_scope, definition_id=definition_id,
            revision=int(revision))
        return {"leaseId": found["leaseId"], "catalog": catalog_view(found["catalog"])}

    # -- submission gate (contracts §1 row 6; planned until Harness C4/C5) -----------

    def plan_for_submission(self, *, server_scope: str, principal: str,
                            session_ref: str, runtime_generation: int,
                            harness: Optional[str] = None,
                            project_id: Optional[str] = None,
                            profile_revision: Optional[str] = None,
                            target_session: Optional[str] = None,
                            expected_revision: Optional[str] = None,
                            submission_permit: Optional[str] = None) -> dict:
        """Freeze the snapshot, bind its credential references at plan time,
        re-resolve the batch fail-closed, and hand the plan to the ONE
        submission gate the Harness owns.

        Two compositions, one gate (contracts §1 row 6):

        * **real C4 port** (``harness.configuration_service`` composed —
          T013): the permit is a required input — without it NOTHING is
          planned, reconfigured or launched (``SUBMISSION_PERMIT_REQUIRED``);
          ``expected_revision`` fences the plan (drift answers the C4
          ``STALE_PLAN`` refusal as ``MCP_CAS_CONFLICT``); the native
          complete-set facet payload is compiled through the composition's
          planner and submitted as one ``DesiredFragment`` through
          ``ConfigurationService.plan``. A ``Refused`` becomes the typed
          refusal it names; an ``Unknown`` keeps reconcile-only semantics
          (:func:`backend.native_binding.unknown_to_mcp_error`) — this
          domain never launches. The permit's verification and spend stay
          with the harness ``apply`` (its ``PermitVerifier`` port); Q4 only
          checks presence and never re-derives the decision;
        * **placeholder / absent** (pre-T013 behaviour, unchanged): no gate
          composed at all -> ``APPLICATION_PORT_ABSENT`` (never a second
          gate, never a success); the placeholder ``SubmissionGate`` port
          answers as before. Composing BOTH the placeholder and the real
          port is the second gate contracts §1 forbids -> typed refusal.

        The credential layers are the host's two (``credentials`` records +
        platform ``secret_store``); either absent resolves to
        ``SECRET_UNRESOLVED`` and the whole plan refuses — plaintext never
        leaves :mod:`backend.secret` and nothing here serialises it."""
        _require_principal(principal)
        real_gate = self.configuration_service
        if real_gate is None:
            return self._plan_for_submission_legacy(
                server_scope=server_scope, principal=principal,
                session_ref=session_ref, runtime_generation=runtime_generation,
                harness=harness, project_id=project_id,
                profile_revision=profile_revision, target_session=target_session)
        if self.submission_gate is not None:
            raise McpError(
                SUBMISSION_GATE_AMBIGUOUS,
                "both the placeholder submission gate and the real Harness C4 "
                "port are composed: plan/apply/reconcile pass through exactly "
                "one submission gate (contracts §1)")
        if not isinstance(submission_permit, str) or not submission_permit.strip():
            raise McpError(
                SUBMISSION_PERMIT_REQUIRED,
                "no submission permit presented: without the permit of the sole "
                "gate nothing is planned, reconfigured or launched (contracts §1 "
                "row 6)")
        if not isinstance(expected_revision, str) or not expected_revision.strip():
            raise McpError(
                EXPECTED_REVISION_REQUIRED,
                "the C4 plan fences on the caller-observed expectedRevision; an "
                "unfenced plan would silently overwrite a concurrent change")
        if self.native_planner is None:
            raise McpError(
                NATIVE_PLANNER_ABSENT,
                "the composition wired the C4 port but no native planner (the "
                "adapters.compile seam with injected destination descriptors and "
                "the credential provenance surface); the planning port is absent "
                "just as the gate would be")
        if not isinstance(harness, str) or not harness.strip():
            raise McpError(
                "MCP_NATIVE_TARGET_UNSUPPORTED",
                "the real submission port needs the harness brand named for the "
                "plan (the native lane owner decides per brand)")
        preview = self._preview_model(
            server_scope=server_scope, principal=principal, harness=harness,
            project_id=project_id, profile_revision=profile_revision,
            session_ref=session_ref, target_session=target_session,
            runtime_generation=runtime_generation)
        resolved = self._freeze_credentials(preview, principal, session_ref)
        intent_set = self.native_planner(preview, harness)
        payload = facet_payload_of(intent_set)
        fragment = desired_fragment(
            payload, source_revision=preview.snapshot_digest,
            business_ref=f"mcp-snapshot:{preview.snapshot_digest}")
        target = application_target(
            server_scope=server_scope, session_ref=session_ref,
            target_session=target_session, harness=harness,
            runtime_generation=int(runtime_generation))
        result = real_gate.plan(target, (fragment,), expected_revision)
        # PlanResult = Plan | Refused; Unknown is accepted defensively with
        # the reconcile-only semantics (harness RuntimeUnknown/Unknown: the
        # next action is query/reconcile, never a re-plan or launch here).
        if getattr(result, "kind", None) == "refused":
            raise refused_to_mcp_error(result)
        if getattr(result, "kind", None) == "unknown":
            raise unknown_to_mcp_error(result)
        view = plan_view(result)
        view["snapshotDigest"] = preview.snapshot_digest
        view["planDigest"] = intent_set.plan_digest
        return {"submission": view,
                "snapshotDigest": preview.snapshot_digest,
                "credentialReferences": [dict(record) for record in resolved.references()]}

    def _plan_for_submission_legacy(self, *, server_scope: str, principal: str,
                                    session_ref: str, runtime_generation: int,
                                    harness: Optional[str], project_id: Optional[str],
                                    profile_revision: Optional[str],
                                    target_session: Optional[str]) -> dict:
        """Pre-T013 flow, unchanged: no gate composed -> APPLICATION_PORT_ABSENT;
        the placeholder gate answers the plan and this domain hands over."""
        gate = self.submission_gate
        if gate is None:
            raise McpError(
                APPLICATION_PORT_ABSENT,
                "the Harness submission gate (C4/C5) is not composed for this "
                "Server; plan/apply/reconcile share that one gate and this "
                "domain never substitutes a second one (contracts §1)")
        preview = self._preview_model(
            server_scope=server_scope, principal=principal, harness=harness,
            project_id=project_id, profile_revision=profile_revision,
            session_ref=session_ref, target_session=target_session,
            runtime_generation=runtime_generation)
        resolved = self._freeze_credentials(preview, principal, session_ref)
        submission = gate.plan_submission(
            principal=principal, server_scope=server_scope, session_ref=session_ref,
            runtime_generation=int(runtime_generation),
            snapshot_digest=preview.snapshot_digest,
            credential_references=resolved.references())
        return {"submission": dict(submission),
                "snapshotDigest": preview.snapshot_digest,
                "credentialReferences": [dict(record) for record in resolved.references()]}

    def _freeze_credentials(self, preview: McpEffectiveSnapshot, principal: str,
                            session_ref: str):
        """Shared credential freeze of both submission paths: read each
        bound credential once (revision identity only; an unwired layer
        raises SECRET_UNRESOLVED here — the fail-closed is the adapter's,
        not a local default), bind the snapshot slots, and re-resolve the
        whole batch fail-closed. Plaintext never leaves this call: only the
        ref-only :meth:`ResolvedSecrets.references` view continues onward."""
        port = self.credential_port
        now = time.time()
        revisions_by_credential: dict = {}
        for entry in preview.credential_ref_revisions:
            credential_id = entry["credential_id"]
            if credential_id in revisions_by_credential:
                continue
            _, revision = port.read(credential_id)
            revisions_by_credential[credential_id] = str(revision)
        bindings = snapshot_credential_bindings(preview, revisions_by_credential)
        plan = LaunchPlan(principal=principal, bindings=bindings,
                          session_ref=session_ref)
        return resolve_for_launch(plan, port, now)

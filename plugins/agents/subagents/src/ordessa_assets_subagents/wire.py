"""The `assets.subagents.*` wire face: §C1's service surface, mapped and no wider.

One place turns a wire/1 request into a `DefinitionService` call. The mapping
adds exactly three facts the transport cannot get wrong:

1. **Identity is attested, never claimed** (§C1 "服务鉴权上下文给 principal，
   客户端不可自报"). A handler reads the principal, the server scope and the
   project/Profile binding from the composed request context
   (`CONTEXT_PORT`, `assets.subagents.context@1`) and *refuses* a request whose
   params name an identity at all — it does not strip a forged key and carry on
   (that would leave every other field trusting the client). The default
   context, `DeploymentAttestation`, attests exactly one principal for the whole
   data root and binds no project or Profile, so a client can neither choose
   whose definitions it reads nor claim an ownership it was never granted
   (G07 "客户端伪 projectId", `scopes.AuthorizationContext.require_project`).
2. **Every mutation carries `expectedRowVersion` + `operationKey`** (§C1) and a
   missing one is a typed refusal *before* the service is reached, so no
   mutation can lean on a default row version.
3. **A readiness claim is only made for what this plugin can back.** Reads and
   content CRUD are ready with no authority wired. `resolvePreview` is declared
   `supported: False` with a named reason and its handler refuses, because the
   assignment source and the pre-effect ceiling authority are not composed
   (`api-requests.md` SR-2/SR-6, rollout R07) — an absent seam is a refusal
   naming itself, never a fabricated `EffectiveSet`. §C1's `approveAssignmentUpdate`
   and `inspectNative` are therefore **not registered at all**: advertising them
   would advertise a surface nothing in this composition can answer.

A refusal keeps the §C5 code and the item-level reason (`details.internalCode`,
`details.item`, `details.detail`) and converges onto the wire/1 family set; the
code never becomes a silent success and an unknown outcome
(`OPERATION_UNKNOWN`, `LOAD_UNVERIFIED`) answers `OUTCOME_UNKNOWN` so the caller
can query it. `DomainError` carries no rejected value, so nothing here can echo
a credential back.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from server_plugin_api import (
    ServerMethodDescriptor,
    WireError,
    bounded as _bounded,
    require as _require,
    version as _version,
)

from . import decoder, dto, errors, limits, scopes
from .digest import bytes_digest, revision_digest
from .permissions_seam import AUTHORIZER_PORT_NAME
from .service import DefinitionService

#: The optional request-context port (§C1's authentication context). The host
#: or the domain that owns identity provides it through this plugin's declared
#: `requires`; nothing here reaches for a process-global locator, which
#: `contracts.md` forbids. Expected shape (`SubagentRequestContext` below):
#: `authorization()`, `verify_principal()`, `permission_ceiling()`.
CONTEXT_PORT = "assets.subagents.context@1"

#: The optional approved import root (`Path` or a zero-arg callable returning
#: one). Absent, the plugin's own directory under the data root is used — a
#: server-owned location, never a client-named path (§C1).
IMPORT_ROOT_PORT = "assets.subagents.import_root@1"

#: The service surface other domains (Profile facet, Chat, Settings) consume so
#: the resolution/ownership facts stay stated once (§C1 "供 Profile 与 Chat 使用
#: 同一个服务", §C2).
SERVICE_PORT = "assets.subagents.service@1"

#: The pre-effect ceiling authority this domain would defer to. Named in the
#: refusal only: `permissions.authorizer@1` answers *execution* adjudication
#: (`evaluate`/`reconcile`), not `verify_principal`/`permission_ceiling`, so it
#: cannot be plugged into `DefinitionService.authority` as it stands — see the
#: report's seam note. The string is the seam's own documented default, so this
#: face never keeps a second copy of it (§SR-15 option 3).
CEILING_AUTHORITY_PORT = AUTHORIZER_PORT_NAME

#: The authorizer-seam wiring the **product composition root** must inject for
#: this face to speak of a live authority (§SR-13b row 4 / §SR-15 option 3: Q5's
#: provider package is not importable from here, so the port name and the
#: authority's conflict types arrive as inputs, exactly like
#: `apply.PRODUCTION_COLLABORATORS`). Each entry is a named, machine-checkable
#: collaborator: `SubagentsWire.missing_production_collaborators()` reports the
#: ones the deployment did not supply, and nothing here substitutes a stub or a
#: permissive default for a missing one.
AUTHORIZER_COLLABORATORS: tuple[tuple[str, str], ...] = (
    ("authorizer_port_name",
     "the port name the composition adjudicates against (absent: the seam states "
     f"the documented default '{AUTHORIZER_PORT_NAME}' for wording only and "
     "resolves nothing by it)"),
    ("authorizer_conflict_types",
     "the authority's conflict types, raised and returned; without them every "
     "conflict the authority reports is unrecognised and refuses as "
     "OPERATION_UNKNOWN (fail-closed, never a silent 'no objection')"),
)


def missing_authorizer_collaborators(
    *, port_name: Any = None, conflict_types: Any = None,
) -> tuple[str, ...]:
    """The authorizer wiring this deployment did not inject — the same report
    shape as `apply.missing_production_collaborators()`, so a reviewer can check
    the seam from the outside instead of trusting prose. An empty tuple means
    the composition supplied both, not that a default stood in for either."""
    supplied = {
        "authorizer_port_name": isinstance(port_name, str) and bool(port_name.strip()),
        "authorizer_conflict_types": bool(tuple(conflict_types or ())),
    }
    return tuple(name for name, _ in AUTHORIZER_COLLABORATORS if not supplied[name])


def authorizer_gap_detail(gaps: Sequence[str]) -> str:
    """The refusal wording that names each missing collaborator and its reason."""
    reasons = dict(AUTHORIZER_COLLABORATORS)
    return "; ".join(f"{gap} is not injected ({reasons[gap]})" for gap in gaps)

#: The assignment source `resolvePreview` needs (the T04/T10 layer: assignment
#: rows plus their approval authority). This plugin owns no assignment store.
ASSIGNMENT_SOURCE_PORT = "assets.subagents.assignments@1"

#: Params that name *who is calling* or *whose data this is*. A request carries
#: none of them; one that does is refused (the values are never read, only the
#: key names are reported).
SELF_REPORTED_IDENTITY_KEYS: frozenset[str] = frozenset({
    "principal", "principalId", "approvedBy", "approvedByPrincipal", "actor",
    "caller", "userId", "user", "sub", "serverScope", "serverScopeId",
    "projectId", "project", "profileId", "profile", "sessionRef", "sessionId",
    "source", "sourceApproval", "approval",
})

#: Compared case-insensitively: a forged identity key wearing another spelling
#: is still a forged identity key.
_IDENTITY_KEY_MATCH: frozenset[str] = frozenset(
    key.lower() for key in SELF_REPORTED_IDENTITY_KEYS
)

#: §C5 code -> wire/1 family. The twelve families are the contract's closed set;
#: a code missing here answers `UNAVAILABLE` (the documented fall-through),
#: which is the honest statement of "this face has no family for that refusal".
C5_ERROR_FAMILIES: Mapping[str, str] = {
    errors.DEFINITION_INVALID: "INVALID_REQUEST",
    errors.REVISION_STALE: "CONFLICT_VERSION",
    errors.ASSIGNMENT_CONFLICT: "CONFLICT_REQUEST",
    errors.REFERENCE_UNRESOLVED: "CONFLICT_REFERENCE",
    errors.PERMISSION_EXCEEDS_CEILING: "FORBIDDEN",
    errors.NATIVE_VERSION_UNKNOWN: "CAPABILITY_UNSUPPORTED",
    errors.NATIVE_ENTRY_UNAVAILABLE: "CAPABILITY_UNSUPPORTED",
    errors.NATIVE_NAME_CONFLICT: "CONFLICT_REFERENCE",
    errors.NATIVE_DISCOVERY_UNCONTROLLED: "FORBIDDEN",
    errors.ADAPTER_MISSING: "CAPABILITY_UNSUPPORTED",
    errors.TARGET_CONFLICT: "CONFLICT_REFERENCE",
    errors.LOAD_UNVERIFIED: "OUTCOME_UNKNOWN",
    errors.OPERATION_UNKNOWN: "OUTCOME_UNKNOWN",
    errors.PROVIDER_BUSY: "CONFLICT_REQUEST",
}

#: Refusals whose outcome a caller may legitimately re-query or replay.
RETRYABLE_CODES: frozenset[str] = frozenset({
    errors.OPERATION_UNKNOWN, errors.LOAD_UNVERIFIED, errors.PROVIDER_BUSY,
})

#: The digest placeholder the content digest is filled in from (the domain's own
#: `_candidate_revision` shape: a provisional revision, then its canonical
#: digest over the real content).
_PLACEHOLDER = "sha256:" + "0" * 64

#: The one readiness reason for the surface that cannot be backed today.
RESOLVE_PREVIEW_UNWIRED = "RESOLVE_PREVIEW_UNWIRED"
#: And the one for an import location this deployment cannot approve (§C1: no
#: arbitrary host path, never a user HOME tree).
IMPORT_ROOT_UNAPPROVED = "IMPORT_ROOT_HOME_BOUND"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _home() -> Path:
    """Indirection so the HOME-bound import root verdict stays testable."""
    return Path.home()


def _token(value: str) -> str:
    """An identifier-safe instance token, or the deployment's own label."""
    text = (value or "").strip()
    if not text or len(text) > limits.MAX_DEFINITION_ID_CHARS:
        return "local"
    return text if limits._ID_RE.match(text) else "local"


def _under(home: Path, target: Path) -> bool:
    try:
        target.relative_to(home)
    except ValueError:
        return False
    return True


class DeploymentAttestation:
    """The server's own attestation while no `CONTEXT_PORT` is composed.

    It states three facts and no more: the caller is whoever operates this data
    root (`local:<instance>`), the data belongs to this server
    (`server:<instance>`), and nothing is granted — an empty ceiling, no
    verified project. Every one of them is *narrower* than an injected context
    could be, so replacing this default with a real authority only ever widens
    what the domain accepts, never the other way round.
    """

    #: False for the default: this object is not the pre-effect authority, so a
    #: permission-bearing definition stays refused.
    grants_permissions = False

    def __init__(self, authorization: scopes.AuthorizationContext) -> None:
        self._authorization = authorization

    @classmethod
    def for_instance(cls, instance_id: str = "") -> "DeploymentAttestation":
        token = _token(instance_id)
        return cls(scopes.AuthorizationContext.issued_by_service(
            scopes.Principal(f"local:{token}"),
            scopes.ServerScope(f"server:{token}"),
        ))

    def authorization(self) -> scopes.AuthorizationContext:
        return self._authorization

    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        return (
            principal == self._authorization.principal.id
            and server_scope == self._authorization.server_scope.id
        )

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset[str]:
        return frozenset()


class SubagentsWire:
    """The handlers, their shapes and their honest readiness claims."""

    def __init__(
        self,
        *,
        service: DefinitionService,
        attestation: Any,
        import_root: Path | str,
        ceiling_authority_wired: bool = False,
        owner: str,
        authorizer_port_name: str | None = None,
        authorizer_conflict_types: Sequence[type[BaseException]] = (),
    ) -> None:
        self._service = service
        self._attestation = attestation
        self._import_root = Path(import_root)
        self._ceiling_authority_wired = bool(ceiling_authority_wired)
        self._owner = owner
        #: The two authorizer wiring facts the composition root injects
        #: (`AUTHORIZER_COLLABORATORS`). Stored verbatim: an absent port name
        #: stays absent here — the seam's documented default is wording, and a
        #: wire face that quietly claimed a name the host never gave would read
        #: as a live port. `authorizer_conflict_types` defaults to empty, which
        #: the seam resolves as fail-closed (`OPERATION_UNKNOWN`).
        self.authorizer_port_name = authorizer_port_name
        self.authorizer_conflict_types = tuple(authorizer_conflict_types or ())

    def missing_production_collaborators(self) -> tuple[str, ...]:
        """Which authorizer-seam wiring this deployment did not supply.

        The same report the apply coordinator gives
        (`apply.missing_production_collaborators`): a named gap, so a reviewer
        or a health check can see that the authority is not wired instead of
        being told it is.
        """
        return missing_authorizer_collaborators(
            port_name=self.authorizer_port_name,
            conflict_types=self.authorizer_conflict_types,
        )

    def seam_wiring(self) -> "dict[str, Any]":
        """The values a composition passes straight into `PermissionsSeam`
        (`port_name=`, `conflict_types=`) — nothing more, nothing defaulted."""
        return {
            "port_name": self.authorizer_port_name,
            "conflict_types": self.authorizer_conflict_types,
        }

    # -- declaration --------------------------------------------------------

    def descriptors(self) -> tuple[ServerMethodDescriptor, ...]:
        ready = self._ready
        import_ready = self._import_root_ready
        unavailable = self._resolve_preview_unavailable
        return (
            self._method(
                "assets.subagents.create",
                required={"requestId", "slug", "displayName", "description",
                          "originScope", "originOwner", "operationKey",
                          "expectedRowVersion"},
                optional={"definitionId"},
                handler=self.create, availability=ready,
            ),
            self._method(
                "assets.subagents.get",
                required={"requestId", "definitionId"}, optional={"revision"},
                handler=self.get, availability=ready,
            ),
            self._method(
                "assets.subagents.list",
                required={"requestId"}, optional={"includeArchived"},
                handler=self.list_definitions, availability=ready,
            ),
            self._method(
                "assets.subagents.saveRevision",
                required={"requestId", "definitionId", "revision", "roleBody",
                          "operationKey", "expectedRowVersion"},
                optional={"modelRef", "toolRefs", "mcpRefs", "skillRefs",
                          "requestedPermission", "isolation", "limits",
                          "retainedNativeFields"},
                handler=self.save_revision, availability=ready,
            ),
            self._method(
                "assets.subagents.archive",
                required={"requestId", "definitionId", "operationKey",
                          "expectedRowVersion"},
                optional=set(), handler=self.archive, availability=ready,
            ),
            self._method(
                "assets.subagents.restore",
                required={"requestId", "definitionId", "operationKey",
                          "expectedRowVersion"},
                optional=set(), handler=self.restore, availability=ready,
            ),
            self._method(
                "assets.subagents.clone",
                required={"requestId", "definitionId", "operationKey",
                          "expectedRowVersion"},
                optional={"slug", "displayName"},
                handler=self.clone, availability=ready,
            ),
            self._method(
                "assets.subagents.importPreview",
                required={"requestId", "path"}, optional=set(),
                handler=self.import_preview, availability=import_ready,
            ),
            self._method(
                "assets.subagents.approveImport",
                required={"requestId", "previewId", "selects", "operationKey",
                          "expectedRowVersion"},
                optional={"origin", "originRef", "originScope", "originOwner"},
                handler=self.approve_import, availability=import_ready,
            ),
            self._method(
                "assets.subagents.resolvePreview",
                required={"requestId", "target"}, optional={"expectedRevisions"},
                handler=self.resolve_preview, availability=unavailable,
            ),
        )

    def _method(self, method_id: str, *, required: Sequence[str],
                optional: Sequence[str], handler: Callable,
                availability: Callable[[], "tuple[bool, str | None]"],
                ) -> ServerMethodDescriptor:
        return ServerMethodDescriptor(
            method_id=method_id,
            required_params=frozenset(required),
            optional_params=frozenset(optional),
            handler=handler, owner=self._owner, availability=availability,
        )

    # -- readiness ----------------------------------------------------------

    def _ready(self) -> "tuple[bool, str | None]":
        return True, None

    def _resolve_preview_unavailable(self) -> "tuple[bool, str | None]":
        return False, RESOLVE_PREVIEW_UNWIRED

    def import_root(self) -> Path:
        return self._import_root

    def _import_root_ready(self) -> "tuple[bool, str | None]":
        """`DefinitionService.import_preview` refuses a root at or under the
        user's HOME: with the default location inside the user's data root that
        refusal is certain, so hello says so instead of advertising a method
        this deployment cannot serve."""
        home = _home().resolve(strict=False)
        resolved = self._import_root.resolve(strict=False)
        if resolved == home or _under(home, resolved):
            return False, IMPORT_ROOT_UNAPPROVED
        return True, None

    # -- the three wire guarantees ------------------------------------------

    def _refusal(self, exc: errors.DomainError) -> WireError:
        details: dict[str, Any] = {"internalCode": exc.code}
        if exc.item_id is not None:
            details["item"] = exc.item_id
        if exc.detail is not None:
            details["detail"] = exc.detail
        details["retryable"] = exc.code in RETRYABLE_CODES
        message = f"{exc.code}: {exc.detail}" if exc.detail else exc.code
        return WireError(C5_ERROR_FAMILIES.get(exc.code, "UNAVAILABLE"),
                         message, details)

    def _refuse(self, code: str, *, item: str, detail: str) -> "WireError":
        return self._refusal(errors.refused(code, item_id=item, detail=detail))

    def _reject_self_reported_identity(self, params: Mapping[str, Any]) -> None:
        """Run first, before any other validation: the request that forges an
        identity is refused for forging it, not quietly re-labelled."""
        offered = sorted(
            str(key) for key in params if str(key).lower() in _IDENTITY_KEY_MATCH
        )
        if offered:
            raise self._refuse(
                errors.PERMISSION_EXCEEDS_CEILING, item=offered[0],
                detail="identity, scope and ownership are attested by the server; "
                       f"a request carries none of them (§C1): {', '.join(offered)}",
            )

    def _mutation_keys(self, params: Mapping[str, Any]) -> "tuple[str, int]":
        """§C1: a mutation without both concurrency facts is refused, never
        defaulted — a missing `operationKey` cannot turn into a second write and
        a missing `expectedRowVersion` cannot turn into an unconditional one."""
        missing = [name for name in ("operationKey", "expectedRowVersion")
                   if name not in params]
        if missing:
            raise self._refuse(
                errors.DEFINITION_INVALID, item=missing[0],
                detail=f"{missing[0]} is required for every mutation (§C1)",
            )
        operation_key = _bounded(params["operationKey"], "operationKey",
                                 limit=limits.MAX_OPERATION_KEY_CHARS)
        return operation_key, _version(params["expectedRowVersion"],
                                       "expectedRowVersion")

    def _context(self) -> scopes.AuthorizationContext:
        authorization = self._attestation.authorization()
        if not isinstance(authorization, scopes.AuthorizationContext):
            raise self._refuse(
                errors.PERMISSION_EXCEEDS_CEILING, item="principal",
                detail=f"the composed {CONTEXT_PORT} answers no server-issued "
                       "AuthorizationContext",
            )
        return authorization

    def _require_origin_binding(self, authorization: scopes.AuthorizationContext,
                                *, origin_scope: Any, origin_owner: Any) -> None:
        """A public definition needs no binding; a project- or Profile-owned one
        needs the server to have attested exactly that binding (G07)."""
        try:
            self._check_origin_binding(
                authorization, origin_scope=origin_scope, origin_owner=origin_owner,
            )
        except errors.DomainError as exc:
            raise self._refusal(exc) from exc

    def _check_origin_binding(self, authorization: scopes.AuthorizationContext,
                              *, origin_scope: Any, origin_owner: Any) -> None:
        scope = _bounded(origin_scope, "originScope")
        owner = _bounded(origin_owner, "originOwner")
        if scope == "public":
            return
        if scope == "project":
            # The domain's own gate for "客户端伪 projectId": a claim the server
            # never verified is refused before any lookup, not narrowed to a
            # scope the caller did not ask for.
            authorization.require_project(owner)
            return
        if scope == "profile":
            raise errors.refused(
                errors.PERMISSION_EXCEEDS_CEILING, item_id="originOwner",
                detail=f"a profile-owned definition needs a server-verified Profile "
                       "binding; the composed request context answers none "
                       f"({CONTEXT_PORT}) and the Profile facet owns it (T10, §C2)",
            )
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="originScope",
            detail=f"originScope is one of {'/'.join(dto.ORIGIN_SCOPES)}",
        )

    def _refuse_unadjudicated_permission(self, requested_permission: Any) -> None:
        """A declared permission is a pre-effect claim; with no ceiling authority
        composed it is refused here, naming the missing seam, before the service
        reaches the store (SR-6, R07). The named gaps are the collaborators this
        face did not receive, not an invented port or a stub authority."""
        if requested_permission is None or self._ceiling_authority_wired:
            return
        gaps = self.missing_production_collaborators()
        detail = (f"no ceiling authority is composed ({CONTEXT_PORT}, "
                  f"{CEILING_AUTHORITY_PORT}); a definition that declares a "
                  "permission is refused before it is stored")
        if gaps:
            detail += f". Missing production collaborators: {authorizer_gap_detail(gaps)}"
        raise self._refuse(
            errors.PERMISSION_EXCEEDS_CEILING, item="requestedPermission",
            detail=detail,
        )

    # -- reads --------------------------------------------------------------

    def get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "definitionId")
        definition_id = _bounded(params["definitionId"], "definitionId")
        return self._guarded(
            lambda: self._get(definition_id, params.get("revision"))
        )

    def _get(self, definition_id: str, revision: Any) -> dict[str, Any]:
        row = self._service.get_definition(definition_id)
        answer: dict[str, Any] = {"definition": definition_record(row)}
        if revision is None:
            if row.latest_revision >= 1:
                answer["revision"] = revision_record(
                    self._service.get_revision(definition_id, row.latest_revision)
                )
            return answer
        number = _version(revision, "revision")
        answer["revision"] = revision_record(
            self._service.get_revision(definition_id, number)
        )
        return answer

    def list_definitions(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId")
        include = params.get("includeArchived", False)
        if not isinstance(include, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        rows = self._guarded(
            lambda: self._service.list_definitions(include_archived=include)
        )
        return {"items": [definition_record(row) for row in rows],
                "nextCursor": None}

    # -- content CRUD -------------------------------------------------------

    def create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "slug", "displayName", "description",
                 "originScope", "originOwner")
        operation_key, expected = self._mutation_keys(params)
        authorization = self._context()
        self._require_origin_binding(
            authorization, origin_scope=params["originScope"],
            origin_owner=params["originOwner"],
        )
        slug = _bounded(params["slug"], "slug")
        display_name = _bounded(params["displayName"], "displayName")
        description = _bounded(params["description"], "description")
        definition_id = params.get("definitionId")
        row = self._guarded(lambda: self._service.create_definition(
            authorization.principal.id,
            server_scope=authorization.server_scope.id,
            slug=slug, display_name=display_name, description=description,
            origin_scope=params["originScope"], origin_owner=params["originOwner"],
            operation_key=operation_key, expected_row_version=expected,
            **({"definition_id": _bounded(definition_id, "definitionId")}
               if definition_id is not None else {}),
        ))
        return {"definition": definition_record(row)}

    def save_revision(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "definitionId", "revision", "roleBody")
        operation_key, expected = self._mutation_keys(params)
        authorization = self._context()
        self._refuse_unadjudicated_permission(params.get("requestedPermission"))
        definition_id = _bounded(params["definitionId"], "definitionId")
        number = _version(params["revision"], "revision")
        body = _bounded(params["roleBody"], "roleBody",
                        limit=limits.MAX_ROLE_BODY_BYTES)
        revision = self._revision_dto(
            authorization=authorization, definition_id=definition_id, number=number,
            body=body, params=params,
        )
        stored = self._guarded(lambda: self._service.save_revision(
            authorization.principal.id, revision,
            server_scope=authorization.server_scope.id,
            operation_key=operation_key, expected_row_version=expected,
        ))
        row = self._guarded(lambda: self._service.get_definition(definition_id))
        return {"revision": revision_record(stored),
                "definition": definition_record(row)}

    def archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return self._set_archived("archive", params)

    def restore(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return self._set_archived("restore", params)

    def _set_archived(self, action: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "definitionId")
        operation_key, expected = self._mutation_keys(params)
        authorization = self._context()
        definition_id = _bounded(params["definitionId"], "definitionId")
        call = self._service.archive if action == "archive" else self._service.restore
        row = self._guarded(lambda: call(
            authorization.principal.id, definition_id,
            server_scope=authorization.server_scope.id,
            operation_key=operation_key, expected_row_version=expected,
        ))
        return {"definition": definition_record(row)}

    def clone(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "definitionId")
        operation_key, expected = self._mutation_keys(params)
        authorization = self._context()
        definition_id = _bounded(params["definitionId"], "definitionId")
        overrides: dict[str, Any] = {}
        for key, field_name in (("slug", "slug"), ("displayName", "display_name")):
            if params.get(key) is not None:
                overrides[field_name] = _bounded(params[key], key)
        row = self._guarded(lambda: self._service.clone(
            authorization.principal.id, definition_id,
            server_scope=authorization.server_scope.id,
            operation_key=operation_key, expected_row_version=expected,
            **overrides,
        ))
        return {"definition": definition_record(row)}

    # -- import: preview, then a separate explicit approval ------------------

    def import_preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "path")
        path = _bounded(params["path"], "path")
        root = self._import_root
        preview = self._guarded(lambda: self._service.import_preview(
            path, import_root=self._ensure_import_root(root),
        ))
        return {"preview": preview_record(preview)}

    def approve_import(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "previewId", "selects")
        operation_key, expected = self._mutation_keys(params)
        authorization = self._context()
        selects = params["selects"]
        if isinstance(selects, (str, bytes)) or not isinstance(selects, list) or not selects:
            raise WireError("INVALID_REQUEST",
                            "selects must be a non-empty list of previewed names")
        names = [_bounded(entry, "selects[]") for entry in selects]
        origin = _bounded(params.get("origin", "user-upload"), "origin")
        origin_ref = params.get("originRef")
        rows = self._guarded(lambda: self._service.approve_import(
            _bounded(params["previewId"], "previewId"),
            principal=authorization.principal.id,
            server_scope=authorization.server_scope.id,
            selects=names, operation_key=operation_key,
            expected_row_version=expected, origin=origin,
            **({"origin_ref": _bounded(origin_ref, "originRef")}
               if origin_ref is not None else {}),
            **self._import_origin_binding(params, authorization),
        ))
        return {"definitions": [definition_record(row) for row in rows]}

    def _import_origin_binding(self, params: Mapping[str, Any],
                               authorization: scopes.AuthorizationContext,
                               ) -> dict[str, Any]:
        """An imported document's ownership goes through the same attestation
        gate as a created one."""
        origin_scope = params.get("originScope", "public")
        origin_owner = params.get("originOwner", "local")
        self._require_origin_binding(
            authorization, origin_scope=origin_scope, origin_owner=origin_owner,
        )
        return {"origin_scope": origin_scope, "origin_owner": origin_owner}

    def _ensure_import_root(self, root: Path) -> Path:
        """The location is the plugin's own; it is created on first use so a
        composed-but-never-used plugin writes nothing at activation, and it is
        never created at all when the domain could only refuse it (a HOME-bound
        root would otherwise leave a stray directory in the user's tree)."""
        if self._import_root_ready()[0]:
            root.mkdir(parents=True, exist_ok=True)
        return root

    # -- the §C1 surface this composition cannot back ------------------------

    def resolve_preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Never an answer: the assignment source and the pre-effect ceiling
        authority are not composed, so an `EffectiveSet` produced here would be
        invented. The refusal is §C5-typed and names both missing seams."""
        self._reject_self_reported_identity(params)
        _require(params, "requestId", "target")
        raise self._refuse(
            errors.REFERENCE_UNRESOLVED, item="assignments",
            detail=f"resolvePreview needs the assignment source ({ASSIGNMENT_SOURCE_PORT}) "
                   f"and the pre-effect ceiling authority ({CEILING_AUTHORITY_PORT}); "
                   "neither is composed, so no effective set can be attested (SR-2/SR-6, R07)",
        )

    # -- shared -------------------------------------------------------------

    def _guarded(self, action: Callable[[], Any]) -> Any:
        """Run one service call, projecting a domain refusal onto the wire.

        Anything else is a bug, not a contract: it propagates so the host's own
        wall answers `UNAVAILABLE` with the exception type, never a success.
        """
        try:
            return action()
        except errors.DomainError as exc:
            raise self._refusal(exc) from exc

    def _revision_dto(self, *, authorization: scopes.AuthorizationContext,
                      definition_id: str, number: int, body: str,
                      params: Mapping[str, Any]) -> dto.DefinitionRevision:
        """Build the revision and stamp its provenance server-side.

        The approval is the attested caller's own act over the body it just
        submitted (`DefinitionService._check_source_is_witnessed`): origin,
        digest, approver and timestamp are computed here, never copied from the
        request — that is what makes §C1's "客户端不可自报" true for the content
        path too.
        """
        principal = authorization.principal.id
        provisional = dto.DefinitionRevision(
            definition_id=definition_id, revision=number, content_digest=_PLACEHOLDER,
            role_body=body,
            declared_model_ref=_ref(params.get("modelRef"), "modelRef", dto.ModelRef),
            tool_refs=_refs(params.get("toolRefs"), "toolRefs", dto.ToolRef),
            mcp_refs=_refs(params.get("mcpRefs"), "mcpRefs", dto.McpRef),
            skill_refs=_refs(params.get("skillRefs"), "skillRefs", dto.SkillRef),
            requested_permission=params.get("requestedPermission"),
            isolation=_scalar_mapping(params.get("isolation"), "isolation"),
            limits=_scalar_mapping(params.get("limits"), "limits"),
            source=dto.SourceApproval(
                origin="user-upload",
                origin_ref=f"wire/{definition_id}@{number}",
                content_digest=bytes_digest(body.encode("utf-8")),
                approved_by_principal=principal,
                approved_at=_now(),
            ),
            retained_native_fields=dict(params.get("retainedNativeFields") or {}),
        )
        return dto.DefinitionRevision(
            **{**decoder.revision_mapping(provisional),
               "content_digest": revision_digest(provisional)}
        )


# -- projections (stored snake_case -> wire camelCase) -----------------------


def definition_record(row: dto.AgentDefinition) -> dict[str, Any]:
    return {
        "serverScope": row.server_scope, "definitionId": row.definition_id,
        "slug": row.slug, "displayName": row.display_name,
        "description": row.description, "originScope": row.origin_scope,
        "originOwner": row.origin_owner, "latestRevision": row.latest_revision,
        "archived": row.archived, "rowVersion": row.row_version,
    }


def revision_record(row: dto.DefinitionRevision) -> dict[str, Any]:
    source = row.source
    return {
        "definitionId": row.definition_id, "revision": row.revision,
        "contentDigest": row.content_digest, "roleBody": row.role_body,
        "declaredModelRef": _ref_record(row.declared_model_ref),
        "toolRefs": [_ref_record(item) for item in row.tool_refs],
        "mcpRefs": [_ref_record(item) for item in row.mcp_refs],
        "skillRefs": [_ref_record(item) for item in row.skill_refs],
        "requestedPermission": row.requested_permission,
        "isolation": dict(row.isolation), "limits": dict(row.limits),
        "source": None if source is None else {
            "origin": source.origin, "originRef": source.origin_ref,
            "contentDigest": source.content_digest,
            "approvedByPrincipal": source.approved_by_principal,
            "approvedAt": source.approved_at,
        },
        "retainedNativeFields": dict(row.retained_native_fields),
        #: an unmapped native fragment is kept but never compiled (§C5, FR07)
        "compilable": decoder.is_compilable(row),
    }


def preview_record(row: dto.ImportPreview) -> dict[str, Any]:
    return {
        "previewId": row.preview_id, "sourceName": row.source_name,
        "sourceDigest": row.source_digest, "diagnostics": list(row.diagnostics),
        "files": [{
            "relativePath": entry.relative_path, "sizeBytes": entry.size_bytes,
            "contentDigest": entry.content_digest,
            "diagnostics": list(entry.diagnostics), "selectable": entry.selectable,
            "declaredSlug": entry.declared_slug,
            "declaredDescription": entry.declared_description,
        } for entry in row.files],
    }


def _ref_record(value: Any) -> "dict[str, Any] | None":
    if value is None:
        return None
    return {"ownerId": value.owner_id, "revision": value.revision}


def _ref(value: Any, item: str, kind: type) -> Any:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _wire_invalid(item, "expected an object with ownerId and revision")
    unknown = sorted(set(value) - {"ownerId", "revision"})
    if unknown:
        raise _wire_invalid(item, f"a reference carries only ownerId and revision, "
                                  f"not {unknown}")
    return kind(owner_id=_ref_owner(value, item), revision=_ref_revision(value, item))


def _refs(value: Any, item: str, kind: type) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _wire_invalid(item, "expected a list of reference objects")
    return tuple(
        _ref(entry, f"{item}[{index}]", kind) for index, entry in enumerate(value)
    )


def _ref_owner(value: Mapping[str, Any], item: str) -> str:
    return _bounded(value.get("ownerId"), f"{item}.ownerId")


def _ref_revision(value: Mapping[str, Any], item: str) -> "str | None":
    revision = value.get("revision")
    return None if revision is None else _bounded(revision, f"{item}.revision")


def _scalar_mapping(value: Any, item: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _wire_invalid(item, "expected an object of scalar entries")
    return {str(key): entry for key, entry in value.items()}


def _wire_invalid(item: str, detail: str) -> WireError:
    return WireError("INVALID_REQUEST", f"{item}: {detail}", {"item": item})


def attestation_for(ports: Mapping[str, Any], instance_id: str) -> Any:
    """The composed context, or the deployment's own attestation.

    Only this module decides the fallback; a handler never guesses who called.
    """
    composed = ports.get(CONTEXT_PORT)
    if composed is not None:
        return composed
    return DeploymentAttestation.for_instance(instance_id)

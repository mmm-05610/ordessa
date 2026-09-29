"""The seam: `permissions.authorizer@1` as the authority `ceiling.admit` consults.

Q5 published the permissions authority (`plugins/permissions/api` plus
`plugins/permissions/backend`; checkpoint
`specs/011-plugin-rollout/checkpoints/permissions-api.json`, status READY,
producer q5). This module presents that real port as the authority behind this
domain's permission ceiling, so admission is answered by the authority that owns
identity and digests instead of by a local look-alike value object.

What is consumed — public exports only, no `ordessa_permissions_*` private
module, no `ordessa_server_*`, no `ordessa_harness`:

* identity and digests stay *theirs*: `ToolIdentity`, `ArgumentDigest`,
  `build_operation_request` (which derives the ceiling/intent revision pins
  through `intersect_ceilings`), `approval_id_for`, `ApprovalRequest`,
  `ApprovalScope` / `OnceApprovalScope` / `BoundedApprovalScope`, `BoundGrant`,
  `PolicyCeiling`, `PermissionIntent`;
* the ruling comes from the port: `Authorizer.evaluate`, whose result union
  (`AllowedOnce` / `Denied` / `PendingApproval`) and the store-level conflict
  outcomes map onto this domain's §C5 codes below. The port's *name* and the
  conflict *types* are wiring inputs the composition root injects
  (`port_name=` / `conflict_types=`, api-requests.md §SR-15 option 3): Q5's
  provider package is not its published contract, and a sibling plugin's
  internals are not importable from here (AGENTS.md rule 3, §SR-13b row 4), so
  nothing is imported from it. The port *name* has a documented local default
  (`AUTHORIZER_PORT_NAME`) that only ever phrases a refusal or an evidence
  line — the authority itself always arrives injected (`authorizer=` /
  `authorizer_provider=`), and an absent one is a typed refusal;
* the standing question is answered by the port's own record, not by this
  adapter's memory: `Authorizer.reconcile` -> `QueriedApproval.state.scope`, and
  only a `BoundedApprovalScope` reads as standing.

Honest scope (their limitation, Request G1, owner C0): **no pre-effect execution
gate exists in this tree** — nothing calls the port before a tool side effect.
This seam therefore proves *adjudication* (admission consumes the authority's
ruling) and never claims a gated side effect. Where no ruling can be obtained —
no authorizer wired to the port, no trusted ceiling in force, an execution the
authority cannot resolve, a one-shot grant whose approval record is unconfirmed —
the answer is a typed refusal: an absent authority is never a permissive default
(SR-6, US3 "refuse, do not silently narrow").

Two of their semantics are kept deliberately distinct from ours:

1. `AllowedOnce` admits *this* admission and nothing after it. The ruling is
   marked non-standing, the item is never folded into the granted set, and every
   later `admit()` re-consults the port — nothing here caches an approval into a
   permission.
2. `unknown` stays `unknown`. No code path turns an indeterminate answer into
   `admitted`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Callable, Mapping, Protocol, Sequence

from ordessa_permissions_api import (
    GRANT_TTL,
    AllowedOnce,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
    ArgumentDigest,
    AuthorizationDecision,
    BoundedApprovalScope,
    BoundGrant,
    Denied,
    InvalidApproval,
    OnceApprovalScope,
    OperationRequest,
    PendingApproval,
    PermissionIntent,
    PolicyCeiling,
    PolicyRefusal,
    QueriedApproval,
    QueryUnknown,
    ToolIdentity,
    UnknownApproval,
    approval_id_for,
    build_operation_request,
    known_tool_keys,
    scope_to_record,
)

from . import dto, errors
from .ceiling import AdmissionContext, ItemRuling
from .scopes import AuthorizationContext, Principal, ProjectId, ServerScope, SessionId

__all__ = [
    "AUTHORIZER_PORT_NAME",
    "CEILING_ITEMS",
    "CONFLICT_C5_CODE",
    "DECISION_TO_C5",
    "REFUSAL_CODE_TO_C5",
    "TOOL_KEY_BY_KIND",
    "AuthorizerPort",
    "PermissionsSeam",
    "conflict_decision_table",
    "default_approval_scope",
    "map_refusal_code",
    "tool_key_for",
]

#: The *documented default name* of Q5's authorizer port, used only to phrase a
#: refusal or an evidence line when the composition injects no `port_name=`; it
#: is never a resolution key (the authority itself is always injected).
#: Duplicates Q5's published `AUTHORIZER_PORT` constant pending §SR-15; delete
#: this literal when §SR-15 re-exports the constant from `ordessa_permissions_api`.
AUTHORIZER_PORT_NAME = "permissions.authorizer@1"

#: The item kinds this domain puts to the authority, and which tool key of the
#: closed permission vocabulary each is adjudicated under. A declared asset
#: capability is an effect the subagent will be able to perform, so everything
#: that is not itself a named tool is adjudicated as `task` (delegated work)
#: with the declaration as its target. `TOOL_EXPOSURE` rates `task` at `exec`,
#: which is the exposure a subagent actually reaches: no ceiling can admit it
#: by accident.
TOOL_KEY_BY_KIND: Mapping[str, str] = {
    "tool": "@declared",       # the declared tool name must itself be in the vocabulary
    "skill": "skill",
    "model": "task",
    "mcp": "task",
    "permission_mode": "task",
    "isolation": "task",
    "definition": "task",
}
#: Kinds an `admit()` call may put to the authority; anything else is a bug in
#: this package and fails closed rather than being adjudicated under a guess.
CEILING_ITEMS: frozenset[str] = frozenset(TOOL_KEY_BY_KIND)

#: Their stable code (`RefusalCode` / `PolicyDenyCode` value, or a
#: `PolicyRefusal.code`) -> this domain's §C5 code. An unmapped code is
#: `OPERATION_UNKNOWN`: never a yes, and never a silently invented code.
REFUSAL_CODE_TO_C5: Mapping[str, str] = {
    "POLICY_CEILING_VIOLATION": errors.PERMISSION_EXCEEDS_CEILING,
    "policy_deny": errors.PERMISSION_EXCEEDS_CEILING,
    "PERMISSION_UNKNOWN_TOOL": errors.OPERATION_UNKNOWN,
    "POLICY_ADAPTER_MISSING": errors.ADAPTER_MISSING,
    "POLICY_SCOPE_UNVERIFIED": errors.OPERATION_UNKNOWN,
    "APPROVAL_RESULT_UNKNOWN": errors.OPERATION_UNKNOWN,
    "APPROVAL_STALE": errors.ASSIGNMENT_CONFLICT,
    "APPROVAL_NOT_ACTIONABLE": errors.ASSIGNMENT_CONFLICT,
}
#: The §C5 code a *recognised* authorizer conflict carries, whether it arrives
#: as a raised exception or as a returned outcome.
CONFLICT_C5_CODE = errors.ASSIGNMENT_CONFLICT
#: The whole decision -> code table, as the reviewer asked for it: the outcome
#: classes of §C1 first, then the codes carried by `Denied`. The two conflict
#: rows document what an *injected* conflict type maps to; the table a running
#: seam actually consults is `conflict_decision_table()` over what the
#: composition injected, so with nothing injected these rows are not in force
#: and a conflict is unrecognised (`OPERATION_UNKNOWN`), never a silent "no
#: objection" (§SR-15 option 3).
DECISION_TO_C5: Mapping[str, str] = {
    "AllowedOnce": "ADMITTED (never standing without a bounded approval scope)",
    "PendingApproval": errors.PERMISSION_EXCEEDS_CEILING,
    "Denied/UNRECOGNISED_CODE": errors.OPERATION_UNKNOWN,
    "UnknownApproval": errors.OPERATION_UNKNOWN,
    "QueryUnknown": errors.OPERATION_UNKNOWN,
    "InvalidApproval": errors.ASSIGNMENT_CONFLICT,
    "VersionConflict": CONFLICT_C5_CODE,
    "CorrelationConflict": CONFLICT_C5_CODE,
    "grant binding mismatch": errors.ASSIGNMENT_CONFLICT,
    "no ruling obtainable": errors.ADAPTER_MISSING,
}

_UNMAPPED = errors.OPERATION_UNKNOWN


def conflict_decision_table(
        conflict_types: Sequence[Any] = ()) -> Mapping[str, str]:
    """The *live* conflict rows: one per type the composition actually injected.

    Derived entirely from `conflict_types`, so an uninjected seam has an empty
    table and every authorizer conflict — raised or returned — stays outside the
    recognised set, which the seam reports as `OPERATION_UNKNOWN` / the refusal
    path rather than as a ruling. Non-class entries in the injected sequence are
    ignored: an unusable "type" cannot widen the set.
    """
    return {
        one.__name__: CONFLICT_C5_CODE for one in conflict_types
        if isinstance(one, type)
    }


class AuthorizerPort(Protocol):
    """The exact §C1 surface this adapter may touch — nothing store-internal.

    Mirrors how Q5's own admission adapter declares its dependency
    (`PermissionsAcpAdmission`): `evaluate` for the ruling, `reconcile` to read
    back the authority's own record when a grant must be classified as standing.
    """

    def evaluate(self, *, principal: Any, session_ref: Any, execution_ref: Any,
                 native_generation: Any, tool_identity: Any, target_facts: Any,
                 argument_digest: Any, ceiling_revision: Any, policy_revision: Any,
                 native_request_id: Any) -> Any: ...

    def reconcile(self, approval_id: str, native_request_id: str) -> Any: ...


def tool_key_for(kind: str, value: str) -> str:
    """Map one of our declared items onto the closed permission vocabulary.

    A declared tool is named by the brand, so it is matched case-insensitively
    against `known_tool_keys()` and nothing else: the vocabulary is closed on
    purpose, and a tool the authority has no word for is refused as unknown
    rather than treated as "no rule" (which is what "no rule" would mean — an
    admission).
    """
    mapped = TOOL_KEY_BY_KIND.get(kind)
    if mapped is None:
        raise LookupError(f"no vocabulary mapping for item kind {kind!r}")
    if mapped != "@declared":
        return mapped
    needle = str(value).strip().lower().replace("_", "")
    for key in known_tool_keys():
        if key.replace("_", "") == needle:
            return key
    # Let their closed vocabulary raise the typed refusal naming the value.
    return ToolIdentity(str(value)).key


def default_approval_scope() -> ApprovalScope:
    """The scope this domain asks under: one operation, one use.

    Deliberately `once` and never `bounded`: asking for a bounded scope would
    request a standing grant on the definition's behalf, and US3 gives the
    standing decision to the authority alone (through its own settled, bounded
    approval record — see `PermissionsSeam._is_standing`).
    """
    return OnceApprovalScope()


def map_refusal_code(code: Any) -> str:
    """Their stable code -> this domain's §C5 code. Unmapped is never a yes.

    `OPERATION_UNKNOWN` for anything unrecognised: an invented or future code
    this adapter has not been taught must fail closed, and must say so as an
    unresolvable ruling rather than as a permission.
    """
    value = getattr(code, "value", code)
    if not isinstance(value, str):
        return _UNMAPPED
    return REFUSAL_CODE_TO_C5.get(value, _UNMAPPED)


class PermissionsSeam:
    """Presents `permissions.authorizer@1` as a `ceiling.CeilingAuthority`.

    The identity facts are the *server-verified* ones (FR02/FR03): a principal
    id, server scope, harness binding, and — when the admission runs inside a
    real turn — the project/session/execution the service issued. A caller
    cannot substitute a self-reported principal here, because the ruling is
    computed under `principal.id` by the authority; a forged claim therefore
    only ever produces a refusal for the claimant, never a grant for somebody
    else (G07 counter-example: 客户端伪 projectId).

    Which port this seam runs against, and which exception/outcome types count
    as the authority's conflicts, are *injected* (`port_name=` /
    `conflict_types=`), because the seam may not import Q5's provider package
    to learn them (AGENTS.md rule 3; SR-15 option 3). The port name falls back
    to the documented `AUTHORIZER_PORT_NAME` only for *phrasing* when the host
    injects nothing: it resolves nothing, and the authority object still has to
    be injected, so a seam without an authorizer is refused `ADAPTER_MISSING`
    exactly as a seam with a name and no authority is.
    `conflict_types` defaults to empty and that default is fail-closed: without
    injected conflict types the authority's raised exceptions and returned
    conflict records are unrecognised, which is `OPERATION_UNKNOWN`, never a
    silent "no objection" and never an admission.
    """

    def __init__(
        self,
        *,
        principal: Principal,
        server_scope: ServerScope,
        harness_id: str,
        port_name: str | None = None,
        project_id: ProjectId | None = None,
        session_id: SessionId | None = None,
        execution_id: str | None = None,
        authorizer: Any | None = None,
        authorizer_provider: Callable[[], Any] | None = None,
        ceiling_provider: Callable[[], Sequence[PolicyCeiling]] | None = None,
        intent_provider: Callable[[], PermissionIntent | None] | None = None,
        conflict_types: Sequence[type] = (),
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.principal = principal
        self.server_scope = server_scope
        self.harness_id = harness_id
        #: The port this seam adjudicates against, as the composition names it.
        #: Only used to *word* a refusal or an evidence line; nothing is
        #: resolved by it. `None` (the host injected nothing) falls back to the
        #: documented `AUTHORIZER_PORT_NAME`; a name the host *did* state is used
        #: verbatim, and a blank or unusable one stays empty so the seam reports
        #: the wiring gap instead of papering over it with the default.
        if port_name is None:
            self.port_name: str = AUTHORIZER_PORT_NAME
        elif isinstance(port_name, str):
            self.port_name = port_name.strip()
        else:
            self.port_name = ""
        self.project_id = project_id
        self.session_id = session_id
        self.execution_id = execution_id
        self._authorizer = authorizer
        self._authorizer_provider = authorizer_provider
        self._ceiling_provider = ceiling_provider
        self._intent_provider = intent_provider
        #: Host-injected conflict types (the authority's correlation/version
        #: failure classes). Default empty: unrecognised is `OPERATION_UNKNOWN`.
        self.conflict_types = tuple(conflict_types or ())
        self._conflict_outcomes = tuple(t for t in self.conflict_types
                                        if isinstance(t, type))
        self._conflict_exceptions = tuple(
            t for t in self._conflict_outcomes if issubclass(t, BaseException))
        #: The live conflict -> §C5 rows, keyed off exactly what was injected
        #: (`conflict_decision_table`); empty means "nothing is recognised".
        self.conflict_table = conflict_decision_table(self._conflict_outcomes)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        #: Rulings this seam has *answered*, for observation only. It is never
        #: read back as a grant: the authority is consulted on every item, so a
        #: one-shot approval cannot become a standing permission by caching.
        self.consultations: list[dict[str, str]] = []

    @classmethod
    def for_authorization(
        cls,
        authorization: AuthorizationContext,
        *,
        harness_id: str,
        port_name: str | None = None,
        claimed_project_id: str | None = None,
        session_id: SessionId | None = None,
        execution_id: str | None = None,
        authorizer: Any | None = None,
        authorizer_provider: Callable[[], Any] | None = None,
        ceiling_provider: Callable[[], Sequence[PolicyCeiling]] | None = None,
        intent_provider: Callable[[], PermissionIntent | None] | None = None,
        conflict_types: Sequence[type] = (),
        clock: Callable[[], dt.datetime] | None = None,
    ) -> "PermissionsSeam":
        """Bind the seam to a *service-issued* context, never to a claim (SR-6).

        The principal and server scope come from the context the service issued;
        a project assertion is only accepted when the server verified it
        (`require_project`, G07: 客户端伪 projectId). This is the entry point a
        wire handler uses; a definition's own text can never name the principal
        the ruling is taken under. The port name and conflict types are part of
        what the composition injects here — the seam never supplies them.
        """
        project = authorization.require_project(claimed_project_id)
        return cls(
            principal=authorization.principal, server_scope=authorization.server_scope,
            harness_id=harness_id, port_name=port_name, project_id=project,
            session_id=session_id, execution_id=execution_id, authorizer=authorizer,
            authorizer_provider=authorizer_provider, ceiling_provider=ceiling_provider,
            intent_provider=intent_provider, conflict_types=conflict_types,
            clock=clock,
        )

    # -- availability ---------------------------------------------------------------

    def resolve_authorizer(self) -> Any | None:
        """The port object, or None. Absence is a fact, never a default."""
        if self._authorizer is not None:
            return self._authorizer
        if self._authorizer_provider is None:
            return None
        try:
            return self._authorizer_provider()
        except Exception:  # a port lookup that fails is an absent port
            return None

    def is_available(self) -> bool:
        """Whether a ruling can be obtained at all. Conservative: the port name
        the seam will speak must be usable, and both the authorizer and a
        ceiling provider must be reachable — a name alone is never
        availability, and an injected-but-blank name is a stated wiring gap."""
        return (bool(self.port_name)
                and self.resolve_authorizer() is not None
                and self._ceiling_provider is not None)

    def subject_for(self, revision: dto.DefinitionRevision) -> AdmissionContext:
        """The identity this seam rules under — its own, never the request's.

        Composition builds the seam from a service-issued context
        (`PermissionsSeam.for_authorization`), so the principal the authority
        sees is the verified one. A definition's text (an embedded
        `approvedByPrincipal`, a claimed project) is data under adjudication,
        never the identity of the party asking.
        """
        return AdmissionContext.from_service(
            principal=self.principal, server_scope=self.server_scope,
            harness_id=self.harness_id, revision=revision, project_id=self.project_id,
            session_id=self.session_id, execution_id=self.execution_id,
        )

    # -- the authority surface `ceiling.admit` / `references` use ---------------------

    def adjudicate(
        self,
        context: AdmissionContext,
        kind: str,
        value: str,
        *,
        field_name: str,
    ) -> ItemRuling:
        """The one entry point `ceiling.admit` / `references` use.

        Any failure that escapes the mapping below is still a typed refusal: the
        wrapper turns it into `OPERATION_UNKNOWN` instead of letting an
        unexplained exception read as "the ceiling did not object".
        """
        try:
            return self._adjudicate(context, kind, value, field_name=field_name)
        except Exception as failure:  # noqa: BLE001 - fail closed, never admit
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                f"the seam could not turn the authority's answer into a ruling "
                f"({type(failure).__name__}); no admission is taken",
            )

    def _adjudicate(
        self,
        context: AdmissionContext,
        kind: str,
        value: str,
        *,
        field_name: str,
    ) -> ItemRuling:
        if not context.verified:
            # A context assembled from a wire payload is a *claim*, not an
            # identity. Refused as an over-ceiling attempt naming `principal`
            # (G07: 客户端伪 principal/projectId), before any ruling is taken.
            return self._refused(
                "principal", errors.PERMISSION_EXCEEDS_CEILING,
                f"the admission identity for '{context.definition_id}' was not issued by "
                "the service; a self-reported principal rules nothing",
            )
        if (context.principal != self.principal
                or context.server_scope != self.server_scope
                or context.harness_id != self.harness_id):
            # The grants and the authority that rules on them must belong to the
            # same verified identity; otherwise a grant record issued for one
            # principal could be waved through by another principal's authority.
            return self._refused(
                "principal", errors.ASSIGNMENT_CONFLICT,
                f"the ceiling names {context.principal.id}@{context.server_scope.id}"
                f"/{context.harness_id} but this authority answers for "
                f"{self.principal.id}@{self.server_scope.id}/{self.harness_id}",
            )
        if kind not in CEILING_ITEMS:
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                f"item kind '{kind}' is not part of the adjudicated ceiling vocabulary",
            )
        if not self.port_name:
            # Only reachable when the composition injects a *blank* name, i.e.
            # says "this seam has no port": the documented
            # `AUTHORIZER_PORT_NAME` default phrases refusals, it never resolves
            # one, so a blank injection is reported as a missing collaborator
            # instead of being papered over with the default.
            return self._refused(
                field_name, errors.ADAPTER_MISSING,
                "the composition injected a blank authorizer port name into this seam "
                f"(the documented Q5 port is '{AUTHORIZER_PORT_NAME}'; an unusable "
                "injection is a missing collaborator, not a port to resolve)",
            )
        authorizer = self.resolve_authorizer()
        if authorizer is None:
            return self._refused(
                field_name, errors.ADAPTER_MISSING,
                f"port '{self.port_name}' provides no authorizer; refusing instead of "
                "defaulting to permissive",
            )
        if not callable(getattr(authorizer, "evaluate", None)):
            return self._refused(
                field_name, errors.ADAPTER_MISSING,
                "the object wired to the authorizer port has no `evaluate` ruling surface",
            )
        if self._ceiling_provider is None:
            return self._refused(
                field_name, errors.ADAPTER_MISSING,
                "no trusted ceiling source is wired to the seam; the authority would "
                "have no upper bound to rule under",
            )
        if context.content_digest == "":
            return self._refused(
                field_name, errors.NATIVE_VERSION_UNKNOWN,
                "the revision content is unverifiable; no ruling is taken on an "
                "undigested declaration",
            )
        try:
            tool_key = tool_key_for(kind, value)
        except PolicyRefusal as refusal:
            return self._from_refusal(refusal, field_name)

        request = self._operation(context, kind=kind, value=value, tool_key=tool_key,
                                  field=field_name)
        if isinstance(request, ItemRuling):
            return request  # a refusal built while assembling their request
        approval = self._approval_request(request)
        if isinstance(approval, ItemRuling):
            return approval

        try:
            outcome = authorizer.evaluate(
                principal=request.principal,
                session_ref={
                    "serverInstanceId": request.server_instance_id,
                    "sessionId": request.session_id,
                    "nativeSessionId": request.native_session_id,
                },
                execution_ref=request.execution_id,
                native_generation=request.native_generation,
                tool_identity=ToolIdentity(request.tool_key),
                target_facts={"target": request.target},
                argument_digest=ArgumentDigest(request.argument_digest.value),
                ceiling_revision=request.ceiling_revision,
                policy_revision=request.policy_revision,
                native_request_id=request.native_request_id,
            )
        except self._conflict_exceptions as conflict:
            # Only a *recognised*, host-injected conflict type lands here; the
            # §C5 code comes from the table built off that injection. Anything
            # else the authority raises is an unrecognised failure and goes to
            # the `OPERATION_UNKNOWN` branch below.
            detail = getattr(conflict, "detail", conflict)
            return self._refused(
                field_name, self.conflict_table.get(type(conflict).__name__, _UNMAPPED),
                f"the authority reported a correlation/version conflict of the "
                f"injected type {type(conflict).__name__}: {detail}",
            )
        except PolicyRefusal as refusal:
            return self._from_refusal(refusal, field_name)
        except Exception as failure:  # a ruling that cannot be obtained is unknown
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                f"the authorizer raised {type(failure).__name__}; no ruling was obtained",
            )
        self.consultations.append({"field": field_name, "outcome": type(outcome).__name__})
        return self._ruling(outcome, authorizer=authorizer, request=request,
                            approval=approval, field_name=field_name)

    # -- their constructors, ours' facts ---------------------------------------------

    def _operation(
        self,
        context: AdmissionContext,
        *,
        kind: str,
        value: str,
        tool_key: str,
        field: str,
    ) -> OperationRequest | ItemRuling:
        """Assemble the operation identity through `build_operation_request`.

        The revision pins are read off the real `PolicyCeiling` /
        `PermissionIntent` objects by their own code, so this domain never
        invents a ceiling revision; the argument digest is a hash over identity
        facts only — there is no field here that could carry a tool payload or
        a credential.
        """
        try:
            ceilings = tuple(self._ceiling_provider() or ())  # type: ignore[misc]
        except Exception as failure:
            return self._refused(
                field, errors.ADAPTER_MISSING,
                f"the ceiling provider failed ({type(failure).__name__}); nothing proceeds",
            )
        intent: PermissionIntent | None = None
        if self._intent_provider is not None:
            try:
                candidate = self._intent_provider()
            except Exception as failure:
                return self._refused(
                    field, errors.ADAPTER_MISSING,
                    f"the intent provider failed ({type(failure).__name__})",
                )
            if candidate is not None and not isinstance(candidate, PermissionIntent):
                return self._refused(
                    field, errors.OPERATION_UNKNOWN,
                    "the intent provider returned something that is not a PermissionIntent",
                )
            intent = candidate
        session_id = (None if context.session_id is None else context.session_id.id) \
            or f"declaration:{context.principal.id}"
        execution_id = context.execution_id or (
            f"assets-declaration:{context.definition_id}#r{context.revision}")
        try:
            return build_operation_request(
                principal=context.principal.id,
                server_instance_id=context.server_scope.id,
                session_id=session_id,
                native_session_id=f"native-{session_id}",
                execution_id=execution_id,
                native_generation=f"assets:{context.content_digest}",
                tool_key=tool_key,
                target=f"{kind}:{value}",
                argument_digest=ArgumentDigest.of(
                    self.argument_digest(context, kind, value)),
                native_request_id=self.native_request_id(context, kind, value),
                ceilings=ceilings,
                intent=intent,
            )
        except PolicyRefusal as refusal:
            return self._from_refusal(refusal, field)

    def argument_digest(self, subject: Any, kind: str, value: str) -> str:
        """The 64-hex digest of *this* declaration item: identity, never payload.

        The principal and server scope are folded in, so two parties declaring
        the same item never share an approval identity — a grant issued to one
        cannot be replayed by the other.
        """
        canonical = json.dumps(
            {
                "principal": subject.principal.id,
                "serverScope": subject.server_scope.id,
                "definitionId": subject.definition_id, "revision": subject.revision,
                "contentDigest": subject.content_digest, "kind": kind, "value": value,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def native_request_id(self, subject: Any, kind: str, value: str) -> str:
        """Deterministic, bounded, printable: the same declaration always
        correlates to the same approval id, and a random id could not be
        reconciled by the authority."""
        folded = hashlib.sha256(
            f"{subject.principal.id}\n{subject.definition_id}\n{subject.revision}\n"
            f"{kind}\n{value}".encode("utf-8")
        ).hexdigest()[:24]
        return f"assets-{kind}-{folded}"

    def _approval_request(
        self, operation: OperationRequest
    ) -> ApprovalRequest | ItemRuling:
        """Their `ApprovalRequest`, built from our facts through their parser.

        The approval id is minted by `approval_id_for`; if the assembled record
        does not validate, there is no ruling to take — the refusal names the
        field rather than coercing the identity.
        """
        now = self._clock()
        try:
            approval = ApprovalRequest.from_record(
                {
                    "approvalId": approval_id_for(
                        operation_digest=operation.operation_digest,
                        native_request_id=operation.native_request_id),
                    "sessionId": operation.session_id,
                    "executionId": operation.execution_id,
                    "nativeRequestId": operation.native_request_id,
                    "operationDigest": operation.operation_digest,
                    "toolKey": operation.tool_key,
                    "target": operation.target,
                    "ceilingRevision": operation.ceiling_revision,
                    "policyRevision": operation.policy_revision,
                    "nativeGeneration": operation.native_generation,
                    "requestedAt": now.isoformat(),
                    "expiresAt": (now + GRANT_TTL).isoformat(),
                    "version": 1,
                }
            )
        except PolicyRefusal as refusal:
            return self._from_refusal(refusal, f"approval:{operation.tool_key}")
        if scope_to_record(self._default_scope()) != {"kind": "once"}:
            # Unreachable by construction; kept so a future default cannot
            # quietly become "bounded" and turn a one-shot into a standing grant.
            return self._refused(
                f"approval:{approval.approval_id}", errors.OPERATION_UNKNOWN,
                "the seam's default approval scope is not 'once'",
            )
        return approval

    @staticmethod
    def _default_scope() -> ApprovalScope:
        """What this domain presents when it asks for a ruling: one operation,
        one use. Never `bounded` — that would ask the authority for a standing
        grant on the definition's behalf."""
        return default_approval_scope()

    # -- outcome -> our §C5 outcome ---------------------------------------------------

    def _ruling(
        self,
        outcome: Any,
        *,
        authorizer: Any,
        request: OperationRequest,
        approval: ApprovalRequest,
        field_name: str,
    ) -> ItemRuling:
        if isinstance(outcome, AllowedOnce):
            return self._allowed_once(outcome, authorizer=authorizer, request=request,
                                      approval=approval, field_name=field_name)
        if isinstance(outcome, Denied):
            code = str(getattr(outcome.code, "value", outcome.code))
            ours = map_refusal_code(outcome.code)
            message = self._reason_text(outcome.reason) or code
            return self._refused(
                field_name, ours,
                f"the authority denied this item as {code}: {message} "
                f"(evidence {outcome.evidence_ref})",
                authority_code=code, approval_id=approval.approval_id,
                payload=self._denied_record(outcome, code),
            )
        if isinstance(outcome, PendingApproval):
            # An unsettled approval grants nothing: the declaration is refused
            # now, naming the field, rather than narrowed and claimed to apply.
            return self._refused(
                field_name, errors.PERMISSION_EXCEEDS_CEILING,
                f"the authority requires an approval that is not settled "
                f"(approval {outcome.approval_id}); nothing may proceed on a pending "
                "approval",
                approval_id=outcome.approval_id,
            )
        if isinstance(outcome, (UnknownApproval, QueryUnknown)):
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                f"the authority could not resolve this ruling ({outcome.reason}); "
                "unknown is not a permission",
            )
        if isinstance(outcome, InvalidApproval):
            # Their own published API outcome: recognised with nothing injected,
            # because this module imports the API package it comes from.
            return self._refused(
                field_name, errors.ASSIGNMENT_CONFLICT,
                f"the authority's approval record no longer refers to this declaration "
                f"({outcome.reason}); nothing was written",
            )
        conflict_code = self.conflict_table.get(type(outcome).__name__)
        if conflict_code is not None and isinstance(outcome, self._conflict_outcomes):
            # Only a host-injected conflict type is a conflict: the code, the
            # class and the recognition all come from the same injection, so
            # deleting it moves this row (and nothing else may fill it).
            reason = getattr(outcome, "reason", "approval_version_conflict")
            return self._refused(
                field_name, conflict_code,
                f"the authority's approval record conflicts for this declaration "
                f"({type(outcome).__name__}: {reason}); nothing was written",
            )
        if isinstance(outcome, (AuthorizationDecision, ApprovalState, QueriedApproval)):
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                f"the port answered with {type(outcome).__name__}, which is a record and "
                "not a ruling; no admission is taken from it",
            )
        return self._refused(
            field_name, errors.OPERATION_UNKNOWN,
            f"unrecognised authorizer outcome {type(outcome).__name__}; failing closed",
        )

    def _allowed_once(
        self, outcome: AllowedOnce, *, authorizer: Any, request: OperationRequest,
        approval: ApprovalRequest, field_name: str,
    ) -> ItemRuling:
        grant: BoundGrant = outcome.grant
        if grant.approval_id != approval.approval_id or not grant.matches(request):
            # A grant that does not bind *this* operation digest, target and
            # revision pins is a conflict; it is never re-bound (their wording,
            # and ours: no write, no admission).
            return self._refused(
                field_name, errors.ASSIGNMENT_CONFLICT,
                f"the one-time grant {grant.approval_id} does not bind this declaration "
                f"(digest {grant.operation_digest[:12]} for approval "
                f"{approval.approval_id}); no write",
                approval_id=grant.approval_id,
            )
        if not grant.single_use:
            return self._refused(
                field_name, errors.OPERATION_UNKNOWN,
                "the authority returned a grant that does not declare itself single-use",
            )
        standing, note = self._is_standing(authorizer, grant, request)
        detail = (f"admitted by {self.port_name} for this operation only "
                  f"(single-use grant {grant.approval_id}; {note})")
        return ItemRuling(
            field_name=field_name, admitted=True, standing=standing,
            detail=detail, authority_code="allowed_once", approval_id=grant.approval_id,
            payload=self._grant_record(grant),
        )

    def _is_standing(
        self, authorizer: Any, grant: BoundGrant, request: OperationRequest
    ) -> tuple[bool, str]:
        """Standing only when the authority's own record says so.

        `AllowedOnce` is, by their definition, one operation and one use. The
        only thing that can make an admission *standing* is an approval the
        authority itself settled with a `bounded` (session-end) scope, read back
        through `reconcile`. Anything else — including "we could not read it
        back" — stays non-standing, which the ceiling layer then records as a
        single-use field instead of folding the item into the granted set.
        """
        reconcile = getattr(authorizer, "reconcile", None)
        if not callable(reconcile):
            return False, "the port offers no way to read the approval scope back"
        try:
            answer = reconcile(grant.approval_id, request.native_request_id)
        except Exception as failure:
            return False, f"reading the approval scope back failed ({type(failure).__name__})"
        if isinstance(answer, QueryUnknown):
            return False, f"the approval record is unconfirmed ({answer.reason})"
        if not isinstance(answer, QueriedApproval):
            return False, f"the port answered the scope read with {type(answer).__name__}"
        state = answer.state
        if state.state.value != "settled" or state.decision is None:
            return False, f"the approval is {state.state.value}, not a settled allow"
        scope = state.scope
        if isinstance(scope, BoundedApprovalScope):
            return True, f"the authority settled this with a bounded scope ({scope.until})"
        if isinstance(scope, OnceApprovalScope):
            return False, "the authority settled this with a 'once' scope"
        return False, "the settled approval carries no scope"

    @staticmethod
    def _denied_record(outcome: Denied, code: str) -> dict[str, Any]:
        """The authority's own denial fields — no argument payload exists to carry."""
        return {
            "code": code,
            "evidenceRef": outcome.evidence_ref,
            "reason": PermissionsSeam._reason_text(outcome.reason),
        }

    @staticmethod
    def _grant_record(grant: BoundGrant) -> dict[str, Any]:
        """The one-use grant's binding fields, exactly as `BoundGrant` holds them."""
        return {
            "approvalId": grant.approval_id, "operationDigest": grant.operation_digest,
            "target": grant.target, "ceilingRevision": grant.ceiling_revision,
            "policyRevision": grant.policy_revision,
            "nativeGeneration": grant.native_generation,
            "expiresAt": grant.expires_at.isoformat(), "singleUse": grant.single_use,
        }

    @staticmethod
    def _reason_text(reason: Any) -> str | None:
        """Their `DecisionReason` message, defensively: an unexpected shape must
        not turn a mapping into a crash (which would leave no typed refusal)."""
        if reason is None:
            return None
        message = getattr(reason, "message", None)
        if isinstance(message, str):
            return message
        if isinstance(reason, str):
            return reason
        return None

    def _from_refusal(self, refusal: PolicyRefusal, field_name: str) -> ItemRuling:
        code = str(refusal.code)
        ours = REFUSAL_CODE_TO_C5.get(code, _UNMAPPED)
        return self._refused(
            field_name, ours,
            f"the authority refused while assembling the ruling as {code}: "
            f"{refusal.human_readable}",
            authority_code=code,
        )

    def _refused(
        self, field_name: str, code: str, detail: str, *,
        authority_code: str | None = None, approval_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> ItemRuling:
        return ItemRuling(
            field_name=field_name, admitted=False, standing=False, code=code,
            detail=detail, authority_code=authority_code, approval_id=approval_id,
            payload=dict(payload or {}),
        )

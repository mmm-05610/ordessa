"""The enforcement boundary (FR06, US3, gate G09).

A `Ceiling` is what the permissions authority has actually granted to
(principal, project, session, harness). A definition's declarations can
meet the ceiling or be refused by it — they can never raise it, whatever
the definition text, `permissionMode` or plugin origin says.

First-release policy: anything over the ceiling or unverifiable is a typed
refusal naming the offending field at item level; nothing is silently
narrowed while the original is claimed to apply (US3). If the authority is
absent, `admit` refuses — there is no permissive default (SR-6).

Two authorities are possible, and the difference matters:

* a `Ceiling` value object on its own is a *record of grants* the caller
  carries. It is still checked exactly as before — every guard below runs —
  but it is only as trustworthy as whoever filled it in;
* a `CeilingAuthority` — satisfied by `permissions_seam.PermissionsSeam` over
  the real `permissions.authorizer@1` port — answers for one declared item at
  a time. When one is wired (directly, or carried by `Ceiling.authority`),
  every item put to it must come back admitted, or `admit` refuses with the
  authority's own §C5 code and the item-level field named. A grant the
  authority issued *once* admits this call and is reported in
  `single_use_fields`; it is never folded back into the standing grant set,
  and nothing here caches a ruling, so a one-shot approval cannot decay into
  a permission.

Adjudication is what this boundary can do; a pre-effect execution gate does
not exist in this tree yet (permissions-api checkpoint, Request G1), so
nothing here may be reported as "the side effect was blocked by the
authority".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from . import dto, errors
from .scopes import (
    AuthorizationContext,
    Principal,
    ProjectId,
    ServerScope,
    SessionId,
)

#: Field spellings whose mere presence is an approval-posture widening
#: attempt when not granted; checked case-insensitively against the values
#: a definition carries.
_PERMISSION_MODE_KEYS = frozenset({"permissionmode", "permission_mode"})


@dataclass(frozen=True)
class ItemRuling:
    """The authority's answer about exactly one declared item.

    `admitted` speaks for this admission only. `standing` says whether the item
    may be treated as a granted capability *after* this call; a one-shot
    approval is admitted without ever being standing. A refusal always carries
    a §C5 code and the field it names.

    `payload` is the authority's own decision record, reduced to the bounded
    identity fields its API exposes (evidence ref, approval id, expiry). It is
    *data*: the consumer that stores it must send it through
    `references.sanitize_facts` first, exactly like any other owner-supplied
    payload — a ruling object cannot smuggle a credential into a snapshot
    because there is no field of ours it could be placed in unsanitized.
    """

    field_name: str
    admitted: bool
    standing: bool = False
    code: str | None = None
    detail: str | None = None
    authority_code: str | None = None
    approval_id: str | None = None
    #: The authority's own decision record, as returned by its public shapes
    #: (`as_record()` / the grant fields). It is *data*: whatever consumes a
    #: ruling must send it through `references.sanitize_facts` before it can
    #: reach a stored snapshot — a ruling object is not a trusted payload.
    payload: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def refusal(self, revision: dto.DefinitionRevision) -> errors.DomainError:
        """The item-level §C5 refusal this ruling obliges (never a yes)."""
        if self.admitted:
            raise ValueError("an admitted ruling produces no refusal")
        return errors.refused(
            self.code or errors.OPERATION_UNKNOWN,
            item_id=f"{revision.definition_id}#r{revision.revision}.{self.field_name}",
            detail=f"field '{self.field_name}' refused by the permissions authority: "
                   f"{self.detail or 'no reason given'}",
        )


class CeilingAuthority(Protocol):
    """What `admit` puts each declared item to.

    Satisfied by `permissions_seam.PermissionsSeam` over the real
    `permissions.authorizer@1` port. Deliberately has no default and no
    permissive member: an authority that cannot answer says so through
    `is_available` or through a refusal ruling.
    """

    def is_available(self) -> bool: ...

    def subject_for(self, revision: dto.DefinitionRevision) -> "AdmissionContext": ...

    def adjudicate(
        self,
        context: "AdmissionContext",
        kind: str,
        value: str,
        *,
        field_name: str,
    ) -> ItemRuling: ...


@dataclass(frozen=True)
class AdmissionContext:
    """Whose declaration is being adjudicated, and under what verified identity.

    The identity fields come from the *service*: either the recorded `Ceiling`
    the service issued (`from_ceiling`) or an `AuthorizationContext` it issued
    (`issued_by_service`, whose project gate is `require_project` — a claimed
    project the server never verified is refused there, G07). A context
    assembled straight from a wire payload carries `verified=False`, and the
    seam refuses to rule on it: definition text and client claims are data, not
    identity (FR02/FR03).
    """

    principal: Principal
    server_scope: ServerScope
    harness_id: str
    definition_id: str
    revision: int
    content_digest: str
    project_id: ProjectId | None = None
    session_id: SessionId | None = None
    execution_id: str | None = None
    verified: bool = False

    @classmethod
    def from_ceiling(
        cls, ceiling: "Ceiling", revision: dto.DefinitionRevision
    ) -> "AdmissionContext":
        """A recorded ceiling is a service output, so its identity is verified."""
        return cls(
            principal=ceiling.principal, server_scope=ceiling.server_scope,
            harness_id=ceiling.harness_id, project_id=ceiling.project_id,
            session_id=ceiling.session_id, definition_id=revision.definition_id,
            revision=revision.revision, content_digest=revision.content_digest,
            verified=True,
        )

    @classmethod
    def issued_by_service(
        cls,
        authorization: AuthorizationContext,
        *,
        harness_id: str,
        revision: dto.DefinitionRevision,
        claimed_project_id: str | None = None,
        session_id: SessionId | None = None,
        execution_id: str | None = None,
    ) -> "AdmissionContext":
        """Identity from a service-issued context; project claim must be verified."""
        return cls(
            principal=authorization.principal, server_scope=authorization.server_scope,
            harness_id=harness_id, project_id=authorization.require_project(
                claimed_project_id),
            session_id=session_id, execution_id=execution_id,
            definition_id=revision.definition_id, revision=revision.revision,
            content_digest=revision.content_digest, verified=True,
        )

    @classmethod
    def from_service(
        cls,
        *,
        principal: Principal,
        server_scope: ServerScope,
        harness_id: str,
        revision: dto.DefinitionRevision,
        project_id: ProjectId | None = None,
        session_id: SessionId | None = None,
        execution_id: str | None = None,
    ) -> "AdmissionContext":
        """The identity a service-side component (the seam, built by composition)
        already holds. Never usable for a claim that came in with the request."""
        return cls(
            principal=principal, server_scope=server_scope, harness_id=harness_id,
            project_id=project_id, session_id=session_id, execution_id=execution_id,
            definition_id=revision.definition_id, revision=revision.revision,
            content_digest=revision.content_digest, verified=True,
        )


@dataclass(frozen=True)
class Ceiling:
    """The maximum capabilities actually granted; empty means none."""

    principal: Principal
    server_scope: ServerScope
    harness_id: str
    project_id: ProjectId | None = None
    session_id: SessionId | None = None
    allowed_tools: frozenset[str] = frozenset()
    allowed_models: frozenset[str] = frozenset()
    allowed_mcp: frozenset[str] = frozenset()
    allowed_skills: frozenset[str] = frozenset()
    allowed_permission_modes: frozenset[str] = frozenset()
    allowed_isolation_keys: frozenset[str] = frozenset()
    #: The live authority behind these grants, when one is wired. The local
    #: subset checks below still run with it present — an authority adds a
    #: ruling, it never removes a guard.
    authority: CeilingAuthority | None = None


@dataclass(frozen=True)
class AdmittedConfig:
    """The effective set after admission — always a subset of the ceiling."""

    definition_id: str
    revision: int
    effective_tools: frozenset[str]
    effective_model: str | None
    effective_mcp: frozenset[str]
    effective_skills: frozenset[str]
    approval_mode: str | None
    evidence: tuple[str, ...] = ()
    #: Fields the authority admitted for this call only (a single-use grant).
    #: They are *not* standing capabilities: a consumer that needs a standing
    #: grant must check `is_standing` instead of assuming one.
    single_use_fields: tuple[str, ...] = ()

    def within_ceiling(self, ceiling: Ceiling) -> bool:
        return (
            self.effective_tools <= ceiling.allowed_tools
            and self.effective_mcp <= ceiling.allowed_mcp
            and self.effective_skills <= ceiling.allowed_skills
            and (self.effective_model is None or self.effective_model in ceiling.allowed_models)
            and (self.approval_mode is None or self.approval_mode in ceiling.allowed_permission_modes)
        )

    @property
    def is_standing(self) -> bool:
        """True when nothing was admitted on a one-shot approval."""
        return not self.single_use_fields


def _refuse(revision: dto.DefinitionRevision, field_name: str, why: str) -> errors.DomainError:
    return errors.refused(
        errors.PERMISSION_EXCEEDS_CEILING,
        item_id=f"{revision.definition_id}#r{revision.revision}.{field_name}",
        detail=f"field '{field_name}' {why}; the definition cannot raise the ceiling",
    )


def _check_mode_fields(revision: dto.DefinitionRevision, ceiling: Ceiling) -> None:
    if revision.requested_permission is not None:
        if revision.requested_permission not in ceiling.allowed_tools:
            raise _refuse(revision, "requested_permission",
                          "requests a tool that is not granted")
    for key, value in revision.retained_native_fields.items():
        if str(key).lower() in _PERMISSION_MODE_KEYS:
            if str(value) not in ceiling.allowed_permission_modes:
                raise _refuse(revision, f"retained_native_fields.{key}",
                              "requests an approval posture that is not granted")


def _check_isolation(revision: dto.DefinitionRevision, ceiling: Ceiling) -> None:
    for key in sorted(revision.isolation):
        if str(key) not in ceiling.allowed_isolation_keys:
            raise _refuse(revision, f"isolation.{key}",
                          "widens isolation beyond the granted set")


def _check_sets(
    revision: dto.DefinitionRevision,
    ceiling: Ceiling,
) -> tuple[frozenset[str], str | None, frozenset[str], frozenset[str]]:
    tools = frozenset(ref.owner_id for ref in revision.tool_refs)
    if tools - ceiling.allowed_tools:
        raise _refuse(revision, "toolRefs", "declares tools outside the granted set")
    model: str | None = None
    if revision.declared_model_ref is not None:
        model = revision.declared_model_ref.owner_id
        if model not in ceiling.allowed_models:
            raise _refuse(revision, "declaredModelRef",
                          "names a model outside the granted set")
    mcp = frozenset(ref.owner_id for ref in revision.mcp_refs)
    if mcp - ceiling.allowed_mcp:
        raise _refuse(revision, "mcpRefs", "names MCP servers outside the granted set")
    skills = frozenset(ref.owner_id for ref in revision.skill_refs)
    if skills - ceiling.allowed_skills:
        raise _refuse(revision, "skillRefs", "names skills outside the granted set")
    return tools, model, mcp, skills


def admission_items(
    revision: dto.DefinitionRevision,
) -> tuple[tuple[str, str, str], ...]:
    """Every capability this revision declares, as (kind, value, field name).

    The field names are the §C5 item-level spellings the refusal must carry;
    the last item is the declaration as a whole, so an authority is never
    presented with an empty set to wave through.
    """
    items: list[tuple[str, str, str]] = []
    if revision.requested_permission is not None:
        items.append(("tool", revision.requested_permission, "requested_permission"))
    for key, value in sorted(revision.retained_native_fields.items(), key=_by_str_key):
        if str(key).lower() in _PERMISSION_MODE_KEYS:
            items.append(("permission_mode", str(value), f"retained_native_fields.{key}"))
    for key in sorted(revision.isolation):
        items.append(("isolation", f"{key}={revision.isolation[key]}", f"isolation.{key}"))
    for ref in revision.tool_refs:
        items.append(("tool", ref.owner_id, f"toolRefs.{ref.owner_id}"))
    if revision.declared_model_ref is not None:
        items.append(("model", revision.declared_model_ref.owner_id, "declaredModelRef"))
    for ref in revision.mcp_refs:
        items.append(("mcp", ref.owner_id, f"mcpRefs.{ref.owner_id}"))
    for ref in revision.skill_refs:
        items.append(("skill", ref.owner_id, f"skillRefs.{ref.owner_id}"))
    items.append(("definition", revision.definition_id, "definition"))
    return tuple(items)


def _by_str_key(entry: tuple[object, object]) -> str:
    return str(entry[0])


def _declared_sets(
    revision: dto.DefinitionRevision,
) -> tuple[frozenset[str], str | None, frozenset[str], frozenset[str], str | None]:
    """The revision's own declarations, used when the authority is the only
    grant record (no local `Ceiling` value to intersect against)."""
    tools = frozenset(ref.owner_id for ref in revision.tool_refs)
    if revision.requested_permission is not None:
        tools = tools | {revision.requested_permission}
    model = None if revision.declared_model_ref is None else revision.declared_model_ref.owner_id
    mcp = frozenset(ref.owner_id for ref in revision.mcp_refs)
    skills = frozenset(ref.owner_id for ref in revision.skill_refs)
    mode: str | None = None
    for key, value in revision.retained_native_fields.items():
        if str(key).lower() in _PERMISSION_MODE_KEYS:
            mode = str(value)
    return tools, model, mcp, skills, mode


def _authority_of(
    ceiling: "Ceiling | CeilingAuthority",
) -> tuple[Ceiling | None, CeilingAuthority | None]:
    if isinstance(ceiling, Ceiling):
        return ceiling, ceiling.authority
    if hasattr(ceiling, "adjudicate") and hasattr(ceiling, "is_available"):
        return None, ceiling
    return None, None


def admit(
    revision: dto.DefinitionRevision,
    ceiling: "Ceiling | CeilingAuthority | None",
) -> AdmittedConfig:
    """Admit one revision against the authority, or refuse before any effect.

    A missing (`None`) authority is `ADAPTER_MISSING`: without the authority
    there is nothing to verify against, and the fail-closed answer is refusal,
    never a permissive default. A `Ceiling` value is checked as before; a
    `CeilingAuthority` (the real port behind `permissions_seam`) additionally
    has to admit every declared item, item by item.
    """
    if ceiling is None:
        raise errors.refused(
            errors.ADAPTER_MISSING,
            item_id=revision.definition_id,
            detail="permissions authority not injected; refusing instead of "
                   "defaulting to permissive",
        )
    granted, authority = _authority_of(ceiling)
    if granted is None and authority is None:
        raise errors.refused(
            errors.ADAPTER_MISSING,
            item_id=revision.definition_id,
            detail=f"{type(ceiling).__name__} is neither a recorded ceiling nor a "
                   "permissions authority; admission cannot proceed",
        )
    if revision.content_digest == "":
        raise errors.refused(
            errors.NATIVE_VERSION_UNKNOWN,
            item_id=revision.definition_id,
            detail="revision content is unverifiable; admission requires a digest",
        )

    if granted is not None:
        _check_mode_fields(revision, granted)
        _check_isolation(revision, granted)
        tools, model, mcp, skills = _check_sets(revision, granted)
        mode: str | None = None
        for key, value in revision.retained_native_fields.items():
            if str(key).lower() in _PERMISSION_MODE_KEYS:
                mode = str(value)
        evidence = [f"admitted against ceiling of {granted.principal.id}"]
    else:
        tools, model, mcp, skills, mode = _declared_sets(revision)
        evidence = []

    single_use: list[str] = []
    if authority is not None:
        if not authority.is_available():
            raise errors.refused(
                errors.ADAPTER_MISSING,
                item_id=f"{revision.definition_id}#r{revision.revision}",
                detail="the permissions authority is wired but cannot answer; "
                       "refusing instead of defaulting to permissive",
            )
        # The subject is the *service's* identity for this admission: the
        # recorded ceiling's principal/scope/harness when one is on hand, the
        # authority's own verified identity otherwise. Definition content never
        # supplies it.
        subject = (AdmissionContext.from_ceiling(granted, revision) if granted is not None
                   else authority.subject_for(revision))
        for kind, value, field_name in admission_items(revision):
            ruling = authority.adjudicate(subject, kind, value, field_name=field_name)
            if not ruling.admitted:
                raise ruling.refusal(revision)
            if not ruling.standing:
                single_use.append(ruling.field_name)
            evidence.append(
                f"{field_name}=admitted by permissions.authorizer@1"
                f"({'standing' if ruling.standing else 'single-use'},"
                f" {ruling.authority_code or 'unattributed'})"
            )
    return AdmittedConfig(
        definition_id=revision.definition_id,
        revision=revision.revision,
        effective_tools=tools,
        effective_model=model,
        effective_mcp=mcp,
        effective_skills=skills,
        approval_mode=mode,
        evidence=tuple(evidence),
        single_use_fields=tuple(single_use),
    )

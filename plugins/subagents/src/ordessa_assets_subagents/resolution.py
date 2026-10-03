"""The one deterministic resolver (FR03/FR04/FR10, gates G07/G08/G09).

Pure function over data: no I/O, no clock, no dict-iteration or timestamp
tie-breaks — Profile and Chat consume the same result and no frontend
re-implements the overlay algorithm (contracts §C1).

Layering per data-model §范围解释, low -> high:
user-global-generic -> user-global-harness -> project-generic ->
project-harness -> same-harness-profile -> session overlay.
A later layer may change an earlier layer's *ordinary* choice; managed
limits and real runtime permissions are verified separately (ceiling.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from . import ceiling as ceiling_mod
from . import dto, errors, limits
from .assignments import (
    ApprovalAuthority,
    Assignment,
    AssignmentDecision,
    disable_effect,
    validate_assignment,
)
from .digest import canonical_digest
from .references import (
    McpResolver,
    ModelResolver,
    ReferenceResolution,
    SkillResolver,
    ToolResolver,
    resolve_references,
)
from .scopes import (
    LAYER_ORDER,
    DefinitionOwnership,
    Diagnostic,
    Principal,
    ProfileId,
    ProjectId,
    ScopeKind,
    ServerScope,
    SessionId,
    ViewerScope,
    harness_binding_matches,
    visible_definition_ids,
)

RESERVED_NATIVE_NAMES = frozenset({"default", "main", "root", "self"})


@dataclass(frozen=True)
class NativeDefinitionObservation:
    """One entry of `inspectNative` (data-model shape); evidence-backed."""

    native_name: str
    scope: str
    source_category: str
    target_generation: str | None = None
    evidence: str | None = None
    suppressible: bool | None = None


@dataclass(frozen=True)
class _Unknown:
    def __repr__(self) -> str:
        return "UNKNOWN"


#: "no observation mechanism" is a different fact from "looked, found none"
#: (FR07: 没有观测机制记 unknown,不能报 false/true 或空表).
UNKNOWN = _Unknown()

NativeInspection = tuple[NativeDefinitionObservation, ...] | _Unknown


def inspect_native(
    observations: Sequence[NativeDefinitionObservation] | None,
) -> NativeInspection:
    if observations is None:
        return UNKNOWN
    return tuple(observations)


@dataclass(frozen=True)
class ResolutionRequest:
    server_scope: ServerScope
    principal: Principal
    harness_id: str
    project_id: ProjectId | None
    profile_id: ProfileId | None
    session_id: SessionId | None
    session_profile_id: ProfileId | None
    session_harness_id: str | None
    definitions: Mapping[str, dto.AgentDefinition]
    ownership: Mapping[str, DefinitionOwnership]
    revisions: Mapping[tuple[str, int], dto.DefinitionRevision]
    assignments: Sequence[Assignment]
    managed_definition_ids: frozenset[str]
    reserved_native_names: frozenset[str] = field(default=RESERVED_NATIVE_NAMES)
    native_observations: Sequence[NativeDefinitionObservation] | None = None
    ceiling: ceiling_mod.Ceiling | None = None

    def viewer(self) -> ViewerScope:
        return ViewerScope(
            principal=self.principal,
            server_scope=self.server_scope,
            project=self.project_id,
            profile_id=self.profile_id,
            session_id=self.session_id,
            session_profile_id=self.session_profile_id,
            session_harness_id=self.session_harness_id,
            harness_id=self.harness_id,
        )


@dataclass(frozen=True)
class ResolvedDefinition:
    definition_id: str
    revision: int
    native_name: str
    selected_by: ScopeKind
    effective_references: ReferenceResolution
    capability_evidence: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ExcludedDefinition:
    definition_id: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class EffectiveSet:
    """For every candidate: a selection or an explicit exclusion reason."""

    resolved: tuple[ResolvedDefinition, ...]
    excluded: tuple[ExcludedDefinition, ...]


def _layer_assignments(request: ResolutionRequest, definition_id: str) -> list[Assignment]:
    matched: list[Assignment] = []
    for assignment in request.assignments:
        if assignment.definition_id != definition_id:
            continue
        if assignment.principal.id != request.principal.id:
            continue
        if assignment.server_scope.id != request.server_scope.id:
            continue
        if not harness_binding_matches(
            target_harness_id=request.harness_id,
            assignment_harness_id=assignment.harness_id,
        ):
            continue
        if assignment.scope_kind in (ScopeKind.PROJECT, ScopeKind.PROJECT_HARNESS):
            if request.project_id is None or assignment.scope_id != request.project_id.id:
                continue
        elif assignment.scope_kind is ScopeKind.PROFILE:
            if request.profile_id is None or assignment.scope_id != request.profile_id.id:
                continue
        elif assignment.scope_kind is ScopeKind.SESSION:
            if request.session_id is None or assignment.scope_id != request.session_id.id:
                continue
        matched.append(assignment)
    return sorted(
        matched,
        key=lambda a: (LAYER_ORDER.index(a.scope_kind), a.scope_kind.value,
                       a.scope_id or "", a.harness_id),
    )


def _final_decision(
    request: ResolutionRequest,
    definition_id: str,
    approvals: ApprovalAuthority,
) -> tuple[Assignment | None, ExcludedDefinition | None]:
    """Walk low -> high; later layers change ordinary earlier choices.

    `inherit` is absence: it neither selects nor excludes. Two assignments
    on the same layer collide as ASSIGNMENT_CONFLICT — never a random
    winner (G07 counter-example: 层次碰撞随机胜出).
    """
    candidates = _layer_assignments(request, definition_id)
    seen_layers: set[ScopeKind] = set()
    winner: Assignment | None = None
    for assignment in candidates:
        if assignment.scope_kind in seen_layers:
            raise errors.refused(
                errors.ASSIGNMENT_CONFLICT,
                item_id=definition_id,
                detail=f"layer '{assignment.scope_kind.value}' carries two "
                       "assignments; resolution has no tie-break",
            )
        seen_layers.add(assignment.scope_kind)
        if assignment.decision is AssignmentDecision.INHERIT:
            continue
        winner = assignment
    if winner is None or winner.decision is AssignmentDecision.INHERIT:
        return None, None
    if winner.decision is AssignmentDecision.DISABLE:
        outcome = disable_effect(winner, managed_definition_ids=request.managed_definition_ids)
        if outcome.disabled:
            return None, ExcludedDefinition(
                definition_id,
                reason_code="disabled",
                detail=f"disable assigned at layer '{winner.scope_kind.value}'",
            )
        assert outcome.diagnostic is not None
        return None, ExcludedDefinition(
            definition_id,
            reason_code=outcome.diagnostic.code,
            detail="natively discovered item is still visible; it is not "
                   "reported as disabled (US5)",
        )
    validate_assignment(winner, approvals)
    return winner, None


def _check_profile_origin(request: ResolutionRequest, definition: dto.AgentDefinition) -> str | None:
    if definition.origin_scope != "profile":
        return None
    direct = request.profile_id is not None and request.profile_id.id == definition.origin_owner
    via_session = (
        request.session_profile_id is not None
        and request.session_profile_id.id == definition.origin_owner
        and request.session_harness_id == request.harness_id
    )
    if direct or via_session:
        return None
    return "profile-scoped definition is usable only by its profile and its legitimate same-harness sessions"


def resolve_preview(
    request: ResolutionRequest,
    *,
    approvals: ApprovalAuthority,
    models: ModelResolver | None = None,
    tools: ToolResolver | None = None,
    mcps: McpResolver | None = None,
    skills: SkillResolver | None = None,
) -> EffectiveSet:
    """Deterministic resolvePreview: EffectiveSet or a typed Refusal (§C1).

    Every refusal (conflict, ceiling, stale pin, aggregate cap) is raised
    before the EffectiveSet is returned, i.e. before any apply side effect.
    """
    ownership_view = {
        definition_id: request.ownership.get(definition_id)
        for definition_id in candidate_ids(request)
    }
    viewable, hidden = visible_definition_ids(ownership_view, request.viewer())
    resolved_by_name: dict[str, ResolvedDefinition] = {}
    excluded: list[ExcludedDefinition] = []
    for diagnostic in hidden:
        excluded.append(
            ExcludedDefinition(diagnostic.item_id, diagnostic.code, diagnostic.detail)
        )
    for definition_id in sorted(viewable):
        winner, exclusion = _final_decision(request, definition_id, approvals)
        if exclusion is not None:
            excluded.append(exclusion)
            continue
        if winner is None:
            continue
        definition = request.definitions[definition_id]
        ownership_problem = _check_profile_origin(request, definition)
        if ownership_problem is not None:
            excluded.append(
                ExcludedDefinition(definition_id, errors.ASSIGNMENT_CONFLICT, ownership_problem)
            )
            continue
        revision = request.revisions.get((definition_id, winner.revision))
        if revision is None:
            raise errors.refused(
                errors.REVISION_STALE,
                item_id=f"{definition_id}@{winner.revision}",
                detail="pinned revision is missing; failing closed before apply",
            )
        admitted = ceiling_mod.admit(revision, request.ceiling)
        reference_resolution = resolve_references(
            revision, models=models, tools=tools, mcps=mcps, skills=skills,
            fail_fast=True,
        )
        resolved = ResolvedDefinition(
            definition_id=definition_id,
            revision=winner.revision,
            native_name=definition.slug,
            selected_by=winner.scope_kind,
            effective_references=reference_resolution,
            capability_evidence=admitted.evidence,
            diagnostics=reference_resolution.diagnostics,
        )
        prior = resolved_by_name.get(resolved.native_name)
        if prior is not None:
            for clash in (prior, resolved):
                excluded.append(
                    ExcludedDefinition(
                        clash.definition_id,
                        errors.NATIVE_NAME_CONFLICT,
                        f"native name '{clash.native_name}' claimed by two definitions",
                    )
                )
            del resolved_by_name[resolved.native_name]
            continue
        resolved_by_name[resolved.native_name] = resolved
    result = _drop_native_and_reserved_collisions(request, resolved_by_name, excluded)
    _check_aggregate_caps(result, request)
    return result


def candidate_ids(request: ResolutionRequest) -> frozenset[str]:
    return frozenset(a.definition_id for a in request.assignments)


def _drop_native_and_reserved_collisions(
    request: ResolutionRequest,
    resolved_by_name: Mapping[str, ResolvedDefinition],
    excluded: list[ExcludedDefinition],
) -> EffectiveSet:
    names = dict(resolved_by_name)
    observed = (
        set()
        if request.native_observations is None
        else {observation.native_name for observation in request.native_observations}
    )
    for native_name in sorted(names):
        definition = names[native_name]
        if native_name in request.reserved_native_names:
            excluded.append(
                ExcludedDefinition(definition.definition_id, errors.NATIVE_NAME_CONFLICT,
                                   f"'{native_name}' is a reserved native name")
            )
            del names[native_name]
        elif native_name in observed:
            excluded.append(
                ExcludedDefinition(definition.definition_id, errors.NATIVE_NAME_CONFLICT,
                                   f"'{native_name}' collides with a natively "
                                   "discovered definition")
            )
            del names[native_name]
    return EffectiveSet(
        resolved=tuple(names[key] for key in sorted(names)),
        excluded=tuple(excluded),
    )


def _check_aggregate_caps(result: EffectiveSet, request: ResolutionRequest) -> None:
    """Total enabled count and description bytes, bounded *before* apply."""
    if len(result.resolved) > limits.MAX_ENABLED_DEFINITIONS:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id="__aggregate__",
            detail=f"{len(result.resolved)} enabled definitions exceed the cap "
                   f"of {limits.MAX_ENABLED_DEFINITIONS}",
        )
    total_description = sum(
        len(request.definitions[item.definition_id].description.encode("utf-8"))
        for item in result.resolved
    )
    if total_description > limits.MAX_AGGREGATE_DESCRIPTION_BYTES:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id="__aggregate__",
            detail="aggregate description size exceeds the cap that guards the "
                   "harness agent directory",
        )


@dataclass(frozen=True)
class DefinitionSnapshot:
    """One frozen commit-time fact set (FR04); immutable, digest-sealed."""

    principal: str
    project_id: str | None
    profile_id: str | None
    session_id: str | None
    runtime_generation: str
    profile_revision: int
    assignment_revisions: tuple[tuple[str, int], ...]
    definition_digests: tuple[tuple[str, int, str], ...]
    adapter_generation: str
    snapshot_digest: str


def build_snapshot(
    request: ResolutionRequest,
    effective: EffectiveSet,
    *,
    approvals: ApprovalAuthority,
    runtime_generation: str,
    profile_revision: int,
    adapter_generation: str,
) -> DefinitionSnapshot:
    """Pin everything a submission needs; fail closed *before* side effects.

    A missing pinned revision, an unapproved pin or a missing digest is
    REVISION_STALE: the caller never reaches an apply with a hole in it.
    """
    winning_rows: dict[str, int] = {}
    for definition_id in sorted(candidate_ids(request)):
        winner, _ = _final_decision(request, definition_id, approvals)
        if winner is not None:
            winning_rows[winner.key()] = winner.row_version
    digests: list[tuple[str, int, str]] = []
    resolved_ids = {item.definition_id for item in effective.resolved}
    for item in effective.resolved:
        revision = request.revisions.get((item.definition_id, item.revision))
        if revision is None or revision.content_digest == "":
            raise errors.refused(
                errors.REVISION_STALE,
                item_id=f"{item.definition_id}@{item.revision}",
                detail="pinned revision or its digest is missing; refusing to "
                       "freeze an incomplete snapshot",
            )
        digests.append((item.definition_id, item.revision, revision.content_digest))
    for item in effective.excluded:
        resolved_ids.discard(item.definition_id)
    if len(resolved_ids) != len(effective.resolved):
        raise errors.refused(
            errors.REVISION_STALE,
            item_id="__snapshot__",
            detail="effective set and pinned revisions disagree",
        )
    payload = {
        "principal": request.principal.id,
        "project": None if request.project_id is None else request.project_id.id,
        "profile": None if request.profile_id is None else request.profile_id.id,
        "session": None if request.session_id is None else request.session_id.id,
        "runtime_generation": runtime_generation,
        "profile_revision": profile_revision,
        "assignment_revisions": sorted(winning_rows.items()),
        "definition_digests": sorted(digests),
        "adapter_generation": adapter_generation,
    }
    return DefinitionSnapshot(
        principal=request.principal.id,
        project_id=None if request.project_id is None else request.project_id.id,
        profile_id=None if request.profile_id is None else request.profile_id.id,
        session_id=None if request.session_id is None else request.session_id.id,
        runtime_generation=runtime_generation,
        profile_revision=profile_revision,
        assignment_revisions=tuple(sorted((key, version) for key, version in winning_rows.items())),
        definition_digests=tuple(sorted(digests)),
        adapter_generation=adapter_generation,
        snapshot_digest=canonical_digest(payload),
    )

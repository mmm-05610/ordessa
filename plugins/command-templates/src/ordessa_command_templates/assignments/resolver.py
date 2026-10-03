"""Deterministic scoped resolution and conflict detection (T06, FR-03/07/08/12).

The chain is fixed and total — user-global → user-harness → project →
project-harness → profile → organisation policy — and a later layer only changes
the outcome when it *declares* something; an undeclared layer inherits, it does
not silently drop. A resolved entry is reported with its real state (available,
disabled, or absent-with-reason); an absence is explained, never collapsed into a
clean empty list (FR-08). A display-name collision between two distinct ids is
detected and surfaced, not resolved by layer order (FR-07).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from ..api.dto import Assignment, Target
from ..api.errors import NameConflictError
from ..library.store import TemplateStore

#: Lowest → highest precedence. Forced policy is applied above all layers.
LAYER_ORDER: "tuple[str, ...]" = (
    "user-global", "user-harness", "project", "project-harness", "profile",
)

#: A forced policy entry: template_id -> ("enable", revision) | ("disable", None).
OrgPolicy = Mapping[str, "tuple[str, Optional[int]]"]


@dataclass(frozen=True)
class EffectiveEntry:
    template_id: str
    display_name: str
    slug: str
    state: str                 # available | disabled | blocked-policy | unavailable
    source: Optional[str]      # the winning layer, or the policy
    scope_identity: Optional[str]
    pinned_revision: Optional[int]
    reason: Optional[str] = None   # a real absence/disabled reason (FR-08)


@dataclass(frozen=True)
class Resolution:
    available: "tuple[EffectiveEntry, ...]"
    excluded: "tuple[EffectiveEntry, ...]"
    conflicts: "tuple[str, ...]"        # slugs claimed by more than one id
    conflict_detail: "tuple[tuple[str, tuple[str, ...]], ...]" = ()


def _applies(assignment: Assignment, target: Target) -> bool:
    if assignment.scope == "user-global":
        return assignment.scope_identity == target.principal
    if assignment.scope == "user-harness":
        return (assignment.scope_identity == target.principal
                and assignment.harness_id is not None
                and assignment.harness_id == target.harness_id)
    if assignment.scope == "project":
        return target.project_id is not None and assignment.scope_identity == target.project_id
    if assignment.scope == "project-harness":
        return (target.project_id is not None
                and assignment.scope_identity == target.project_id
                and assignment.harness_id is not None
                and assignment.harness_id == target.harness_id)
    if assignment.scope == "profile":
        return target.profile_id is not None and assignment.scope_identity == target.profile_id
    return False


def resolve_effective(store: TemplateStore, target: Target,
                      assignments: Optional[Sequence[Assignment]] = None,
                      *, org_policy: Optional[OrgPolicy] = None) -> Resolution:
    """Resolve what the ``target`` may use, with source and honest absence."""
    rows = list(assignments) if assignments is not None else store.assignments()
    # Only assignments that apply to this target participate.
    applicable: "dict[str, dict]" = {}
    for assignment in rows:
        if not _applies(assignment, target):
            continue
        if assignment.scope == "profile" and target.profile_revision is None:
            continue  # a profile layer needs a concrete revision to apply
        layer = LAYER_ORDER.index(assignment.scope)
        current = applicable.get(assignment.template_id)
        # Highest-precedence explicit declaration wins; ties broken deterministically.
        if current is None or layer > current["layer"]:
            applicable[assignment.template_id] = {"layer": layer, "assignment": assignment}

    available: list[EffectiveEntry] = []
    excluded: list[EffectiveEntry] = []
    for template_id, chosen in applicable.items():
        assignment: Assignment = chosen["assignment"]
        entry = _resolve_one(store, template_id, assignment, chosen["layer"])
        # Forced policy overrides the user's declaration entirely.
        forced = (org_policy or {}).get(template_id)
        if forced is not None:
            entry = _apply_policy(store, template_id, forced, entry)
        (available if entry.state == "available" else excluded).append(entry)

    ordered = sorted(available + excluded, key=lambda e: (e.slug, e.template_id))
    conflicts = _detect_conflicts([e for e in ordered if e.state == "available"])
    conflict_detail = tuple(
        (slug, tuple(sorted(ids))) for slug, ids in _slug_groups(ordered).items()
        if len(set(ids)) > 1)
    return Resolution(
        available=tuple(e for e in ordered if e.state == "available"),
        excluded=tuple(e for e in ordered if e.state != "available"),
        conflicts=tuple(sorted(conflicts)),
        conflict_detail=conflict_detail,
    )


def _resolve_one(store: TemplateStore, template_id: str, assignment: Assignment,
                 layer: int) -> EffectiveEntry:
    source = LAYER_ORDER[layer]
    display_name, slug = store.display_of(template_id)
    if assignment.state == "disable":
        return EffectiveEntry(template_id, display_name, slug, "disabled", source,
                              assignment.scope_identity, None, reason="DISABLED_BY_PREFERENCE")
    revision = assignment.pinned_revision
    try:
        tmpl = store.get_template(template_id)
    except Exception:  # pragma: no cover - assignment already validated the id
        return EffectiveEntry(template_id, display_name, slug, "unavailable", source,
                              assignment.scope_identity, revision, reason="CONTENT_MISSING")
    if tmpl.is_archived:
        return EffectiveEntry(template_id, display_name, slug, "unavailable", source,
                              assignment.scope_identity, revision, reason="ARCHIVED")
    if not store.is_approved(template_id, revision):
        return EffectiveEntry(template_id, display_name, slug, "unavailable", source,
                              assignment.scope_identity, revision, reason="REVISION_UNAPPROVED")
    return EffectiveEntry(template_id, display_name, slug, "available", source,
                          assignment.scope_identity, revision)


def _apply_policy(store: TemplateStore, template_id: str,
                  forced: "tuple[str, Optional[int]]", base: EffectiveEntry) -> EffectiveEntry:
    display_name, slug = store.display_of(template_id)
    state, revision = forced
    if state == "disable":
        return EffectiveEntry(template_id, display_name, slug, "blocked-policy",
                              "org-policy", base.scope_identity, None,
                              reason="FORCED_DISABLED_BY_POLICY")
    # Forced enable pins a specific revision the policy mandates.
    try:
        tmpl = store.get_template(template_id)
    except Exception:  # pragma: no cover
        return EffectiveEntry(template_id, display_name, slug, "unavailable",
                              "org-policy", base.scope_identity, revision, reason="CONTENT_MISSING")
    if tmpl.is_archived or not store.is_approved(template_id, revision):
        return EffectiveEntry(template_id, display_name, slug, "unavailable",
                              "org-policy", base.scope_identity, revision,
                              reason="POLICY_REVISION_NOT_APPROVABLE")
    return EffectiveEntry(template_id, display_name, slug, "available", "org-policy",
                          base.scope_identity, revision)


def _slug_groups(entries: Sequence[EffectiveEntry]) -> "dict[str, list[str]]":
    groups: "dict[str, list[str]]" = {}
    for entry in entries:
        groups.setdefault(entry.slug, []).append(entry.template_id)
    return groups


def _detect_conflicts(entries: Sequence[EffectiveEntry]) -> "list[str]":
    """Slugs claimed by more than one *distinct* id among available items.

    Namespaced ids (``template:<slug>``) and display names never claim a bare
    ``/slug`` route, so a collision here is surfaced for the menu to disambiguate,
    never resolved by silently dropping a layer (FR-07 / gate G12).
    """
    return [slug for slug, ids in _slug_groups(entries).items() if len(set(ids)) > 1]

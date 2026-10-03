"""Tri-state assignment decisions (FR02, US5, gates G07/G08).

`inherit` is the *absence* of a decision at a layer, never a wildcard.
`enable` must pin an already-approved revision; `disable` only ever acts on
a managed item — disabling a natively-discovered definition yields a typed
`NATIVE_DISCOVERY_UNCONTROLLED` diagnostic instead of a fake "disabled"
state (US5: "无法遮蔽的项目原生项仍可见").

Error-code usage here:
- ``enable`` with no revision      -> DEFINITION_INVALID (malformed decision)
- ``enable`` with an unapproved revision -> ASSIGNMENT_CONFLICT (upgrade not
  separately approved; approve_assignment_update semantics)
- ``disable`` of a native-only item -> returned diagnostic, never raised as
  a disabled state
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from . import dto, errors
from .scopes import ANY_HARNESS, Diagnostic, Principal, ScopeKind, ServerScope


class AssignmentDecision(str, Enum):
    INHERIT = "inherit"
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(frozen=True)
class Assignment:
    server_scope: ServerScope
    principal: Principal
    scope_kind: ScopeKind
    scope_id: str | None
    harness_id: str
    definition_id: str
    decision: AssignmentDecision
    revision: int | None = None
    row_version: int = 0

    def key(self) -> str:
        return f"{self.scope_kind.value}:{self.scope_id or ''}:{self.definition_id}"


class ApprovalAuthority(Protocol):
    """Answers "was exactly this revision of this definition approved?".

    Injected by the caller; there is deliberately no default so an absent
    authority can never wave an assignment through.
    """

    def has_approved_revision(self, definition_id: str, revision: int) -> bool: ...


@dataclass(frozen=True)
class DisableOutcome:
    """Honest result of a `disable`: managed items drop, native items do not."""

    definition_id: str
    disabled: bool
    diagnostic: Diagnostic | None


def disable_effect(
    assignment: Assignment,
    *,
    managed_definition_ids: frozenset[str],
) -> DisableOutcome:
    if assignment.decision is not AssignmentDecision.DISABLE:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id=assignment.definition_id,
            detail="disable_effect requires a disable decision",
        )
    if assignment.definition_id in managed_definition_ids:
        return DisableOutcome(assignment.definition_id, disabled=True, diagnostic=None)
    return DisableOutcome(
        assignment.definition_id,
        disabled=False,
        diagnostic=Diagnostic(
            errors.NATIVE_DISCOVERY_UNCONTROLLED,
            item_id=assignment.definition_id,
            detail="item is natively discovered; it stays visible and cannot be "
                   "reported as disabled",
        ),
    )


def validate_assignment(
    assignment: Assignment,
    approvals: ApprovalAuthority,
) -> Assignment:
    """Gate an assignment before it is stored (G07/G08 counter-examples)."""
    if not assignment.definition_id:
        raise errors.refused(errors.DEFINITION_INVALID, item_id="assignment",
                             detail="definition_id is required")
    if assignment.harness_id == "":
        raise errors.refused(errors.DEFINITION_INVALID, item_id=assignment.definition_id,
                             detail="harness_id must be a brand or 'any'")
    if assignment.decision is AssignmentDecision.INHERIT:
        return assignment
    if assignment.decision is AssignmentDecision.ENABLE:
        if assignment.revision is None:
            raise errors.refused(
                errors.DEFINITION_INVALID,
                item_id=assignment.definition_id,
                detail="enable must pin an approved revision; a floating enable "
                       "would silently follow content edits",
            )
        if not approvals.has_approved_revision(assignment.definition_id, assignment.revision):
            raise errors.refused(
                errors.ASSIGNMENT_CONFLICT,
                item_id=f"{assignment.definition_id}@{assignment.revision}",
                detail="pinned revision has no approval record; each upgrade needs "
                       "its own approval",
            )
        return assignment
    if assignment.revision is not None and not approvals.has_approved_revision(
        assignment.definition_id, assignment.revision
    ):
        raise errors.refused(
            errors.ASSIGNMENT_CONFLICT,
            item_id=f"{assignment.definition_id}@{assignment.revision}",
            detail="referenced revision has no approval record",
        )
    return assignment


def pinned_revision(
    assignment: Assignment,
    definition: dto.AgentDefinition,
) -> int:
    """The revision an `enable` resolves to: its pin, never the newest one.

    Publishing revision N+1 must not move an `enable(revision=N)` binding
    (FR02 "编辑不自动更新固定分配", G08 counter-example).
    """
    if assignment.decision is not AssignmentDecision.ENABLE:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id=assignment.definition_id,
            detail="only an enable assignment pins a revision",
        )
    if assignment.revision is None:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id=assignment.definition_id,
            detail="enable assignment lost its pinned revision",
        )
    if assignment.definition_id != definition.definition_id:
        raise errors.refused(
            errors.DEFINITION_INVALID,
            item_id=assignment.definition_id,
            detail="assignment pins a different definition",
        )
    return assignment.revision


def approve_assignment_update(
    existing: Assignment | None,
    desired: Assignment,
    *,
    expected_row_version: int | None,
    approvals: ApprovalAuthority,
) -> Assignment:
    """One separately-approved upgrade: CAS on the assignment row version.

    `expected_row_version` is None only when creating where nothing exists;
    a stale expectation yields REVISION_STALE and writes nothing.
    """
    validate_assignment(desired, approvals)
    current_version = 0 if existing is None else existing.row_version
    if expected_row_version is None:
        if existing is not None:
            raise errors.refused(
                errors.REVISION_STALE,
                item_id=desired.key(),
                detail="assignment already exists; an upgrade must carry the "
                       "expected row version",
            )
    elif existing is None or existing.row_version != expected_row_version:
        raise errors.refused(
            errors.REVISION_STALE,
            item_id=desired.key(),
            detail="expected row version does not match the stored assignment",
        )
    return replace(desired, row_version=current_version + 1)


def is_generic_layer(harness_id: str) -> bool:
    return harness_id == ANY_HARNESS

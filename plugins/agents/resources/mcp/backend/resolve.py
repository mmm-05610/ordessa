"""Effective-snapshot resolution (pure read; no side effects, no spawn).

Merge order follows Skills:
``user-default/any -> user-default/harness -> project/any -> project/harness
-> profile -> session``. A later layer may re-enable what an earlier layer
disabled, but only if the definition is not under a higher administrator
prohibition (``policy_denied`` input - the T06 Permission authority seam) and
the bound revision carries an approval record. Session overrides live only on
session rows and never write back to Profile.

Tool visibility never widens automatically: an ``allObserved`` selection is
frozen to its bound catalog digest, ``allowNames`` stays a subset of the
approved revision's observed catalog, and a drifted current catalog only
marks the snapshot ``needs-revalidation``. Native-lane entries whose host
cannot prove the reduced exposure/enforcement are downgraded to
``enforcement: "unproven"`` in the snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Sequence, Tuple

from .assignment import McpAssignment, McpAssignmentStore
from .definition import McpRevision, SecretRef, definition_digest
from .definition_store import McpDefinitionStore
from .errors import McpError

_ENFORCEMENT_PROVEN = "proven"
_ENFORCEMENT_UNPROVEN = "unproven"

LAYERS: Tuple[Tuple[str, str], ...] = (
    ("user-default", "any"),
    ("user-default", "harness"),
    ("project", "any"),
    ("project", "harness"),
    ("profile", "any"),
    ("session", "any"),
)


@dataclass(frozen=True)
class McpEffectiveSnapshot:
    target_session: Optional[str]
    runtime_generation: Optional[int]
    project_id: Optional[str]
    profile_revision: Optional[str]
    definition_revisions: Tuple[Mapping[str, object], ...]
    assignment_revisions: Tuple[Mapping[str, object], ...]
    credential_ref_revisions: Tuple[Mapping[str, object], ...]
    allowed_tool_names: Tuple[str, ...]
    lane_by_definition: Mapping[str, Mapping[str, str]]
    needs_revalidation: Tuple[str, ...]
    snapshot_digest: str
    submission_id: Optional[str] = None

    def content_for_digest(self) -> dict:
        return {
            "target_session": self.target_session,
            "runtime_generation": self.runtime_generation,
            "project_id": self.project_id,
            "profile_revision": self.profile_revision,
            "definition_revisions": [dict(e) for e in self.definition_revisions],
            "assignment_revisions": [dict(e) for e in self.assignment_revisions],
            "credential_ref_revisions": [dict(e) for e in self.credential_ref_revisions],
            "allowed_tool_names": list(self.allowed_tool_names),
            "lane_by_definition": {k: dict(v) for k, v in self.lane_by_definition.items()},
            "needs_revalidation": list(self.needs_revalidation),
        }


def _snapshot_digest(snapshot: McpEffectiveSnapshot) -> str:
    return definition_digest(snapshot.content_for_digest())


def _revision_secret_refs(revision: McpRevision) -> list:
    transport = revision.transport
    if hasattr(transport, "env"):
        values = transport.env
    else:
        values = transport.headers
    return [
        {"definition_id": revision.definition_id, "revision": revision.revision,
         "slot": name, "credential_id": value.credential_id}
        for name, value in sorted(values.items())
        if isinstance(value, SecretRef)
    ]


def _layer_rows(
    rows: Sequence[McpAssignment], scope_kind: str, scope_id: Optional[str],
    harness_mode: str, harness: Optional[str],
) -> list:
    wanted_harness = harness if harness_mode == "harness" else "any"
    if scope_id is None:
        return []
    return [
        row for row in rows
        if row.scope_kind == scope_kind and row.scope_id == scope_id
        and row.harness == wanted_harness
    ]


def resolve_preview(
    *, server_scope: str, principal: str, assignments: McpAssignmentStore,
    definitions: McpDefinitionStore, harness: Optional[str] = None,
    project_id: Optional[str] = None, profile_revision: Optional[str] = None,
    session_ref: Optional[str] = None, target_session: Optional[str] = None,
    runtime_generation: Optional[int] = None,
    catalog_provider: Optional[Callable[[str, int], Optional[Mapping[str, object]]]] = None,
    policy_denied: Sequence[str] = (),
    lane_by_definition: Optional[Mapping[str, str]] = None,
    native_enforcement_proven: Sequence[str] = (),
) -> McpEffectiveSnapshot:
    """Preview the effective MCP set for one target. Read-only, deterministic.

    ``catalog_provider(definition_id, revision)`` returns the latest observed
    catalog ``{"catalogDigest": .., "toolNames": [..]}`` or ``None`` (nothing
    observed yet). Before T03 it is injected; when absent, no drift is
    asserted. ``policy_denied`` is the reserved hook for the T06 Permission
    authority: definition ids no layer may re-enable.
    """
    if lane_by_definition is None:
        lane_by_definition = {}
    denied = set(policy_denied)
    proven = set(native_enforcement_proven)
    # list_for already isolates by server scope and principal.
    rows = assignments.list_for(server_scope=server_scope, principal=principal)
    state: dict = {}
    for scope_kind, harness_mode in LAYERS:
        scope_id = {
            "user-default": principal, "project": project_id,
            "profile": profile_revision, "session": session_ref,
        }[scope_kind]
        for row in _layer_rows(rows, scope_kind, scope_id, harness_mode, harness):
            if row.decision == "enable":
                state[row.definition_id] = row
            else:
                state.pop(row.definition_id, None)

    definition_entries = []
    assignment_entries = []
    credential_entries = []
    allowed = set()
    needs_revalidation = []
    lanes: dict = {}
    for definition_id in sorted(state):
        row = state[definition_id]
        if definition_id in denied:
            continue
        try:
            revision = definitions.read_revision(
                server_scope=server_scope, definition_id=definition_id,
                revision=int(row.approved_revision))
        except McpError:
            continue
        if revision.approval is None:
            continue
        definition_entries.append({
            "definition_id": definition_id,
            "revision": revision.revision,
            "canonical_digest": revision.canonical_digest,
            "canonical_shape": revision.canonical_shape,
        })
        assignment_entries.append({
            "definition_id": definition_id, "scope_kind": row.scope_kind,
            "scope_id": row.scope_id, "harness": row.harness,
            "decision": row.decision, "row_version": row.row_version,
        })
        credential_entries.extend(_revision_secret_refs(revision))
        names = set(row.tool_selection.names) if row.tool_selection else set()
        allowed |= names
        if row.tool_selection is not None and catalog_provider is not None:
            current = catalog_provider(definition_id, int(row.approved_revision))
            if (current is not None
                    and current.get("catalogDigest") != row.tool_selection.catalog_digest):
                needs_revalidation.append(definition_id)
        lane = lane_by_definition.get(definition_id, "managed")
        if lane == "native" and definition_id not in proven:
            lanes[definition_id] = {"lane": lane, "enforcement": _ENFORCEMENT_UNPROVEN}
        else:
            lanes[definition_id] = {"lane": lane, "enforcement": _ENFORCEMENT_PROVEN}

    snapshot = McpEffectiveSnapshot(
        target_session=target_session if target_session is not None else session_ref,
        runtime_generation=runtime_generation,
        project_id=project_id,
        profile_revision=profile_revision,
        definition_revisions=tuple(definition_entries),
        assignment_revisions=tuple(assignment_entries),
        credential_ref_revisions=tuple(credential_entries),
        allowed_tool_names=tuple(sorted(allowed)),
        lane_by_definition=lanes,
        needs_revalidation=tuple(sorted(needs_revalidation)),
        snapshot_digest="",
        submission_id=None,
    )
    return replace(snapshot, snapshot_digest=_snapshot_digest(snapshot))

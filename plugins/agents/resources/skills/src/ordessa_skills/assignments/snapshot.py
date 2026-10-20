"""The frozen `SkillSnapshot` (FR08, verification.md G18 freeze side;
data-model.md §解析顺序 last paragraph).

    SkillSnapshot: targetSession, runtimeGeneration, projectId,
                   profileRevision, assignmentRevisions, resolvedSkills,
                   snapshotDigest

Construction reads each layer's row versions in ONE SQLite transaction —
that is :func:`ordessa_skills.assignments.resolver.resolve_effective`'s
single read snapshot — and digests the outcome deterministically:
resolvedSkills sorted by assetId, assignmentRevisions sorted by layer key,
canonical JSON (``sort_keys``, fixed separators, ASCII), sha256 hex with
the domain's ``sha256:`` spelling. Same inputs ⇒ byte-identical digest,
independent of insertion order (test-asserted).

G18's freeze rule (提交时冻结集合…失效/冲突在任何原生写入前拒绝):
:func:`matches_frozen` re-runs the SAME shared resolution and compares
assignment row versions, the Profile revision identity and the resolved
asset→revision pins; :func:`assert_apply_eligible` turns a moved layer into
the typed ``SNAPSHOT_STALE`` refusal. Only the pure-decision side is owned
here: the actual apply (原生写入 + prompt 一次发送) is blocked on C0's
harness-api plan/apply/reconcile (api-requests.md §G2) and is deliberately
NOT faked in this slice (AGENTS.md rule 9).

Cross-domain honesty (data-model: 跨业务 DB 无伪造原子性): the Profile
layer lives in another store, so its identity is *frozen as read* and
re-checked at apply time, exactly like the assignment versions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..api.errors import AssetDomainError
from .resolver import Resolution, SkillsResolutionService

#: Canonical-JSON digest envelope tag; part of the pre-image so a digest is
#: never accidentally shared with another domain's identical payload shape.
DIGEST_DOMAIN = "ordessa-skills-snapshot-v1"


class SnapshotError(AssetDomainError):
    """One snapshot/freeze operation was refused (codes:
    ``SNAPSHOT_STALE``, ``SNAPSHOT_TARGET_MISMATCH``)."""


def canonical_digest(payload: Mapping[str, Any]) -> str:
    """The deterministic digest: sorted-key canonical JSON, UTF-8, sha256."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SkillSnapshot:
    target_session: str
    runtime_generation: int
    project_id: str | None
    profile_revision: Mapping[str, Any] | None
    #: layer key -> row version, as read in the ONE resolution transaction
    assignment_revisions: Mapping[str, int]
    #: the frozen pin list the apply side consumes after its freshness check
    resolved_skills: tuple[Mapping[str, Any], ...]
    snapshot_digest: str

    def view(self) -> dict[str, Any]:
        return {
            "targetSession": self.target_session,
            "runtimeGeneration": self.runtime_generation,
            "projectId": self.project_id,
            "profileRevision": (dict(self.profile_revision)
                                if self.profile_revision else None),
            "assignmentRevisions": dict(self.assignment_revisions),
            "resolvedSkills": [dict(item) for item in self.resolved_skills],
            "snapshotDigest": self.snapshot_digest,
        }


def _digest_payload(*, target_session: str, runtime_generation: int,
                    project_id: str | None, profile_revision: Any,
                    assignment_revisions: Mapping[str, int],
                    resolved_skills: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "domain": DIGEST_DOMAIN,
        "targetSession": target_session,
        "runtimeGeneration": runtime_generation,
        "projectId": project_id,
        "profileRevision": dict(profile_revision) if profile_revision else None,
        # stable ordering on BOTH collections: insertion order must never
        # move a byte of the digest (test: digest stability).
        "assignmentRevisions": dict(sorted(assignment_revisions.items())),
        "resolvedSkills": sorted(
            ({"assetId": item["assetId"], "revision": item["revision"],
              "treeDigest": item["treeDigest"]} for item in resolved_skills),
            key=lambda item: item["assetId"]),
    }


def build_snapshot(resolution: Resolution) -> SkillSnapshot:
    """Freeze one resolution into the snapshot row of data-model.md.

    Pure function of the resolution — no second read, so the versions the
    snapshot carries are exactly the ones the shared algorithm saw inside
    its single transaction (FR08)."""
    resolved = [
        {"assetId": item["assetId"], "revision": item["revision"],
         "treeDigest": item["treeDigest"]}
        for item in resolution.included
    ]
    payload = _digest_payload(
        target_session=resolution.target.session_ref,
        runtime_generation=resolution.target.runtime_generation,
        project_id=resolution.target.project_id,
        profile_revision=resolution.profile_revision,
        assignment_revisions=resolution.assignment_revisions,
        resolved_skills=resolved,
    )
    return SkillSnapshot(
        target_session=resolution.target.session_ref,
        runtime_generation=resolution.target.runtime_generation,
        project_id=resolution.target.project_id,
        profile_revision=(dict(resolution.profile_revision)
                          if resolution.profile_revision else None),
        assignment_revisions=dict(resolution.assignment_revisions),
        resolved_skills=tuple(resolved),
        snapshot_digest=canonical_digest(payload),
    )


def matches_frozen(snapshot: SkillSnapshot, service: SkillsResolutionService,
                   target: Any) -> bool:
    """True while nothing the freeze pinned has moved: every assignment row
    still at the frozen version, the Profile identity unchanged, and the
    same assetIds resolved to the same revisions.

    Re-runs the SAME shared algorithm (one instance serving preview and
    plan) against current state — that is what makes the comparison about
    semantics, not about stored bytes."""
    if (target.session_ref != snapshot.target_session
            or target.runtime_generation != snapshot.runtime_generation
            or target.project_id != snapshot.project_id):
        raise SnapshotError(
            "SNAPSHOT_TARGET_MISMATCH",
            "the snapshot was frozen for a different target",
            detail=snapshot.target_session)
    current = service.effective(target)
    if dict(current.assignment_revisions) != dict(snapshot.assignment_revisions):
        return False
    if (dict(current.profile_revision or {}) !=
            dict(snapshot.profile_revision or {})):
        return False
    current_pins = sorted(
        ((item["assetId"], int(item["revision"])) for item in current.included))
    frozen_pins = sorted(((item["assetId"], int(item["revision"]))
                          for item in snapshot.resolved_skills))
    return current_pins == frozen_pins


def assert_apply_eligible(snapshot: SkillSnapshot,
                          service: SkillsResolutionService, target: Any) -> None:
    """The G18/FR08 refusal gate on the decision side: any moved revision
    (assignment row bumped, Profile identity replaced, resolution shifted)
    is refused BEFORE any native write happens. The write/apply path itself
    belongs to C0's harness-api and is intentionally absent here."""
    if not matches_frozen(snapshot, service, target):
        raise SnapshotError(
            "SNAPSHOT_STALE",
            "an assignment or profile revision moved after the snapshot was "
            "frozen; the apply is refused before any native write "
            "(FR08/G18)")

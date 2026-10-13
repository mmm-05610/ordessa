"""Closed review targets and existing deterministic set identity."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Literal
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from .refs import SubmissionRef
SubjectRef = ArtifactRevisionRef | ProposalRef | SubmissionRef | RepositorySnapshotRef

@dataclass(frozen=True)
class Target:
    role: Literal["primary", "base", "proposed", "output", "support"]
    ref: SubjectRef

    def __post_init__(self):
        if type(self.role) is not str or self.role not in {"primary", "base", "proposed", "output", "support"} or type(self.ref) not in {ArtifactRevisionRef, ProposalRef, SubmissionRef, RepositorySnapshotRef}:
            raise ReferenceError("INVALID_SCHEMA")


def _target_key(target: Target) -> tuple:
    ref = target.ref
    if type(ref) is ArtifactRevisionRef:
        stable, version, digest = ref.artifact_id, ref.revision_id, ref.digest.hex
    elif type(ref) is ProposalRef:
        stable, version, digest = ref.change_id, ref.proposal_id, ref.digest.hex
    elif type(ref) is SubmissionRef:
        stable, version, digest = ref.submission_id, ref.submission_id, ref.digest.hex
    else:
        stable, version, digest = ref.repository_id, ref.commit_id or "", ref.tree_digest.hex
    return target.role, ref.kind, stable, version, digest


@dataclass(frozen=True)
class TargetSet:
    targets: tuple[Target, ...]
    digest: Digest = field(init=False)

    def __post_init__(self):
        if type(self.targets) is not tuple or not self.targets or any(type(t) is not Target for t in self.targets):
            raise ReferenceError("INVALID_SCHEMA")
        scope = {(t.ref.realm_id, t.ref.project_id) for t in self.targets}
        if len(scope) != 1:
            raise ReferenceError("REALM_MISMATCH")
        identities = [_target_key(t)[:3] for t in self.targets]
        if len(set(identities)) != len(identities):
            raise ReferenceError("DUPLICATE_TARGET")
        ordered = tuple(sorted(self.targets, key=_target_key))
        object.__setattr__(self, "targets", ordered)
        object.__setattr__(self, "digest", record_digest("target-set", {"targets": [asdict(t) for t in ordered]}))

"""Closed review targets and existing deterministic set identity."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Literal
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.mechanisms.codec import projection
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.artifacts.provenance import SourceRef, VersionCapture
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from .refs import SubmissionRef
@dataclass(frozen=True)
class SourceTargetRef:
    """A scope-bound external source pin; this is not a material record."""
    scope: Scope
    source_ref: SourceRef
    kind: Literal["external_source"] = field(default="external_source", init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.source_ref) is not SourceRef
                or type(self.source_ref.capture) is not VersionCapture):
            raise ReferenceError("INVALID_SCHEMA")

    def __canonical_projection__(self, *, identity=False):
        if identity:
            return {"kind": self.kind, "scope": projection(self.scope, identity=True),
                    "content_identity": projection(self.source_ref.content_identity, identity=True)}
        return {"kind": self.kind, "scope": projection(self.scope),
                "source_ref": projection(self.source_ref)}


SubjectRef = ArtifactRevisionRef | ProposalRef | SubmissionRef | RepositorySnapshotRef | SourceTargetRef

@dataclass(frozen=True)
class Target:
    role: Literal["primary", "base", "proposed", "output", "support"]
    ref: SubjectRef

    def __post_init__(self):
        if type(self.role) is not str or self.role not in {"primary", "base", "proposed", "output", "support"} or type(self.ref) not in {ArtifactRevisionRef, ProposalRef, SubmissionRef, RepositorySnapshotRef, SourceTargetRef}:
            raise ReferenceError("INVALID_SCHEMA")

    @classmethod
    def external(cls, role, scope, source_ref):
        return cls(role, SourceTargetRef(scope, source_ref))


def _target_key(target: Target) -> tuple:
    ref = target.ref
    if type(ref) is ArtifactRevisionRef:
        stable, version, digest = ref.artifact_id, ref.revision_id, ref.digest.hex
    elif type(ref) is ProposalRef:
        stable, version, digest = ref.change_id, ref.proposal_id, ref.digest.hex
    elif type(ref) is SubmissionRef:
        stable, version, digest = ref.submission_id, ref.submission_id, ref.digest.hex
    elif type(ref) is SourceTargetRef:
        capture = ref.source_ref.capture
        stable = canonical_bytes(projection(ref.source_ref.locator, identity=True)).decode("utf-8")
        version, digest = capture.upstream_version, capture.content_digest.hex
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
        scope = {
            (t.ref.scope.realm_id, t.ref.scope.project_id)
            if type(t.ref) is SourceTargetRef else (t.ref.realm_id, t.ref.project_id)
            for t in self.targets
        }
        if len(scope) != 1:
            raise ReferenceError("REALM_MISMATCH")
        identities = [_target_key(t) if type(t.ref) is SourceTargetRef else _target_key(t)[:3]
                      for t in self.targets]
        if len(set(identities)) != len(identities):
            raise ReferenceError("DUPLICATE_TARGET")
        ordered = tuple(sorted(self.targets, key=_target_key))
        object.__setattr__(self, "targets", ordered)
        if any(type(t.ref) is SourceTargetRef for t in ordered):
            payload = {"targets": [
                {"role": t.role, "external_source": {
                    "scope": asdict(t.ref.scope),
                    "content_identity": projection(t.ref.source_ref.content_identity, identity=True),
                }} if type(t.ref) is SourceTargetRef else asdict(t)
                for t in ordered
            ]}
        else:
            payload = {"targets": [asdict(t) for t in ordered]}
        object.__setattr__(self, "digest", record_digest("target-set", payload))

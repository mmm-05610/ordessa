"""Application snapshot storage / released-identity ports; DTOs do not authenticate."""
from typing import Protocol
from ...methods.definitions.models import BlobRef, MethodRef, MethodSnapshot

__all__ = ['SnapshotStore', 'ReleasedIdentityIndex']


class SnapshotStore(Protocol):
    def put_blob(self, digest: str, media_type: str, raw_bytes: bytes) -> BlobRef: ...
    def publish(self, snapshot: MethodSnapshot) -> MethodRef: ...
    def get(self, ref: MethodRef) -> MethodSnapshot: ...


class ReleasedIdentityIndex(Protocol):
    def get_digest(self, method_id: str, release_version: str) -> str | None: ...


from dataclasses import dataclass
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import validate_id, validate_version
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.reviews.targets import Target, TargetSet


@dataclass(frozen=True)
class EngineeringTargetBindings:
    """Resolved business inputs to E7 conversion; never authentication facts.

    Document labels and available slots must come from the configured original
    owner. Numeric versions preserve domain projection identities; exact source
    resource digests, not integer coercion, bind external standard revisions.
    """
    scope: Scope
    targets: TargetSet
    document_types: tuple[tuple[Target, str], ...]
    input_slots: tuple[str, ...]
    eligible_reviewer_roles: tuple[str, ...]
    phase_key: str
    requirement_version: int = 1
    criterion_set_version: int = 1
    workflow_node_id: str | None = None
    review_purpose: str | None = None

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.targets) is not TargetSet:
            raise ReferenceError('INVALID_SCHEMA')
        if any((t.ref.realm_id,t.ref.project_id)!=(self.scope.realm_id,self.scope.project_id) for t in self.targets.targets):
            raise ReferenceError('REALM_MISMATCH')
        if type(self.document_types) is not tuple or any(type(p) is not tuple or len(p)!=2 or type(p[0]) is not Target or type(p[1]) is not str for p in self.document_types):
            raise ReferenceError('INVALID_SCHEMA')
        labels=dict(self.document_types)
        if len(labels)!=len(self.document_types) or set(labels)!=set(self.targets.targets):
            raise ReferenceError('INCOMPLETE_BATCH')
        for names in (self.input_slots,self.eligible_reviewer_roles):
            if type(names) is not tuple or any(type(n) is not str for n in names) or len(set(names))!=len(names):
                raise ReferenceError('INVALID_SCHEMA')
            for name in names: validate_id(name)
        if not self.eligible_reviewer_roles:
            raise ReferenceError('INVALID_SCHEMA')
        for label in labels.values(): validate_id(label)
        object.__setattr__(self,'input_slots',tuple(sorted(self.input_slots)))
        object.__setattr__(self,'eligible_reviewer_roles',tuple(sorted(self.eligible_reviewer_roles)))
        if self.workflow_node_id is not None:
            validate_id(self.workflow_node_id)
            if self.phase_key != self.workflow_node_id:
                raise ReferenceError("METHOD_PHASE_BINDING_MISMATCH")
        if (self.review_purpose is not None and (type(self.review_purpose) is not str
                or self.review_purpose not in {'quality','provenance_support','acceptance'})):
            raise ReferenceError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
        validate_id(self.phase_key)
        validate_version(self.requirement_version,positive=True)
        validate_version(self.criterion_set_version,positive=True)


__all__.append('EngineeringTargetBindings')


@dataclass(frozen=True)
class ResolvedReviewMaterial:
    """One named immutable owner projection; the value is not source authority.

    The original binding resolver resolves ``ref`` and holds its source guards.
    Records retain their actual ref types; they are never wrapped as artifacts.
    Canonical bytes keep nested caller aliases outside the fixed delivery.
    """
    name: str
    ref: object
    projection: str
    value_bytes: bytes

    def __post_init__(self):
        from ...domain.artifacts.refs import ArtifactRevisionRef
        from ...domain.changes.refs import ProposalRef
        from ...domain.changes.baselines import RepositorySnapshotRef
        from ...domain.packages.refs import ImplementationPackageRef
        from ...domain.reviews.refs import ReviewRef, SubmissionRef
        from ordessa_infrastructure.encoding import canonical_bytes, decode_json
        validate_id(self.name)
        validate_id(self.projection)
        if (type(self.ref) not in (ArtifactRevisionRef, ProposalRef, RepositorySnapshotRef,
                                  ImplementationPackageRef, SubmissionRef, ReviewRef)
                or type(self.value_bytes) is not bytes or not self.value_bytes
                or len(self.value_bytes) > 2097152):
            raise ReferenceError('INVALID_REVIEW_MATERIAL')
        try:
            value = decode_json(self.value_bytes)
            if canonical_bytes(value) != self.value_bytes:
                raise ReferenceError('INVALID_REVIEW_MATERIAL')
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ReferenceError('INVALID_REVIEW_MATERIAL') from exc

    @property
    def value(self):
        from ordessa_infrastructure.encoding import decode_json
        return decode_json(self.value_bytes)


__all__.append('ResolvedReviewMaterial')

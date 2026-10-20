"""Immutable E4.5 implementation facts; no authorization or acceptance logic."""
from dataclasses import dataclass, field
from typing import Literal

from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.artifacts.provenance import SourceRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.mechanisms.codec import projection
from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest, validate_id, validate_items, validate_text, utc_instant
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import SubmissionRef

def _validate_union(value, kinds):
    if type(value) is not tuple or len(value) > 4096 or any(type(item) not in kinds for item in value):
        raise ReferenceError('INVALID_SUBMISSION')


@dataclass(frozen=True)
class ExecutionRecordRef:
    """Closed identity of an external public execution record, never its session."""
    environment_namespace: str
    unit_id: str
    owner_provider_ref_bytes: bytes
    source_revision: str
    operation_ref: str
    prompt_input_digest: Digest
    captured_observation_ref: BlobRef

    def __post_init__(self):
        for value in (self.environment_namespace, self.unit_id, self.source_revision, self.operation_ref):
            validate_id(value)
        if (type(self.owner_provider_ref_bytes) is not bytes or len(self.owner_provider_ref_bytes) > 4096
                or type(self.prompt_input_digest) is not Digest or type(self.captured_observation_ref) is not BlobRef):
            raise ReferenceError('INVALID_EXECUTION_RECORD_REF')
        from ordessa_infrastructure.encoding import canonical_bytes, decode_json
        try:
            value = decode_json(self.owner_provider_ref_bytes)
            if type(value) is not dict or canonical_bytes(value) != self.owner_provider_ref_bytes:
                raise ReferenceError('INVALID_EXECUTION_RECORD_REF')
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ReferenceError('INVALID_EXECUTION_RECORD_REF') from None


@dataclass(frozen=True)
class CommitRef:
    repository_id: str
    commit_id: str
    tree_digest: Digest

    def __post_init__(self):
        validate_id(self.repository_id)
        if (type(self.commit_id) is not str or len(self.commit_id) not in (40, 64)
                or any(c not in '0123456789abcdef' for c in self.commit_id) or type(self.tree_digest) is not Digest):
            raise ReferenceError('INVALID_COMMIT_REF')


@dataclass(frozen=True)
class FileChange:
    change_id: str
    repository_id: str
    normalized_path: str
    operation: Literal['add', 'modify', 'delete', 'rename']
    before_blob_digest: Digest | None
    after_blob_digest: Digest | None
    rename_from: str | None
    proposal_refs: tuple[ProposalRef, ...]

    def __post_init__(self):
        validate_id(self.change_id); validate_id(self.repository_id)
        from ordessa_engineering.domain.common.models.values import normalized_path
        normalized_path(self.normalized_path)
        if type(self.operation) is not str or self.operation not in {'add','modify','delete','rename'}:
            raise ReferenceError('INVALID_FILE_CHANGE')
        validate_items(self.proposal_refs, ProposalRef, nonempty=True)
        if len(set(self.proposal_refs)) != len(self.proposal_refs):
            raise ReferenceError('INVALID_FILE_CHANGE')
        if any(x is not None and type(x) is not Digest for x in (self.before_blob_digest,self.after_blob_digest)):
            raise ReferenceError('INVALID_FILE_CHANGE')
        if self.operation == 'add': valid = self.before_blob_digest is None and self.after_blob_digest is not None and self.rename_from is None
        elif self.operation == 'delete': valid = self.before_blob_digest is not None and self.after_blob_digest is None and self.rename_from is None
        elif self.operation == 'modify': valid = self.before_blob_digest is not None and self.after_blob_digest is not None and self.rename_from is None
        else:
            valid = self.before_blob_digest is not None and self.after_blob_digest is not None and self.rename_from is not None
            if valid:
                normalized_path(self.rename_from)
                valid = self.rename_from != self.normalized_path
        if not valid:
            raise ReferenceError('INVALID_FILE_CHANGE')


@dataclass(frozen=True)
class TestEvidence:
    check_id: str
    requirement_id: str
    subject_snapshot: RepositorySnapshotRef
    execution_ref: ExecutionRecordRef
    result: Literal['pass','fail','unknown','not_run']
    observation_ref: BlobRef
    tool_version: str
    measured_at: str

    def __post_init__(self):
        validate_id(self.check_id); validate_id(self.requirement_id); validate_id(self.tool_version); utc_instant(self.measured_at)
        if type(self.subject_snapshot) is not RepositorySnapshotRef or type(self.execution_ref) is not ExecutionRecordRef or type(self.observation_ref) is not BlobRef or type(self.result) is not str or self.result not in {'pass','fail','unknown','not_run'}:
            raise ReferenceError('INVALID_TEST_EVIDENCE')


@dataclass(frozen=True)
class EffectTargetRef:
    target_id: str
    constraint_digest: Digest

    def __post_init__(self):
        validate_id(self.target_id)
        if type(self.constraint_digest) is not Digest:
            raise ReferenceError('INVALID_EFFECT_TARGET')


@dataclass(frozen=True)
class EffectObservation:
    effect_id: str
    action: str
    target_ref: EffectTargetRef
    observed_state: Literal['not_started','applied','reverted','unknown']
    evidence_refs: tuple[BlobRef, ...]
    reversible: bool
    compensation_ref: BlobRef | None = None

    def __post_init__(self):
        from ordessa_engineering.domain.approvals.scope import ACTIONS
        validate_id(self.effect_id)
        if (type(self.action) is not str or self.action not in ACTIONS or type(self.target_ref) is not EffectTargetRef or
                type(self.observed_state) is not str or self.observed_state not in {'not_started','applied','reverted','unknown'} or
                type(self.reversible) is not bool or (self.compensation_ref is not None and type(self.compensation_ref) is not BlobRef)):
            raise ReferenceError('INVALID_EFFECT_OBSERVATION')
        validate_items(self.evidence_refs, BlobRef)
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ReferenceError('INVALID_EFFECT_OBSERVATION')


@dataclass(frozen=True)
class SubmissionCoverage:
    proposal_ref: ProposalRef
    output_refs: tuple[ArtifactRevisionRef | BlobRef, ...]
    file_change_ids: tuple[str, ...]
    evidence_refs: tuple[ArtifactRevisionRef | BlobRef, ...]
    disposition: Literal['implemented','unchanged_with_reason','not_implemented']
    reason: str | None = None

    def __post_init__(self):
        if type(self.proposal_ref) is not ProposalRef or type(self.disposition) is not str or self.disposition not in {'implemented','unchanged_with_reason','not_implemented'}:
            raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        _validate_union(self.output_refs, (ArtifactRevisionRef, BlobRef))
        _validate_union(self.evidence_refs, (ArtifactRevisionRef, BlobRef))
        if len(set(self.output_refs)) != len(self.output_refs) or len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        validate_items(self.file_change_ids, str)
        for item in self.file_change_ids: validate_id(item)
        if len(set(self.file_change_ids)) != len(self.file_change_ids):
            raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        if self.disposition == 'implemented' and self.reason is not None:
            raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        if self.disposition != 'implemented':
            validate_text(self.reason)


@dataclass(frozen=True)
class Submission:
    scope: Scope
    submission_id: str
    created_at: str
    created_by: ActorRef
    change_set: ChangeSet
    authorization_refs: tuple[ApprovalRef, ...]
    package_ref: ImplementationPackageRef
    execution_ref: ExecutionRecordRef
    baseline_snapshots: tuple[RepositorySnapshotRef, ...]
    resulting_snapshots: tuple[RepositorySnapshotRef, ...]
    commit_refs: tuple[CommitRef, ...]
    file_changes: tuple[FileChange, ...]
    output_refs: tuple[ArtifactRevisionRef | BlobRef, ...]
    test_evidence: tuple[TestEvidence, ...]
    effect_observations: tuple[EffectObservation, ...]
    coverage: tuple[SubmissionCoverage, ...]
    source_refs: tuple[SourceRef, ...]
    method_content: MethodContent | None = None
    checkpoint_ref: BlobRef | None = None
    schema_version: int = 1
    digest: Digest = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.created_by) is not ActorRef or type(self.change_set) is not ChangeSet:
            raise ReferenceError('INVALID_SUBMISSION')
        validate_id(self.submission_id); utc_instant(self.created_at)
        validate_items(self.authorization_refs, ApprovalRef, nonempty=True)
        if len(self.authorization_refs) != 1:
            raise ReferenceError('INVALID_SUBMISSION')
        if type(self.package_ref) is not ImplementationPackageRef or type(self.execution_ref) is not ExecutionRecordRef:
            raise ReferenceError('INVALID_SUBMISSION')
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            raise ReferenceError('INVALID_SUBMISSION')
        validate_items(self.baseline_snapshots, RepositorySnapshotRef, nonempty=self.schema_version == 1)
        for name, typ in (('resulting_snapshots',RepositorySnapshotRef),('commit_refs',CommitRef),('file_changes',FileChange),('test_evidence',TestEvidence),('effect_observations',EffectObservation),('coverage',SubmissionCoverage),('source_refs',SourceRef)):
            validate_items(getattr(self,name),typ)
        _validate_union(self.output_refs, (ArtifactRevisionRef, BlobRef))
        for items in (self.authorization_refs,self.baseline_snapshots,self.resulting_snapshots,self.commit_refs,
                      self.file_changes,self.output_refs,self.test_evidence,self.effect_observations,
                      self.coverage,self.source_refs):
            if len(items) != len(set(items)):
                raise ReferenceError('DUPLICATE_SUBMISSION_ITEM')
        if self.method_content is not None and type(self.method_content) is not MethodContent or self.checkpoint_ref is not None and type(self.checkpoint_ref) is not BlobRef:
            raise ReferenceError('INVALID_SUBMISSION')
        if self.schema_version == 2 and (
                self.baseline_snapshots or self.resulting_snapshots or self.commit_refs
                or self.file_changes or self.test_evidence or self.effect_observations
                or self.method_content is None
                or len(self.output_refs) != 1 or type(self.output_refs[0]) is not BlobRef
                or self.method_content.rendered_body_ref != self.output_refs[0]):
            raise ReferenceError('INVALID_SUBMISSION_REPORT')
        for items in (self.baseline_snapshots,self.resulting_snapshots):
            keys=[(i.realm_id,i.project_id,i.repository_id) for i in items]
            if len(keys)!=len(set(keys)): raise ReferenceError('DUPLICATE_SNAPSHOT')
        for items in (self.file_changes,self.test_evidence,self.effect_observations):
            if len(items)>4096: raise ReferenceError('INVALID_SUBMISSION')
        scope=(self.scope.realm_id,self.scope.project_id)
        if (self.package_ref.realm_id,self.package_ref.project_id)!=scope or any((r.realm_id,r.project_id)!=scope for r in self.authorization_refs+self.change_set.proposal_refs+self.baseline_snapshots+self.resulting_snapshots):
            raise ReferenceError('REALM_MISMATCH')
        if any((r.realm_id,r.project_id)!=scope for r in self.output_refs if type(r) is ArtifactRevisionRef):
            raise ReferenceError('REALM_MISMATCH')
        if any((item.subject_snapshot.realm_id,item.subject_snapshot.project_id)!=scope for item in self.test_evidence):
            raise ReferenceError('REALM_MISMATCH')
        if any((ref.realm_id,ref.project_id)!=scope for c in self.coverage for ref in c.output_refs+c.evidence_refs if type(ref) is ArtifactRevisionRef):
            raise ReferenceError('REALM_MISMATCH')
        expected=set(self.change_set.proposal_refs)
        if len(self.coverage)!=len(expected) or {c.proposal_ref for c in self.coverage}!=expected:
            raise ReferenceError('INCOMPLETE_SUBMISSION_COVERAGE')
        file_ids={f.change_id for f in self.file_changes}
        if len(file_ids)!=len(self.file_changes): raise ReferenceError('DUPLICATE_FILE_CHANGE')
        baseline_repos={r.repository_id for r in self.baseline_snapshots}
        if any(f.repository_id not in baseline_repos or any(p not in expected for p in f.proposal_refs) for f in self.file_changes):
            raise ReferenceError('INVALID_FILE_CHANGE_BINDING')
        for c in self.coverage:
            if not set(c.file_change_ids)<=file_ids or any(not any(f.change_id==fid and c.proposal_ref in f.proposal_refs for f in self.file_changes) for fid in c.file_change_ids):
                raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        for items,key in ((self.test_evidence,lambda x:x.check_id),(self.effect_observations,lambda x:x.effect_id),
                          (self.source_refs,lambda x:x.source_id if self.schema_version == 1 else (x.source_id,x.content_identity))):
            if len({key(i) for i in items}) != len(items):
                raise ReferenceError('DUPLICATE_SUBMISSION_ITEM')
        if any(len(items) > 4096 for items in (self.coverage,self.baseline_snapshots,self.resulting_snapshots,self.commit_refs,self.source_refs)):
            raise ReferenceError('SUBMISSION_TOO_LARGE')
        for c in self.coverage:
            if set(c.file_change_ids) != {f.change_id for f in self.file_changes if c.proposal_ref in f.proposal_refs} or not set(c.output_refs) <= set(self.output_refs):
                raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        if {o for c in self.coverage for o in c.output_refs} != set(self.output_refs):
            raise ReferenceError('INCOMPLETE_SUBMISSION_COVERAGE')
        from ordessa_infrastructure.encoding import canonical_bytes
        if len(canonical_bytes(self.hash_payload())) > 2*1024*1024:
            raise ReferenceError('SUBMISSION_TOO_LARGE')
        object.__setattr__(self,'digest',record_digest('submission',self.hash_payload()))

    def hash_payload(self):
        from ordessa_infrastructure.encoding import decode_json
        execution = projection(self.execution_ref, identity=True)
        execution['owner_provider_ref_bytes'] = decode_json(self.execution_ref.owner_provider_ref_bytes)
        tests = []
        for item in self.test_evidence:
            row = projection(item, identity=True)
            nested = projection(item.execution_ref, identity=True)
            nested['owner_provider_ref_bytes'] = decode_json(item.execution_ref.owner_provider_ref_bytes)
            row['execution_ref'] = nested
            tests.append(row)
        payload = {'realm_id':self.scope.realm_id,'project_id':self.scope.project_id,'submission_id':self.submission_id,
            'created_at':self.created_at,'created_by':projection(self.created_by,identity=True),
            'change_set':projection(self.change_set,identity=True),'authorization_refs':projection(self.authorization_refs,identity=True),
            'package_ref':projection(self.package_ref,identity=True),'execution_ref':execution,
            'baseline_snapshots':projection(self.baseline_snapshots,identity=True),'resulting_snapshots':projection(self.resulting_snapshots,identity=True),
            'commit_refs':projection(self.commit_refs,identity=True),'file_changes':projection(self.file_changes,identity=True),
            'output_refs':projection(self.output_refs,identity=True),'test_evidence':tests,
            'effect_observations':projection(self.effect_observations,identity=True),'coverage':projection(self.coverage,identity=True),
            'source_refs':projection(self.source_refs,identity=True),'method_content':None if self.method_content is None else self.method_content.projection(identity=True),
            'checkpoint_ref':projection(self.checkpoint_ref,identity=True)}
        # Historical schema-1 bytes and digests have no version field. Only the
        # explicit Work report variant adds one; empty snapshots never downgrade.
        if self.schema_version == 2:
            payload['schema_version'] = 2
        return payload

    @property
    def ref(self):
        return SubmissionRef(self.scope.realm_id,self.scope.project_id,self.submission_id,self.digest)

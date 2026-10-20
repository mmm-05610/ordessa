"""Agent report facts, separate from historical Unit Submission schemas.

This value authenticates neither the receipt nor the report text. Native-source,
method, approval and commit-time guards belong to the consuming use case.
"""
from dataclasses import dataclass, field

from ordessa_infrastructure.encoding import canonical_bytes
from ..approvals.refs import ApprovalRef
from ..artifacts.models import MethodContent
from ..artifacts.provenance import SourceRef
from ..artifacts.refs import ArtifactRevisionRef
from ..common.mechanisms.codec import projection
from ..common.mechanisms.hashing import record_digest
from ..common.models.identity import Scope, ActorRef
from ..common.models.refs import BlobRef
from ..common.models.values import Digest, validate_id, validate_items, utc_instant
from ..common.outcomes.diagnostics import ReferenceError
from ..packages.refs import ImplementationPackageRef
from ..reviews.refs import SubmissionRef
from .agent_execution_ref import AgentExecutionRecordRef
from .models import ChangeSet
from .submission import SubmissionCoverage

AGENT_SUBMISSION_REPORT_VERSION = 'engineering-agent-submission-report/1'


@dataclass(frozen=True)
class AgentSubmissionReport:
    scope: Scope
    submission_id: str
    created_at: str
    created_by: ActorRef
    change_set: ChangeSet
    authorization_refs: tuple[ApprovalRef, ...]
    package_ref: ImplementationPackageRef
    execution_ref: AgentExecutionRecordRef
    output_refs: tuple[BlobRef, ...]
    coverage: tuple[SubmissionCoverage, ...]
    source_refs: tuple[SourceRef, ...]
    method_content: MethodContent
    checkpoint_ref: BlobRef | None = None
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.created_by) is not ActorRef
                or type(self.change_set) is not ChangeSet
                or type(self.package_ref) is not ImplementationPackageRef
                or type(self.execution_ref) is not AgentExecutionRecordRef
                or type(self.method_content) is not MethodContent
                or self.checkpoint_ref is not None and type(self.checkpoint_ref) is not BlobRef):
            raise ReferenceError('INVALID_AGENT_SUBMISSION_REPORT')
        validate_id(self.submission_id)
        utc_instant(self.created_at)
        for items, kind in ((self.authorization_refs, ApprovalRef), (self.output_refs, BlobRef),
                            (self.coverage, SubmissionCoverage), (self.source_refs, SourceRef)):
            validate_items(items, kind)
            if len(items) > 4096:
                raise ReferenceError('SUBMISSION_TOO_LARGE')
            if len(set(items)) != len(items):
                raise ReferenceError('DUPLICATE_SUBMISSION_ITEM')
        if (len(self.authorization_refs) != 1 or len(self.output_refs) != 1
                or self.method_content.rendered_body_ref != self.output_refs[0]):
            raise ReferenceError('INVALID_SUBMISSION_REPORT')
        scope = (self.scope.realm_id, self.scope.project_id)
        if any((ref.realm_id, ref.project_id) != scope for ref in
               (self.package_ref,) + self.authorization_refs + self.change_set.proposal_refs):
            raise ReferenceError('REALM_MISMATCH')
        if any((ref.realm_id, ref.project_id) != scope for item in self.coverage
               for ref in item.output_refs + item.evidence_refs if type(ref) is ArtifactRevisionRef):
            raise ReferenceError('REALM_MISMATCH')
        expected = set(self.change_set.proposal_refs)
        if len(self.coverage) != len(expected) or {item.proposal_ref for item in self.coverage} != expected:
            raise ReferenceError('INCOMPLETE_SUBMISSION_COVERAGE')
        for item in self.coverage:
            if item.file_change_ids or not set(item.output_refs) <= set(self.output_refs):
                raise ReferenceError('INVALID_SUBMISSION_COVERAGE')
        if {ref for item in self.coverage for ref in item.output_refs} != set(self.output_refs):
            raise ReferenceError('INCOMPLETE_SUBMISSION_COVERAGE')
        if len({(item.source_id, item.content_identity) for item in self.source_refs}) != len(self.source_refs):
            raise ReferenceError('DUPLICATE_SUBMISSION_ITEM')
        if len(canonical_bytes(self.hash_payload())) > 2 * 1024 * 1024:
            raise ReferenceError('SUBMISSION_TOO_LARGE')
        object.__setattr__(self, 'digest', record_digest('agent-submission-report', self.hash_payload()))

    def hash_payload(self):
        return {
            'schemaVersion': AGENT_SUBMISSION_REPORT_VERSION,
            'realm_id': self.scope.realm_id, 'project_id': self.scope.project_id,
            'submission_id': self.submission_id, 'created_at': self.created_at,
            'created_by': projection(self.created_by, identity=True),
            'change_set': projection(self.change_set, identity=True),
            'authorization_refs': projection(self.authorization_refs, identity=True),
            'package_ref': projection(self.package_ref, identity=True),
            'execution_ref': self.execution_ref.projection(identity=True),
            'output_refs': projection(self.output_refs, identity=True),
            'coverage': projection(self.coverage, identity=True),
            'source_refs': projection(self.source_refs, identity=True),
            'method_content': self.method_content.projection(identity=True),
            'checkpoint_ref': projection(self.checkpoint_ref, identity=True),
        }

    @property
    def ref(self):
        return SubmissionRef(self.scope.realm_id, self.scope.project_id, self.submission_id, self.digest)

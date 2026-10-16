"""Finite, immutable E4.4 package content. No repository IO or grant issuance."""
from dataclasses import dataclass, field, asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.models.identity import Scope, ActorRef
from ..common.models.refs import BlobRef
from ..common.models.values import Digest, validate_id, validate_items, normalized_path, utc_instant, validate_text
from ..common.outcomes.diagnostics import ReferenceError
from ..common.mechanisms.hashing import record_digest
from ..common.mechanisms.codec import projection
from ..changes.models import ChangeSet
from ..changes.refs import ProposalRef
from ..changes.baselines import RepositorySnapshotRef
from ..approvals.refs import ApprovalRef
from ..approvals.scope import ACTIONS, FILE_OPERATIONS, EnvironmentRef
from ..artifacts.refs import ArtifactRevisionRef
from ..artifacts.method_binding import MethodRef, ExactMethodResourceRef
from ..artifacts.models import MethodContent
from ..artifacts.provenance import SourceRef, VersionCapture
from ..reviews.refs import ReviewRef
from ..reviews.requirements import ReviewRequirementTemplateRef
from .refs import ImplementationPackageRef

@dataclass(frozen=True)
class PackageFile:
    repository_id: str
    path: str
    operation: str
    before_blob_digest: Digest | None
    rename_from: str | None
    proposal_refs: tuple[ProposalRef, ...]
    purpose: str

    def __post_init__(self):
        validate_id(self.repository_id)
        normalized_path(self.path)
        validate_text(self.purpose)
        validate_items(self.proposal_refs, ProposalRef, nonempty=True)
        if len(set(self.proposal_refs)) != len(self.proposal_refs):
            raise ReferenceError('PACKAGE_PROPOSAL_DUPLICATE')
        if self.operation not in FILE_OPERATIONS:
            raise ReferenceError('INVALID_PACKAGE_FILE')
        if self.operation == 'add':
            if self.before_blob_digest is not None:
                raise ReferenceError('INVALID_PACKAGE_FILE')
        elif type(self.before_blob_digest) is not Digest:
            raise ReferenceError('INVALID_PACKAGE_FILE')
        if self.operation == 'rename':
            normalized_path(self.rename_from)
            if self.rename_from == self.path:
                raise ReferenceError('INVALID_PACKAGE_RENAME')
        elif self.rename_from is not None:
            raise ReferenceError('INVALID_PACKAGE_RENAME')

@dataclass(frozen=True)
class PackageCoverage:
    proposal_ref: ProposalRef
    instructions: tuple[BlobRef, ...]
    files: tuple[str, ...]
    acceptance_requirements: tuple[ReviewRequirementTemplateRef, ...]
    basis_refs: tuple[ArtifactRevisionRef, ...]

    def __post_init__(self):
        if type(self.proposal_ref) is not ProposalRef:
            raise ReferenceError('INVALID_PACKAGE_COVERAGE')
        validate_items(self.instructions, BlobRef, nonempty=True)
        validate_items(self.files, str)
        validate_items(self.acceptance_requirements, ReviewRequirementTemplateRef)
        validate_items(self.basis_refs, ArtifactRevisionRef, nonempty=True)
        for name in self.files:
            normalized_path(name)
        if len(set(self.files)) != len(self.files):
            raise ReferenceError('INVALID_PACKAGE_COVERAGE')

@dataclass(frozen=True)
class PackageDerivation:
    intent_digest: Digest
    input_refs: tuple[BlobRef, ...]
    generator_id: str
    generator_version: str
    output_manifest_digest: Digest

    def __post_init__(self):
        if type(self.intent_digest) is not Digest or type(self.output_manifest_digest) is not Digest:
            raise ReferenceError('INVALID_PACKAGE_DERIVATION')
        validate_items(self.input_refs, BlobRef, nonempty=True)
        validate_id(self.generator_id)
        validate_id(self.generator_version)


@dataclass(frozen=True)
class PackageDocument:
    role: str
    source_ref: SourceRef

    def __post_init__(self):
        validate_id(self.role)
        if len(self.role) > 128 or type(self.source_ref) is not SourceRef or type(self.source_ref.capture) is not VersionCapture:
            raise ReferenceError('INVALID_PACKAGE_DOCUMENT')


@dataclass(frozen=True)
class PreparedPackagePayload:
    baseline: SourceRef
    candidate: SourceRef
    change_ref: ProposalRef
    review_refs: tuple[ReviewRef, ...]
    method_ref: MethodRef
    method_resource_refs: tuple[ExactMethodResourceRef, ...]
    documents: tuple[PackageDocument, ...]
    package_schema: str = field(default='ordessa.implementation-package/v2', init=False)

    def __post_init__(self):
        if (type(self.baseline) is not SourceRef or type(self.candidate) is not SourceRef
                or type(self.baseline.capture) is not VersionCapture
                or type(self.candidate.capture) is not VersionCapture
                or self.baseline.locator != self.candidate.locator
                or self.baseline.content_identity == self.candidate.content_identity
                or type(self.change_ref) is not ProposalRef or type(self.method_ref) is not MethodRef):
            raise ReferenceError('INVALID_PACKAGE')
        validate_items(self.review_refs, ReviewRef, nonempty=True)
        if len(self.review_refs) > 4096:
            raise ReferenceError('PACKAGE_BOUND_EXCEEDED')
        object.__setattr__(self, 'review_refs', ordered_refs(self.review_refs))
        validate_items(self.method_resource_refs, ExactMethodResourceRef, nonempty=True)
        if (len(self.method_resource_refs) > 256
                or any(item.method_ref != self.method_ref for item in self.method_resource_refs)):
            raise ReferenceError('INVALID_METHOD_RESOURCE')
        object.__setattr__(self, 'method_resource_refs', ordered_refs(self.method_resource_refs))
        validate_items(self.documents, PackageDocument)
        if len(self.documents) > 4096:
            raise ReferenceError('PACKAGE_BOUND_EXCEEDED')
        identities = [(item.role, item.source_ref.content_identity) for item in self.documents]
        if len(set(identities)) != len(identities):
            raise ReferenceError('DUPLICATE_PACKAGE_DOCUMENT')


def ordered_refs(items):
    if len(set(items)) != len(items):
        raise ReferenceError('DUPLICATE_CHECK')
    return tuple(sorted(items, key=lambda item: canonical_bytes(asdict(item))))

def package_manifest_digest(files):
    return record_digest('implementation-package-manifest', {'files': [projection(f, identity=True) for f in files]})

@dataclass(frozen=True)
class ImplementationPackagePayload:
    implementation_intent_id: str
    change_set: ChangeSet
    design_targets: tuple[ArtifactRevisionRef, ...]
    authorization_refs: tuple[ApprovalRef, ...]
    method_ref: MethodRef
    required_review_refs: tuple[ReviewRef, ...]
    baseline_snapshots: tuple[RepositorySnapshotRef, ...]
    resolved_file_manifest: tuple[PackageFile, ...]
    instructions_ref: BlobRef
    skill_snapshot_refs: tuple[ExactMethodResourceRef, ...]
    execution_profile_ref: EnvironmentRef
    allowed_actions: tuple[str, ...]
    acceptance_requirements: tuple[ReviewRequirementTemplateRef, ...]
    proposal_coverage: tuple[PackageCoverage, ...]
    method_content: MethodContent | None
    derivation: PackageDerivation
    package_schema: str = field(default='ordessa.implementation-package/v1', init=False)

    def __post_init__(self):
        validate_id(self.implementation_intent_id)
        if type(self.change_set) is not ChangeSet or type(self.method_ref) is not MethodRef:
            raise ReferenceError('INVALID_PACKAGE')
        for name, kind, required in (
            ('design_targets',ArtifactRevisionRef,True), ('authorization_refs',ApprovalRef,True),
            ('required_review_refs',ReviewRef,False), ('baseline_snapshots',RepositorySnapshotRef,True),
            ('resolved_file_manifest',PackageFile,False), ('skill_snapshot_refs',ExactMethodResourceRef,False),
            ('allowed_actions',str,True), ('acceptance_requirements',ReviewRequirementTemplateRef,False),
            ('proposal_coverage',PackageCoverage,True)):
            validate_items(getattr(self,name),kind,nonempty=required)
            if len(getattr(self,name)) > 4096:
                raise ReferenceError('PACKAGE_BOUND_EXCEEDED')
        if len(self.authorization_refs) != 1:
            raise ReferenceError('PACKAGE_SINGLE_GRANT_REQUIRED')
        if (len(set(self.allowed_actions)) != len(self.allowed_actions)
                or any(a not in ACTIONS for a in self.allowed_actions)):
            raise ReferenceError('INVALID_PACKAGE_ACTIONS')
        if type(self.instructions_ref) is not BlobRef or type(self.execution_profile_ref) is not EnvironmentRef:
            raise ReferenceError('INVALID_PACKAGE')
        if type(self.derivation) is not PackageDerivation:
            raise ReferenceError('INVALID_PACKAGE_DERIVATION')
        if self.method_content is not None and (type(self.method_content) is not MethodContent
                or self.method_content.schema_ref.method_ref != self.method_ref):
            raise ReferenceError('INVALID_METHOD_CONTENT')
        expected = self.change_set.proposal_refs
        if (len(self.proposal_coverage) != len(expected)
                or set(c.proposal_ref for c in self.proposal_coverage) != set(expected)):
            raise ReferenceError('PACKAGE_COVERAGE_INCOMPLETE')
        manifest = self.resolved_file_manifest
        if tuple((f.repository_id,f.path) for f in manifest) != tuple(sorted((f.repository_id,f.path) for f in manifest)):
            raise ReferenceError('PACKAGE_MANIFEST_NOT_SORTED')
        touched = [(f.repository_id,p) for f in manifest for p in ((f.path,f.rename_from) if f.rename_from else (f.path,))]
        if len(touched) != len(set(touched)):
            raise ReferenceError('PACKAGE_FILE_CONFLICT')
        touched_set = set(touched)
        if any((repo,'/'.join(path.split('/')[:i])) in touched_set
               for repo,path in touched for i in range(1,len(path.split('/')))):
            raise ReferenceError('PACKAGE_FILE_CONFLICT')
        if 'edit_repository' in self.allowed_actions and not manifest:
            raise ReferenceError('PACKAGE_EDIT_MANIFEST_REQUIRED')
        for row in manifest:
            if not set(row.proposal_refs) <= set(expected):
                raise ReferenceError('PACKAGE_FOREIGN_PROPOSAL')
        for c in self.proposal_coverage:
            rows = {f.path for f in manifest if c.proposal_ref in f.proposal_refs}
            if set(c.files) != rows or not set(c.acceptance_requirements) <= set(self.acceptance_requirements):
                raise ReferenceError('PACKAGE_COVERAGE_MISMATCH')
        if self.derivation.output_manifest_digest != package_manifest_digest(manifest):
            raise ReferenceError('PACKAGE_MANIFEST_DIGEST_MISMATCH')
        refs = (*self.design_targets,*self.authorization_refs,*self.baseline_snapshots,*self.required_review_refs,
                *(r for c in self.proposal_coverage for r in c.basis_refs))
        scope = (expected[0].realm_id,expected[0].project_id)
        if any((r.realm_id,r.project_id) != scope for r in refs):
            raise ReferenceError('REALM_MISMATCH')
        if any((r.scope.realm_id,r.scope.project_id) != scope for r in self.acceptance_requirements):
            raise ReferenceError('REALM_MISMATCH')
        if len({r.repository_id for r in self.baseline_snapshots}) != len(self.baseline_snapshots):
            raise ReferenceError('PACKAGE_BASELINE_DUPLICATE')
        if any(f.repository_id not in {r.repository_id for r in self.baseline_snapshots} for f in manifest):
            raise ReferenceError('PACKAGE_BASELINE_MISSING')

@dataclass(frozen=True)
class ImplementationPackage:
    scope: Scope
    package_id: str
    created_at: str
    created_by: ActorRef
    payload: ImplementationPackagePayload | PreparedPackagePayload
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.created_by) is not ActorRef
                or type(self.payload) not in {ImplementationPackagePayload, PreparedPackagePayload}):
            raise ReferenceError('INVALID_PACKAGE')
        validate_id(self.package_id)
        utc_instant(self.created_at)
        change_ref = (self.payload.change_set.proposal_refs[0]
                      if type(self.payload) is ImplementationPackagePayload else self.payload.change_ref)
        if (change_ref.realm_id,change_ref.project_id) != (self.scope.realm_id,self.scope.project_id):
            raise ReferenceError('REALM_MISMATCH')
        if type(self.payload) is PreparedPackagePayload:
            refs = (change_ref, *self.payload.review_refs)
            if any((item.realm_id,item.project_id)!=(self.scope.realm_id,self.scope.project_id) for item in refs):
                raise ReferenceError('REALM_MISMATCH')
        value={'scope':asdict(self.scope),'package_id':self.package_id,'created_at':self.created_at,
               'created_by':asdict(self.created_by),'payload':package_payload_projection(self.payload,identity=True)}
        object.__setattr__(self,'digest',record_digest('implementation-package',value))

    @property
    def ref(self):
        return ImplementationPackageRef(self.scope.realm_id,self.scope.project_id,self.package_id,self.digest)


def package_payload_projection(payload, *, identity=False):
    value = projection(payload, identity=identity)
    if type(payload) is ImplementationPackagePayload:
        value['method_content'] = None if payload.method_content is None else payload.method_content.projection(identity=identity)
    return value

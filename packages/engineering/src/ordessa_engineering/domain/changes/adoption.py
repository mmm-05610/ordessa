"""Exact Artifact acceptance facts; no authority, storage or workflow effects."""
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from .application_plan import HeadExpectation
from ..artifacts.refs import ArtifactRevisionRef
from ..approvals.refs import ApprovalRef
from ..reviews.refs import SubmissionRef
from ..reviews.models import ReviewRef
from ..common.models.identity import Scope
from ..common.models.values import Digest, validate_id, validate_items, validate_version, utc_instant
from ..common.outcomes.diagnostics import ReferenceError
from ..common.mechanisms.hashing import record_digest
from ordessa_infrastructure.encoding import canonical_bytes


def _body(record):
    def plain(value):
        if is_dataclass(value):
            return asdict(value)
        if type(value) is tuple:
            return [plain(item) for item in value]
        return value
    return {f.name: plain(getattr(record,f.name)) for f in fields(record) if f.name != 'digest'}


@dataclass(frozen=True)
class AcceptanceTarget:
    target_ref: ArtifactRevisionRef
    expected: HeadExpectation

    def __post_init__(self):
        if (type(self.target_ref) is not ArtifactRevisionRef or type(self.expected) is not HeadExpectation
                or self.expected.artifact_id != self.target_ref.artifact_id):
            raise ReferenceError('INVALID_ACCEPTANCE_TARGET')
        if self.expected.head_ref is not None and (
                self.expected.head_ref.realm_id, self.expected.head_ref.project_id) != (
                self.target_ref.realm_id, self.target_ref.project_id):
            raise ReferenceError('REALM_MISMATCH')


@dataclass(frozen=True)
class AcceptancePlan:
    scope: Scope
    submission_ref: SubmissionRef
    acceptance_use: str
    targets: tuple[AcceptanceTarget, ...]
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.submission_ref) is not SubmissionRef
                or self.acceptance_use not in ('reference', 'adopt_content')):
            raise ReferenceError('INVALID_ACCEPTANCE_PLAN')
        validate_items(self.targets, AcceptanceTarget, nonempty=True)
        if len(self.targets) > 4096 or len({t.target_ref.artifact_id for t in self.targets}) != len(self.targets):
            raise ReferenceError('INVALID_ACCEPTANCE_PLAN')
        refs = (self.submission_ref,) + tuple(t.target_ref for t in self.targets)
        refs += tuple(t.expected.head_ref for t in self.targets if t.expected.head_ref is not None)
        if any((r.realm_id, r.project_id) != (self.scope.realm_id, self.scope.project_id) for r in refs):
            raise ReferenceError('REALM_MISMATCH')
        if self.acceptance_use == 'adopt_content' and any(t.expected.version >= (1 << 63)-1 for t in self.targets):
            raise ReferenceError('VERSION_EXHAUSTED')
        object.__setattr__(self, 'targets', tuple(sorted(self.targets, key=lambda t:t.target_ref.artifact_id)))
        object.__setattr__(self, 'digest', record_digest('artifact-acceptance-plan',
            _body(self)))


@dataclass(frozen=True)
class AcceptanceReceiptRef:
    realm_id: str
    project_id: str
    adoption_id: str
    digest: Digest
    kind: str = field(default='acceptance-receipt', init=False)

    def __post_init__(self):
        for value in (self.realm_id, self.project_id, self.adoption_id):
            validate_id(value)
        if type(self.digest) is not Digest:
            raise ReferenceError('INVALID_ACCEPTANCE_RECEIPT')


@dataclass(frozen=True)
class AcceptanceReceipt:
    scope: Scope
    adoption_id: str
    action_instance_id: str
    approval_ref: ApprovalRef
    intent_digest: Digest
    plan: AcceptancePlan
    review_refs: tuple[ReviewRef, ...]
    grant_control_version: int
    adopted_at: str
    digest: Digest = field(init=False)

    def __post_init__(self):
        validate_id(self.adoption_id); validate_id(self.action_instance_id)
        validate_version(self.grant_control_version); utc_instant(self.adopted_at)
        if (type(self.scope) is not Scope or type(self.approval_ref) is not ApprovalRef
                or type(self.intent_digest) is not Digest or type(self.plan) is not AcceptancePlan
                or self.plan.scope != self.scope):
            raise ReferenceError('INVALID_ACCEPTANCE_RECEIPT')
        validate_items(self.review_refs, ReviewRef, nonempty=True)
        if len(set(self.review_refs)) != len(self.review_refs):
            raise ReferenceError('INVALID_ACCEPTANCE_RECEIPT')
        if any((r.realm_id,r.project_id) != (self.scope.realm_id,self.scope.project_id)
                for r in self.review_refs+(self.approval_ref,)):
            raise ReferenceError('REALM_MISMATCH')
        body=_body(self)
        if len(canonical_bytes(body)) > 2*1024*1024:
            raise ReferenceError('MATERIAL_LIMIT')
        object.__setattr__(self,'digest',record_digest('artifact-acceptance-receipt',body))

    @property
    def ref(self):
        return AcceptanceReceiptRef(self.scope.realm_id,self.scope.project_id,self.adoption_id,self.digest)


def decode_acceptance_plan(value):
    from ..common.mechanisms.codec import require_object, decode_scope, decode_digest, decode_tuple
    from ..artifacts.ref_codec import decode_artifact_ref
    from ..reviews.target_codec import decode_subject_ref
    require_object(value,{f.name for f in fields(AcceptancePlan)},'INVALID_ACCEPTANCE_PLAN')
    def target(v):
        require_object(v,{'target_ref','expected'},'INVALID_ACCEPTANCE_TARGET')
        h=v['expected']; require_object(h,{'artifact_id','version','head_ref'},'INVALID_ACCEPTANCE_TARGET')
        return AcceptanceTarget(decode_artifact_ref(v['target_ref']),HeadExpectation(h['artifact_id'],h['version'],
            None if h['head_ref'] is None else decode_artifact_ref(h['head_ref'])))
    plan=AcceptancePlan(decode_scope(value['scope']),decode_subject_ref(value['submission_ref']),
        value['acceptance_use'],decode_tuple(value['targets'],target,'INVALID_ACCEPTANCE_TARGET'))
    if plan.digest != decode_digest(value['digest']):
        raise ReferenceError('DIGEST_MISMATCH')
    return plan


def encode_acceptance_receipt(receipt):
    if type(receipt) is not AcceptanceReceipt:
        raise ReferenceError('INVALID_ACCEPTANCE_RECEIPT')
    return canonical_bytes(asdict(receipt))


def decode_acceptance_receipt(raw):
    from ..common.mechanisms.codec import canonical_value, require_object, decode_scope, decode_digest, decode_tuple
    from ..approvals.ref_codec import decode_approval_ref
    from ..reviews.ref_codec import decode_review_ref
    value=canonical_value(raw)
    require_object(value,{f.name for f in fields(AcceptanceReceipt)},'INVALID_ACCEPTANCE_RECEIPT')
    receipt=AcceptanceReceipt(decode_scope(value['scope']),value['adoption_id'],value['action_instance_id'],
        decode_approval_ref(value['approval_ref']),decode_digest(value['intent_digest']),
        decode_acceptance_plan(value['plan']),decode_tuple(value['review_refs'],decode_review_ref,'INVALID_REVIEW'),
        value['grant_control_version'],value['adopted_at'])
    if receipt.digest != decode_digest(value['digest']):
        raise ReferenceError('DIGEST_MISMATCH')
    return receipt

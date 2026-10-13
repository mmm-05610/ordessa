"""Pure whole-batch head plan. A plan is not an authorization or a write."""
from dataclasses import dataclass, asdict, field, fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..artifacts.models import Artifact, ArtifactRevision
from ..artifacts.refs import ArtifactRevisionRef
from ..common.models.values import validate_id, validate_version, MAX_VERSION
from ..common.outcomes.diagnostics import ReferenceError
from .models import ChangeSet
from .operations import validate_change_set, validate_proposal
from ..common.models.identity import Scope
from ..common.models.values import Digest, utc_instant
from ..common.mechanisms.hashing import record_digest
from ..approvals.refs import ApprovalRef
from ..reviews.refs import ReviewRef


@dataclass(frozen=True)
class HeadExpectation:
    artifact_id: str
    version: int
    head_ref: ArtifactRevisionRef | None

    def __post_init__(self):
        validate_id(self.artifact_id)
        if type(self.version) is not int or not 0 <= self.version <= (1 << 63) - 1:
            raise ReferenceError('INVALID_VERSION')
        if self.head_ref is not None and (type(self.head_ref) is not ArtifactRevisionRef
                or self.head_ref.artifact_id != self.artifact_id):
            raise ReferenceError('BASE_TARGET_MISMATCH')


@dataclass(frozen=True)
class HeadMutation:
    expected: HeadExpectation
    proposed_ref: ArtifactRevisionRef

    def __post_init__(self):
        if type(self.expected) is not HeadExpectation or type(self.proposed_ref) is not ArtifactRevisionRef:
            raise ReferenceError('INVALID_MUTATION')
        if self.expected.artifact_id != self.proposed_ref.artifact_id:
            raise ReferenceError('BASE_TARGET_MISMATCH')
        if self.expected.version >= (1 << 63) - 1:
            raise ReferenceError('VERSION_EXHAUSTED')


@dataclass(frozen=True)
class ChangeMutationPlan:
    change_set: ChangeSet
    mutations: tuple[HeadMutation, ...]

    def __post_init__(self):
        if type(self.change_set) is not ChangeSet or type(self.mutations) is not tuple or not self.mutations:
            raise ReferenceError('INVALID_CHANGE_SET')
        if any(type(m) is not HeadMutation for m in self.mutations):
            raise ReferenceError('INVALID_MUTATION')
        if len({m.expected.artifact_id for m in self.mutations}) != len(self.mutations):
            raise ReferenceError('DUPLICATE_MUTATION')


def plan_change_application(proposals, controls, artifacts, revisions, expectations):
    """Validate exact resolved values; the application supplies authority/gates."""
    result = validate_change_set(proposals, controls)
    if not result.ok:
        raise ReferenceError(result.error.code.value)
    if (type(artifacts) is not tuple or type(revisions) is not tuple or type(expectations) is not tuple
            or any(type(a) is not Artifact for a in artifacts)
            or any(type(r) is not ArtifactRevision for r in revisions)
            or any(type(e) is not HeadExpectation for e in expectations)):
        raise ReferenceError('INVALID_RESOLVED_GRAPH')
    owners = {a.artifact_id: a for a in artifacts}
    expected = {e.artifact_id: e for e in expectations}
    graph = {r.ref: r for r in revisions}
    mutation_ids = {m.artifact_id for p in proposals for m in p.mutations}
    if (len(owners) != len(artifacts) or len(expected) != len(expectations)
            or len(graph) != len(revisions) or set(owners) != mutation_ids or set(expected) != mutation_ids):
        raise ReferenceError('INCOMPLETE_BATCH')
    planned = []
    for proposal in proposals:
        # Each proposal owns only its mutation owners, but sees the supplied
        # closed graph for claims and parents. No latest lookup happens here.
        validate_proposal(proposal, tuple(owners[m.artifact_id] for m in proposal.mutations), revisions)
        for mutation in proposal.mutations:
            owner, expectation = owners[mutation.artifact_id], expected[mutation.artifact_id]
            if owner.version != expectation.version:
                raise ReferenceError('VERSION_CONFLICT')
            current_ref = None
            if owner.head_revision_id is not None:
                matches = [r.ref for r in revisions if r.artifact_id == owner.artifact_id
                           and r.revision_id == owner.head_revision_id]
                if len(matches) != 1:
                    raise ReferenceError('INVALID_RESOLVED_GRAPH')
                current_ref = matches[0]
            if current_ref != expectation.head_ref or current_ref != mutation.base_ref:
                raise ReferenceError('BASE_TARGET_MISMATCH')
            planned.append(HeadMutation(expectation, mutation.proposed_ref))
    return ChangeMutationPlan(result.value, tuple(sorted(planned, key=lambda m: m.expected.artifact_id)))


@dataclass(frozen=True)
class ChangeApplicationReceipt:
    scope: Scope
    apply_id: str
    action_instance_id: str
    approval_ref: ApprovalRef
    intent_digest: Digest
    change_set: ChangeSet
    mutations: tuple[HeadMutation, ...]
    review_refs: tuple[ReviewRef, ...]
    grant_control_version: int
    applied_at: str
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_id(self.apply_id)
        validate_id(self.action_instance_id)
        utc_instant(self.applied_at)
        validate_version(self.grant_control_version)
        if type(self.scope) is not Scope or type(self.approval_ref) is not ApprovalRef or type(self.intent_digest) is not Digest:
            raise ReferenceError('INVALID_CHANGE_SET')
        ChangeMutationPlan(self.change_set, self.mutations)
        refs = tuple(self.change_set.proposal_refs) + tuple(m.proposed_ref for m in self.mutations)
        refs += tuple(m.expected.head_ref for m in self.mutations if m.expected.head_ref is not None)
        if type(self.review_refs) is not tuple or any(type(r) is not ReviewRef for r in self.review_refs):
            raise ReferenceError('INVALID_REVIEW')
        refs += self.review_refs + (self.approval_ref,)
        if any((r.realm_id, r.project_id) != (self.scope.realm_id, self.scope.project_id) for r in refs):
            raise ReferenceError('REALM_MISMATCH')
        body = {k: v for k, v in asdict(self).items() if k != 'digest'}
        if len(canonical_bytes(body)) > 2 * 1024 * 1024:
            raise ReferenceError('PROPOSAL_TOO_LARGE')
        object.__setattr__(self, 'digest', record_digest('change-application-receipt', body))


def decode_application_receipt(raw):
    from ..common.mechanisms.codec import canonical_value, require_object, decode_scope, decode_digest, decode_tuple
    from ..artifacts.ref_codec import decode_artifact_ref
    from ..approvals.ref_codec import decode_approval_ref
    from ..reviews.ref_codec import decode_review_ref
    from .ref_codec import decode_proposal_ref
    value = canonical_value(raw)
    require_object(value, {f.name for f in fields(ChangeApplicationReceipt)}, 'INVALID_CHANGE_SET')
    change = value['change_set']
    require_object(change, {'proposal_refs', 'digest'}, 'INVALID_CHANGE_SET')
    batch = ChangeSet(decode_tuple(change['proposal_refs'], decode_proposal_ref, 'INVALID_CHANGE_SET'))
    if batch.digest != decode_digest(change['digest']):
        raise ReferenceError('DIGEST_MISMATCH')
    def mutation(v):
        require_object(v, {'expected', 'proposed_ref'}, 'INVALID_MUTATION')
        h = v['expected']
        require_object(h, {'artifact_id', 'version', 'head_ref'}, 'INVALID_MUTATION')
        return HeadMutation(HeadExpectation(h['artifact_id'], h['version'],
            None if h['head_ref'] is None else decode_artifact_ref(h['head_ref'])), decode_artifact_ref(v['proposed_ref']))
    receipt = ChangeApplicationReceipt(decode_scope(value['scope']), value['apply_id'], value['action_instance_id'],
        decode_approval_ref(value['approval_ref']), decode_digest(value['intent_digest']), batch,
        decode_tuple(value['mutations'], mutation, 'INVALID_MUTATION'),
        decode_tuple(value['review_refs'], decode_review_ref, 'INVALID_REVIEW'),
        value['grant_control_version'], value['applied_at'])
    if receipt.digest != decode_digest(value['digest']):
        raise ReferenceError('DIGEST_MISMATCH')
    return receipt

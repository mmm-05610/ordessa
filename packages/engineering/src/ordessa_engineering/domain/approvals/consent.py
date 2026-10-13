"""Exact conversation-backed acceptance values; attribution is not authentication.

This first action branch accepts exact artifacts. Unsupported implementation or
batch-apply scopes are not coerced into this branch. Product policy/admission,
reference resolution, current reviewer trust and persistence are external.
"""
from dataclasses import dataclass, field, asdict

from ordessa_infrastructure.encoding import canonical_bytes
from ..common.models.identity import Scope
from ..common.models.values import Digest, validate_id, validate_text, validate_items, utc_instant
from ..common.outcomes.diagnostics import ReferenceError
from ..common.mechanisms.hashing import record_digest
from ..artifacts.refs import ArtifactRevisionRef
from ..artifacts.method_binding import MethodRef
from ..reviews.models import ReviewRequirement
from .refs import ApprovalRef, ConsentPolicyRef, NoticeRef
from ..changes.models import ChangeSet
from ..changes.application_plan import HeadExpectation


def _refs(scope, refs):
    validate_items(refs, ArtifactRevisionRef, nonempty=True)
    if len(set(refs)) != len(refs) or any((r.realm_id, r.project_id) !=
            (scope.realm_id, scope.project_id) for r in refs):
        raise ReferenceError('INVALID_ACCEPTANCE_TARGETS')


def _seal(record, kind):
    payload = {k: v for k, v in asdict(record).items() if k != 'digest'}
    if len(canonical_bytes(payload)) > 2 * 1024 * 1024:
        raise ReferenceError('CONSENT_RECORD_TOO_LARGE')
    object.__setattr__(record, 'digest', record_digest(kind, payload))


@dataclass(frozen=True)
class ConversationSource:
    locator: str
    message_refs: tuple[str, ...]
    limitations: str
    attestor_id: str
    captured_at: str
    trust_grade: str = 'agent-attested'

    def __post_init__(self):
        validate_text(self.locator)
        validate_text(self.limitations)
        validate_id(self.attestor_id)
        utc_instant(self.captured_at)
        validate_items(self.message_refs, str)
        for ref in self.message_refs:
            validate_text(ref)
        if self.trust_grade != 'agent-attested':
            raise ReferenceError('UNSUPPORTED_CONSENT_SOURCE')


@dataclass(frozen=True)
class ConversationNotice:
    scope: Scope
    notice_id: str
    targets: tuple[ArtifactRevisionRef, ...]
    summary_ref: ArtifactRevisionRef
    actual_text: str
    source: ConversationSource
    policy_ref: ConsentPolicyRef
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.source) is not ConversationSource or type(self.policy_ref) is not ConsentPolicyRef:
            raise ReferenceError('INVALID_NOTICE')
        validate_id(self.notice_id)
        validate_text(self.actual_text)
        _refs(self.scope, self.targets)
        _refs(self.scope, (self.summary_ref,))
        _seal(self, 'conversation-notice')

    @property
    def ref(self):
        return NoticeRef(self.scope, self.notice_id, self.digest)


@dataclass(frozen=True)
class AuthorizationIntent:
    scope: Scope
    intent_id: str
    targets: tuple[ArtifactRevisionRef, ...]
    method_ref: MethodRef
    notice_ref: NoticeRef
    policy_ref: ConsentPolicyRef
    required_review_requirements: tuple[ReviewRequirement, ...]
    acceptance_use: str
    request_summary: str
    not_before: str
    expires_at: str
    action_budget: int = 1
    actions: tuple[str, ...] = ('accept_artifact',)
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_id(self.intent_id)
        if type(self.scope) is not Scope or type(self.method_ref) is not MethodRef or type(self.policy_ref) is not ConsentPolicyRef:
            raise ReferenceError('INVALID_AUTHORIZATION_INTENT')
        _refs(self.scope, self.targets)
        if type(self.notice_ref) is not NoticeRef or self.notice_ref.scope != self.scope:
            raise ReferenceError('INVALID_NOTICE')
        if self.actions != ('accept_artifact',) or self.acceptance_use not in {'reference', 'adopt_content'}:
            raise ReferenceError('UNSUPPORTED_AUTHORIZATION_ACTION')
        if type(self.action_budget) is not int or not 1 <= self.action_budget <= 4096:
            raise ReferenceError('INVALID_AUTHORIZATION_BUDGET')
        validate_items(self.required_review_requirements, ReviewRequirement, nonempty=True)
        keys = [(r.requirement_id, r.requirement_version) for r in self.required_review_requirements]
        if len(keys) != len(set(keys)):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
        covered = set()
        for requirement in self.required_review_requirements:
            if requirement.scope != self.scope or requirement.method_ref != self.method_ref:
                raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
            refs = {target.ref for target in requirement.expected_targets.targets}
            if not refs.issubset(set(self.targets)):
                raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
            covered.update(refs)
        if covered != set(self.targets):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
        validate_text(self.request_summary)
        utc_instant(self.not_before)
        utc_instant(self.expires_at)
        if self.not_before >= self.expires_at:
            raise ReferenceError('INVALID_CONSENT_TIME')
        _seal(self, 'authorization-intent')


@dataclass(frozen=True)
class ConsentChallenge:
    scope: Scope
    challenge_id: str
    intent_id: str
    binding_digest: Digest
    presented_digest: Digest
    nonce_digest: Digest
    expires_at: str

    def __post_init__(self):
        validate_id(self.challenge_id)
        validate_id(self.intent_id)
        if type(self.scope) is not Scope or any(type(v) is not Digest for v in
                (self.binding_digest, self.presented_digest, self.nonce_digest)):
            raise ReferenceError('INVALID_CONSENT_CHALLENGE')
        utc_instant(self.expires_at)


@dataclass(frozen=True)
class ChangeAuthorizationIntent:
    """Exact DID artifact batch, distinct from repository implementation rights."""
    scope: Scope
    intent_id: str
    change_set: ChangeSet
    targets: tuple[ArtifactRevisionRef, ...]
    expected_heads: tuple[HeadExpectation, ...]
    method_ref: MethodRef
    notice_ref: NoticeRef
    policy_ref: ConsentPolicyRef
    required_review_requirements: tuple[ReviewRequirement, ...]
    request_summary: str
    not_before: str
    expires_at: str
    action_budget: int = 1
    actions: tuple[str, ...] = ('apply_change',)
    intent_kind: str = field(default='change_apply', init=False)
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_id(self.intent_id)
        if (type(self.scope) is not Scope or type(self.change_set) is not ChangeSet
                or type(self.method_ref) is not MethodRef or type(self.policy_ref) is not ConsentPolicyRef
                or type(self.notice_ref) is not NoticeRef or self.notice_ref.scope != self.scope):
            raise ReferenceError('INVALID_AUTHORIZATION_INTENT')
        if any((r.realm_id, r.project_id) != (self.scope.realm_id, self.scope.project_id)
               for r in self.change_set.proposal_refs):
            raise ReferenceError('REALM_MISMATCH')
        _refs(self.scope, self.targets)
        validate_items(self.expected_heads, HeadExpectation, nonempty=True)
        ids = [h.artifact_id for h in self.expected_heads]
        if len(ids) != len(set(ids)) or set(ids) != {r.artifact_id for r in self.targets}:
            raise ReferenceError('INCOMPLETE_BATCH')
        for h in self.expected_heads:
            if h.head_ref is not None and (h.head_ref.realm_id, h.head_ref.project_id) != (self.scope.realm_id, self.scope.project_id):
                raise ReferenceError('REALM_MISMATCH')
        if self.actions != ('apply_change',) or type(self.action_budget) is not int or not 1 <= self.action_budget <= 4096:
            raise ReferenceError('INVALID_AUTHORIZATION_BUDGET')
        validate_items(self.required_review_requirements, ReviewRequirement, nonempty=True)
        keys = [(r.requirement_id, r.requirement_version) for r in self.required_review_requirements]
        if len(keys) != len(set(keys)) or any(r.scope != self.scope or r.method_ref != self.method_ref
                for r in self.required_review_requirements):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
        validate_text(self.request_summary)
        utc_instant(self.not_before)
        utc_instant(self.expires_at)
        if self.not_before >= self.expires_at:
            raise ReferenceError('INVALID_CONSENT_TIME')
        _seal(self, 'change-authorization-intent')


@dataclass(frozen=True)
class ConversationEvidence:
    evidence_id: str
    question: str
    necessary_context: str
    user_answer: str
    source: ConversationSource
    policy_ref: ConsentPolicyRef
    intent_digest: Digest
    notice_ref: NoticeRef
    disposition: str
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_id(self.evidence_id)
        for text in (self.question, self.necessary_context, self.user_answer):
            validate_text(text)
        if (type(self.source) is not ConversationSource or type(self.policy_ref) is not ConsentPolicyRef
                or type(self.intent_digest) is not Digest or type(self.notice_ref) is not NoticeRef
                or self.disposition not in {'confirm', 'decline', 'ambiguous'}):
            raise ReferenceError('INVALID_CONVERSATION_EVIDENCE')
        _seal(self, 'conversation-evidence')


@dataclass(frozen=True)
class ApprovalGrant:
    approval_id: str
    intent: AuthorizationIntent
    challenge_id: str
    evidence: ConversationEvidence
    granted_at: str
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_id(self.approval_id)
        validate_id(self.challenge_id)
        utc_instant(self.granted_at)
        from .implementation import ImplementationAuthorizationIntent
        if (type(self.intent) not in (AuthorizationIntent, ChangeAuthorizationIntent, ImplementationAuthorizationIntent) or type(self.evidence) is not ConversationEvidence
                or self.evidence.disposition != 'confirm' or self.evidence.intent_digest != self.intent.digest
                or self.evidence.notice_ref != self.intent.notice_ref or self.evidence.policy_ref != self.intent.policy_ref
                or not self.intent.not_before <= self.granted_at < self.intent.expires_at):
            raise ReferenceError('CONSENT_BINDING_MISMATCH')
        _seal(self, 'approval-grant')

    @property
    def ref(self):
        return ApprovalRef(self.intent.scope.realm_id, self.intent.scope.project_id,
                           self.approval_id, self.digest)

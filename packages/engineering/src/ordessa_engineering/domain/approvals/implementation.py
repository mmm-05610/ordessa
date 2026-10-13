"""Closed implementation authorization values; no trust or persistence owner."""
from dataclasses import asdict, dataclass, field

from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.hashing import record_digest
from ..common.models.identity import Scope
from ..common.models.values import Digest, validate_id, validate_items, validate_text, utc_instant
from ..common.outcomes.diagnostics import ReferenceError
from ..artifacts.refs import ArtifactRevisionRef
from ..artifacts.method_binding import MethodRef
from ..changes.models import ChangeSet
from ..changes.intent import ImplementationIntentSpec
from ..reviews.models import ReviewRequirement
from ..reviews.refs import ReviewRef
from .refs import ConsentPolicyRef, NoticeRef
from .scope import ACTIONS, ActionScope

MAX_IMPLEMENTATION_AUTHORIZATION_BYTES = 2 * 1024 * 1024
_FORBIDDEN_IMPLEMENTATION_ACTIONS = frozenset({'accept_artifact', 'apply_change'})


@dataclass(frozen=True)
class ActionBudgetSlot:
    """A frozen per-action limit; consumption belongs to the application owner."""

    action: str
    limit: int

    def __post_init__(self):
        if type(self.action) is not str or self.action not in ACTIONS or self.action in _FORBIDDEN_IMPLEMENTATION_ACTIONS:
            raise ReferenceError('INVALID_AUTHORIZATION_BUDGET')
        if type(self.limit) is not int or not 1 <= self.limit <= 4096:
            raise ReferenceError('INVALID_AUTHORIZATION_BUDGET')


@dataclass(frozen=True)
class ImplementationAuthorizationIntent:
    """Exact request for bounded implementation actions, not a grant."""

    scope: Scope
    intent_id: str
    change_set: ChangeSet
    targets: tuple[ArtifactRevisionRef, ...]
    method_ref: MethodRef
    notice_ref: NoticeRef
    policy_ref: ConsentPolicyRef
    implementation_spec: ImplementationIntentSpec
    required_review_requirements: tuple[ReviewRequirement, ...]
    supporting_review_refs: tuple[ReviewRef, ...]
    scope_by_action: tuple[tuple[str, ActionScope], ...]
    action_budgets: tuple[ActionBudgetSlot, ...]
    request_summary: str
    not_before: str
    expires_at: str
    actions: tuple[str, ...]
    intent_kind: str = field(default='implementation', init=False)
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.change_set) is not ChangeSet:
            raise ReferenceError('INVALID_AUTHORIZATION_INTENT')
        validate_id(self.intent_id)
        if (type(self.method_ref) is not MethodRef or type(self.notice_ref) is not NoticeRef
                or type(self.policy_ref) is not ConsentPolicyRef
                or type(self.implementation_spec) is not ImplementationIntentSpec):
            raise ReferenceError('INVALID_AUTHORIZATION_INTENT')
        if self.notice_ref.scope != self.scope:
            raise ReferenceError('INVALID_NOTICE')

        validate_items(self.actions, str, nonempty=True)
        if (any(action not in ACTIONS or action in _FORBIDDEN_IMPLEMENTATION_ACTIONS
                for action in self.actions)
                or len(set(self.actions)) != len(self.actions)
                or not set(self.actions).issubset(self.implementation_spec.requested_actions)):
            raise ReferenceError('UNSUPPORTED_AUTHORIZATION_ACTION')

        spec = self.implementation_spec
        if spec.digest != record_digest('implementation-intent-spec', spec.hash_payload()):
            raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
        if (spec.scope.project_id != self.scope.project_id
                or any(ref.realm_id != self.scope.realm_id for ref in spec.expected_baselines)
                or any((ref.realm_id, ref.project_id) !=
                       (self.scope.realm_id, self.scope.project_id)
                       for ref in self.change_set.proposal_refs)):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')

        validate_items(self.targets, ArtifactRevisionRef, nonempty=True)
        if (len(set(self.targets)) != len(self.targets)
                or any((ref.realm_id, ref.project_id) !=
                       (self.scope.realm_id, self.scope.project_id) for ref in self.targets)):
            raise ReferenceError('INVALID_AUTHORIZATION_TARGETS')

        validate_items(self.required_review_requirements, ReviewRequirement, nonempty=True)
        requirement_keys = [(r.requirement_id, r.requirement_version)
                            for r in self.required_review_requirements]
        if len(set(requirement_keys)) != len(requirement_keys):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
        design_targets = set(self.targets)
        covered_design_targets = set()
        for requirement in self.required_review_requirements:
            if requirement.scope != self.scope or requirement.method_ref != self.method_ref:
                raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
            refs = {target.ref for target in requirement.expected_targets.targets}
            if any((ref.realm_id, ref.project_id) !=
                   (self.scope.realm_id, self.scope.project_id) for ref in refs):
                raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')
            covered_design_targets.update(refs & design_targets)
        if covered_design_targets != design_targets:
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')

        validate_items(self.supporting_review_refs, ReviewRef)
        if (len(set(self.supporting_review_refs)) != len(self.supporting_review_refs)
                or any((ref.realm_id, ref.project_id) !=
                       (self.scope.realm_id, self.scope.project_id)
                       for ref in self.supporting_review_refs)):
            raise ReferenceError('INVALID_AUTHORIZATION_REQUIREMENTS')

        validate_items(self.scope_by_action, tuple, nonempty=True)
        scope_map = {}
        for entry in self.scope_by_action:
            if (type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str
                    or type(entry[1]) is not ActionScope or entry[0] in scope_map):
                raise ReferenceError('INVALID_ACTION_SCOPE')
            scope_map[entry[0]] = entry[1]
        if set(scope_map) != set(self.actions) or any(value != spec.scope for value in scope_map.values()):
            raise ReferenceError('INVALID_ACTION_SCOPE')

        validate_items(self.action_budgets, ActionBudgetSlot, nonempty=True)
        budget_map = {slot.action: slot.limit for slot in self.action_budgets}
        if len(budget_map) != len(self.action_budgets) or set(budget_map) != set(self.actions):
            raise ReferenceError('INVALID_AUTHORIZATION_BUDGET')

        validate_text(self.request_summary)
        utc_instant(self.not_before)
        utc_instant(self.expires_at)
        if self.not_before >= self.expires_at:
            raise ReferenceError('INVALID_CONSENT_TIME')

        payload = {key: value for key, value in asdict(self).items()
                   if key != 'digest'}
        if len(canonical_bytes(payload)) > MAX_IMPLEMENTATION_AUTHORIZATION_BYTES:
            raise ReferenceError('CONSENT_RECORD_TOO_LARGE')
        object.__setattr__(self, 'digest', record_digest('implementation-authorization-intent', payload))

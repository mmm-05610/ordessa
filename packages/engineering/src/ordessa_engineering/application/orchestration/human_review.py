"""Human review disposition projection under an independently selected policy.

This module is a pure rules helper. It does not select/authenticate a policy,
attest a person, or replace the original method/source admission guards.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes
from ..contracts.errors import ApplicationError
from ..contracts.manual_reviews import ManualReviewReply
from ..contracts.reviewer_admission import CriterionAnswer
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.common.models.values import Digest, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.reviews.models import Observation, ReviewPlan
from ...methods.loading.captured import parse_captured_resource
from ...methods.definitions.models import ResourceBytes
from ...methods.definitions.errors import MethodFailure
from ...methods.definitions.models.compiled import thaw_value

_ADMISSION = 'human_review_admission'
_ADMISSION_CONTRACT = 'ordessa.human-review-admission/1'
_POLICY_CONTRACT = 'ordessa.human-review-policy/1'
_STATUSES = {'satisfied', 'violated', 'insufficient', 'unknown'}
_DISPOSITIONS = {'pass', 'block', 'manual'}
_POLICY_REQUIRED_FIELDS = {
    'schema_version', 'contract_version', 'policy_id', 'revision', 'selection_authority',
    'authorized_attestor_role', 'accepted_source_trust_level', 'review_path',
    'whole_plan_answer', 'missing_answer', 'ambiguous_answer', 'mechanical_integrity',
    'review_is_implementation_grant', 'status_dispositions',
}


def _fail(code):
    raise ApplicationError(code)


def _policy(raw):
    if type(raw) is not bytes or not raw or len(raw) > 262144:
        _fail('HUMAN_REVIEW_POLICY_INVALID')
    try:
        value = parse_captured_resource(ResourceBytes('product-chat-human-review.v1.yaml', 'application/yaml', raw))
    except (MethodFailure, ValueError, TypeError, RecursionError):
        _fail('HUMAN_REVIEW_POLICY_INVALID')
    if (type(value) is not dict or not _POLICY_REQUIRED_FIELDS <= set(value)
            or set(value) - _POLICY_REQUIRED_FIELDS - {'provenance'}
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or value.get('contract_version') != _POLICY_CONTRACT
            or type(value.get('policy_id')) is not str
            or type(value.get('revision')) is not int or value['revision'] < 1
            or value.get('selection_authority') != 'product_composition_and_configured_engineering_admission'
            or value.get('authorized_attestor_role') != 'registered_main_agent'
            or value.get('accepted_source_trust_level') != 'agent-attested'
            or value.get('review_path') != 'human_semantic_review'
            or value.get('whole_plan_answer') != 'explicit_complete_checklist'
            or value.get('missing_answer') != 'pending' or value.get('ambiguous_answer') != 'pending'
            or value.get('mechanical_integrity') != 'required'
            or value.get('review_is_implementation_grant') is not False):
        _fail('HUMAN_REVIEW_POLICY_INVALID')
    try:
        validate_id(value['policy_id'])
    except (ReferenceError, TypeError, ValueError):
        _fail('HUMAN_REVIEW_POLICY_INVALID')
    statuses = value.get('status_dispositions')
    if (type(statuses) is not dict or set(statuses) != _STATUSES
            or any(type(x) is not str or x not in _DISPOSITIONS for x in statuses.values())
            or statuses.get('violated') == 'pass' or statuses.get('insufficient') == 'pass'
            or statuses.get('unknown') == 'pass'):
        _fail('HUMAN_REVIEW_POLICY_INVALID')
    return value


def _human_declaration(criterion):
    checks = getattr(criterion, 'checks', ())
    if len(checks) != 1:
        _fail('HUMAN_REVIEW_NOT_ADMITTED')
    bindings = thaw_value(checks[0].bindings)
    if type(bindings) is not dict:
        _fail('HUMAN_REVIEW_NOT_ADMITTED')
    return bindings.get(_ADMISSION)


def _match_declaration(declaration, policy, policy_digest):
    if declaration is None:
        _fail('HUMAN_REVIEW_NOT_ADMITTED')
    expected = {
        'contract_version': _ADMISSION_CONTRACT,
        'activation': 'selected_product_policy_required',
        'policy_id': policy['policy_id'],
        'policy_revision': policy['revision'],
        'policy_digest': 'sha256:' + policy_digest,
        'status_dispositions': policy['status_dispositions'],
    }
    if type(declaration) is not dict or declaration != expected:
        _fail('HUMAN_REVIEW_POLICY_BINDING_MISMATCH')


def human_review_observations(plan, standard, reply: ManualReviewReply, policy_bytes: bytes,
                              mechanical_answers: tuple[CriterionAnswer, ...]) -> tuple[Observation, ...]:
    """Project full-plan human answers using only the exact selected external policy.

    Human status does not override missing mechanical source/coverage facts.
    """
    if type(plan) is not ReviewPlan or type(reply) is not ManualReviewReply:
        _fail('HUMAN_REVIEW_REPLY_INVALID')
    policy = _policy(policy_bytes)
    policy_digest = hashlib.sha256(policy_bytes).hexdigest()
    if (getattr(standard, 'standard_id', None) != plan.requirement.criterion_set_ref.criterion_set_id
            or getattr(getattr(standard, 'resource_ref', None), 'sha256', None)
            != plan.requirement.criterion_set_ref.digest.hex):
        _fail('METHOD_REQUIREMENTS_CHANGED')
    if (type(reply.check_answers) is not tuple or len(reply.check_answers) != len(plan.check_keys)
            or any(type(a) is not CriterionAnswer or a.status not in _STATUSES for a in reply.check_answers)
            or len({a.check_key for a in reply.check_answers}) != len(reply.check_answers)
            or {a.check_key for a in reply.check_answers} != set(plan.check_keys)):
        _fail('MANUAL_REVIEW_REPLY_INCOMPLETE')
    if (type(mechanical_answers) is not tuple
            or any(type(a) is not CriterionAnswer or a.status not in _STATUSES for a in mechanical_answers)
            or len({a.check_key for a in mechanical_answers}) != len(mechanical_answers)):
        _fail('REVIEW_SOURCE_INVALID')

    criteria = {item.criterion_id: item for item in standard.criteria}
    reply_by_key = {item.check_key: item for item in reply.check_answers}
    mechanical_by_key = {item.check_key: item for item in mechanical_answers}
    expected_mechanical = {key for key in plan.check_keys
        if (len(getattr(criteria.get(key.criterion_id), 'checks', ())) == 1
            and criteria[key.criterion_id].checks[0].capability_id in
                {'ordessa.sources.integrity', 'ordessa.claims.coverage'})}
    if set(mechanical_by_key) != expected_mechanical:
        _fail('REVIEW_SOURCE_INCOMPLETE')

    observations = []
    semantic_seen = False
    for key in plan.check_keys:
        criterion = criteria.get(key.criterion_id)
        if (criterion is None or len(getattr(criterion, 'checks', ())) != 1
                or criterion.decision_policy is not None):
            _fail('METHOD_REQUIREMENTS_CHANGED')
        check = criterion.checks[0]
        if check.interface_version != '1.0.0':
            _fail('HUMAN_REVIEW_NOT_ADMITTED')
        capability = check.capability_id
        answer = reply_by_key[key]
        if capability == 'ordessa.sources.integrity':
            declaration = _human_declaration(criterion)
            if declaration is not None:
                _fail('HUMAN_REVIEW_NOT_ADMITTED')
            mechanical = mechanical_by_key[key]
            if mechanical.status not in {'satisfied', 'insufficient', 'unknown'}:
                _fail('REVIEW_SOURCE_INVALID')
            if mechanical.status != answer.status:
                _fail('HUMAN_REVIEW_MECHANICAL_CONFLICT')
            disposition = getattr(criterion.policy, mechanical.status, None)
            if disposition not in _DISPOSITIONS:
                _fail('METHOD_REQUIREMENTS_CHANGED')
        elif capability in {'ordessa.claims.coverage', 'ordessa.decision.evaluate'}:
            declaration = _human_declaration(criterion)
            _match_declaration(declaration, policy, policy_digest)
            semantic_seen = True
            mechanical = mechanical_by_key.get(key)
            if capability == 'ordessa.claims.coverage':
                if mechanical is None:
                    _fail('REVIEW_SOURCE_INCOMPLETE')
                if mechanical.status not in {'unknown', 'insufficient'}:
                    _fail('REVIEW_SOURCE_INVALID')
                if mechanical.status == 'insufficient' and answer.status == 'satisfied':
                    _fail('HUMAN_REVIEW_MECHANICAL_CONFLICT')
            disposition = policy['status_dispositions'][answer.status]
        else:
            _fail('HUMAN_REVIEW_NOT_ADMITTED')
        result = {'pass': 'pass', 'block': 'fail', 'manual': 'indeterminate'}[disposition]
        observations.append(Observation(key, result, answer.evidence_refs, answer.rationale))
    if not semantic_seen:
        _fail('HUMAN_REVIEW_NOT_ADMITTED')
    return tuple(sorted(observations, key=lambda item: item.check_key.sort_key))


def human_review_presentation_digest(plan, reply: ManualReviewReply, policy_bytes: bytes) -> Digest:
    """Hash the exact human-facing context and selected policy; never an auth proof."""
    if type(plan) is not ReviewPlan or type(reply) is not ManualReviewReply:
        _fail('HUMAN_REVIEW_REPLY_INVALID')
    _policy(policy_bytes)
    return record_digest('human-review-presentation', {
        'plan_digest': asdict(plan.plan_digest),
        'method_ref': asdict(plan.requirement.method_ref),
        'criterion_set_ref': asdict(plan.requirement.criterion_set_ref),
        'check_keys': [asdict(key) for key in plan.check_keys],
        'targets': [asdict(target) for target in plan.requirement.expected_targets.targets],
        'question': reply.question,
        'necessary_context': reply.necessary_context,
        'user_answer': reply.user_answer,
        'source': asdict(reply.source),
        'reply_answers': [asdict(answer) for answer in reply.check_answers],
        'selected_policy_raw_digest': hashlib.sha256(policy_bytes).hexdigest(),
    })

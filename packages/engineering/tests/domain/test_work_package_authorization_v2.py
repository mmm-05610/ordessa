"""Schema-2 Work/package authorization closure; all identities are synthetic.

This slice is a pure domain value model plus its closed codec. It issues no
grant and wires no dispatch: an intent here is a request, never a permission.
"""
import hashlib
from dataclasses import fields, replace

import pytest

from ordessa_engineering.domain.approvals.consent import (
    ApprovalGrant, AuthorizationIntent, ConsentPolicyRef, ConversationEvidence,
    ConversationNotice, ConversationSource, NoticeRef, WorkPackageNotice,
)
from ordessa_engineering.domain.approvals.consent_codec import decode_record, encode_record
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, ImplementationAuthorizationIntent, WorkPackageAuthorization,
    WorkPackageAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, PathRule, RepositoryScope,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.models import (
    CheckKey, CriterionSetRef, ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_infrastructure.encoding import canonical_bytes, decode_json

SCOPE = Scope('synthetic-implementation-realm', 'synthetic-implementation-project')
METHOD = MethodRef('synthetic-method', '1.0.0', 1, Digest('sha256', 'a' * 64))
CREATED = '2026-10-11T12:00:00.000000Z'
EXPIRES = '2026-10-12T12:00:00.000000Z'

# Pinned from the pre-schema-2 codec at HEAD (verified against the frozen
# before-image of this slice): the v1 implementation-authorization bytes are
# untouched by the schema-2 additions below.
V1_BYTES_LENGTH = 6048
V1_BYTES_SHA256 = '1a906869e537d62d6cbb8948e58a8698d509c77eae214938794e43ae14d04192'


def _digest(text):
    return Digest('sha256', hashlib.sha256(text.encode()).hexdigest())


def _policy():
    return ConsentPolicyRef('synthetic-policy', 1, _digest('policy'))


def _v1_intent():
    """The schema-1 implementation authorization; its bytes must never move."""
    target = ArtifactRevisionRef(*SCOPE.__dict__.values(), 'design-doc', 'revision-1', _digest('design'))
    proposal = ProposalRef(*SCOPE.__dict__.values(), 'change-1', 'proposal-1', _digest('proposal'))
    baseline = RepositorySnapshotRef(*SCOPE.__dict__.values(), 'repo-1', 'none', None, _digest('tree'), None)
    action_scope = ActionScope(
        SCOPE.project_id,
        (RepositoryScope('repo-1', (PathRule('src', 'subtree', ('modify',)),)),),
        (), (), (), 'implementation-intent-1',
    )
    spec = ImplementationIntentSpec(
        'implementation-intent-1', ('generate_package', 'edit_repository'), action_scope,
        (baseline,), (), ('Use only the approved proposal.',),
    )
    targets = TargetSet((Target('primary', target), Target('support', proposal)))
    requirement = ReviewRequirement(
        SCOPE, 'implementation-review', 1, 'quality', targets, METHOD,
        CriterionSetRef('synthetic-criteria', 1, _digest('criteria')),
        (CheckKey(Target('primary', target), 'criterion-design'),
         CheckKey(Target('support', proposal), 'criterion-proposal')),
        ('synthetic-reviewer',), 'quality_review',
    )
    return ImplementationAuthorizationIntent(
        scope=SCOPE,
        intent_id='implementation-authorization-1',
        change_set=ChangeSet((proposal,)),
        targets=(target,),
        method_ref=METHOD,
        notice_ref=NoticeRef(SCOPE, 'synthetic-notice', _digest('notice')),
        policy_ref=_policy(),
        implementation_spec=spec,
        required_review_requirements=(requirement,),
        supporting_review_refs=(ReviewRef(*SCOPE.__dict__.values(), 'synthetic-review', _digest('review')),),
        scope_by_action=(('generate_package', action_scope), ('edit_repository', action_scope)),
        action_budgets=(ActionBudgetSlot('generate_package', 2), ActionBudgetSlot('edit_repository', 1)),
        request_summary='Synthetic fixture; this does not represent human confirmation.',
        not_before=CREATED,
        expires_at=EXPIRES,
        actions=('generate_package', 'edit_repository'),
    )


def _action_scope(intent_id='work-package-intent-1'):
    # Empty repository/environment/effect/exclusion sets: the v2 subject carries
    # no exhaustive file plan, no checkout verification and no directory identity.
    return ActionScope(SCOPE.project_id, (), (), (), (), intent_id)


def _package(package_id='package-1', digest=None):
    return ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, package_id,
                                    digest or _digest('package'))


def _subject(**changes):
    action_scope = _action_scope()
    values = dict(
        scope=SCOPE,
        intent_id='work-package-intent-1',
        work_id='work-1',
        work_revision=3,
        work_digest=_digest('work'),
        action_id='incremental.prepare-packages',
        step_id='draft',
        package_ref=_package(),
        method_ref=METHOD,
        actions=('edit_repository', 'run_checks'),
        scope_by_action=(('edit_repository', action_scope), ('run_checks', action_scope)),
        action_budgets=(ActionBudgetSlot('edit_repository', 1), ActionBudgetSlot('run_checks', 4)),
        request_summary='Synthetic Work/package fixture; not human confirmation.',
        not_before=CREATED,
        expires_at=EXPIRES,
    )
    values.update(changes)
    return WorkPackageAuthorization(**values)


def _source():
    return ConversationSource(
        'synthetic-locator', ('message-1',),
        'Synthetic transcript; not a genuine capture.',
        'synthetic-attestor', CREATED,
    )


def _records():
    subject = _subject()
    notice = WorkPackageNotice('work-package-notice-1', subject,
                               'Approve this exact Work/package.', _source(), _policy())
    intent = WorkPackageAuthorizationIntent(subject, notice.ref, _policy())
    return subject, notice, intent


def _reject(call, code):
    with pytest.raises(ReferenceError) as caught:
        call()
    assert caught.value.code == code


def test_v2_subject_is_a_versioned_work_package_value():
    subject = _subject()
    assert subject.schema_version == 2
    assert subject.subject_kind == 'work_package'
    assert subject.work_revision == 3
    # Rebuilding the identical value reproduces the identical seal.
    assert subject.digest == _subject().digest
    # No grant or proof field can manufacture permission from this value.
    assert not hasattr(subject, 'approval_ref')
    assert not hasattr(subject, 'binding_proof')


def test_v2_notice_and_intent_roundtrip_and_share_one_authorization_value():
    subject, notice, intent = _records()
    assert notice.authorization is subject
    assert intent.authorization is subject
    assert notice.authorization == intent.authorization
    assert notice.ref == intent.notice_ref
    assert notice.ref.scope == subject.scope
    assert intent.intent_kind == 'implementation'
    # The notice must not carry an intent summary: that would be a cycle.
    assert not hasattr(notice, 'intent_digest')
    for record, cls in ((subject, WorkPackageAuthorization),
                        (notice, WorkPackageNotice),
                        (intent, WorkPackageAuthorizationIntent)):
        raw = encode_record(record)
        assert decode_record(raw, cls) == record
        assert encode_record(decode_record(raw, cls)) == raw


def test_v2_rejects_extra_fields_unknown_version_and_forged_seal():
    from ordessa_infrastructure.encoding import canonical_bytes, decode_json
    raw = encode_record(_subject())
    extra = decode_json(raw)
    extra['unexpected'] = 'x'
    _reject(lambda: decode_record(canonical_bytes(extra), WorkPackageAuthorization),
            'INVALID_CONSENT_RECORD')
    future = decode_json(raw)
    future['schema_version'] = 3
    _reject(lambda: decode_record(canonical_bytes(future), WorkPackageAuthorization),
            'INVALID_CONSENT_RECORD')
    forged = decode_json(raw)
    forged['digest'] = {'algorithm': 'sha256', 'hex': '0' * 64}
    _reject(lambda: decode_record(canonical_bytes(forged), WorkPackageAuthorization),
            'CONSENT_DIGEST_MISMATCH')


def test_v2_rejects_forbidden_duplicate_and_empty_actions():
    for forbidden in ('generate_package', 'apply_change', 'accept_artifact'):
        _reject(lambda forbidden=forbidden: _subject(actions=(forbidden,)),
                'UNSUPPORTED_AUTHORIZATION_ACTION')
    _reject(lambda: _subject(actions=('edit_repository', 'edit_repository')),
            'UNSUPPORTED_AUTHORIZATION_ACTION')
    _reject(lambda: _subject(actions=('not_a_declared_action',)),
            'UNSUPPORTED_AUTHORIZATION_ACTION')
    _reject(lambda: _subject(actions=()), 'INVALID_SCHEMA')


def test_v2_scope_and_budget_keys_must_match_actions_exactly():
    # scope_by_action key set must equal actions, and every ActionScope must
    # carry this subject's project and intent id.
    _reject(lambda: _subject(scope_by_action=(('edit_repository', _action_scope()),)),
            'INVALID_ACTION_SCOPE')
    _reject(lambda: _subject(scope_by_action=(
        ('edit_repository', _action_scope('another-intent')), ('run_checks', _action_scope()))),
        'INVALID_ACTION_SCOPE')
    _reject(lambda: _subject(scope_by_action=(
        ('edit_repository', _action_scope()), ('run_checks', _action_scope('another-intent')))),
        'INVALID_ACTION_SCOPE')
    _reject(lambda: _subject(action_budgets=(ActionBudgetSlot('edit_repository', 1),)),
            'INVALID_AUTHORIZATION_BUDGET')
    # A budget for an action the v2 contract forbids can never match the action set.
    _reject(lambda: _subject(action_budgets=(
        ActionBudgetSlot('edit_repository', 1), ActionBudgetSlot('run_checks', 1),
        ActionBudgetSlot('generate_package', 1))), 'INVALID_AUTHORIZATION_BUDGET')


def test_v2_budget_and_time_bounds_are_the_shared_integer_bounds():
    _reject(lambda: ActionBudgetSlot('run_checks', 0), 'INVALID_AUTHORIZATION_BUDGET')
    _reject(lambda: ActionBudgetSlot('run_checks', 4097), 'INVALID_AUTHORIZATION_BUDGET')
    _reject(lambda: ActionBudgetSlot('run_checks', True), 'INVALID_AUTHORIZATION_BUDGET')
    _reject(lambda: _subject(not_before=EXPIRES, expires_at=CREATED), 'INVALID_CONSENT_TIME')
    _reject(lambda: _subject(not_before=CREATED, expires_at=CREATED), 'INVALID_CONSENT_TIME')


def test_v2_package_scope_and_work_identity_are_exact():
    other = Scope('synthetic-other-realm', 'synthetic-other-project')
    foreign_package = ImplementationPackageRef('synthetic-other-realm', 'synthetic-other-project',
                                               'package-1', _digest('package'))
    _reject(lambda: _subject(package_ref=foreign_package), 'INVALID_WORK_PACKAGE_AUTHORIZATION')
    # A matching package but a foreign scope leaves the ActionScope project stale.
    _reject(lambda: _subject(scope=other, package_ref=foreign_package), 'INVALID_ACTION_SCOPE')
    _reject(lambda: _subject(work_revision=0), 'INVALID_VERSION')
    # The intent's notice reference must name the authorization's own scope.
    _, notice, _ = _records()
    foreign_notice = NoticeRef(other, notice.notice_id, notice.digest)
    _reject(lambda: WorkPackageAuthorizationIntent(_subject(), foreign_notice, _policy()),
            'INVALID_NOTICE')


def test_v2_digest_changes_with_any_frozen_field():
    base = _subject().digest
    assert replace(_subject(), work_revision=4).digest != base
    assert replace(_subject(), work_digest=_digest('other-work')).digest != base
    assert replace(_subject(), action_id='incremental.other').digest != base
    assert replace(_subject(), step_id='other-step').digest != base
    assert replace(_subject(), package_ref=_package('package-2')).digest != base
    assert replace(_subject(), package_ref=_package(digest=_digest('other-package'))).digest != base
    assert replace(_subject(), not_before='2026-10-11T13:00:00.000000Z').digest != base
    assert replace(_subject(), expires_at='2026-10-12T13:00:00.000000Z').digest != base
    # The notice and intent seals cover the same frozen subject plus their own
    # version domain.
    _, notice, intent = _records()
    assert replace(intent, authorization=replace(_subject(), work_revision=4)).digest != intent.digest
    assert replace(notice, authorization=replace(_subject(), work_revision=4)).digest != notice.digest


def test_v1_record_bytes_are_byte_level_unchanged():
    intent = _v1_intent()
    raw = encode_record(intent)
    assert len(raw) == V1_BYTES_LENGTH
    assert hashlib.sha256(raw).hexdigest() == V1_BYTES_SHA256
    # The schema-2 additions never re-encode or re-validate a stored v1 record.
    assert decode_record(raw, ImplementationAuthorizationIntent) == intent
    assert encode_record(decode_record(raw, ImplementationAuthorizationIntent)) == raw
    # v1 still admits `generate_package`; the v2-only bound does not leak into it.
    assert 'generate_package' in intent.actions


def test_other_approval_types_still_roundtrip():
    intent = _v1_intent()
    for record, cls in ((_source(), ConversationSource),
                        (intent.notice_ref, NoticeRef),
                        (intent.policy_ref, ConsentPolicyRef),
                        (intent, ImplementationAuthorizationIntent)):
        raw = encode_record(record)
        assert decode_record(raw, cls) == record


# --- W2-A2: strict version dispatch, derived views and nested-intent grants ---

DERIVED_INTENT_VIEWS = ('scope', 'intent_id', 'method_ref', 'actions', 'not_before', 'expires_at')


def _v1_notice():
    """The schema-1 conversation notice; its branch must stay unchanged."""
    target = ArtifactRevisionRef(*SCOPE.__dict__.values(), 'design-doc', 'revision-1', _digest('design'))
    return ConversationNotice(
        SCOPE, 'synthetic-conversation-notice', (target,), target,
        'Synthetic v1 notice text; not a genuine capture.', _source(), _policy(),
    )


def _evidence(intent, **changes):
    values = dict(
        evidence_id='work-package-evidence-1',
        question='Approve this exact Work/package?',
        necessary_context='Synthetic transcript; not a genuine capture.',
        user_answer='Yes.',
        source=_source(),
        policy_ref=_policy(),
        intent_digest=intent.digest,
        notice_ref=intent.notice_ref,
        disposition='confirm',
    )
    values.update(changes)
    return ConversationEvidence(**values)


def _grant(intent, **changes):
    values = dict(
        approval_id='work-package-approval-1',
        intent=intent,
        challenge_id='work-package-challenge-1',
        evidence=_evidence(intent),
        granted_at=CREATED,
    )
    values.update(changes)
    return ApprovalGrant(**values)


def test_v2_generic_base_decode_dispatches_new_versions_by_schema_version():
    # The generic intent entry is AuthorizationIntent; a declared v2 version
    # selects the Work/package intent, an absent version the original v1 one.
    _, notice, intent = _records()
    intent_raw = encode_record(intent)
    decoded = decode_record(intent_raw, AuthorizationIntent)
    assert type(decoded) is WorkPackageAuthorizationIntent
    assert decoded == intent
    assert encode_record(decoded) == intent_raw

    notice_raw = encode_record(notice)
    decoded_notice = decode_record(notice_raw, ConversationNotice)
    assert type(decoded_notice) is WorkPackageNotice
    assert decoded_notice == notice
    assert encode_record(decoded_notice) == notice_raw

    # The old branches are untouched: v1 records keep their own class.
    v1_intent = _v1_intent()
    assert type(decode_record(encode_record(v1_intent), AuthorizationIntent)) is ImplementationAuthorizationIntent
    assert decode_record(encode_record(v1_intent), AuthorizationIntent) == v1_intent
    v1_notice = _v1_notice()
    assert type(decode_record(encode_record(v1_notice), ConversationNotice)) is ConversationNotice
    assert decode_record(encode_record(v1_notice), ConversationNotice) == v1_notice


def test_v2_generic_dispatch_refuses_unknown_version_and_shape_mismatch():
    _, notice, intent = _records()
    # An unknown declared version is refused, never guessed or downgraded.
    future = decode_json(encode_record(intent))
    future['schema_version'] = 3
    _reject(lambda: decode_record(canonical_bytes(future), AuthorizationIntent),
            'INVALID_CONSENT_RECORD')
    future_notice = decode_json(encode_record(notice))
    future_notice['schema_version'] = 9
    _reject(lambda: decode_record(canonical_bytes(future_notice), ConversationNotice),
            'INVALID_CONSENT_RECORD')
    # A v2 version with a v1 shape (and vice versa) is a shape mismatch.
    no_version = decode_json(encode_record(intent))
    no_version.pop('schema_version')
    _reject(lambda: decode_record(canonical_bytes(no_version), AuthorizationIntent),
            'INVALID_CONSENT_RECORD')
    forged_v1 = decode_json(encode_record(_v1_intent()))
    forged_v1['schema_version'] = 2
    _reject(lambda: decode_record(canonical_bytes(forged_v1), AuthorizationIntent),
            'INVALID_CONSENT_RECORD')
    forged_notice = decode_json(encode_record(_v1_notice()))
    forged_notice['schema_version'] = 2
    _reject(lambda: decode_record(canonical_bytes(forged_notice), ConversationNotice),
            'INVALID_CONSENT_RECORD')


def test_v2_intent_and_notice_expose_only_readonly_derived_views():
    subject, notice, intent = _records()
    # The scope is the authorization's own scope, derived rather than stored.
    assert notice.scope == subject.scope
    assert intent.scope == subject.scope
    assert intent.intent_id == subject.intent_id
    assert intent.method_ref == subject.method_ref
    assert intent.actions == subject.actions
    assert intent.not_before == subject.not_before
    assert intent.expires_at == subject.expires_at

    # Read-only: the descriptors have no setter.
    assert isinstance(WorkPackageNotice.scope, property) and WorkPackageNotice.scope.fset is None
    for name in DERIVED_INTENT_VIEWS:
        descriptor = getattr(WorkPackageAuthorizationIntent, name)
        assert isinstance(descriptor, property) and descriptor.fset is None

    # No second stored source: the derived names are neither fields nor bytes.
    stored_fields = {f.name for f in fields(WorkPackageAuthorizationIntent)}
    assert stored_fields.isdisjoint(DERIVED_INTENT_VIEWS)
    encoded_intent = decode_json(encode_record(intent))
    assert stored_fields == set(encoded_intent)
    assert 'scope' not in decode_json(encode_record(notice))

    # The intent fabricates no empty review requirement to satisfy a caller.
    for absent in ('required_review_requirements', 'supporting_review_refs', 'targets'):
        assert not hasattr(intent, absent)


def test_v2_nested_intent_grant_roundtrips_without_relaxing_binding():
    _, _, intent = _records()
    grant = _grant(intent)
    assert grant.intent is intent
    assert (grant.ref.realm_id, grant.ref.project_id) == (SCOPE.realm_id, SCOPE.project_id)
    raw = encode_record(grant)
    decoded = decode_record(raw, ApprovalGrant)
    assert type(decoded.intent) is WorkPackageAuthorizationIntent
    assert decoded == grant
    assert encode_record(decoded) == raw
    # The grant still manufactures no proof of its own.
    assert not hasattr(grant, 'proof')
    assert not hasattr(grant, 'binding_proof')


def test_v2_grant_refuses_wrong_evidence_and_time_binding():
    _, _, intent = _records()
    # Evidence must still be a confirmed ConversationEvidence bound to this intent.
    _reject(lambda: _grant(intent, evidence=_evidence(intent, intent_digest=_digest('other'))),
            'CONSENT_BINDING_MISMATCH')
    _reject(lambda: _grant(intent, evidence=_evidence(intent, disposition='decline')),
            'CONSENT_BINDING_MISMATCH')
    foreign_notice = NoticeRef(Scope('synthetic-other-realm', 'synthetic-other-project'),
                               'work-package-notice-1', _digest('other-notice'))
    _reject(lambda: _grant(intent, evidence=_evidence(intent, notice_ref=foreign_notice)),
            'CONSENT_BINDING_MISMATCH')
    other_policy = ConsentPolicyRef('synthetic-policy', 2, _digest('policy'))
    _reject(lambda: _grant(intent, evidence=_evidence(intent, policy_ref=other_policy)),
            'CONSENT_BINDING_MISMATCH')
    _reject(lambda: _grant(intent, evidence=_source()), 'CONSENT_BINDING_MISMATCH')
    # The original validity window is not widened: granted_at must be in
    # [not_before, expires_at), exactly as for the v1 intents.
    _reject(lambda: _grant(intent, granted_at=EXPIRES), 'CONSENT_BINDING_MISMATCH')
    _reject(lambda: _grant(intent, granted_at='2026-10-11T11:00:00.000000Z'),
            'CONSENT_BINDING_MISMATCH')

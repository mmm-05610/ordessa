"""Unit review adapter tests use synthetic source/trust ports only.

They exercise the original cold-read/capture and BlobStore seams. They do not
qualify a production UnitRecords live-trust authority or a real reviewer.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from test_method_control_admission import env, build_plan, context
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.orchestration.unit_review import (
    UnitReviewBinding, UnitReviewCheckSource,
)
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.identity import RecordIdentity
from ordessa_engineering.domain.reviews.models import CurrentReviewTrust, ReviewRecord
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.methods.definitions.models.identity import ResourceRef


class _SyntheticRecords:
    """Deterministic original-reader fixture, not production trust evidence."""
    def __init__(self, receipt):
        self.receipt = receipt

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest):
        return 'sha256:' + 'a' * 64

    def query_acp_turn(self, unit_ref, operation_ref, invocation, *, input_digest,
                       expected_prompt_input_digest):
        assert invocation.facts['inputDigest'] == input_digest
        assert input_digest == self.acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest)
        return self.receipt


class _SyntheticBindings:
    def __init__(self, binding, plan):
        self.binding, self.plan = binding, plan

    def resolve_unit_review(self, context, plan, request, *, standard):
        assert plan == self.plan
        assert request.state in ('requested', 'recorded')
        return self.binding

    def decode_response(self, binding, response_value, *, plan, standard):
        assert response_value == {'answers': []}
        return tuple(CriterionAnswer(key, 'satisfied', (), 'synthetic Unit review')
                     for key in plan.check_keys)

    def resolve_record_request(self, context, plan, record):
        assert record.plan == plan
        return SimpleNamespace(scope=plan.scope, review_id=plan.review_id,
                               state='recorded', version=1, fence=1)


class _SyntheticReviewerAuthority:
    """Synthetic injected owner; not a product reviewer identity source."""
    def __init__(self, scope, actor):
        self.scope, self.actor = scope, actor
        self.held = False
        self.revoked = False
        self.roles = None

    @contextmanager
    def guard_unit_reviewer(self, ctx, plan, request, binding, raw_ref, obs_digest, *, expected=None):
        if self.revoked:
            raise ApplicationError('UNIT_REVIEWER_REVOKED')
        author_ref = binding.reviewer_identity_constraints.get('authorUnitRef')
        if author_ref is not None and (
                author_ref.get('environmentNamespace'), author_ref.get('unitId')) == (
                    binding.unit_ref.get('environmentNamespace'), binding.unit_ref.get('unitId')):
            raise ApplicationError('UNIT_REVIEWER_IDENTITY_CONSTRAINT_FAILED')
        if expected is not None and expected.reviewer != self.actor:
            raise ApplicationError('UNIT_REVIEWER_CHANGED')
        evidence = VerifiedReviewerEvidence(
            self.scope, self.actor, tuple(self.roles or plan.reviewer_requirements),
            'synthetic-unit-review-owner', '1', 1, plan.request_digest,
            raw_ref.digest, obs_digest, Digest('sha256', 'b' * 64))
        self.held = True
        try:
            yield evidence
        finally:
            self.held = False


def _source(env, *, authority=True, mismatch=False):
    lib, method, factory, _, controls = env
    plan, _ = build_plan(env)
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef
    snapshot = SQLiteSnapshotStore(lib).get(SnapshotRef(
        method.method_id, method.release_version, method.schema_version, method.snapshot_digest.hex))
    standard = next(item for item in snapshot.program.standard_definitions
                    if item.standard_id == plan.requirement.criterion_set_ref.criterion_set_id)
    prompt = 'sha256:' + 'c' * 64
    unit_ref = {'environmentNamespace': 'synthetic-test', 'unitId': 'review-unit',
                'ownerProviderRef': 'fixture-owner', 'sourceRevision': 'fixed-v1'}
    document = snapshot.program.document_definitions[0]
    stored_schema = next(item for item in snapshot.resources
                         if item.resource_id == document.schema_resource.resource_id)
    schema = controls.snapshots.read_blob(stored_schema.blob_ref)
    binding = UnitReviewBinding(
        plan.plan_digest, 1, 1, unit_ref, 'review-operation', prompt,
        SimpleNamespace(facts={'inputDigest': 'sha256:' + 'a' * 64}),
        (plan.requirement.expected_targets.targets[0].ref,),
        document.schema_resource, document.document_type, schema,
        Digest('sha256', hashlib.sha256(schema).hexdigest()),
        {'principal': 'fixture-configured-reviewer'}, plan.check_keys)
    text = '{"answers":[]}'
    receipt = {
        'contractVersion': 'unit-acp-turn/1', 'unitRef': unit_ref,
        'operationRef': 'review-operation', 'inputDigest': prompt,
        'state': 'completed', 'revision': 3,
        'summary': {'text': text, 'modelQualityVerified': False},
    }
    if mismatch:
        receipt['state'] = 'unknown'
    blobs = SQLiteBlobStore(lib)
    raw = text.encode('utf-8')
    raw_ref = blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'text/plain')
    records = _SyntheticRecords(receipt)
    actor = context('unit-review-response').authenticated_actor
    owner = _SyntheticReviewerAuthority(plan.scope, actor) if authority else None
    source = UnitReviewCheckSource(factory, controls, records, blobs,
        bindings=_SyntheticBindings(binding, plan), reviewer_authority=owner)
    request = SimpleNamespace(scope=plan.scope, review_id=plan.review_id, state='requested', version=1, fence=1)
    return source, context('unit-review-response'), plan, request, standard, raw_ref, owner


def test_exact_completed_capture_and_trusted_owner_guard_produce_answers(env):
    source, ctx, plan, request, standard, raw_ref, owner = _source(env)
    verified = source.verify_response(ctx, plan, request, raw_ref, standard=standard)
    assert {answer.check_key for answer in verified.answers} == set(plan.check_keys)
    assert verified.reviewer_evidence.roles == tuple(plan.reviewer_requirements)
    assert not owner.held


def test_missing_current_authority_refuses_even_when_execution_capture_is_valid(env):
    source, ctx, plan, request, standard, raw_ref, _ = _source(env, authority=False)
    with pytest.raises(ApplicationError, match='UNIT_REVIEW_AUTHORITY_UNAVAILABLE'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_unknown_unit_state_refuses(env):
    source, ctx, plan, request, standard, raw_ref, _ = _source(env, mismatch=True)
    with pytest.raises(ApplicationError, match='UNIT_REVIEW_NOT_COMPLETED'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_raw_text_mismatch_refuses(env):
    source, ctx, plan, request, standard, raw_ref, _ = _source(env)
    # A caller blob cannot substitute for the completed Unit response bytes.
    wrong = source.blobs.put_verified(b'fabricated', Digest('sha256', hashlib.sha256(b'fabricated').hexdigest()), 'text/plain')
    with pytest.raises(ApplicationError, match='UNIT_REVIEW_RESPONSE_MISMATCH'):
        source.verify_response(ctx, plan, request, wrong, standard=standard)


def test_request_fence_must_match_the_resolved_fixed_unit_binding(env):
    source, ctx, plan, request, standard, raw_ref, _ = _source(env)
    source.bindings.binding = replace(source.bindings.binding, request_fence=2)
    with pytest.raises(ApplicationError, match='UNIT_REVIEW_REQUEST_BINDING_MISMATCH'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_response_schema_must_resolve_to_actual_method_snapshot_resource(env):
    source, ctx, plan, request, standard, raw_ref, _ = _source(env)
    ref = source.bindings.binding.response_schema_ref
    source.bindings.binding = replace(source.bindings.binding,
        response_schema_ref=ResourceRef('not-a-published-resource', ref.sha256, ref.kind))
    with pytest.raises(ApplicationError, match='UNIT_REVIEW_SCHEMA_UNAVAILABLE'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_current_reviewer_revocation_refuses_after_valid_captured_execution(env):
    source, ctx, plan, request, standard, raw_ref, owner = _source(env)
    owner.revoked = True
    with pytest.raises(ApplicationError, match='UNIT_REVIEWER_REVOKED'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_evidence_must_cover_every_method_declared_reviewer_role(env):
    source, ctx, plan, request, standard, raw_ref, owner = _source(env)
    owner.roles = ('unrelated-role',)
    with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_injected_method_identity_guard_rejects_same_author_reviewer_after_false_capture(env):
    source, ctx, plan, request, standard, raw_ref, _owner = _source(env)
    binding = source.bindings.binding
    source.bindings.binding = replace(binding, reviewer_identity_constraints={
        'authorUnitRef': dict(binding.unit_ref),
        'reviewerUnitRef': dict(binding.unit_ref),
    })
    # Original UnitRecords explicitly reports false quality; it is retained as
    # a source fact and does not substitute for the method's identity guard.
    assert source.records.receipt['summary']['modelQualityVerified'] is False
    with pytest.raises(ApplicationError, match='UNIT_REVIEWER_IDENTITY_CONSTRAINT_FAILED'):
        source.verify_response(ctx, plan, request, raw_ref, standard=standard)


def test_historical_review_record_rechecks_original_unit_and_holds_current_owner_guard(env):
    source, ctx, plan, request, standard, raw_ref, owner = _source(env)
    admitted = source.verify_response(ctx, plan, request, raw_ref, standard=standard)
    observations = review_observations(plan, standard, admitted.answers)
    record = ReviewRecord(
        RecordIdentity(plan.scope, plan.review_id, ctx.received_at, ctx.authenticated_actor, schema_version=2),
        plan, admitted.reviewer_evidence, observations, raw_response_ref=raw_ref)

    with source.guard_trust(ctx, (record,)) as current:
        assert owner.held
        assert current == (CurrentReviewTrust(record.ref, admitted.reviewer_evidence.verifier_id,
                                              admitted.reviewer_evidence.trust_version),)
    assert not owner.held

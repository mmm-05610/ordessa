"""Mixed source checks use the original review command and durable authorities.

All source/reviewer ports below are synthetic mechanism fixtures. Their DTOs and
identities do not prove production source provenance or reviewer qualification.
"""
from contextlib import contextmanager
import hashlib

import pytest

from test_method_control_admission import env, build_plan, context
from test_proposal_usecases import SyntheticAccess
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import VerifiedCheckResponse
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.application.usecases.reviews.mixed import (
    MixedReviewerSource, MixedCheckPart, encode_mixed_response,
)
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence


class _SyntheticLeaf:
    """Mechanism-only leaf; no claim that it authenticates a real run."""
    def __init__(self, source_id, marker):
        self.source_id, self.marker = source_id, marker
        self.guarded = False
        self.revoked = False

    def verify_checks(self, ctx, plan, request, raw_ref, *, standard, check_keys):
        assert request.plan_digest == plan.plan_digest
        assert raw_ref is not None and check_keys
        self.last_keys = tuple(check_keys)
        return VerifiedCheckResponse(tuple(CriterionAnswer(k, 'satisfied', (), 'synthetic leaf fixture')
                                           for k in check_keys),
                                     Digest('sha256', self.marker * 64))

    @contextmanager
    def guard_checks(self, ctx, admissions):
        if self.revoked:
            raise ApplicationError('REVIEW_SOURCE_REVOKED')
        assert admissions and all(a.request.plan_digest == a.plan.plan_digest
                                  and a.check_keys for a in admissions)
        self.guarded = True
        try:
            yield
        finally:
            self.guarded = False


class _SyntheticCompositeReviewer:
    """Test fixture for one composite principal; not a production authority."""
    def __init__(self, scope, actor):
        self.scope, self.actor = scope, actor
        self.guarded = False

    @contextmanager
    def guard_verification(self, ctx, plan, raw_ref, obs_digest, provenance, *, expected=None):
        assert ctx.scope == self.scope and raw_ref.digest
        if expected is not None:
            assert expected.reviewer == self.actor
        evidence = VerifiedReviewerEvidence(
            self.scope, self.actor, ('reviewer',), 'synthetic-composite-reviewer', '1', 1,
            plan.request_digest, raw_ref.digest, obs_digest, provenance)
        self.guarded = True
        try:
            yield evidence
        finally:
            self.guarded = False


def _mixed_setup(env, *, authority=True, mapping_mutation=None, source_mutation=None):
    lib, method, factory, _, controls = env
    plan, bindings = build_plan(env)
    # The actual immutable standard is obtained from the same published snapshot
    # used by the pre-existing method-review fixture.
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef
    snapshot = SQLiteSnapshotStore(lib).get(SnapshotRef(method.method_id, method.release_version,
                                                        method.schema_version, method.snapshot_digest.hex))
    standard = next(s for s in snapshot.program.standard_definitions
                    if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id)
    criteria = {c.criterion_id: c for c in standard.criteria}
    caps = {}
    for key in plan.check_keys:
        check = criteria[key.criterion_id].checks[0]
        caps.setdefault((check.capability_id, check.interface_version), 'leaf-' + check.capability_id)
    issued_caps=dict(caps)
    if mapping_mutation == 'misroute':
        first = next(iter(caps))
        caps[first] = 'not-a-configured-leaf'
    leaves = {source_id: _SyntheticLeaf(source_id, chr(97 + i % 20))
              for i, source_id in enumerate(sorted(set(issued_caps.values())))}
    if source_mutation == 'missing-leaf':
        leaves.pop(next(iter(leaves)))
    reviewer = _SyntheticCompositeReviewer(plan.scope, context('mixed-record').authenticated_actor) if authority else None
    blobs = SQLiteBlobStore(lib)
    mixed = MixedReviewerSource(factory, controls, blobs, sources=leaves,
                                source_for_capability=caps, reviewer_authority=reviewer)
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    admission=EngineeringReviewAdmission(factory,controls,bindings,mixed)
    reviews = ReviewUseCases(factory, SyntheticAccess(), admission, blobs=blobs)
    request_result = reviews.plan(plan, context('mixed-request'))
    request = request_result.result['request']

    grouped = {}
    for key in plan.check_keys:
        check = criteria[key.criterion_id].checks[0]
        source_id = issued_caps[(check.capability_id, check.interface_version)]
        grouped.setdefault(source_id, []).append(key)
    parts = []
    for source_id, keys in grouped.items():
        raw = ('leaf:' + source_id).encode()
        ref = blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/octet-stream')
        parts.append(MixedCheckPart(source_id, tuple(keys), ref))
    if source_mutation == 'duplicate-key':
        p = parts[0]
        parts[0] = MixedCheckPart(p.source_id, p.check_keys + (p.check_keys[0],), p.raw_response_ref)
    elif source_mutation == 'missing-key':
        p = parts[0]
        parts[0] = MixedCheckPart(p.source_id, p.check_keys[:-1], p.raw_response_ref)
    elif source_mutation == 'wrong-capability-source':
        p = parts[0]
        parts[0] = MixedCheckPart('wrong-source', p.check_keys, p.raw_response_ref)
    raw_response = encode_mixed_response(plan, request['version'], request['fence'], tuple(parts))
    if source_mutation == 'wrong-request-fence':
        raw_response = encode_mixed_response(plan, request['version'], request['fence'] + 1, tuple(parts))
    return lib, factory, controls, plan, standard, mixed, reviews, request, raw_response, leaves, reviewer


def test_exact_partition_and_single_composite_reviewer_are_admitted(env):
    (lib, factory, controls, plan, standard, mixed, reviews, request,
     raw, leaves, reviewer) = _mixed_setup(env)
    result = reviews.record_response(plan.review_id, raw, context('mixed-record'),
                                     expected_request_version=request['version'], fence=request['fence'])
    assert result.status == 'completed'
    assert all(not leaf.guarded for leaf in leaves.values()) and not reviewer.guarded
    with factory.begin(plan.scope, 'read') as uow:
        from ordessa_engineering.domain.reviews.models import ReviewSetKey
        snapshot = uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement))
        record = next(item.record for item in snapshot.reviews if item.control.state == 'active')
        expected = review_observations(plan, standard, tuple(
            CriterionAnswer(k, 'satisfied', (), 'synthetic leaf fixture') for k in plan.check_keys))
        assert record.observations == expected
        assert record.reviewer_evidence.reviewer == context('mixed-record').authenticated_actor
        assert len({record.reviewer_evidence.reviewer}) == 1


@pytest.mark.parametrize('mutation,code', [
    ('duplicate-key', 'REVIEW_SOURCE_INVALID'),
    ('missing-key', 'REVIEW_SOURCE_INCOMPLETE'),
    ('wrong-capability-source', 'REVIEW_SOURCE_INVALID'),
    ('wrong-request-fence', 'REVIEW_REQUEST_CHANGED'),
])
def test_partition_and_frozen_request_must_match_exactly(env, mutation, code):
    (_, _, _, plan, _, _, reviews, request, raw, _, _) = _mixed_setup(env, source_mutation=mutation)
    with pytest.raises(ApplicationError, match=code):
        reviews.record_response(plan.review_id, raw, context('bad-mixed-' + mutation),
                               expected_request_version=request['version'], fence=request['fence'])


def test_configured_capability_mapping_is_required(env):
    (_, _, _, plan, _, _, reviews, request, raw, _, _) = _mixed_setup(env, mapping_mutation='misroute')
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_BINDING_MISMATCH'):
        reviews.record_response(plan.review_id, raw, context('bad-mapping'),
                                expected_request_version=request['version'], fence=request['fence'])


def test_all_leaf_owners_are_required(env):
    (_, _, _, plan, _, _, reviews, request, raw, _, _) = _mixed_setup(env, source_mutation='missing-leaf')
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_INVALID'):
        reviews.record_response(plan.review_id, raw, context('missing-leaf'),
                                expected_request_version=request['version'], fence=request['fence'])


def test_missing_composite_authority_fails_closed(env):
    (_, _, _, plan, _, _, reviews, request, raw, _, _) = _mixed_setup(env, authority=False)
    with pytest.raises(ApplicationError, match='MIXED_REVIEWER_AUTHORITY_UNAVAILABLE'):
        reviews.record_response(plan.review_id, raw, context('no-composite-authority'),
                                expected_request_version=request['version'], fence=request['fence'])


def test_leaf_and_composite_guards_are_held_through_original_review_run_commit(env, monkeypatch):
    (_, _, _, plan, _, _, reviews, request, raw, leaves, reviewer) = _mixed_setup(env)
    original_run = reviews._run
    reached = []

    def guarded_run(*args, **kwargs):
        assert all(leaf.guarded for leaf in leaves.values())
        assert reviewer.guarded
        reached.append(True)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(reviews, '_run', guarded_run)
    result = reviews.record_response(plan.review_id, raw, context('guarded-mixed-record'),
                                     expected_request_version=request['version'], fence=request['fence'])
    assert result.status == 'completed' and reached == [True]
    assert all(not leaf.guarded for leaf in leaves.values()) and not reviewer.guarded


def test_revoked_leaf_cannot_enter_original_record_commit(env):
    (_, factory, _, plan, _, _, reviews, request, raw, leaves, _) = _mixed_setup(env)
    next(iter(leaves.values())).revoked = True
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_REVOKED'):
        reviews.record_response(plan.review_id, raw, context('revoked-mixed-source'),
                                expected_request_version=request['version'], fence=request['fence'])
    from ordessa_engineering.domain.reviews.models import ReviewSetKey
    with factory.begin(plan.scope, 'read') as uow:
        assert not uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement)).reviews
        assert uow.reviews.get_request(plan.review_id).state == 'requested'


def test_recorded_review_rechecks_current_leaf_trust(env):
    (_, factory, _, plan, _, mixed, reviews, request, raw, leaves, _) = _mixed_setup(env)
    result = reviews.record_response(plan.review_id, raw, context('record-before-revoke'),
                                     expected_request_version=request['version'], fence=request['fence'])
    assert result.status == 'completed'
    from ordessa_engineering.domain.reviews.models import ReviewSetKey
    with factory.begin(plan.scope, 'read') as uow:
        record = uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement)).reviews[0].record
    next(iter(leaves.values())).revoked = True
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_REVOKED'):
        with mixed.guard_trust(context('gate-after-revoke'), (record,)):
            pytest.fail('revoked leaf must refuse the current trust guard')


def test_nominal_projection_stays_manual_even_with_satisfied_leaf_answers(tmp_path):
    from test_method_per_claim import ROOT, published, revision, binding
    from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary

    library = EngineeringLibrary.create((tmp_path/'mixed-nominal.sqlite').resolve(),
                                        library_id='mixed-nominal-fixture', schema_version=7)
    try:
        source = ROOT / 'candidates/2.3.0'
        snapshot = published(library, source)
        material = revision()
        bindings = binding((material,))
        bridge = MethodBridge()
        requirement = next(r for r in bridge.review_requirements(snapshot, bindings, revisions=(material,))
                           if r.criterion_set_ref.criterion_set_id == 'source-review')
        plan = bridge.review_plan(snapshot, bindings, requirement, 'mixed-nominal', revisions=(material,))
        standard = next(s for s in snapshot.program.standard_definitions if s.standard_id == 'source-review')
    finally:
        library.close()
    answers = tuple(CriterionAnswer(k, 'satisfied', (), 'synthetic source says satisfied')
                    for k in plan.check_keys)
    observations = review_observations(plan, standard, answers)
    nominal_keys = {k for k in plan.check_keys if k.criterion_id == 'claim_support'}
    assert nominal_keys
    assert all(o.result == 'indeterminate' for o in observations if o.check_key in nominal_keys)

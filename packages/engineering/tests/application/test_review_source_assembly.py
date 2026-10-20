"""Public assembly of review check sources over the real SQLite owner.

The SQLite method/material source and same-authority blob store are real. The
Unit Records, binding resolvers, and reviewer guards below are explicit test
ports; this verifies composition and refusals, not production reviewer trust.
"""
from types import SimpleNamespace

import pytest

from test_invariant_checks import invariant_source
from test_proposal_usecases import SCOPE
from ordessa_engineering.application.assembly import build_review_check_admission
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.decision_checks import GenericDecisionCheckSource
from ordessa_engineering.application.orchestration.unit_review import UnitReviewCheckSource
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.invariants import DeclaredInvariantReviewCheckSource
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.application.usecases.reviews.mixed import MixedReviewerSource


class _Records:
    @staticmethod
    def acp_turn_query_digest(*args):
        raise AssertionError('assembly must not query or authenticate a Unit')

    def query_acp_turn(self, *args, **kwargs):
        raise AssertionError('assembly must not query or authenticate a Unit')


class _UnitBindings:
    def resolve_unit_review(self, *args, **kwargs):
        raise AssertionError('assembly must not invent method bindings')

    def decode_response(self, *args, **kwargs):
        raise AssertionError('assembly must not decode a review response')

    def resolve_record_request(self, *args, **kwargs):
        raise AssertionError('assembly must not infer historical request identity')


class _UnitReviewer:
    def guard_unit_reviewer(self, *args, **kwargs):
        raise AssertionError('assembly must not issue reviewer evidence')


class _CompositeReviewer:
    def __init__(self, access):
        self.access = access
        self.principal_id = access.authority.principal_id
        self.scope = SCOPE

    def guard_verification(self, *args, **kwargs):
        raise AssertionError('assembly must not issue reviewer evidence')


class _ReviewBindings:
    def resolve_bindings(self, *args, **kwargs):
        raise AssertionError('assembly must not select business review targets')


def _builder_args(source):
    access = SimpleNamespace(authority=SimpleNamespace(principal_id='selected-principal'))
    return dict(
        factory=source.factory,
        method_control=source.methods,
        blobs=source.blobs,
        review_bindings=_ReviewBindings(),
        records=_Records(),
        unit_review_bindings=_UnitBindings(),
        unit_reviewer_authority=_UnitReviewer(),
        composite_reviewer_authority=_CompositeReviewer(access),
        expected_access=access,
        expected_scope=SCOPE,
    )


def test_public_builder_composes_exact_original_sources(invariant_source):
    invariant, *_ = invariant_source
    args = _builder_args(invariant)
    admission = build_review_check_admission(**args)

    assert type(admission) is EngineeringReviewAdmission
    assert admission.factory is invariant.factory
    assert type(admission.source) is MixedReviewerSource
    assert admission.source.factory is invariant.factory
    assert type(admission.source.sources['mechanical']) is MechanicalReviewCheckSource
    assert type(admission.source.sources['invariants']) is DeclaredInvariantReviewCheckSource
    assert admission.source.sources['invariants'].factory is invariant.factory
    decision = admission.source.sources['decision']
    assert type(decision) is GenericDecisionCheckSource
    assert type(decision.source) is UnitReviewCheckSource
    assert decision.source.factory is invariant.factory
    assert decision.source.records is args['records']
    assert decision.source.bindings is args['unit_review_bindings']
    assert decision.source.authority is args['unit_reviewer_authority']
    assert admission.bindings is args['review_bindings']
    assert admission.methods is args['method_control']
    assert admission.source.blobs is args['blobs']
    assert admission.source.authority is args['composite_reviewer_authority']
    assert set(admission.source.mapping) == {
        ('ordessa.sources.integrity', '1.0.0'),
        ('ordessa.claims.coverage', '1.0.0'),
        ('ordessa.schema.validate', '1.0.0'),
        ('ordessa.submission.binding', '1.0.0'),
        ('ordessa.decision.evaluate', '1.0.0'),
    }


@pytest.mark.parametrize('port', [
    'review_bindings', 'records', 'unit_review_bindings', 'unit_reviewer_authority',
    'composite_reviewer_authority',
])
def test_public_builder_refuses_missing_required_ports(invariant_source, port):
    invariant, *_ = invariant_source
    args = _builder_args(invariant)
    args[port] = None
    with pytest.raises(ApplicationError):
        build_review_check_admission(**args)


def test_public_builder_refuses_foreign_composite_access_and_scope(invariant_source):
    invariant, *_ = invariant_source
    args = _builder_args(invariant)
    args['composite_reviewer_authority'].access = SimpleNamespace(
        authority=SimpleNamespace(principal_id='other-principal'))
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        build_review_check_admission(**args)

    args = _builder_args(invariant)
    args['expected_scope'] = SimpleNamespace(realm_id='foreign-realm', project_id=SCOPE.project_id)
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        build_review_check_admission(**args)


def test_review_runner_and_plan_factory_reach_service_and_are_required_together():
    factory = SimpleNamespace(begin=lambda *_args, **_kwargs: None)
    access = SimpleNamespace(require=lambda *_args, **_kwargs: None)

    async def review_run(_context, _plan, _request):
        raise AssertionError("the assembly test must not invoke review")

    def plan_factory(_context, _binding, *, review_id, baseline, candidate):
        raise AssertionError("the assembly test must not build a review plan")

    selected = build_engineering_service(factory, EngineeringPorts(
        access, review_run=review_run, review_plan_factory=plan_factory))
    assert selected._review_run is review_run
    assert selected._review_change_steps.review_run is review_run
    assert selected._review_change_steps.plan_factory is plan_factory
    assert selected._review_change_steps.runnable is True

    absent = build_engineering_service(factory, EngineeringPorts(access))
    assert absent._review_run is None
    assert absent._review_change_steps.runnable is False

    partial = build_engineering_service(factory, EngineeringPorts(
        access, review_run=review_run))
    assert partial._review_change_steps.runnable is False

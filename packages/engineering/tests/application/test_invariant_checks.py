"""Actual SQLite invariant checks over a frozen method and exact materials.

The method catalog and management/access fixtures are explicitly test-only.
The checks read the original SQLite snapshot, artifact, schema blob, and review
proof store; they do not establish production trust or acceptance.
"""
from dataclasses import replace
import hashlib
from types import SimpleNamespace
import runpy
from pathlib import Path

import pytest

from test_method_per_claim import ROOT, published
from test_method_control_admission import TestManagement, context
from test_proposal_usecases import SCOPE, ACTOR, CREATED_AT, SyntheticAccess
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import (
    CheckSourceAdmission, FrozenCheckRequest,
)
from ordessa_engineering.application.usecases.reviews.invariants import (
    DeclaredInvariantReviewCheckSource,
)
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.domain.artifacts.method_binding import (
    ExactMethodResourceRef, MethodRef,
)
from ordessa_engineering.domain.artifacts.models import (
    Artifact, ArtifactRevision, InlinePayload, MethodContent, MethodPayload,
)
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan,
    ReviewRequirement,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.methods.definitions.models.compiled import thaw_value


def _sha(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


@pytest.fixture
def invariant_source(tmp_path):
    library = EngineeringLibrary.create(
        (tmp_path / 'invariants.sqlite').resolve(),
        library_id='declared-invariant-checks', schema_version=14,
    )
    try:
        snapshot = published(library, ROOT / 'candidates/2.4.0')
        factory = SQLiteUoWFactory(library)
        store = SQLiteSnapshotStore(library)
        methods = MethodUseCases(factory, SyntheticAccess(), store, TestManagement())
        method_ref = MethodRef(snapshot.ref.method_id, snapshot.ref.release_version,
            snapshot.ref.schema_version, Digest('sha256', snapshot.ref.snapshot_digest))
        methods.adopt(method_ref, context('invariant-adopt'), expected_version=0)
        controls = SQLiteMethodControl(factory, store)
        blobs = SQLiteBlobStore(library)

        document = next(item for item in snapshot.program.document_definitions
                        if item.document_type == 'did')
        resource = next(item for item in snapshot.resources
                        if item.resource_id == document.schema_resource.resource_id)
        schema_ref = ExactMethodResourceRef(method_ref, resource.logical_path,
            Digest('sha256', resource.digest), resource.resource_id)
        value = {
            'document_type': 'did', 'schema_version': 1, 'title': 'Invariant fixture',
            'intent': 'Exercise exact method schema validation.',
            'claims': [{'claim_id': 'C1', 'kind': 'user_request',
                        'statement': 'Validate the exact frozen schema.',
                        'source_ids': [], 'counter_source_ids': []}],
            'goals': ['Validate exact bytes.'], 'non_goals': ['Assert no acceptance.'],
            'change_plan': [{'path': 'fixture.py', 'change': 'Add a fixture.',
                             'reason_claim_ids': ['C1']}],
            'risks': [], 'rollback': 'Remove the fixture.',
            'acceptance': [{'acceptance_id': 'A1', 'description': 'Schema is checked.',
                            'test_ids': ['test_invariant_checks']}],
            'open_questions': [],
        }
        content = MethodContent.from_value(schema_ref, value)
        schema_id = thaw_value(document.value_schema)['$id']
        revision = ArtifactRevision(SCOPE, 'invariant-artifact', 'revision-1',
            CREATED_AT, ACTOR, MethodPayload('application/json', schema_id, content),
            method_refs=(method_ref,),schema_version=2)
        with factory.begin(SCOPE) as uow:
            uow.engineering.create(Artifact(SCOPE, revision.artifact_id, 'design', CREATED_AT))
            verify_material(revision,uow.engineering.validated_budget())
            uow.engineering.append_revision(revision, expected_version=0)
            uow.commit()

        target = Target('primary', revision.ref)
        key = CheckKey(target, 'document_shape')
        standard = next(item for item in snapshot.program.standard_definitions
                        if item.standard_id == 'quality-review')
        requirement = ReviewRequirement(SCOPE, 'invariant-requirement', 1, 'quality',
            TargetSet((target,)), method_ref,
            CriterionSetRef(standard.standard_id, 1, Digest('sha256', standard.resource_ref.sha256)),
            (key,), ('reviewer',), 'quality')
        plan = ReviewPlan('invariant-review', requirement,
            (CheckPolicy(key, True, True),), AggregationPolicy(), ('reviewer',))
        request = FrozenCheckRequest(plan.plan_digest, 0, 1)
        source = DeclaredInvariantReviewCheckSource(factory, controls, blobs)
        yield source, context('invariant-check'), plan, request, standard, (key,), methods, revision
    finally:
        library.close()


def test_exact_frozen_schema_bytes_and_method_content_are_checked(invariant_source):
    source, ctx, plan, request, standard, keys, _, _ = invariant_source
    proof_ref = source.capture_proof(ctx, plan, request, standard=standard, check_keys=keys)
    response = source.verify_checks(ctx, plan, request, proof_ref,
        standard=standard, check_keys=keys)
    assert tuple(answer.status for answer in response.answers) == ('satisfied',)
    assert response.provenance_digest == proof_ref.digest
    admission = CheckSourceAdmission(plan, request, proof_ref, keys, response)
    with source.guard_checks(ctx, (admission,)):
        assert source.factory.library._method_guard_fences.values
    assert not source.factory.library._method_guard_fences.values


def test_invalid_method_content_is_refused_and_proof_request_is_exact(invariant_source):
    source, ctx, plan, request, standard, keys, _, revision = invariant_source
    invalid = replace(revision, revision_id='revision-2', payload=MethodPayload('application/json',
        revision.payload.schema_id,
        MethodContent.from_value(revision.payload.content.schema_ref, {'document_type': 'did'})))
    # The original material owner rejects malformed method content before a
    # formal revision can be written. Do not bypass it to fake a checker verdict.
    with pytest.raises(ApplicationError,match='METHOD_CONTENT_INVALID'):
        with source.factory.begin(SCOPE) as uow:
            verify_material(invalid,uow.engineering.validated_budget())
            uow.engineering.append_revision(invalid,expected_version=1)
            uow.commit()
    with source.factory.begin(SCOPE,'read') as uow:
        with pytest.raises(ApplicationError,match='NOT_FOUND'):
            uow.engineering.resolve_revision(invalid.ref)

    proof_ref=source.capture_proof(ctx,plan,request,standard=standard,check_keys=keys)
    changed_request=replace(request,request_version=1)
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_PROOF_CHANGED'):
        source.verify_checks(ctx,plan,changed_request,proof_ref,standard=standard,check_keys=keys)


def test_method_disable_invalidates_captured_invariant_proof(invariant_source):
    source, ctx, plan, request, standard, keys, methods, _ = invariant_source
    proof_ref = source.capture_proof(ctx, plan, request, standard=standard, check_keys=keys)
    response = source.verify_checks(ctx, plan, request, proof_ref,
        standard=standard, check_keys=keys)
    methods.control(plan.requirement.method_ref, context('invariant-disable'),
        expected_version=0, enabled=False, reason='fixture revocation')
    with pytest.raises(ApplicationError, match='METHOD_DISABLED'):
        with source.guard_checks(ctx, (CheckSourceAdmission(plan, request, proof_ref, keys, response),)):
            pytest.fail('disabled method must refuse the source proof')


def test_invalid_subset_and_non_method_target_do_not_pass(invariant_source):
    source, ctx, plan, request, standard, keys, _, revision = invariant_source
    with pytest.raises(ApplicationError):
        source.capture_proof(ctx, plan, request, standard=standard, check_keys=(keys[0], keys[0]))

    inline = ArtifactRevision(SCOPE, 'inline-artifact', 'inline-1', CREATED_AT, ACTOR,
        InlinePayload.from_value('application/json', 'urn:test:inline', {'not': 'MethodContent'}),
        schema_version=2)
    with source.factory.begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, inline.artifact_id, 'design', CREATED_AT))
        verify_material(inline,uow.engineering.validated_budget())
        uow.engineering.append_revision(inline, expected_version=0)
        uow.commit()
    target = Target('primary', inline.ref)
    key = CheckKey(target, 'document_shape')
    req = replace(plan.requirement, requirement_id='inline-requirement',
        expected_targets=TargetSet((target,)), required_check_keys=(key,))
    inline_plan = ReviewPlan('inline-review', req, (CheckPolicy(key, True, True),),
        AggregationPolicy(), ('reviewer',))
    inline_request = FrozenCheckRequest(inline_plan.plan_digest, 0, 1)
    ref = source.capture_proof(ctx, inline_plan, inline_request,
        standard=standard, check_keys=(key,))
    answer, = source.verify_checks(ctx, inline_plan, inline_request, ref,
        standard=standard, check_keys=(key,)).answers
    assert answer.status == 'insufficient'


def test_missing_submission_graph_is_refused_instead_of_claiming_binding(invariant_source):
    source, ctx, plan, _, _, _, _, _ = invariant_source
    # The fixture's exact frozen acceptance standard is resolved through the
    # same method-control guard used by capture; no standalone check registry.
    with source.methods.guard_method(ctx, plan.requirement.method_ref) as frozen:
        standard = next(item for item in frozen.program.standard_definitions
                        if item.standard_id == 'acceptance')
    target = Target('primary', SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
        'missing-submission', Digest('sha256', 'a' * 64)))
    key = CheckKey(target, 'submission_binding')
    requirement = replace(plan.requirement, requirement_id='missing-submission-requirement',
        purpose='acceptance', expected_targets=TargetSet((target,)),
        criterion_set_ref=CriterionSetRef('acceptance', 1,
            Digest('sha256', standard.resource_ref.sha256)), required_check_keys=(key,))
    submission_plan = ReviewPlan('missing-submission-review', requirement,
        (CheckPolicy(key, True, True),), AggregationPolicy(), ('reviewer',))
    request = FrozenCheckRequest(submission_plan.plan_digest, 0, 1)
    with pytest.raises(ApplicationError, match='NOT_FOUND'):
        source.capture_proof(ctx, submission_plan, request,
            standard=standard, check_keys=(key,))


@pytest.mark.parametrize(('extra_result', 'expected'), [(False, 'satisfied'), (True, 'violated')])
def test_submission_binding_correlates_original_graph_without_claiming_acceptance(
        invariant_source, monkeypatch, extra_result, expected):
    source, ctx, base_plan, _, _, _, _, _ = invariant_source
    fixture_path = Path(__file__).parents[1] / 'domain/test_submission_binding.py'
    fixture = runpy.run_path(str(fixture_path))['fixture']
    record, package, grant, before, resulting = fixture(extra_result=extra_result)
    target = Target('primary', record.ref)
    key = CheckKey(target, 'submission_binding')

    # Use the real frozen acceptance check declaration. The synthetic graph
    # fixture and local repository doubles exercise correlation only; they do
    # not represent production consent or native dispatch evidence.
    with source.methods.guard_method(ctx, base_plan.requirement.method_ref) as snapshot:
        standard = next(item for item in snapshot.program.standard_definitions
                        if item.standard_id == 'acceptance')

    requirement = ReviewRequirement(record.scope, 'synthetic-submission-binding', 1,
        'acceptance', TargetSet((target,)), package.payload.method_ref,
        CriterionSetRef(standard.standard_id, 1,
            Digest('sha256', standard.resource_ref.sha256)), (key,), ('reviewer',), 'acceptance')
    plan = ReviewPlan('synthetic-submission-binding-review', requirement,
        (CheckPolicy(key, True, True),), AggregationPolicy(), ('reviewer',))

    baselines = {item.ref: item for item in before + resulting}

    class Repositories:
        def resolve(self, ref):
            assert ref == record.ref
            return record

    class Implementation:
        def resolve_package(self, ref):
            assert ref == package.ref
            return package

        def resolve_repository_baseline(self, ref):
            return baselines[ref]

    class Authorization:
        def get_grant(self, ref):
            assert ref == grant.ref
            return grant

        def get_control(self, ref):
            assert ref == grant.ref
            return {'state': 'fixture-granted', 'version': 0}

    class Dispatch:
        def by_operation(self, operation_ref, scope):
            assert operation_ref == record.execution_ref.operation_ref
            assert scope == record.scope
            return {'dispatch_phase': 'fixture-only'}

    uow = SimpleNamespace(scope=record.scope, submissions=Repositories(),
        implementation=Implementation(), authorization=Authorization(), dispatch=Dispatch())
    invariant_module = __import__(
        'ordessa_engineering.application.usecases.reviews.invariants', fromlist=['invariants'])
    observed = {}

    def resolve_native_binding(original_uow, submission):
        observed['uow'] = original_uow
        observed['submission'] = submission
        return SimpleNamespace(package_ref=package.ref, approval_ref=grant.ref,
            digest=Digest('sha256', 'b' * 64))

    monkeypatch.setattr(invariant_module, 'resolve_dispatch_submission_binding',
        resolve_native_binding)
    answer, evidence = invariant_module.DeclaredInvariantReviewCheckSource._submission_answer(
        uow, snapshot, plan, standard, key)
    assert answer.status == expected
    if expected == 'satisfied':
        assert evidence['graph_error'] is None
    else:
        assert evidence['graph_error']
    assert evidence['accepted'] is False
    assert evidence['dispatch_phase'] == 'fixture-only'
    assert observed == {'uow': uow, 'submission': record}

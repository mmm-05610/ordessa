"""Phase 90 fixed delivery consumes typed, immutable method material projections."""
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.persistence.sqlite.unit_review_bindings import _fixed_material_inputs
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import ResolvedReviewMaterial
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_infrastructure.encoding import canonical_bytes


def test_fixed_delivery_keeps_original_ref_and_decodes_canonical_owner_projection():
    package = ImplementationPackageRef('realm', 'project', 'pkg', Digest('sha256', 'a' * 64))
    submission = SubmissionRef('realm', 'project', 'sub', Digest('sha256', 'b' * 64))
    source_value = {'documents': [{'type': 'review', 'ref': 'immutable'}], 'revision': 3}
    materials = (
        ResolvedReviewMaterial('package_record', package, 'package_record', canonical_bytes(source_value)),
        ResolvedReviewMaterial('submission_record', submission, 'submission_record',
                              canonical_bytes({'output_refs': ['original-ref']})),
    )

    delivered = _fixed_material_inputs(materials)

    assert delivered == {
        'package_record': {'ref': asdict(package), 'value': source_value},
        'submission_record': {'ref': asdict(submission), 'value': {'output_refs': ['original-ref']}},
    }
    delivered['package_record']['value']['documents'][0]['ref'] = 'changed-copy'
    assert materials[0].value['documents'][0]['ref'] == 'immutable'


def test_fixed_delivery_refuses_legacy_revision_pairs_and_duplicate_material_names():
    ref = ImplementationPackageRef('realm', 'project', 'pkg', Digest('sha256', 'c' * 64))
    material = ResolvedReviewMaterial('subject', ref, 'package_record', canonical_bytes({'id': 'pkg'}))

    with pytest.raises(ApplicationError, match='DECISION_INPUT_BINDING_UNAVAILABLE'):
        _fixed_material_inputs((('subject', object()),))
    with pytest.raises(ApplicationError, match='DECISION_INPUT_BINDING_UNAVAILABLE'):
        _fixed_material_inputs((material, material))
    with pytest.raises(ApplicationError, match='DECISION_INPUT_BINDING_UNAVAILABLE'):
        _fixed_material_inputs([material])


def test_sqlite_submission_material_uses_canonical_projection_and_exact_ref(tmp_path):
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.domain.changes.submission_codec import (
        decode_submission, encode_submission, submission_projection,
    )
    from ordessa_engineering.methods.definitions.models.review_bindings import ReviewMaterialSource
    from submission_wait_business_fixture import build_submission_wait_fixture

    env = build_submission_wait_fixture(tmp_path, report_phase=True)
    try:
        submission = env['submission']
        raw = encode_submission(submission)
        assert decode_submission(raw) == submission
        projection = submission_projection(submission)
        assert type(projection['execution_ref']['owner_provider_ref_bytes']) is dict
        with pytest.raises((TypeError, ValueError)):
            canonical_bytes(asdict(submission))

        reader = object.__new__(SQLiteWorkReviewBindings)
        group = SimpleNamespace(material_sources=(ReviewMaterialSource(
            name='executor_report', source='submission_record', slot='submission_ref'),))
        with env['factory'].begin(env['scope'], 'read') as uow:
            materials, pending = reader._material_values(
                uow, env['snapshot'], group, env['proposal'], submission.ref, (), (),
                {'submission_ref': asdict(submission.ref)})
        assert pending == ()
        assert len(materials) == 1
        assert materials[0].ref == submission.ref
        assert materials[0].value == projection
        assert _fixed_material_inputs(materials) == {
            'executor_report': {'ref': asdict(submission.ref), 'value': projection}}
    finally:
        env['library'].close()


def test_sqlite_acceptance_mapping_requires_the_exact_submission_slot(tmp_path):
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.domain.reviews.refs import SubmissionRef
    from ordessa_engineering.methods.definitions.models.review_bindings import ReviewMaterialSource
    from submission_wait_business_fixture import build_submission_wait_fixture

    env = build_submission_wait_fixture(tmp_path, report_phase=True)
    try:
        reader = object.__new__(SQLiteWorkReviewBindings)
        group = SimpleNamespace(material_sources=(ReviewMaterialSource(
            name='acceptance_mapping', source='acceptance_mapping', slot='submission_ref'),))
        slots = {'submission_ref': asdict(env['submission'].ref)}
        with env['factory'].begin(env['scope'], 'read') as uow:
            materials, pending = reader._material_values(
                uow, env['snapshot'], group, env['proposal'], env['submission'].ref,
                (), (), slots)
        assert pending == ()
        assert materials[0].ref == env['submission'].ref
        assert materials[0].value['requirements']

        foreign = SubmissionRef(env['scope'].realm_id, env['scope'].project_id,
                                'unrelated-submission', Digest('sha256', 'e' * 64))
        with env['factory'].begin(env['scope'], 'read') as uow:
            with pytest.raises(ApplicationError, match='METHOD_ACCEPTANCE_MAPPING_UNAVAILABLE'):
                reader._material_values(uow, env['snapshot'], group, env['proposal'],
                    env['submission'].ref, (), (), {'submission_ref': asdict(foreign)})
    finally:
        env['library'].close()


def test_sqlite_review_material_projects_the_record_from_controlled_envelope(tmp_path):
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.methods.definitions.models.review_bindings import ReviewMaterialSource
    from test_review_usecases import (
        LIBRARY_ID, SyntheticAccess, SyntheticAdmission, SyntheticControl, CountingBlobStore,
        _context, _create_source, _plan, _plan_review, _record_review, _review_usecases, _scope,
    )

    library = EngineeringLibrary.create((tmp_path / 'review-material.sqlite').resolve(),
        library_id=LIBRARY_ID + '.typed-material90', schema_version=6)
    try:
        factory = SQLiteUoWFactory(library)
        scope = _scope()
        source_ref = _create_source(factory, scope)
        plan = _plan(scope, source_ref, 'review-material-source')
        counted = CountingBlobStore(library)
        admission = SyntheticAdmission(library, counted)
        service = _review_usecases(factory, SyntheticAccess(), admission, SyntheticControl(library))
        _plan_review(service, plan, scope)
        _record_review(service, plan, scope)
        with factory.begin(scope, 'read') as uow:
            from ordessa_engineering.domain.reviews.models import ReviewSetKey
            controlled = uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement)).reviews[0]
            assert uow.reviews.get_review(controlled.record.ref) == controlled
            assert controlled.record.ref.review_id == plan.review_id
            assert controlled.control.state == 'active'
            group = SimpleNamespace(material_sources=(ReviewMaterialSource(
                name='acceptance_review_content', source='review_record', slot=None),))
            snapshot_ref = SimpleNamespace(method_id=plan.requirement.method_ref.method_id,
                release_version=plan.requirement.method_ref.release_version,
                schema_version=plan.requirement.method_ref.schema_version,
                snapshot_digest=plan.requirement.method_ref.snapshot_digest.hex)
            materials, pending = object.__new__(SQLiteWorkReviewBindings)._material_values(
                uow, SimpleNamespace(ref=snapshot_ref), group, None,
                controlled.record.ref, (), (), {})
        assert pending == ()
        assert materials[0].ref == controlled.record.ref
        from ordessa_infrastructure.encoding import decode_json
        assert materials[0].value == decode_json(canonical_bytes(controlled.record.projection()))
        assert _fixed_material_inputs(materials)['acceptance_review_content']['ref'] == asdict(
            controlled.record.ref)
    finally:
        library.close()


def test_no_review_group_in_original_method_refuses_binding_with_controlled_error(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from submission_wait_business_fixture import build_submission_wait_fixture

    env = build_submission_wait_fixture(tmp_path)
    try:
        reader = SQLiteWorkReviewBindings(env['factory'], env['controls'],
                                          scope=env['scope'], blobs=env['blobs'])
        with pytest.raises(ApplicationError, match='WORK_REVIEW_BINDING_UNAVAILABLE'):
            reader.resolve_intent_bindings(env['context'], env['method_ref'], env['proposal'].ref)
    finally:
        env['library'].close()


def test_package_design_target_is_not_frozen_package_document_derivation_proof(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.domain.reviews.targets import Target
    from submission_wait_business_fixture import build_submission_wait_fixture

    env = build_submission_wait_fixture(tmp_path)
    try:
        reader = object.__new__(SQLiteWorkReviewBindings)
        package = env['package']
        design = env['design']
        output = env['output']
        with env['factory'].begin(env['scope'], 'read') as uow:
            with pytest.raises(ApplicationError, match='METHOD_PACKAGE_DOCUMENT_BINDING_UNAVAILABLE'):
                reader._check_package_target_binding(uow, env['snapshot'], package.ref,
                    ((Target('primary', design.ref), 'test-document', design),))
            with pytest.raises(ApplicationError, match='METHOD_PACKAGE_DOCUMENT_BINDING_UNAVAILABLE'):
                reader._check_package_target_binding(uow, env['snapshot'], package.ref,
                    ((Target('primary', output.ref), 'test-document', output),))
    finally:
        env['library'].close()


def test_review_group_model_rejects_an_empty_member_set():
    from ordessa_engineering.methods.definitions.models.review_bindings import (
        ReviewGroupSpec, ReviewTargetSource,
    )

    with pytest.raises(ValueError, match='must declare members'):
        ReviewGroupSpec(contract='ordessa.method-review-group/1', anchor_node='anchor',
            group_id='group', subject_slot='subject',
            target_sources=(ReviewTargetSource('slot', 'subject', ('test-document',), 'primary'),),
            material_sources=(), members=(), gate_wait='gate',
            required_members='all_declared', empty_members='error')


def _review_group_snapshot(base, *, empty=False, mismatched_applicability=False):
    from dataclasses import replace
    from ordessa_engineering.methods.definitions.models.compiled import (
        OperationNode, OutcomeBinding, OutcomeMap, SlotBinding, SlotMap, StopNode,
        TransitionTarget, WaitNode, WorkflowSpec, freeze_value,
    )

    standard = next(item for item in base.program.standard_definitions if item.purpose == 'quality')
    if mismatched_applicability:
        standard = replace(standard, criteria=tuple(replace(c, applies_to=('unmatched-document',))
                                                    for c in standard.criteria))
    standard_ref = asdict(standard.resource_ref)
    members = [] if empty else [{'member_id': 'member', 'request_node': 'request',
        'plan_slot': 'plan', 'standard': standard_ref,
        'response_wait': 'response', 'record_node': 'record'}]
    group = {'contract': 'ordessa.method-review-group/1', 'group_id': 'source-group',
        'subject_slot': 'proposal_ref',
        'target_sources': [{'source': 'slot', 'slot': 'target_ref',
            'document_types': ['test-document'], 'role': 'primary'}],
        'material_sources': [{'name': 'proposal_record', 'source': 'proposal_record'}],
        'members': members, 'gate_wait': 'gate', 'required_members': 'all_declared',
        'empty_members': 'error'}
    binding = {'contract': 'ordessa.method-review-binding/1', 'anchor_node': 'request',
        'group_id': 'source-group', 'member_id': 'member'}
    request = OperationNode(id='request', kind='operation', operation='engineering.reviews.request',
        outcomes=OutcomeMap(entries=(OutcomeBinding(outcome='completed', target=TransitionTarget(next='response')),
                             OutcomeBinding(outcome='rejected', target=TransitionTarget(stop='failed')))),
        inputs=SlotMap(entries=(SlotBinding(name='plan', slot='plan'),)),
        config=freeze_value({'review_group': group, 'review_binding': binding,
            'purpose': 'quality', 'standards': [standard_ref],
            'unit_submission_review_strategy': {'roles': {'reviewer': 'reviewer'}}}))
    response = WaitNode(id='response', kind='wait', event='engineering.work.current_condition', next='record')
    record = OperationNode(id='record', kind='operation', operation='engineering.reviews.record',
        outcomes=OutcomeMap(entries=(OutcomeBinding(outcome='completed', target=TransitionTarget(next='gate')),
                             OutcomeBinding(outcome='rejected', target=TransitionTarget(stop='failed')))),
        inputs=SlotMap(entries=()), config=freeze_value({}))
    gate = WaitNode(id='gate', kind='wait', event='engineering.work.current_condition', next='done')
    done = StopNode(id='done', kind='stop', outcome='done')
    workflow = WorkflowSpec(schema_version=1, entry='request', steps=(request,response,record,gate,done),
        stop_outcomes=('done','failed'), wait_kinds=('engineering.work.current_condition',),
        workflow_id='method-stage-bindings90', context_slots=('proposal_ref','target_ref','plan'))
    standards = tuple(standard if item.resource_ref == standard.resource_ref else item
                      for item in base.program.standard_definitions)
    return replace(base, program=replace(base.program, workflow=workflow,
                                         standard_definitions=standards))


@pytest.mark.parametrize('case,code', [
    ('empty', 'METHOD_REVIEW_GROUP_UNAVAILABLE'),
    ('coverage', 'METHOD_REVIEW_TARGET_UNCOVERED'),
])
def test_sqlite_phase_resolution_requires_declared_members_and_full_target_coverage(
        tmp_path, case, code):
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from submission_wait_business_fixture import build_submission_wait_fixture

    env = build_submission_wait_fixture(tmp_path)
    try:
        snapshot = _review_group_snapshot(env['snapshot'], empty=case == 'empty',
                                         mismatched_applicability=case == 'coverage')
        reader = object.__new__(SQLiteWorkReviewBindings)
        selector = SimpleNamespace(phase_key='request', subject_ref=env['proposal'].ref)
        slots = {'proposal_ref': asdict(env['proposal'].ref),
                 'target_ref': asdict(env['design'].ref)}
        with env['factory'].begin(env['scope'], 'read') as uow:
            if case == 'empty':
                with pytest.raises(ApplicationError, match=code):
                    reader._phases(env['context'], snapshot, env['proposal'], selector, slots, uow)
            else:
                with pytest.raises(ApplicationError, match=code):
                    reader._phases(env['context'], snapshot, env['proposal'], selector, slots, uow)
    finally:
        env['library'].close()

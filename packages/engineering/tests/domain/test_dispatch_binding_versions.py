"""Dispatch binding schema versions: v1 rows untouched, v2 declared-Work only."""
import hashlib
from dataclasses import asdict

import pytest

from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, package_ref_projection,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_infrastructure.encoding import canonical_bytes

SCOPE = Scope('realm-1', 'project-1')
UNIT_BYTES = canonical_bytes({'environmentNamespace': 'env-1', 'unitId': 'unit-1',
                              'ownerProviderRef': {'provider': 'owner-1'},
                              'sourceRevision': 'rev-1'})


def digest(text):
    return Digest('sha256', hashlib.sha256(text).hexdigest())


def package_ref():
    return ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'fixture-package',
                                    digest(b'package'))


def other_package_ref():
    """A second package in the same scope: only its identity differs."""
    return ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'other-package',
                                    digest(b'other-package'))


def frozen_package_subject(ref=None, subject_ref=None):
    """A frozen-package subject: exactly the projection of the package it names.

    The contract is not satisfied by a well-typed reference — the subject must
    be the full canonical projection of the very package the binding acts on.
    `subject_ref` overrides that projection so a negative case can name another
    package, a partial projection, or an unrelated shape.
    """
    return {'subject_kind': 'frozen_package',
            'subject_ref': (package_ref_projection(ref if ref is not None else package_ref())
                            if subject_ref is None else subject_ref)}


PACKAGE_PROJECTION = package_ref_projection(package_ref())
OTHER_PACKAGE_PROJECTION = package_ref_projection(other_package_ref())


def change_ref():
    return ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1', 'proposal-1',
                       digest(b'proposal'))


def method_ref():
    return MethodRef('incremental-engineering', '2.7.2', 1, digest(b'method'))


def review_ref():
    return ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-1', digest(b'review'))


def generation_subject(**extra):
    """The reviewed change, its review, the pinned method and the inputs digest."""
    ref = {'review_ref': asdict(review_ref()), 'change_ref': asdict(change_ref()),
           'method_ref': asdict(method_ref()), 'inputs_digest': asdict(digest(b'inputs'))}
    ref.update(extra)
    return {'subject_kind': 'reviewed_change', 'subject_ref': ref}


def binding(**overrides):
    fields = dict(
        scope=SCOPE, run_id='run-a', step_id='step-a', attempt=1, fence=1,
        package_ref=package_ref(),
        approval_ref=ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'fixture-approval',
                                 digest(b'approval')),
        intent_digest=digest(b'intent'), control_version=0,
        action_instances=(('edit_repository', '00000000-0000-0000-0000-000000000001'),),
        unit_ref_bytes=UNIT_BYTES, execution_operation_ref='op-1',
        prompt_ref=BlobRef(digest(b'prompt'), 12, 'text/plain', 'blob-1'),
        prompt_input_digest=digest(b'prompt-input'), expected_query_digest='query-1',
        required_results=('result-1',))
    fields.update(overrides)
    return DispatchBinding(**fields)


def work_fields(dispatch_key='w1:work-1:incremental.prepare-packages:draft',
                subject_kind='reviewed_change', subject=None):
    return dict(binding_version=2,
                work={'work_id': 'work-1', 'action_id': 'incremental.prepare-packages',
                      'step_id': 'draft', 'dispatch_key': dispatch_key},
                subject=(subject if subject is not None else
                         (generation_subject() if subject_kind == 'reviewed_change' else
                          frozen_package_subject())))


def generation_fields(**overrides):
    """A generation binding: reviewed change plus host execution, no approval."""
    fields = dict(package_ref=None, approval_ref=None, intent_digest=None,
                  control_version=None,
                  action_instances=(('generate_package',
                                     '00000000-0000-0000-0000-000000000003'),))
    fields.update(work_fields())
    fields.update(overrides)
    return fields


def test_v1_projection_is_unchanged_and_round_trips():
    value = binding()
    projection = value.projection()
    for key in ('binding_version', 'work', 'subject'):
        assert key not in projection, 'a v1 row never gains new keys'
    assert decode_dispatch(encode_dispatch(value)) == value


def test_v1_refuses_declared_work_fields():
    with pytest.raises(ReferenceError):
        binding(work={'work_id': 'w', 'action_id': 'a', 'step_id': 's',
                      'dispatch_key': 'w1:w:a:s'})
    with pytest.raises(ReferenceError):
        binding(subject={'subject_kind': 'reviewed_change', 'subject_ref': {'x': 1}})


def test_v1_still_refuses_generate_package():
    with pytest.raises(ReferenceError):
        binding(action_instances=(('generate_package', '00000000-0000-0000-0000-000000000002'),))


def test_v1_still_requires_an_approval_and_intent():
    with pytest.raises(ReferenceError):
        binding(approval_ref=None)
    with pytest.raises(ReferenceError):
        binding(intent_digest=None)
    with pytest.raises(ReferenceError):
        binding(control_version=None)


def test_v2_generation_binding_acts_on_the_reviewed_change_only():
    value = binding(**generation_fields())
    projection = value.projection()
    assert projection['binding_version'] == 2 and projection['package_ref'] is None
    assert projection['work']['dispatch_key'].startswith('w1:')
    assert projection['subject']['subject_kind'] == 'reviewed_change'
    assert set(projection['subject']['subject_ref']) == {
        'review_ref', 'change_ref', 'method_ref', 'inputs_digest'}
    assert decode_dispatch(encode_dispatch(value)) == value


def test_v2_generation_refuses_a_fabricated_package_ref():
    with pytest.raises(ReferenceError):
        binding(**generation_fields(package_ref=package_ref()))


@pytest.mark.parametrize('field,value', [
    ('approval_ref', ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'some-approval',
                                 digest(b'approval'))),
    ('intent_digest', digest(b'intent')),
    ('control_version', 0),
])
def test_v2_generation_refuses_an_unrelated_approval_or_intent(field, value):
    """No unrelated approval may be stuffed into a generation binding."""
    with pytest.raises(ReferenceError):
        binding(**generation_fields(**{field: value}))


@pytest.mark.parametrize('subject', [
    {'subject_kind': 'reviewed_change', 'subject_ref': {'review_ref': asdict(review_ref())}},
    generation_subject(extra_key='x'),
    {'subject_kind': 'reviewed_change', 'subject_ref': {'review_ref': asdict(review_ref()),
                                                       'change_ref': asdict(change_ref()),
                                                       'method_ref': asdict(method_ref())}},
])
def test_v2_generation_subject_is_exactly_the_reviewed_change(subject):
    with pytest.raises(ReferenceError):
        binding(**generation_fields(subject=subject))


def test_v2_never_widens_accept_or_apply():
    for action in ('accept_artifact', 'apply_change'):
        with pytest.raises(ReferenceError):
            binding(**generation_fields(
                action_instances=((action, '00000000-0000-0000-0000-000000000004'),)))


def test_v2_frozen_package_subject_still_requires_a_typed_package_ref():
    with pytest.raises(ReferenceError):
        binding(package_ref=None, **work_fields(subject_kind='frozen_package'))
    value = binding(**work_fields(subject_kind='frozen_package'))
    assert value.projection()['subject']['subject_kind'] == 'frozen_package'
    assert value.projection()['subject']['subject_ref'] == package_ref_projection(package_ref())


@pytest.mark.parametrize('subject_ref', [
    OTHER_PACKAGE_PROJECTION,
    {key: value for key, value in PACKAGE_PROJECTION.items() if key != 'kind'},
    {**PACKAGE_PROJECTION, 'digest': asdict(digest(b'other-package'))},
    {'review_id': 'review-1'},
], ids=['another-package', 'partial-projection', 'another-digest', 'unrelated-shape'])
def test_v2_frozen_package_subject_is_decoded_verbatim_and_guarded_only_at_the_write(subject_ref):
    """The exact-projection rule is an active-write guard, not a decode rule.

    A typed ``package_ref`` is not enough for a *write* — the subject must be that
    package's own full projection. But that question is asked at the write point
    (``SQLiteWorkDispatchRepository.reserve``), never while decoding: a v2 record
    stored before the guard existed still decodes, with its subject preserved
    verbatim whatever package it names. The write-side refusal is asserted against
    the real repository in ``tests/persistence/test_work_dispatch_legacy_read.py``.
    """
    value = binding(**work_fields(subject_kind='frozen_package',
                                  subject=frozen_package_subject(subject_ref=subject_ref)))
    assert value.projection()['subject']['subject_ref'] == subject_ref
    assert decode_dispatch(encode_dispatch(value)) == value


def test_v2_frozen_package_still_requires_the_legacy_authority_fields():
    fields = dict(package_ref=None, **work_fields(subject_kind='frozen_package'))
    for name in ('approval_ref', 'intent_digest', 'control_version'):
        with pytest.raises(ReferenceError):
            binding(**{**fields, name: None})


@pytest.mark.parametrize('work', [
    {'work_id': 'work-1', 'action_id': 'a', 'step_id': 's'},
    {'work_id': 'work-1', 'action_id': 'a', 'step_id': 's', 'dispatch_key': 'run-1'},
    {'work_id': 'work-1', 'action_id': 'a', 'step_id': 's', 'dispatch_key': 'w2:w:a:s'},
])
def test_v2_requires_a_stable_namespaced_work_identity(work):
    with pytest.raises(ReferenceError):
        binding(**generation_fields(work=work))


def test_unknown_binding_version_is_refused():
    with pytest.raises(ReferenceError):
        binding(binding_version=3)

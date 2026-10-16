"""The source-change generation route has no implementation-grant helper."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.declared_prepare_packages import (
    DeclaredPreparePackagesSteps)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.provenance import (
    SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import ReviewRef

SCOPE = Scope('generation-scope', 'generation-project')
CONTEXT = SimpleNamespace(scope=SCOPE)
METHOD = MethodRef('ordessa.incremental-engineering', '2.7.2', 1,
                   Digest('sha256', 'a' * 64))
REVIEW = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-a',
                   Digest('sha256', 'b' * 64))


def source(source_id, version, byte):
    return SourceRef(source_id, 'document',
        SourceLocator('document', provider='project-files', document_id='design.md'),
        VersionCapture(version, Digest('sha256', byte * 64)),
        '2026-10-14T12:00:00.000000Z',
        ActorRef('generation-author', 'human', 'controlled-local-caller'),
        'text/markdown', 1)


def test_implementation_grant_generation_route_is_retired():
    steps = DeclaredPreparePackagesSteps(None, method_guard=object(),
                                         review_admission=object())
    assert not hasattr(steps, 'generate_package')
    assert not hasattr(steps, '_bound_grant')


def test_input_scope_must_match_the_authenticated_context():
    baseline = source('baseline-a', 'v1', 'c')
    candidate = source('candidate-a', 'v2', 'd')
    binding = SimpleNamespace(method_ref=METHOD, associations=[])
    steps = DeclaredPreparePackagesSteps(None, method_guard=object(),
                                         review_admission=object())
    inputs = {'scope': {'realm_id': 'other-realm', 'project_id': 'other-project'},
              'review': asdict(REVIEW), 'baseline': asdict(baseline),
              'candidate': asdict(candidate), 'method': asdict(METHOD)}
    with pytest.raises(ApplicationError) as exc:
        steps.check_package_admission(CONTEXT, binding, inputs=inputs)
    assert exc.value.code == 'WORK_ACTION_ADMISSION_SAME_SCOPE_FAILED'


def test_package_output_without_exact_change_provenance_is_refused():
    steps = DeclaredPreparePackagesSteps(None, method_guard=object(),
                                         review_admission=object())
    binding = SimpleNamespace(associations=[])
    with pytest.raises(ApplicationError) as exc:
        steps.validate_generated_package(CONTEXT, binding, {})
    assert exc.value.code == 'WORK_ACTION_GENERATION_OUTPUT_PROVENANCE_INVALID'

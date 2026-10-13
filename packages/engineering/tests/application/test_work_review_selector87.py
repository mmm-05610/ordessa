"""Closed Work selector and service boundary; no permission or runtime fixture."""
from dataclasses import asdict, replace

import pytest

from ordessa_engineering.application.api import (
    ApplicationError, CommandContext, EngineeringService, ReadSet,
    WorkReviewSelector, decode_work_review_selector, work_review_selector_projection,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import SubmissionRef


SCOPE = Scope('realm', 'project')
DIGEST = Digest('sha256', 'a' * 64)
INPUT = ArtifactRevisionRef('realm', 'project', 'input', 'revision', DIGEST)
METHOD = MethodRef('method', '2.6.0', 1, DIGEST)
CONTEXT = CommandContext(SCOPE, 'principal', ActorRef('actor', 'service', 'issuer'),
    'request', '2026-10-13T00:00:00.000000Z', 'trace')


def selector(subject=None):
    return WorkReviewSelector(SCOPE, 'run', METHOD, 'review', 1, INPUT,
        subject or ProposalRef('realm', 'project', 'change', 'proposal', DIGEST), DIGEST, 3)


@pytest.mark.parametrize('subject', (
    ProposalRef('realm', 'project', 'change', 'proposal', DIGEST), INPUT,
    ImplementationPackageRef('realm', 'project', 'package', DIGEST),
    SubmissionRef('realm', 'project', 'submission', DIGEST),
))
def test_original_subject_ref_round_trip(subject):
    value = selector(subject)
    projected = work_review_selector_projection(value)
    assert projected == asdict(value)
    assert decode_work_review_selector(projected) == value
    projected['run_id'] = 'other'
    assert value.run_id == 'run'


@pytest.mark.parametrize('change', (
    {'attempt': True}, {'attempt': 0}, {'expected_next_step_ordinal': -1},
    {'expected_next_step_ordinal': False}, {'ready': True},
    {'scope': {'realm_id': 'realm', 'project_id': 'foreign'}},
    {'subject_ref': {'kind': 'unknown'}},
))
def test_selector_refuses_shape_or_cross_scope_claim(change):
    value = asdict(selector())
    value.update(change)
    with pytest.raises(ApplicationError, match='WORK_REVIEW_SELECTOR_INVALID'):
        decode_work_review_selector(value)


@pytest.mark.asyncio
async def test_service_forwards_same_selector_without_operation_payload_translation():
    captured = []

    def request(parameters, context, *, read_set=None, work_selector=None):
        captured.append((parameters, context, read_set, work_selector))
        return 'original-result'

    service = object.__new__(EngineeringService)
    service._commands = {'engineering.reviews.request': request}
    params = {'plan': {'actual': 'owner-plan'}}
    reads = ReadSet(SCOPE, ())
    selected = selector()
    assert await service.execute('engineering.reviews.request', params, CONTEXT,
        read_set=reads, work_selector=selected) == 'original-result'
    assert captured == [(params, CONTEXT, reads, selected)]
    assert captured[0][0] is params and captured[0][3] is selected


@pytest.mark.asyncio
async def test_service_refuses_selector_on_wrong_operation_or_scope_before_dispatch():
    service = object.__new__(EngineeringService)
    with pytest.raises(ApplicationError, match='WORK_REVIEW_SELECTOR_UNSUPPORTED'):
        await service.execute('engineering.artifacts.create', {}, CONTEXT,
            work_selector=selector())
    other = replace(CONTEXT, scope=Scope('realm', 'foreign'))
    with pytest.raises(ApplicationError, match='WORK_REVIEW_SELECTOR_INVALID'):
        await service.execute('engineering.reviews.request', {}, other,
            work_selector=selector())


def test_selection_is_part_of_original_command_identity_only_when_present():
    operation, params, reads = 'engineering.reviews.request', {'plan': {}}, ReadSet(SCOPE, ())
    digest = EngineeringService.command_request_digest(operation, params, CONTEXT, reads)
    assert EngineeringService.command_request_digest(operation, params, CONTEXT, reads,
        work_selector=None) == digest
    selected = EngineeringService.command_request_digest(operation, params, CONTEXT, reads,
        work_selector=selector())
    assert selected != digest
    assert selected != EngineeringService.command_request_digest(operation, params, CONTEXT,
        reads, work_selector=replace(selector(), run_id='another-run'))


def test_service_and_review_owner_use_the_same_original_command_identity():
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
    operation, params, reads = 'engineering.reviews.request', {'plan': {}}, ReadSet(SCOPE, ())
    for selected in (None, selector()):
        assert EngineeringService.command_request_digest(operation, params, CONTEXT, reads,
            work_selector=selected) == ReviewUseCases._digest(operation, CONTEXT, params, reads,
            work_selector=selected)

"""Narrow expiry successor checks for the report-only disposition seam."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.application.orchestration.report_only_disposition import (
    ReportOnlyDispositionPermit)
from ordessa_engineering.application.orchestration.steps import (
    declared_implementation_dispatch as dispatch)


@dataclass(frozen=True)
class Ref:
    value: str


class Access:
    def __init__(self, context):
        self.context = context

    def current_context(self):
        return self.context

    def require(self, context, operation):
        assert context is self.context
        assert operation == 'engineering.work.invoke'


class Approval:
    def __init__(self, factory, access, blobs, selected):
        self.factory, self.access, self.blobs = factory, access, blobs
        self.selected = selected
        self.calls = 0
        self.reject = False

    @contextmanager
    def guard(self, context, *, plan_ref):
        assert context is self.access.current_context()
        if plan_ref != PLAN:
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        self.calls += 1
        if self.reject:
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_EXPIRED')
        yield self.selected


class Commands:
    def __init__(self, entries, parent):
        self.entries, self.parent = entries, parent

    def get(self, key):
        return self.entries.get(key)

    def find_operation(self, _scope, _operation_id, *, operation):
        assert operation == 'engineering.work.invoke'
        return self.parent


class Reviews:
    def __init__(self, ref, record, control):
        self.ref, self.record, self.control = ref, record, control

    def get_review(self, ref):
        assert ref == self.ref
        return SimpleNamespace(record=self.record, control=self.control)


def _entry(key, project, operation, operation_id, digest):
    return SimpleNamespace(key=key, project_id=project, operation=operation,
        operation_id=operation_id, request_digest=digest, state='pending')


def _make_permit(*, permit_type=ReportOnlyDispositionPermit):
    scope = SimpleNamespace(realm_id='realm', project_id='project')
    context = SimpleNamespace(scope=scope, principal_id='principal')
    access = Access(context)
    factory, blobs = object(), object()
    plan, approval_ref = Ref('plan'), Ref('approval')
    parent_key = CommandKey('realm', 'principal', 'original')
    parent_digest = Ref('parent-digest')
    origin_review, source_submission = Ref('origin-review'), Ref('source-submission')
    submission, review = Ref('new-submission'), Ref('new-review')
    binding = SimpleNamespace(execution_operation_ref='business-op')
    work = SimpleNamespace(work_id='work', revision=7)
    claim_key = CommandKey('realm', 'principal', 'claim')
    tail_key = CommandKey('realm', 'principal', 'tail')
    claim_digest, tail_digest = Ref('claim-digest'), Ref('tail-digest')
    parent_method = {'disposition': 'rejected', 'review_ref': asdict(origin_review),
        'submission_ref': asdict(source_submission),
        'implementation_operation_ref': 'business-op'}
    parent_result = {'method_result': parent_method}
    parent = SimpleNamespace(key=parent_key, request_digest=parent_digest, version=3,
        state='completed', project_id='project', result_bytes=b'{"method_result":{}}')
    from ordessa_infrastructure.encoding import canonical_bytes
    parent.result_bytes = canonical_bytes(parent_result)
    claim_id = 'report-content-rework-claim/id'
    tail_id = 'report-content-rework-tail/id'
    entries = {
        claim_key: _entry(claim_key, 'project',
            'engineering.report_content_rework.claim', claim_id, claim_digest),
        tail_key: _entry(tail_key, 'project',
            'engineering.report_content_rework.tail', tail_id, tail_digest)}
    approval = Approval(factory, access, blobs, approval_ref)
    permit = permit_type(approval_port=approval, factory=factory, access=access,
        blobs=blobs, context=context, plan_ref=plan, approval_ref=approval_ref,
        parent_operation_id='parent-op', parent_key=parent_key,
        parent_request_digest=parent_digest, parent_version=3,
        work_id='work', work_revision=7, binding=binding,
        origin_review_ref=origin_review, source_submission_ref=source_submission,
        submission_ref=submission, review_ref=review, claim_key=claim_key,
        claim_operation_id=claim_id, claim_digest=claim_digest, tail_key=tail_key,
        tail_operation_id=tail_id, tail_digest=tail_digest)
    uow = SimpleNamespace(commands=Commands(entries, parent),
        reviews=Reviews(origin_review, SimpleNamespace(ref=origin_review,
            complete=True, verdict='fail'), SimpleNamespace(state='active')))
    return permit, uow, context, work, binding, submission, review, approval


PLAN = Ref('plan')


def test_report_only_permit_rechecks_exact_proof_and_claim_tail():
    permit, uow, context, work, binding, submission, review, approval = _make_permit()
    permit.validate(uow, context=context, work=work, binding=binding,
        submission_ref=submission, review_ref=review,
        now=datetime.now(timezone.utc))
    assert approval.calls == 1


def test_report_only_permit_rejects_changed_plan_review_and_claim():
    permit, uow, context, work, binding, submission, review, _ = _make_permit()
    for changes in ({'plan_ref': Ref('other-plan')}, {'review_ref': Ref('other-review')},
                    {'claim_digest': Ref('other-claim')}):
        changed = permit.__class__(**{**permit.__dict__, **changes}) if hasattr(permit, '__dict__') else None
        if changed is None:
            from dataclasses import replace
            changed = replace(permit, **changes)
        with pytest.raises(ApplicationError,
                           match='REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID'):
            changed.validate(uow, context=context, work=work, binding=binding,
                submission_ref=submission, review_ref=review,
                now=datetime.now(timezone.utc))


def test_report_only_permit_rejects_expired_trusted_port():
    permit, uow, context, work, binding, submission, review, approval = _make_permit()
    approval.reject = True
    with pytest.raises(ApplicationError, match='REPORT_CONTENT_REWORK_APPROVAL_EXPIRED'):
        permit.validate(uow, context=context, work=work, binding=binding,
            submission_ref=submission, review_ref=review,
            now=datetime.now(timezone.utc))
    assert approval.calls == 1


def test_report_only_gate_rejects_untyped_or_missing_permit():
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    uow = SimpleNamespace(authorization=SimpleNamespace(get_grant=lambda _ref: object()))
    binding = SimpleNamespace(approval_ref='grant')
    for permit in (None, object()):
        with pytest.raises(ApplicationError,
                           match='REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID'):
            dispatch._report_only_disposition_grant_facts(uow, 'work', 'action', 'step', now,
                binding=binding, permit=permit, context=object(), work=object(),
                submission_ref=object(), review_ref=object())


@dataclass
class GrantIntent:
    not_before: datetime
    expires_at: datetime


def test_only_report_disposition_helper_allows_expired_grant(monkeypatch):
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    @dataclass
    class Authorization:
        work_id: str = 'work'
        action_id: str = 'action'
        step_id: str = 'step'

    @dataclass
    class Intent:
        not_before: datetime
        expires_at: datetime
        authorization: object = field(default_factory=Authorization)
        digest: object = 'intent-digest'

    control = {'state': 'granted', 'version': 0, 'revoked_at': None}
    grant = SimpleNamespace(intent=Intent(
        datetime(2026, 10, 18, 10, tzinfo=timezone.utc),
        datetime(2026, 10, 18, 11, tzinfo=timezone.utc)), ref='grant')
    binding = SimpleNamespace(approval_ref='grant', intent_digest='intent-digest',
        control_version=0, action_instances=(('edit_repository', 'x'),))
    authorization = SimpleNamespace(get_grant=lambda _ref: grant,
        get_control=lambda _ref: control,
        action_budget=lambda _ref: {'actions': [
            {'action': 'edit_repository', 'limit': 1, 'consumed': 1}]})
    uow = SimpleNamespace(authorization=authorization)
    monkeypatch.setattr(dispatch, 'WorkPackageAuthorizationIntent', Intent)
    monkeypatch.setattr(dispatch, 'resolve_work_package_authorization',
                        lambda *_args: object())
    class Permit:
        def validate(self, *args, **kwargs):
            assert kwargs['now'] == now
    from ordessa_engineering.application.orchestration.report_only_disposition import (
        ReportOnlyDispositionPermit)
    permit = object.__new__(ReportOnlyDispositionPermit)
    monkeypatch.setattr(ReportOnlyDispositionPermit, 'validate', Permit.validate)
    dispatch._report_only_disposition_grant_facts(uow, 'work', 'action', 'step', now,
        binding=binding, permit=permit, context=object(), work=object(),
        submission_ref=object(), review_ref=object())
    with pytest.raises(ApplicationError, match='APPROVAL_CONTROL_CHANGED'):
        dispatch._grant_facts(uow, 'work', 'action', 'step', now, binding=binding)
    control['state'] = 'revoked'
    with pytest.raises(ApplicationError, match='APPROVAL_CONTROL_CHANGED'):
        dispatch._report_only_disposition_grant_facts(uow, 'work', 'action', 'step', now,
            binding=binding, permit=permit, context=object(), work=object(),
            submission_ref=object(), review_ref=object())

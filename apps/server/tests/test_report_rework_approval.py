"""Trusted host consent lease: no wire authority and no Blob I/O at COMMIT."""
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_server.composition.report_rework_approval import (
    CapturedReportReworkConsent, CapturedReportReworkApproval,
)


def fixture():
    scope = object()
    context = SimpleNamespace(scope=scope, principal_id='registered')
    access = SimpleNamespace(current_context=lambda: context)
    factory = SimpleNamespace(authority_id='original')
    policy = object()
    state = {'writes': 0, 'in_tx': False, 'expired': False, 'revoked': False}

    class Blobs:
        authority_id = 'original'
        def put_verified(self, raw, digest, media_type):
            assert not state['in_tx']
            assert sha256(raw).hexdigest() == digest.hex
            state['writes'] += 1
            return BlobRef(digest, len(raw), media_type, 'fixture:' + digest.hex)

    class Attestor:
        policy_ref = policy
        @contextmanager
        def guard(self, selected_context, selected_policy):
            assert selected_context is context and selected_policy is policy
            if state['revoked']:
                raise ApplicationError('UNTRUSTED_CONSENT_ATTESTOR')
            yield

    attestor = Attestor()
    attestor.access = access
    def current():
        if state['expired']:
            raise ApplicationError('REPORT_REWORK_EXPIRED')
    budget = SimpleNamespace(plan_digest='a' * 64, not_before='2026-10-18T14:00:00.000000Z',
        expires_at='2026-10-18T15:30:00.000000Z', require_current=current)
    capture = CapturedReportReworkConsent('fixture-thread', 'fixture-message',
        '2026-10-18T13:00Z', 'keyi', 'Synthetic explicit report-only approval.', 'a' * 64)
    owner = CapturedReportReworkApproval(factory=factory, access=access, blobs=Blobs(),
        scope=scope, attestor=attestor, policy_ref=policy, capture=capture, budget=budget)
    return owner, context, state


def test_commit_guard_reuses_immutable_proof_without_blob_io():
    owner, context, state = fixture()
    plan = BlobRef(Digest('sha256', 'a' * 64), 3, 'application/json', 'fixture:plan')
    with owner.guard(context, plan_ref=plan) as first:
        assert state['writes'] == 2
        state['in_tx'] = True
        with owner.guard(context, plan_ref=plan) as final:
            assert final == first
        assert state['writes'] == 2
        state['in_tx'] = False


@pytest.mark.parametrize('change', ['expired', 'revoked', 'different_plan'])
def test_current_deadline_attestor_and_plan_are_not_wire_claims(change):
    owner, context, state = fixture()
    plan = BlobRef(Digest('sha256', 'a' * 64), 3, 'application/json', 'fixture:plan')
    with owner.guard(context, plan_ref=plan):
        pass
    if change == 'different_plan':
        plan = BlobRef(Digest('sha256', 'b' * 64), 3, 'application/json', 'fixture:other')
    else:
        state[change] = True
    with pytest.raises((ApplicationError, RuntimeError)):
        with owner.guard(context, plan_ref=plan):
            pytest.fail('Changed authority must not reach write permission')

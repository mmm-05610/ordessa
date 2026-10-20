"""Captured main-agent consent for one exact report-only plan and run window.

The same registered main-agent capability used by product chat attests this
capture. It is not independent human authentication. Wire values, old business
Grants and a supplied Blob cannot select or replace the capture/authority.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import Digest


@dataclass(frozen=True)
class CapturedReportReworkConsent:
    source_thread_id: str
    message_id: str
    captured_at: str
    answer: str
    question: str
    plan_digest: str

    def __post_init__(self):
        if (any(type(v) is not str or not v.strip() for v in (
                self.source_thread_id, self.message_id, self.captured_at,
                self.answer, self.question, self.plan_digest))
                or self.answer not in {'keyi', '行吧'}
                or len(self.plan_digest) != 64
                or any(c not in '0123456789abcdef' for c in self.plan_digest)):
            raise ApplicationError('REPORT_REWORK_CAPTURE_INVALID')


class CapturedReportReworkApproval:
    def __init__(self, *, factory, access, blobs, scope, attestor, policy_ref,
                 capture, budget):
        if (type(capture) is not CapturedReportReworkConsent
                or capture.plan_digest != budget.plan_digest
                or blobs.authority_id != factory.authority_id
                or attestor.access is not access or attestor.policy_ref != policy_ref):
            raise ApplicationError('REPORT_REWORK_CAPTURE_AUTHORITY_MISMATCH')
        self.factory, self.access, self.blobs = factory, access, blobs
        self.scope, self.attestor, self.policy_ref = scope, attestor, policy_ref
        self.capture, self.budget = capture, budget
        self._lock = RLock()
        self._proof = None
        self._proof_bytes = None

    @contextmanager
    def guard(self, context, *, plan_ref):
        with self._lock:
            self.budget.require_current()
            if (self.access.current_context() is not context
                    or context.scope != self.scope
                    or plan_ref.digest.hex != self.capture.plan_digest):
                raise ApplicationError('REPORT_REWORK_CAPTURE_BINDING_MISMATCH')
            # This original capability authenticates the selected machine
            # attestor, with exactly the same disclosed trust as product chat.
            with self.attestor.guard(context, self.policy_ref):
                raw_capture = canonical_bytes({
                    'contract': 'ordessa.report-rework-captured-consent/1',
                    'source_thread_id': self.capture.source_thread_id,
                    'message_id': self.capture.message_id,
                    'captured_at': self.capture.captured_at,
                    'answer': self.capture.answer, 'question': self.capture.question,
                    'plan_digest': self.capture.plan_digest,
                    'limitation': 'registered main-agent capture; shared bearer machine identity, not independent human authentication',
                })
                if self._proof is None:
                    capture_ref = self.blobs.put_verified(raw_capture,
                        Digest('sha256', sha256(raw_capture).hexdigest()), 'application/json')
                    from dataclasses import asdict
                    raw = canonical_bytes({
                        'contract': 'ordessa.report-content-rework-approval/1',
                        'plan_ref': asdict(plan_ref),
                        'principal_id': context.principal_id, 'decision': 'approved',
                        'not_before': self.budget.not_before,
                        'expires_at': self.budget.expires_at, 'max_uses': 1})
                    self._proof = self.blobs.put_verified(raw,
                        Digest('sha256', sha256(raw).hexdigest()), 'application/json')
                    self._proof_bytes = raw
                    self.capture_ref = capture_ref
                # Immutable proof bytes were stored/checked before entering the
                # business transaction. Reentrant final-COMMIT guards must not
                # perform BlobStore I/O inside that transaction.
                if (sha256(self._proof_bytes).hexdigest() != self._proof.digest.hex
                        or self._proof.byte_length != len(self._proof_bytes)):
                    raise ApplicationError('REPORT_REWORK_CAPTURE_PROOF_CHANGED')
                self.budget.require_current()
                yield self._proof
                # Never substitute the request's received_at for current time.
                self.budget.require_current()

"""Drive a declared report's assigned reviewer on the original Unit owner.

No alternate Unit manager, ledger, grant, acceptance or model client is created.
The original Work action owns order; this producer connects its review step to
the original reviewer assignment, fixed permission and native ACP byte cut.
"""
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
import asyncio
import hashlib
from threading import Lock, current_thread
import time

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.declared_report import resolve_declared_report_binding
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.adapters.native_records.declared_reviewer import CONTRACT
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_units.public import EffectWriteGuard


def _plain(value):
    return decode_json(safe_json(value).encode('utf-8'))


class DeclaredUnitReviewRuntime:
    def __init__(self, *, factory, access, owner, blobs, methods, bindings,
                 assignments, source, before_review=None, timeout=1800,
                 before_native_prompt=None, reviewer_assignment_guard=None,
                 native_prompt_guard=None):
        if (getattr(methods, 'factory', None) is not factory
                or getattr(bindings, 'factory', None) is not factory
                or getattr(assignments, 'factory', None) is not factory
                or getattr(assignments, 'access', None) is not access
                or source.factory is not factory or source.records is not owner.records
                or source.blobs is not blobs or source.access is not access
                or source.bindings is not bindings
                or type(timeout) not in (int, float) or not 0 < timeout <= 3600
                or before_review is not None and not callable(before_review)
                or before_native_prompt is not None and not callable(before_native_prompt)
                or reviewer_assignment_guard is not None
                   and not callable(reviewer_assignment_guard)
                or native_prompt_guard is not None
                   and not callable(native_prompt_guard)):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory, self.access, self.owner, self.blobs = factory, access, owner, blobs
        self.methods, self.bindings = methods, bindings
        self.assignments, self.source = assignments, source
        self.before_review, self.timeout = before_review, timeout
        self.before_native_prompt = before_native_prompt
        self.reviewer_assignment_guard = reviewer_assignment_guard
        self.native_prompt_guard = native_prompt_guard
        self._base, self._slot = None, None
        self._lock, self._send = Lock(), Lock()

    def wrap_dispatch_factory(self, factory):
        if (self._base is not None or not callable(factory)
                or not callable(getattr(factory, 'guard_effect_handoff', None))):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self._base = factory
        return self

    @contextmanager
    def guard_effect_handoff(self, *args, **kwargs):
        with self._base.guard_effect_handoff(*args, **kwargs) as value:
            yield value

    @contextmanager
    def _current(self, context, plan, request, assignment, unit, params,
                 report_cut_permit=None):
        self.access.require(context, 'engineering.reviews.request')
        with self.methods.guard(context, plan.requirement.method_ref) as definition:
            self.bindings.resolve_declared_submission_plan(context, plan, definition)
            # Reconstruct through its original read owners before taking the
            # final read transaction retained across the bounded byte cut.
            expected = self.source.prompt_parameters(context, plan, request, assignment,
                unit.snapshot()['sessionId'])
            if canonical_bytes(expected) != canonical_bytes(params):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            with self.factory.begin(context.scope, 'read') as uow:
                current = uow.reviews.get_request(plan.review_id)
                original_plan = uow.reviews.get_plan(plan.review_id)
                active, control = uow.reviewer_assignments.active_for_review(plan.review_id)
                submission = uow.submissions.resolve(plan.requirement.expected_targets.targets[0].ref)
                binding = resolve_declared_report_binding(uow, submission)
                if (current != request or current.state != 'requested' or original_plan != plan
                        or active != assignment or control.state != 'active'
                        or assignment.request_version != request.version
                        or assignment.fence != request.fence
                        or assignment.plan_digest != plan.plan_digest
                        or assignment.author_unit_ref_bytes != binding.unit_ref_bytes
                        or canonical_bytes(assignment.reviewer_unit_ref) != canonical_bytes(_plain(unit.identity))):
                    raise ApplicationError('REVIEW_REQUEST_CHANGED')
                if report_cut_permit is not None:
                    report_cut_permit.validate_current(
                        uow, context, plan, request, submission)
                self.owner.native_unit(unit, self.owner.authorization())
                # Retain this original-library read lock across only the
                # bounded SDK write, never across the model response wait.
                yield

    def __call__(self, unit_ref, operation, digest, params):
        with self._lock:
            slot = self._slot
        if slot is None:
            return self._base(unit_ref, operation, digest, params)
        context, plan, request, assignment, unit, native, handoff, origin, report_cut_permit = slot
        expected_operation = self.source.operation_ref(plan, assignment)
        expected_digest = self.owner.records.acp_prompt_input_digest(unit.identity, native)
        if (current_thread() is not origin or operation != expected_operation
                or digest != expected_digest
                or canonical_bytes(_plain(unit_ref)) != canonical_bytes(_plain(unit.identity))
                or canonical_bytes(_plain(params)) != canonical_bytes(native)):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')

        @asynccontextmanager
        async def acquire(identity, deadline):
            if asyncio.get_running_loop().time() >= deadline:
                raise ApplicationError('REVIEW_NATIVE_WRITE_TIMEOUT')
            key = bytes.fromhex(expected_digest.removeprefix('sha256:'))
            with self.access.consume_effect_write(handoff, context,
                    invocation_key=key, action_instances=()):
                guard = (self.native_prompt_guard(
                    context, plan, request, assignment, report_cut_permit)
                         if self.native_prompt_guard is not None else None)
                if guard is None:
                    with self._current(context, plan, request, assignment, unit, native,
                                       report_cut_permit):
                        if asyncio.get_running_loop().time() >= deadline:
                            raise ApplicationError('REVIEW_NATIVE_WRITE_TIMEOUT')
                        yield
                else:
                    with guard:
                        with self._current(context, plan, request, assignment, unit, native,
                                           report_cut_permit):
                            if asyncio.get_running_loop().time() >= deadline:
                                raise ApplicationError('REVIEW_NATIVE_WRITE_TIMEOUT')
                            yield

        return EffectWriteGuard(unit_ref, operation, digest, params, acquire)

    def run_review(self, context, plan, request):
        self.access.require(context, 'engineering.reviews.request')
        if self._base is None or not self._send.acquire(blocking=False):
            raise ApplicationError('REVIEW_NATIVE_WRITE_BUSY')
        try:
            # The report is already formally persisted at this point. A
            # product observer may deliver it before the next block starts.
            if self.before_review is not None:
                self.before_review(context, plan, request)
            with self.access.guard_unit_bootstrap(context, permission=self.owner.permission):
                unit = self.owner.manager.create(self.owner.spec, self.owner.authorization())
            if self.before_native_prompt is not None:
                self.before_native_prompt(self.owner, unit)
            assignment_key = 'assign-reviewer-' + hashlib.sha256(context.request_id.encode()).hexdigest()
            report_cut_permit = None
            with self.access.admit_work_step(context, 'engineering.reviews.assign_reviewer',
                    request_id=assignment_key) as child:
                guard = (self.reviewer_assignment_guard(
                    child, plan, request, prompt_context=context)
                         if self.reviewer_assignment_guard is not None else None)
                if guard is None:
                    answer = self.assignments.assign_reviewer(child, review_id=plan.review_id,
                        expected_plan_digest=plan.plan_digest, request_version=request.version,
                        fence=request.fence,
                        reviewer_unit_ref=decode_json(safe_json(unit.identity).encode()))
                else:
                    with guard as prepared_permit:
                        report_cut_permit = prepared_permit
                        answer = self.assignments.assign_reviewer(child, review_id=plan.review_id,
                            expected_plan_digest=plan.plan_digest, request_version=request.version,
                            fence=request.fence,
                            reviewer_unit_ref=decode_json(safe_json(unit.identity).encode()))
                if answer.status != 'completed':
                    raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
            with self.factory.begin(context.scope, 'read') as uow:
                assignment, control = uow.reviewer_assignments.active_for_review(plan.review_id)
            if control.state != 'active':
                raise ApplicationError('UNTRUSTED_REVIEWER')
            params = self.source.prompt_parameters(context, plan, request, assignment,
                unit.snapshot()['sessionId'])
            with self._current(context, plan, request, assignment, unit, params):
                pass
            raw = canonical_bytes(params)
            params_ref = self.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                'application/json')
            instance = self.owner.native_unit(unit, self.owner.authorization())
            lease = self.owner.authorize('interaction', unit, self.owner.authorization())
            operation = self.source.operation_ref(plan, assignment)
            digest = self.owner.records.acp_prompt_input_digest(unit.identity, params)
            with self.access.handoff_effect_write(context,
                    invocation_key=bytes.fromhex(digest.removeprefix('sha256:')),
                    action_instances=(), target_thread=instance.effect_write_thread,
                    expires_at=time.monotonic() + 60) as handoff:
                slot = (context, plan, request, assignment, unit, params, handoff,
                        current_thread(), report_cut_permit)
                with self._lock:
                    self._slot = slot
                try:
                    instance.prompt(unit.identity, lease, operation_ref=operation,
                        timeout=self.timeout, **params)
                finally:
                    with self._lock:
                        self._slot = None
            observation = capture_execution_observation(self.owner.records, self.blobs,
                authority_id=self.factory.authority_id, unit_ref=_plain(unit.identity),
                operation_ref=operation, expected_prompt_digest=digest,
                query_invocation=self.source.query(context, unit.identity, operation, digest),
                max_receipt_bytes=self.owner.records.acp_turn_evidence_max_bytes)
            if observation.state != 'completed':
                raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
            envelope = canonical_bytes({'contract': CONTRACT, 'review_id': plan.review_id,
                'plan_digest': asdict(plan.plan_digest), 'request_version': request.version,
                'fence': request.fence, 'assignment_ref': asdict(assignment.ref),
                'unit_ref': decode_json(safe_json(unit.identity).encode()), 'operation_ref': operation,
                'params_ref': asdict(params_ref), 'observation_ref': asdict(observation)})
            return self.blobs.put_verified(envelope,
                Digest('sha256', hashlib.sha256(envelope).hexdigest()), 'application/json')
        finally:
            self._send.release()

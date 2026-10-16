"""One authenticated current-condition read/resume over the original run CAS.

No background executor and no prototype-to-CompiledProgram reinterpretation.
Actual business side effects must still re-admit at their own commit/write cut.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from ...contracts.commands import CommandContext
from ...contracts.errors import ApplicationError
from ...contracts.run_waits import (
    BoundRunWait, ReviewReadiness, run_wait_row_digest,
)
from ...contracts.method_work import BoundWorkWait
from ..approvals.service import ApprovalUseCases
from ..support.clock import utc_now
from .references import resolve_exact
from ....domain.changes.adoption import AcceptanceReceiptRef
from ....domain.reviews.refs import SubmissionRef
from ....domain.common.mechanisms.codec import require_object
from ....domain.common.models.values import Digest, validate_id
from ....domain.common.outcomes.diagnostics import ReferenceError
from ...orchestration.method_runs import MethodRunOrchestrator


class CurrentRunWaitUseCases(ApprovalUseCases):
    def __init__(self, factory, access, bindings=None, review_admission=None):
        super().__init__(factory, access, review_admission=review_admission)
        self.bindings = bindings

    def _row(self, uow, run_id):
        try:
            row = uow.workflow.run_row(run_id)
        except Exception as exc:
            if getattr(exc, 'code', None) == 'run_not_found':
                raise ApplicationError('NOT_FOUND') from exc
            raise
        return row

    @contextmanager
    def _bound(self, context, run_id):
        if self.bindings is None:
            raise ApplicationError('WORK_WAIT_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope, 'read') as uow:
            row = self._row(uow, run_id)
            ordinal = uow.workflow.next_step_ordinal(run_id)
        with self.bindings.guard_wait(context, run_id, row) as condition:
            if (type(condition) not in (BoundRunWait, BoundWorkWait) or condition.scope != context.scope
                    or condition.run_id != run_id or condition.row_digest != run_wait_row_digest(row)
                    or condition.next_step_ordinal != ordinal):
                raise ApplicationError('RUN_WAIT_CHANGED')
            if not row['status'].startswith('WAITING_FOR_'):
                raise ApplicationError('RUN_NOT_WAITING')
            with ExitStack() as guards:
                decisions = ()
                if condition.family in {'review_gate','action_authorization'}:
                    decisions = guards.enter_context(self._gates(context, condition.intent))
                elif condition.family in {'review_plan_ready','review_response_ready'}:
                    readiness = condition.readiness
                    if type(readiness) is not ReviewReadiness:
                        raise ApplicationError('REVIEW_READINESS_UNAVAILABLE')
                    read_guard = getattr(self.factory, 'guard_read_set', None)
                    if not callable(read_guard):
                        raise ApplicationError('WORK_READ_SET_GUARD_UNAVAILABLE')
                    # guard_wait is the selected Work-source boundary. Its
                    # readiness owner guard remains held here through COMMIT;
                    # this fence additionally rechecks the typed owner reads.
                    guards.enter_context(read_guard(readiness.read_set))
                    yield condition, row, decisions
                    return
                yield condition, row, decisions

    def _check(self, uow, condition, decisions, now):
        self._check_gates(uow, decisions)
        if condition.family in {'review_plan_ready','review_response_ready'}:
            readiness = condition.readiness
            if type(readiness) is not ReviewReadiness:
                raise ApplicationError('REVIEW_READINESS_UNAVAILABLE')
            uow.engineering.check_read_set(readiness.read_set)
            input_revision = uow.engineering.resolve_revision(readiness.input_ref)
            if input_revision.ref != readiness.input_ref:
                raise ApplicationError('REVIEW_READINESS_CHANGED')
            if resolve_exact(uow, readiness.subject_ref) is None:
                raise ApplicationError('REVIEW_READINESS_CHANGED')
            for target in readiness.plan.requirement.expected_targets.targets:
                if resolve_exact(uow, target.ref) is None:
                    raise ApplicationError('REVIEW_READINESS_CHANGED')
            if condition.family == 'review_response_ready':
                expectation = readiness.read_set.review_requests[0]
                try:
                    stored_plan = uow.reviews.get_plan(readiness.plan.review_id)
                    request = uow.reviews.get_request(readiness.plan.review_id)
                except Exception as exc:
                    if getattr(exc, 'code', None) == 'NOT_FOUND':
                        raise ApplicationError('REVIEW_REQUEST_CHANGED') from exc
                    raise
                if (stored_plan != readiness.plan or request.state != 'requested'
                        or request.version != expectation.expected_request_version
                        or request.fence != expectation.expected_fence):
                    raise ApplicationError('REVIEW_REQUEST_CHANGED')
        if condition.family in {'object_exists','result_exists'}:
            for ref in condition.refs:
                if type(ref) is AcceptanceReceiptRef:
                    if (ref.realm_id,ref.project_id) != (uow.scope.realm_id,uow.scope.project_id):
                        raise ApplicationError('SCOPE_MISMATCH')
                    if uow.acceptance.resolve(ref.adoption_id).ref != ref:
                        raise ApplicationError('REFERENCE_MISMATCH')
                elif condition.family == 'result_exists' and type(ref) is not SubmissionRef:
                    # hasResult/SDK completed/Blob alone cannot prove a normal result.
                    raise ApplicationError('WAIT_RESULT_OWNER_UNAVAILABLE')
                else:
                    resolve_exact(uow, ref)
        if condition.family == 'action_authorization':
            grant = uow.authorization.get_grant(condition.approval_ref)
            control = uow.authorization.get_control(condition.approval_ref)
            if (grant.intent != condition.intent or control['version'] != condition.expected_control_version
                    or control['state'] != 'granted'):
                raise ApplicationError('AUTHORIZATION_REVOKED')
            if not grant.intent.not_before <= now < grant.intent.expires_at:
                raise ApplicationError('AUTHORIZATION_EXPIRED')
            self._resolve(uow, grant.intent)
            budget = uow.authorization.action_budget(grant.ref)
            slots = budget.get('actions', [budget])
            slot = next((s for s in slots if s['action'] == condition.action), None)
            if slot is None or slot['consumed'] >= slot['limit']:
                raise ApplicationError('ACTION_BUDGET_EXHAUSTED')

    def read(self, parameters, context, *, query_operation="engineering.runs.get_wait"):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        if query_operation not in ('engineering.runs.get_wait', 'engineering.work.current_condition'):
            raise ApplicationError('QUERY_UNAVAILABLE')
        self.access.require(context, query_operation)
        try:
            require_object(parameters, {'run_id'}, 'INVALID_INPUT')
            validate_id(parameters['run_id'])
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        with self._bound(context, parameters['run_id']) as (condition,row,decisions):
            with self.factory.begin(context.scope, 'read') as uow:
                if run_wait_row_digest(self._row(uow,condition.run_id)) != condition.row_digest:
                    raise ApplicationError('RUN_WAIT_CHANGED')
                self._check(uow, condition, decisions, utc_now())
            return {'run_id':condition.run_id, 'status':row['status'], 'cursor':row['cursor'],
                'wait_reason':row['wait_reason'], 'family':condition.family, 'ready':True,
                'row_digest':asdict(condition.row_digest), 'condition_digest':asdict(condition.digest),
                'next_step_ordinal':condition.next_step_ordinal}

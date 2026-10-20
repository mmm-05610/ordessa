"""Narrow typed adapters over the three original Engineering owners.

Composition dependencies (factory, context, native execution records and blob
store) are deliberately not accepted from the operation payload.
"""
from dataclasses import asdict, dataclass
import math
from typing import Any

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ..contracts.commands import CommandContext, CommandResult
from ..contracts.errors import ApplicationError
from ..contracts.failure_diagnostic import FAILURE_MEDIA_TYPE, FailureDiagnostic
from ..orchestration.steps.implementation_dispatch import ImplementationDispatch
from .packages.implementation import ImplementationUseCases
from .changes.submissions import SubmissionUseCases
from ...domain.packages.codec import decode_package, decode_package_ref
from ...domain.changes.submission_codec import decode_submission
from ...domain.changes.dispatch_codec import decode_dispatch
from ...domain.common.mechanisms.codec import decode_blob_ref


MAX_RECORD_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class OwnerOperationResult:
    operation: str
    outcome: str
    value: Any = None
    engineering_completed: bool = False
    accepted: bool = False
    dispatch_phase: str | None = None
    reason: str | None = None


def _closed_record(value, decoder):
    try:
        raw = canonical_bytes(value)
        if len(raw) > MAX_RECORD_BYTES:
            raise ApplicationError('OWNER_OPERATION_INPUT_TOO_LARGE')
        return decoder(raw)
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError('OWNER_OPERATION_RECORD_INVALID') from exc


def _result_json(result, factory):
    if type(result) is not CommandResult or result.authority_id != factory.authority_id:
        raise ApplicationError('OWNER_OPERATION_RESULT_AUTHORITY_MISMATCH')
    if result.result_bytes is None:
        return None
    return decode_json(result.result_bytes)


def _journal_matches(factory, context, operation, result):
    with factory.begin(context.scope, 'read') as uow:
        entry = uow.commands.get(context.key)
        return (entry is not None and entry.operation == operation
                and entry.operation_id == result.operation_id
                and entry.project_id == context.scope.project_id
                and entry.state == result.status
                and entry.result_bytes == result.result_bytes)


class EngineeringOwnerOperations:
    """Call package freeze, native dispatch and submission recording owners."""
    def __init__(self, factory, *, packages: ImplementationUseCases,
                 dispatch: ImplementationDispatch, submissions: SubmissionUseCases,
                 records, blobs, access=None, unit_ref_resolver=None, implementation_timeout=60,
                 agent_ref_resolver=None):
        if any(getattr(owner, 'factory', None) is not factory
               for owner in (packages, dispatch, submissions)):
            raise ApplicationError('OWNER_OPERATION_FACTORY_MISMATCH')
        execution = getattr(dispatch, 'execution', None)
        if (getattr(blobs, 'authority_id', None) != factory.authority_id
                or getattr(dispatch, 'blobs', None) is not blobs
                or records is None or getattr(execution, 'records', None) is not records
                or not callable(getattr(execution, 'query_factory', None))):
            raise ApplicationError('OWNER_OPERATION_SOURCE_AUTHORITY_UNAVAILABLE')
        self.factory, self.packages, self.dispatch = factory, packages, dispatch
        self.submissions, self.records, self.blobs = submissions, records, blobs
        if access is not None and any(getattr(owner,'access',None) is not access
                                     for owner in (packages,dispatch,submissions)):
            raise ApplicationError('OWNER_OPERATION_ACCESS_MISMATCH')
        self.access=access
        if unit_ref_resolver is not None and not callable(unit_ref_resolver):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        self.unit_ref_resolver = unit_ref_resolver
        if agent_ref_resolver is not None and not callable(agent_ref_resolver):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        if agent_ref_resolver is not None and unit_ref_resolver is not None:
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_AMBIGUOUS')
        self.agent_ref_resolver = agent_ref_resolver
        if (type(implementation_timeout) not in (int, float)
                or not math.isfinite(implementation_timeout) or not 0 < implementation_timeout <= 3600):
            raise ApplicationError('DISPATCH_TIMEOUT_INVALID')
        self.implementation_timeout = implementation_timeout

    @property
    def declared_implementation_ready(self):
        selection = self.dispatch.selection
        return (getattr(selection, 'work_scope_ready', False) is True
                and callable(getattr(selection, 'describe_work_profile', None))
                and (callable(self.agent_ref_resolver) or callable(self.unit_ref_resolver))
                and callable(getattr(selection, 'guard_work_selection', None))
                and callable(getattr(selection, 'guard_work_scope', None))
                and getattr(self.dispatch.method_guard, 'factory', None) is self.factory
                and getattr(self.dispatch.source_materials, 'factory', None) is self.factory)

    def assemble_declared_work_dispatch(self, work, action_id, step_id, inputs, context):
        """Derive one first-attempt envelope from the enclosing declared Work.

        The selected-unit resolver is trusted composition over an *existing*
        original Unit/Profile owner. It creates no Unit or execution permission.
        An existing attempt supplies its original Unit/actions without invoking
        that resolver or selecting a new Grant.
        """
        if self.agent_ref_resolver is not None:
            return self.assemble_agent_work_dispatch(work, action_id, step_id, inputs, context)
        from ..contracts.dispatch_identity import work_dispatch_key
        from ..contracts.work_context import WorkBinding
        from ..orchestration.steps.declared_implementation_dispatch import _existing, _grant_facts
        if type(work) is not WorkBinding or work.scope != context.scope or type(inputs) is not dict:
            raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
        package = decode_package_ref(inputs.get('package'))
        if tuple(a.ref for a in work.associations if a.kind == 'package') != (package,):
            raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
        key = work_dispatch_key(work.work_id, action_id, step_id)
        with self.factory.begin(context.scope, 'read') as uow:
            old = _existing(uow, key, step_id, 1)
            if old is not None:
                binding = decode_dispatch(old['binding_bytes'])
                if binding.package_ref != package:
                    raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                unit = decode_json(binding.unit_ref_bytes)
                actions = tuple(action for action, _ in binding.action_instances)
                authorization = None
            else:
                grant, facts, _ = _grant_facts(uow, work.work_id, action_id, step_id, context.received_at)
                if facts.work != work or facts.package.ref != package:
                    raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
                authorization = grant.intent.authorization
                actions = authorization.actions
        if old is None:
            if self.unit_ref_resolver is None:
                raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_UNAVAILABLE')
            unit = self.unit_ref_resolver(context, work, inputs.get('profile'), authorization)
        return {'dispatch': {'work_id': work.work_id, 'action_id': action_id,
            'step_id': step_id, 'attempt': 1, 'unit_ref': unit, 'params': {},
            'actions': list(actions), 'timeout': self.implementation_timeout}}

    def execute(self, operation: str, parameters, context: CommandContext) -> OwnerOperationResult:
        if type(context) is not CommandContext or type(parameters) is not dict:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        try:
            raw = canonical_bytes(parameters)
        except Exception as exc:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID') from exc
        if len(raw) > MAX_RECORD_BYTES:
            raise ApplicationError('OWNER_OPERATION_INPUT_TOO_LARGE')
        if operation == 'engineering.packages.freeze':
            return self.freeze_package(parameters, context)
        if operation == 'engineering.executions.dispatch':
            if self.agent_ref_resolver is not None:
                return self.dispatch_agent_execution(parameters, context)
            return self.dispatch_execution(parameters, context)
        if operation == 'engineering.submissions.record_report':
            return self.record_report(parameters, context)
        raise ApplicationError('OWNER_OPERATION_UNKNOWN')

    def record_report(self, parameters, context):
        if set(parameters) != {'record'}:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        record = _closed_record(parameters['record'], decode_submission)
        operation = 'engineering.submissions.record_report'
        result = self.submissions.record_report(record, context, records=self.records,
            blobs=self.blobs, query_factory=self.dispatch.execution.query_factory)
        value = _result_json(result, self.factory)
        if (result.status != 'completed' or type(value) is not dict
                or not _journal_matches(self.factory, context, operation, result)):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        if (set(value) != {'submission_ref', 'workflow_state', 'review_status', 'accepted'}
                or value['workflow_state'] != 'submitted' or value['review_status'] != 'pending_review'
                or value['accepted'] is not False):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_SHAPE_MISMATCH')
        from ...domain.reviews.target_codec import decode_subject_ref
        ref = decode_subject_ref(value['submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            stored = uow.submissions.resolve(ref)
        if stored != record or stored.ref != ref:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RECORD_MISMATCH')
        return OwnerOperationResult(operation, 'submitted', value, accepted=False)

    def freeze_package(self, parameters, context):
        if set(parameters) != {'record'}:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        record = _closed_record(parameters['record'], decode_package)
        operation = 'engineering.packages.freeze'
        result = self.packages.freeze_package(record, context)
        value = _result_json(result, self.factory)
        if result.status != 'completed' or type(value) is not dict:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        if not _journal_matches(self.factory, context, operation, result):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_JOURNAL_MISMATCH')
        if (set(value) != {'package_ref', 'dispatchable'}
                or value['dispatchable'] is not False):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_SHAPE_MISMATCH')
        ref = decode_package_ref(value['package_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            stored = uow.implementation.resolve_package(ref)
        if stored != record:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RECORD_MISMATCH')
        return OwnerOperationResult(operation, 'completed', {'package_ref': ref, 'record': stored})

    # The declared-Work dispatch form: the Work's own identity (its dispatch key
    # is derived from `work_id`/`action_id`/`step_id`) on schema-17 work_step_log.
    # `run_id` is never part of it — the historical run form is not an active
    # writer — and this exact set is what the owner capability advertises.
    _WORK_DISPATCH_FORM = frozenset({'work_id', 'action_id', 'step_id', 'attempt',
                                     'unit_ref', 'params', 'actions', 'timeout'})

    _CONTINUATION_DRAFT_FIELDS = frozenset({'origin', 'reservation_origin',
        'causal_operation_id', 'failure_evidence_ref', 'acp_observation_ref',
        'acp_revision', 'stop_proof_ref', 'release_proof_ref', 'semantic_prompt_digest'})

    def dispatch_continuation(self, request, draft, context):
        """Run one continuation attempt from an in-process draft.

        The request is the same closed declared-work form minus the impossible
        successor digest; the draft carries domain values and is never persisted
        or accepted from a wire caller. The declared-work wrapper has no
        continuation parameter, so its guards are re-asserted here and the single
        dispatch implementation stays the only writer.
        """
        if (type(request) is not dict or type(draft) is not dict
                or set(draft) != self._CONTINUATION_DRAFT_FIELDS
                or set(request) != self._WORK_DISPATCH_FORM
                or type(request['actions']) is not list
                or type(request['attempt']) is not int or not 2 <= request['attempt'] <= 4096):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        from ..orchestration.steps.declared_implementation_dispatch import dispatch as declared_dispatch
        from ..contracts.dispatch_identity import work_dispatch_key
        from ...domain.changes.dispatch import DispatchOriginRef
        if (type(draft['origin']) is not DispatchOriginRef
                or type(draft['reservation_origin']) is not DispatchOriginRef
                or type(draft['acp_revision']) is not int or draft['acp_revision'] < 1):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        self.dispatch._access(context, 'engineering.executions.dispatch')
        if set(request['actions']) & {'generate_package', 'apply_change', 'accept_artifact'}:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        identity = work_dispatch_key(request['work_id'], request['action_id'], request['step_id'])
        if identity != draft['origin'].dispatch_key:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        returned = declared_dispatch(self.dispatch, identity, request['work_id'],
            request['action_id'], request['step_id'], request['attempt'], request['unit_ref'],
            request['params'], tuple(request['actions']), context,
            timeout=request['timeout'], continuation=draft)
        return self._dispatch_result(request, context, returned)

    def reserve_continuation_unit_bootstrap(self, context, candidate, profile_ref, owner_identity):
        """Reserve the one Unit-bootstrap row for this causal continuation request.

        Identity reuses the existing helpers: the caller's request id is already
        the causal operation id, so the key is the internal bootstrap key and the
        operation id is that key's request id. The generation bootstrap id (which
        hard-codes action/step/attempt 1) is never used here.
        """
        from ..contracts.dispatch_identity import (
            UNIT_BOOTSTRAP_OPERATION, unit_bootstrap_digest, unit_bootstrap_request_key)
        from ..contracts.commands import Reservation
        from .changes.dispatch_continuation import (
            CONTINUATION_OPERATION, ContinuationCandidate, continuation_operation_id)
        self.dispatch._access(context, 'engineering.executions.dispatch')
        if type(candidate) is not ContinuationCandidate or type(profile_ref) is not dict:
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        causal_id = continuation_operation_id(context.scope, candidate.origin)
        if context.request_id != causal_id:
            raise ApplicationError('CONTINUATION_OPERATION_MISMATCH')
        key = unit_bootstrap_request_key(context)
        operation_id = key.request_id
        digest = unit_bootstrap_digest(candidate.work, profile_ref, owner_identity)
        with self.factory.begin(context.scope) as uow:
            # The continuation claim of this same caller must still be pending.
            claim = uow.commands.find_operation(context.scope, causal_id,
                                               operation=CONTINUATION_OPERATION)
            if (claim is None or claim.state != 'pending'
                    or claim.operation_id != causal_id
                    or claim.key.principal_id != context.principal_id):
                raise ApplicationError('CONTINUATION_CLAIM_UNAVAILABLE')
            existing = uow.commands.find_operation(context.scope, operation_id,
                                                   operation=UNIT_BOOTSTRAP_OPERATION)
            if existing is not None:
                if (existing.operation_id != operation_id
                        or existing.project_id != context.scope.project_id
                        or existing.key != key or existing.request_digest != digest
                        or existing.state != 'pending'):
                    raise ApplicationError('CONTINUATION_BOOTSTRAP_UNAVAILABLE')
                return Reservation(existing, False)
            try:
                reserved = uow.commands.reserve(key, project_id=context.scope.project_id,
                    operation=UNIT_BOOTSTRAP_OPERATION, operation_id=operation_id,
                    request_digest=digest)
            except ApplicationError as exc:
                if exc.code in {'OPERATION_ID_CONFLICT', 'OPERATION_IDENTITY_CONFLICT'}:
                    raise ApplicationError('CONTINUATION_BOOTSTRAP_UNAVAILABLE') from None
                raise
            if not reserved.created:
                raise ApplicationError('CONTINUATION_BOOTSTRAP_UNAVAILABLE')
            uow.commit()
            return reserved

    def complete_continuation_unit_bootstrap(self, context, reservation, unit_ref):
        """Record the real Unit ref on the exact still-pending bootstrap row.

        Only the bootstrap row is completed; the continuation claim stays pending
        for the dispatch step that follows.
        """
        from ..contracts.dispatch_identity import UNIT_BOOTSTRAP_OPERATION, unit_bootstrap_request_key
        from ..contracts.commands import Reservation
        _UNIT_KEYS = {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
        self.dispatch._access(context, 'engineering.executions.dispatch')
        if (type(reservation) is not Reservation or not reservation.created
                or type(unit_ref) is not dict or set(unit_ref) != _UNIT_KEYS):
            raise ApplicationError('CONTINUATION_BOOTSTRAP_BINDING_MISMATCH')
        entry = reservation.entry
        key = unit_bootstrap_request_key(context)
        if (entry.key != key or entry.operation != UNIT_BOOTSTRAP_OPERATION
                or type(entry.operation_id) is not str or entry.state != 'pending'):
            raise ApplicationError('CONTINUATION_BOOTSTRAP_BINDING_MISMATCH')
        result_bytes = canonical_bytes({'unit_ref': unit_ref})
        with self.factory.begin(context.scope) as uow:
            current = uow.commands.get(key)
            if (current is None or current != entry
                    or current.operation != UNIT_BOOTSTRAP_OPERATION
                    or current.operation_id != entry.operation_id
                    or current.request_digest != entry.request_digest
                    or current.version != entry.version or current.state != 'pending'):
                raise ApplicationError('CONTINUATION_BOOTSTRAP_BINDING_MISMATCH')
            final = uow.commands.complete(key, expected_version=entry.version,
                result_bytes=result_bytes, state='completed')
            if final.operation_id != entry.operation_id or final.state != 'completed':
                raise ApplicationError('CONTINUATION_BOOTSTRAP_BINDING_MISMATCH')
            uow.commit()
        return None

    def verify_continuation_grant(self, binding, context):
        """Read-only re-check of the original Grant before a new Unit exists.

        Reuses the dispatch step's own `_grant_facts` (current control, deadline,
        scope, package/method facts) rather than a second simplified grant check.
        """
        from ..orchestration.steps.declared_implementation_dispatch import _grant_facts
        self.dispatch._access(context, 'engineering.executions.dispatch')
        if binding is None or getattr(binding, 'work', None) is None:
            raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
        with self.factory.begin(context.scope, 'read') as uow:
            grant, facts, control = _grant_facts(uow, binding.work['work_id'],
                binding.work['action_id'], binding.step_id, context.received_at, binding=binding)
        if facts.work is None or facts.package is None:
            raise ApplicationError('CONTINUATION_GRANT_UNAVAILABLE')
        return {'approval_ref': grant.ref, 'intent_digest': grant.intent.digest,
                'control_version': control.get('version')}

    def dispatch_execution(self, parameters, context):
        if set(parameters) != {'dispatch'} or type(parameters['dispatch']) is not dict:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        request = parameters['dispatch']
        # The active write entry takes a declared Work identity only. The
        # historical run form is never an active writer here; old dispatch rows
        # stay readable/reconcilable through their own records.
        if 'run_id' in request or 'work_id' not in request:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        continuation = None
        if 'continuation' in request:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        required = self._WORK_DISPATCH_FORM
        if set(request) != required or type(request['actions']) is not list:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        if (type(request['attempt']) is not int or not 1 <= request['attempt'] <= 4096
                or type(request['timeout']) not in (int, float) or not 0 < request['timeout'] <= 3600
                or not request['actions'] or any(type(a) is not str or not a for a in request['actions'])
                or len(set(request['actions'])) != len(request['actions'])
                or type(request['unit_ref']) is not dict or type(request['params']) is not dict):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        operation = 'engineering.executions.dispatch'
        from ..contracts.dispatch_identity import work_dispatch_key
        identity = work_dispatch_key(request['work_id'], request['action_id'],
                                    request['step_id'])
        # The original dispatch owner assembles method/package bytes itself.
        # Empty params requests that assembly; supplied params must match it
        # exactly, including the fixed original Unit session.
        returned = self.dispatch.dispatch_declared_work(identity,
            request['work_id'], request['action_id'], request['step_id'], request['attempt'],
            request['unit_ref'], request['params'], tuple(request['actions']), context,
            timeout=request['timeout'])
        return self._dispatch_result(request, context, returned)

    def _dispatch_result(self, request, context, returned):
        """Read the same durable binding/result for ordinary and continued dispatch."""
        from ..contracts.dispatch_identity import work_dispatch_key
        operation = 'engineering.executions.dispatch'
        if type(returned) is not dict:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        identity = work_dispatch_key(request['work_id'], request['action_id'], request['step_id'])
        # The declared Work's own relation (schema 17) is the only row an active
        # dispatch writes: a declared Work has no `runs` row, so the run-scoped
        # `step_log` is never this step's record. The stored row must be this
        # Work identity, this step and this attempt, and its binding must be the
        # frozen declared-Work binding the owner accepted.
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.get(identity, request['step_id'], request['attempt'],
                                        context.scope)
            binding = decode_dispatch(row['binding_bytes'])
        if (row['run_id'] != identity or row['step_id'] != request['step_id']
                or row['attempt'] != request['attempt']
                or binding.binding_version != 2 or binding.work is None
                or binding.work.get('dispatch_key') != identity
                or binding.work.get('work_id') != request['work_id']
                or binding.work.get('action_id') != request['action_id']
                or binding.work.get('step_id') != request['step_id']
                or binding.attempt != request['attempt']
                or binding.unit_ref_bytes != canonical_bytes(request['unit_ref'])
                or tuple(action for action, _ in binding.action_instances) != tuple(request['actions'])
                or binding.scope != context.scope):
            return OwnerOperationResult(operation, 'unknown', engineering_completed=False,
                                        reason='OWNER_BINDING_MISMATCH')
        phase = row['dispatch_phase']
        outcome = phase if phase in {'completed', 'failed'} else 'unknown'
        result_ref = None
        failure_diagnostic = None
        if row['result_blob_json'] is not None:
            result_ref = decode_blob_ref(decode_json(row['result_blob_json']))
            # The original UoW verifies the observed bytes under the same
            # authority before this adapter reports a native record outcome.
            with self.factory.begin(context.scope, 'read') as uow:
                observed = uow.implementation.read_blob(result_ref)
            if result_ref.media_type == FAILURE_MEDIA_TYPE:
                failure_diagnostic = FailureDiagnostic(observed)
        # Compare the owner's immediate view with its durable row. A caller
        # cannot substitute an identity, an attempt, a frozen input or an outcome
        # after the transaction has committed. The view carries the declared Work
        # identity, never a run id; an absent completion flag is not a claim, a
        # present true one is refused.
        if (type(returned) is not dict or returned.get('phase') != phase
                or returned.get('identity') != identity
                or returned.get('step_id') != request['step_id']
                or returned.get('attempt') != request['attempt']
                or returned.get('binding_digest') != {'algorithm': binding.digest.algorithm,
                                                       'hex': binding.digest.hex}
                or returned.get('params_assembly') != 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT'
                or returned.get('engineering_completed', False) is not False
                or canonical_bytes(returned.get('result_blob_ref')) !=
                   (b'null' if result_ref is None else canonical_bytes(decode_json(row['result_blob_json'])))):
            outcome = 'unknown'
        native = {'binding': binding, 'observation_ref': result_ref,
                  'params_assembly': returned.get('params_assembly')}
        if failure_diagnostic is not None:
            native['failure_diagnostic'] = failure_diagnostic
        return OwnerOperationResult(operation, outcome, native,
            engineering_completed=False, accepted=False, dispatch_phase=phase,
            reason=None if outcome == phase else 'OWNER_RESULT_MISMATCH')

    @property
    def dispatch_descriptor(self):
        from ..orchestration.owner_capabilities import agent_dispatch_capability, owner_capabilities
        if self.agent_ref_resolver is not None:
            return agent_dispatch_capability()
        return next(d for d in owner_capabilities() if d.capability_id == 'engineering.executions.dispatch')

    def assemble_agent_work_dispatch(self, work, action_id, step_id, inputs, context):
        """Explicit trusted original Agent/session selection for the exact Work."""
        from ..contracts.dispatch_identity import work_dispatch_key
        from ..contracts.work_context import WorkBinding
        from ..orchestration.steps.declared_implementation_dispatch import _existing, _grant_facts
        from ...domain.changes.agent_dispatch import AgentWorkDispatchBinding
        from ...domain.changes.agent_dispatch_codec import decode_agent_dispatch
        from ...domain.common.models.execution_refs import agent_instance_ref_bytes
        if type(work) is not WorkBinding or work.scope != context.scope or type(inputs) is not dict:
            raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
        package = decode_package_ref(inputs.get('package'))
        if tuple(a.ref for a in work.associations if a.kind == 'package') != (package,):
            raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
        key = work_dispatch_key(work.work_id, action_id, step_id)
        with self.factory.begin(context.scope, 'read') as uow:
            old = _existing(uow, key, step_id, 1)
            if old is not None:
                binding = decode_agent_dispatch(old['binding_bytes'])
                if type(binding) is not AgentWorkDispatchBinding or binding.package_ref != package:
                    raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                agent = decode_json(binding.agent_ref_bytes)
                session = decode_json(uow.implementation.read_blob(binding.prompt_ref)).get('sessionId')
                actions = tuple(action for action, _ in binding.action_instances)
                authorization = None
            else:
                grant, facts, _ = _grant_facts(uow, work.work_id, action_id, step_id, context.received_at)
                if facts.work != work or facts.package.ref != package:
                    raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
                authorization = grant.intent.authorization
                actions = authorization.actions
        if old is None:
            if self.agent_ref_resolver is None:
                raise ApplicationError('WORK_ACTION_IMPLEMENTATION_AGENT_UNAVAILABLE')
            selected = self.agent_ref_resolver(context, work, inputs.get('profile'), authorization)
            if type(selected) is not dict or set(selected) != {'agent_ref', 'session_id'}:
                raise ApplicationError('WORK_ACTION_IMPLEMENTATION_AGENT_UNAVAILABLE')
            agent, session = selected['agent_ref'], selected['session_id']
        agent_instance_ref_bytes(agent)
        if type(session) is not str or not session:
            raise ApplicationError('AGENT_WORK_FIXED_SESSION_REQUIRED')
        return {'dispatch':{'work_id':work.work_id, 'action_id':action_id, 'step_id':step_id,
            'attempt':1, 'agent_ref':agent, 'params':{'sessionId':session},
            'actions':list(actions), 'timeout':self.implementation_timeout}}

    async def dispatch_agent_execution(self, parameters, context):
        from jsonschema import Draft202012Validator
        if (self.agent_ref_resolver is None or set(parameters) != {'dispatch'}
                or not Draft202012Validator(self.dispatch_descriptor.contract['input_schema']).is_valid(parameters)):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        request = parameters['dispatch']
        from ..contracts.dispatch_identity import work_dispatch_key
        identity = work_dispatch_key(request['work_id'], request['action_id'], request['step_id'])
        returned = await self.dispatch.dispatch_agent_work(identity,
            request['work_id'], request['action_id'], request['step_id'], request['attempt'],
            request['agent_ref'], request['params'], tuple(request['actions']), context,
            timeout=request['timeout'])
        return self._agent_dispatch_result(request, context, returned)

    def _agent_dispatch_result(self, request, context, returned):
        from ..contracts.dispatch_identity import work_dispatch_key
        from ...domain.changes.agent_dispatch import AgentWorkDispatchBinding
        from ...domain.changes.agent_dispatch_codec import decode_agent_dispatch
        operation = 'engineering.executions.dispatch'
        if type(returned) is not dict:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        identity = work_dispatch_key(request['work_id'], request['action_id'], request['step_id'])
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.get(identity, request['step_id'], request['attempt'], context.scope)
            binding = decode_agent_dispatch(row['binding_bytes'])
        if (type(binding) is not AgentWorkDispatchBinding or row['run_id'] != identity
                or row['step_id'] != request['step_id'] or row['attempt'] != request['attempt']
                or binding.work != {'work_id':request['work_id'], 'action_id':request['action_id'],
                                    'step_id':request['step_id'], 'dispatch_key':identity}
                or binding.attempt != request['attempt'] or binding.scope != context.scope
                or binding.agent_ref_bytes != canonical_bytes(request['agent_ref'])
                or tuple(a for a, _ in binding.action_instances) != tuple(request['actions'])):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_BINDING_MISMATCH')
        phase = row['dispatch_phase']
        outcome = phase if phase in {'completed', 'failed'} else 'unknown'
        result_ref = None
        if row['result_blob_json'] is not None:
            result_ref = decode_blob_ref(decode_json(row['result_blob_json']))
            with self.factory.begin(context.scope, 'read') as uow:
                uow.implementation.read_blob(result_ref)
        if (returned.get('phase') != phase or returned.get('identity') != identity
                or returned.get('step_id') != request['step_id'] or returned.get('attempt') != request['attempt']
                or returned.get('binding_digest') != asdict(binding.digest)
                or returned.get('params_assembly') != 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_AGENT'
                or returned.get('engineering_completed', False) is not False
                or canonical_bytes(returned.get('result_blob_ref')) !=
                    (b'null' if result_ref is None else canonical_bytes(asdict(result_ref)))):
            outcome = 'unknown'
        return OwnerOperationResult(operation, outcome,
            {'binding':binding, 'observation_ref':result_ref,
             'params_assembly':returned.get('params_assembly')},
            engineering_completed=False, accepted=False, dispatch_phase=phase,
            reason=None if outcome == phase else 'OWNER_RESULT_MISMATCH')

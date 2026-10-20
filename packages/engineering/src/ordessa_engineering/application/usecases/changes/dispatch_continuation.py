"""Owner-side qualification, unique claim and verification of one continuation.

Segment B of the frozen pre-write continuation order. Nothing here is derived
from caller text, and nothing here creates a Unit: the module reads the original
dispatch rows through the original unit of work, journals the causal request
exactly once, and re-verifies the causal chain before a new attempt may run.

Execution-side reads (native observation, stop/release proof) arrive through
``ContinuationEvidenceReader``. When that port is not bound, every function here
refuses with a named error instead of guessing from empty records.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ordessa_engineering.application.contracts.commands import CommandContext, CommandResult
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_observations import (
    ContinuationEvidenceReader, ExecutionObservationRef, OriginPrewriteEvidence,
)
from ordessa_engineering.application.contracts.failure_diagnostic import (
    FAILURE_MEDIA_TYPE, FailureDiagnostic,
)
from ordessa_engineering.application.contracts.work_context import WorkBinding
from ordessa_engineering.domain.changes.dispatch import (
    CONTINUATION_SCHEMA_VERSION, DispatchBinding, DispatchContinuation, DispatchOriginRef,
)
from ordessa_engineering.domain.changes.dispatch_codec import (
    decode_continuation, decode_dispatch, encode_dispatch,
)
from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest

CONTINUATION_OPERATION = 'engineering.work.invoke'
CONTINUATION_OPERATION_PREFIX = 'work-continuation-'
MAX_CONTINUATION_ATTEMPT = 4096


def _digest(raw: bytes) -> Digest:
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def continuation_operation_id(scope, origin: DispatchOriginRef) -> str:
    """Stable id of the causal request for one origin; never caller-selected.

    Derived only from the exact scope and the origin attempt's own digests, so a
    different request id or principal competing for the same origin derives the
    same id and can only ever create one journal row.
    """
    if type(origin) is not DispatchOriginRef or origin.scope != scope:
        raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
    payload = {
        'contract': 'engineering.work-continuation-operation/1',
        'realm_id': scope.realm_id, 'project_id': scope.project_id,
        'dispatch_key': origin.dispatch_key, 'step_id': origin.step_id,
        'attempt': origin.attempt,
        'binding_bytes_digest': {'algorithm': origin.binding_bytes_digest.algorithm,
                                 'hex': origin.binding_bytes_digest.hex},
    }
    return CONTINUATION_OPERATION_PREFIX + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def origin_ref_from_row(row, binding: DispatchBinding, *, expected_acp_revision: int) -> DispatchOriginRef:
    """Build the owner's origin reference from its own durable row.

    The row is the original ``work_step_log`` row; both digests are read from it
    rather than derived from each other. The expected native revision is a
    request condition that the original evidence reader must independently check.
    """
    if (type(binding) is not DispatchBinding or binding.binding_version != 2
            or type(row) is not dict or type(expected_acp_revision) is not int
            or expected_acp_revision < 1):
        raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
    raw = row.get('binding_bytes')
    if (type(raw) is not bytes or encode_dispatch(binding) != raw
            or hashlib.sha256(raw).hexdigest() != row.get('binding_digest', Digest('sha256', '0' * 64)).hex):
        raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
    return DispatchOriginRef(
        scope=binding.scope,
        dispatch_key=row['run_id'],
        step_id=row['step_id'],
        attempt=row['attempt'],
        execution_operation_ref=row['execution_operation_ref'],
        binding_bytes_digest=_digest(raw),
        binding_record_digest=binding.digest,
        expected_dispatch_version=row['dispatch_version'],
        expected_acp_revision=expected_acp_revision,
    )


@dataclass(frozen=True)
class ContinuationCandidate:
    """One derived, unauthenticated qualification of a single continuation."""

    work: WorkBinding
    origin: DispatchOriginRef
    origin_binding: DispatchBinding
    diagnostic: FailureDiagnostic
    failure_evidence_ref: BlobRef
    evidence: OriginPrewriteEvidence
    attempt: int
    actions: tuple[str, ...]


@dataclass(frozen=True)
class ContinuationReservation:
    """The journal row that owns this causal request, and whether it was created."""

    operation_id: str
    created: bool
    entry: object


def affirmative_prewrite(diagnostic: FailureDiagnostic, binding: DispatchBinding) -> None:
    """Accept only a diagnostic that proves this frame never reached stdin."""
    record = diagnostic.to_dict()
    native = record.get('native_write')
    if record.get('recording_failure') is not None:
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
    if type(native) is not dict:
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
    if (native.get('phase') != 'effect_guard_acquire'
            or native.get('before_write') != 'not_entered'
            or native.get('write_stdin') != 'not_entered'
            or native.get('acknowledged_bytes') is not None
            or native.get('frame_bytes', 0) <= 0
            or native.get('operation_ref') != binding.execution_operation_ref
            or native.get('input_digest') != 'sha256:' + binding.prompt_input_digest.hex
            or native.get('unit_ref_digest') != 'sha256:' + hashlib.sha256(binding.unit_ref_bytes).hexdigest()):
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')


def qualify_continuation(context: CommandContext, work: WorkBinding, action_id: str, step_id: str,
                         origin: DispatchOriginRef, *, factory, evidence_reader,
                         reader_evidence: OriginPrewriteEvidence | None = None) -> ContinuationCandidate:
    """Read the original rows and decide whether this origin may be continued.

    A missing reader, a missing or non-affirmative diagnostic, a changed tip, an
    occupied causal request, or any identity mismatch refuses here — before any
    Unit is created. Nothing is written.
    """
    if (type(context) is not CommandContext or type(work) is not WorkBinding
            or type(origin) is not DispatchOriginRef or origin.scope != context.scope
            or factory is None or evidence_reader is None
            or not callable(getattr(evidence_reader, 'read_origin', None))):
        raise ApplicationError('CONTINUATION_EVIDENCE_UNAVAILABLE')
    evidence = reader_evidence if reader_evidence is not None else evidence_reader.read_origin(context, origin)
    if type(evidence) is not OriginPrewriteEvidence:
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
    observation = evidence.acp_observation
    if (type(observation) is not ExecutionObservationRef
            or observation.state != 'unknown'
            or observation.operation_ref != origin.execution_operation_ref
            or observation.revision != origin.expected_acp_revision
            or observation.authority_id != factory.authority_id
            or type(evidence.stop_record) is not dict or not evidence.stop_record
            or type(evidence.release_record) is not dict or not evidence.release_record):
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
    with factory.begin(context.scope, 'read') as uow:
        latest = uow.work_dispatch.latest_attempt(origin.dispatch_key, origin.step_id, context.scope)
        if latest != origin.attempt:
            # Only the current tip may be continued: an older attempt already has
            # its own successor, and a newer one means this link is no longer the
            # predecessor of the next attempt.
            raise ApplicationError('CONTINUATION_NOT_TIP')
        row = uow.work_dispatch.get(origin.dispatch_key, origin.step_id, origin.attempt, context.scope)
        binding = decode_dispatch(row['binding_bytes'])
        if (binding.binding_version != 2 or binding.work is None
                or binding.work.get('dispatch_key') != origin.dispatch_key
                or binding.work.get('work_id') != work.work_id
                or binding.work.get('action_id') != action_id
                or binding.work.get('step_id') != step_id
                or binding.step_id != step_id or binding.attempt != origin.attempt
                or binding.scope != context.scope
                or binding.execution_operation_ref != origin.execution_operation_ref
                or row['execution_operation_ref'] != origin.execution_operation_ref
                or row['dispatch_phase'] != 'unknown'
                or row['dispatch_version'] != origin.expected_dispatch_version
                or _digest(row['binding_bytes']) != origin.binding_bytes_digest
                or binding.digest != origin.binding_record_digest
                or observation.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
                or observation.query_digest != binding.expected_query_digest
                or canonical_bytes(decode_json(binding.unit_ref_bytes)) != canonical_bytes(observation.unit_ref)):
            raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
        if row['result_blob_json'] is None:
            raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
        result_ref = decode_blob_ref(decode_json(row['result_blob_json']))
        if result_ref.media_type != FAILURE_MEDIA_TYPE:
            raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
        try:
            observed = uow.implementation.read_blob(result_ref)
            diagnostic = FailureDiagnostic(observed)
        except (TypeError, ValueError):
            raise ApplicationError('CONTINUATION_EVIDENCE_INVALID') from None
        affirmative_prewrite(diagnostic, binding)
        occupied = uow.commands.find_operation(
            context.scope, continuation_operation_id(context.scope, origin),
            operation=CONTINUATION_OPERATION)
        if occupied is not None:
            raise ApplicationError('CONTINUATION_ALREADY_CLAIMED')
        actions = tuple(action for action, _ in binding.action_instances)
        attempt = origin.attempt + 1
        if attempt > MAX_CONTINUATION_ATTEMPT:
            raise ApplicationError('CONTINUATION_ATTEMPT_EXHAUSTED')
    return ContinuationCandidate(work=work, origin=origin, origin_binding=binding,
                                 diagnostic=diagnostic, failure_evidence_ref=result_ref,
                                 evidence=evidence, attempt=attempt, actions=actions)


def recheck_continuation_candidate(uow, context, candidate):
    """Recheck the origin, current Grant and retained debit in the claim's UoW."""
    from ...orchestration.steps.declared_implementation_dispatch import _grant_facts
    from ..support.clock import utc_now
    if type(candidate) is not ContinuationCandidate:
        raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
    origin, binding = candidate.origin, candidate.origin_binding
    row = uow.work_dispatch.get(origin.dispatch_key, origin.step_id, origin.attempt, context.scope)
    if (uow.work_dispatch.latest_attempt(origin.dispatch_key, origin.step_id, context.scope) != origin.attempt
            or row['dispatch_phase'] != 'unknown'
            or row['dispatch_version'] != origin.expected_dispatch_version
            or row['binding_bytes'] != encode_dispatch(binding)
            or _digest(row['binding_bytes']) != origin.binding_bytes_digest
            or binding.digest != origin.binding_record_digest
            or candidate.attempt != origin.attempt + 1
            or candidate.actions != tuple(a for a, _ in binding.action_instances)
            or row['result_blob_json'] is None
            or decode_blob_ref(decode_json(row['result_blob_json'])) != candidate.failure_evidence_ref):
        raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
    diagnostic = FailureDiagnostic(uow.implementation.read_blob(candidate.failure_evidence_ref))
    affirmative_prewrite(diagnostic, binding)
    _, facts, _ = _grant_facts(uow, candidate.work.work_id, binding.work['action_id'],
        binding.step_id, utc_now(), binding=binding)
    if facts.work != candidate.work:
        raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
    root = verify_continuation_reservation(uow, binding) or binding
    uow.authorization.check_action_consumptions(root.approval_ref,
        intent_digest=root.intent_digest, target_digest=root.digest,
        action_instances=root.action_instances)


def claim_continuation(uow, context: CommandContext, candidate: ContinuationCandidate,
                       request_digest: Digest) -> ContinuationReservation:
    """Reserve the one causal journal row for this origin, inside the write UoW.

    The journal must be claimed before a Unit exists. A competing request id or
    principal derives the same operation id and can only observe the occupied
    row: it never creates a second reservation.
    """
    if type(candidate) is not ContinuationCandidate or type(request_digest) is not Digest:
        raise ApplicationError('CONTINUATION_ORIGIN_INVALID')
    operation_id = continuation_operation_id(context.scope, candidate.origin)
    try:
        reservation = uow.commands.reserve(
            context.key, project_id=context.scope.project_id,
            operation=CONTINUATION_OPERATION, operation_id=operation_id,
            request_digest=request_digest)
    except ApplicationError as error:
        if error.code != 'OPERATION_ID_CONFLICT':
            raise
        existing = uow.commands.find_operation(context.scope, operation_id,
                                               operation=CONTINUATION_OPERATION)
        if existing is None:
            raise ApplicationError('CONTINUATION_OCCUPIED_UNAVAILABLE') from None
        return ContinuationReservation(operation_id=operation_id, created=False, entry=existing)
    entry = reservation.entry
    if entry.operation_id != operation_id or entry.state not in ('pending', 'completed', 'failed'):
        raise ApplicationError('CONTINUATION_OPERATION_MISMATCH')
    return ContinuationReservation(operation_id=operation_id, created=reservation.created,
                                   entry=entry)


def resolve_continuation_root(uow, binding: DispatchBinding):
    """Walk this attempt's own immutable marker chain back to its root.

    The proof lives in the stored rows, never in a caller-supplied root: the
    continuation is parsed from the current row's marker, every hop is checked
    against its predecessor row (scope/key/step/attempt/native operation/versions
    and both digests), and breaks, cycles and skipped attempts are refused. An
    ordinary first-attempt marker returns ``None``; a continuation that fails any
    check raises.

    This only reads the caller's UoW and returns a projection, never authority.
    Write cuts use verify_continuation_reservation to additionally check the
    original debit. Neither entry calls the external execution evidence reader.
    """
    if type(binding) is not DispatchBinding or binding.digest is None:
        raise ApplicationError('CONTINUATION_RELATION_INVALID')
    row = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, binding.scope)
    if (type(row) is not dict or row.get('binding_bytes') != encode_dispatch(binding)
            or row.get('binding_digest') != _digest(row['binding_bytes'])):
        raise ApplicationError('CONTINUATION_RELATION_INVALID')
    continuation = row.get('continuation')
    if continuation is None:
        # Ordinary marker: this row claims no predecessor, so there is no chain.
        return None
    seen = set()
    reservation_origins = []
    successor, successor_row = binding, row
    while True:
        if type(continuation) is not DispatchContinuation:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        origin = continuation.origin
        reservation_origins.append(continuation.reservation_origin)
        hop = (origin.dispatch_key, origin.step_id, origin.attempt)
        if hop in seen:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')  # cycle
        seen.add(hop)
        if (continuation.schema_version != CONTINUATION_SCHEMA_VERSION
                or continuation.successor_binding_record_digest != successor.digest
                or successor.work is None
                or successor.work.get('dispatch_key') != origin.dispatch_key
                or successor.work.get('step_id') != origin.step_id
                or successor.attempt != origin.attempt + 1
                or successor.scope != origin.scope):
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        # The causal journal row must exist and be owned by this exact origin.
        causal_id = continuation_operation_id(origin.scope, origin)
        causal = uow.commands.find_operation(origin.scope, causal_id,
                                             operation=CONTINUATION_OPERATION)
        if (continuation.causal_operation_id != causal_id or causal is None
                or causal.operation_id != causal_id or causal.state not in ('pending', 'completed')):
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        # Stop/release and observation references must be this authority's blobs.
        for ref in (continuation.failure_evidence_ref, continuation.acp_observation_ref):
            uow.implementation.read_blob(ref)
        predecessor_row = uow.work_dispatch.get(origin.dispatch_key, origin.step_id,
                                                 origin.attempt, origin.scope)
        if (type(predecessor_row) is not dict
                or type(predecessor_row.get('binding_bytes')) is not bytes):
            raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
        predecessor = decode_dispatch(predecessor_row['binding_bytes'])
        if (predecessor.binding_version != 2 or predecessor.work is None
                or predecessor.scope != origin.scope
                or predecessor.run_id != origin.dispatch_key
                or predecessor.step_id != origin.step_id
                or predecessor.attempt != origin.attempt
                or predecessor.attempt + 1 != successor.attempt
                or predecessor.execution_operation_ref != origin.execution_operation_ref
                or predecessor_row.get('execution_operation_ref') != origin.execution_operation_ref
                or predecessor_row.get('dispatch_version') != origin.expected_dispatch_version
                or predecessor_row.get('dispatch_phase') != 'unknown'
                or _digest(predecessor_row['binding_bytes']) != origin.binding_bytes_digest
                or predecessor.digest != origin.binding_record_digest):
            raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
        if (predecessor_row.get('result_blob_json') is None
                or decode_blob_ref(decode_json(predecessor_row['result_blob_json']))
                    != continuation.failure_evidence_ref):
            raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
        affirmative_prewrite(FailureDiagnostic(uow.implementation.read_blob(
            continuation.failure_evidence_ref)), predecessor)
        observation = decode_json(uow.implementation.read_blob(continuation.acp_observation_ref))
        if (observation.get('state') != 'unknown'
                or observation.get('revision') != continuation.acp_revision
                or observation.get('operationRef') != predecessor.execution_operation_ref
                or canonical_bytes(observation.get('unitRef')) != predecessor.unit_ref_bytes
                or observation.get('inputDigest') != 'sha256:' + predecessor.prompt_input_digest.hex
                or observation.get('request') is not None or observation.get('response') is not None
                or observation.get('events') != []):
            raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
        for item in (predecessor, successor):
            prompt = decode_json(uow.implementation.read_blob(item.prompt_ref))
            if _digest(canonical_bytes(prompt['prompt'])) != continuation.semantic_prompt_digest:
                raise ApplicationError('CONTINUATION_SEMANTIC_PROMPT_CHANGED')
        # One chain, one business root: same Work/package/method and Grant/intent,
        # the same action instances and a consistent semantic prompt digest.
        if (predecessor.work.get('work_id') != successor.work.get('work_id')
                or predecessor.work.get('action_id') != successor.work.get('action_id')
                or predecessor.package_ref != successor.package_ref
                or predecessor.approval_ref != successor.approval_ref
                or predecessor.intent_digest != successor.intent_digest
                or predecessor.action_instances != successor.action_instances
                or predecessor.required_results != successor.required_results
                or predecessor.subject != successor.subject):
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        next_continuation = predecessor_row.get('continuation')
        if next_continuation is None:
            root = predecessor
            break
        if type(next_continuation) is not DispatchContinuation:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        if next_continuation.semantic_prompt_digest != continuation.semantic_prompt_digest:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        if next_continuation.origin.attempt + 1 != predecessor.attempt:
            raise ApplicationError('CONTINUATION_RELATION_INVALID')
        continuation = next_continuation
        successor, successor_row = predecessor, predecessor_row
    if (root.work is None or root.digest is None
            or any(ref != origin for ref in reservation_origins)):
        raise ApplicationError('CONTINUATION_RELATION_INVALID')
    return root


def verify_continuation_reservation(uow, binding: DispatchBinding):
    """Verify retained consumption at a write cut after resolving the same chain.

    Read-only report/round projections use ``resolve_continuation_root``. This
    write-cut entry retains the original authorization repository's write fence.
    """
    root = resolve_continuation_root(uow, binding)
    if root is None:
        return None
    # Root consumption is checked at the root's own record digest and instances.
    uow.authorization.check_action_consumptions(
        root.approval_ref, intent_digest=root.intent_digest,
        target_digest=root.digest, action_instances=root.action_instances)
    return root

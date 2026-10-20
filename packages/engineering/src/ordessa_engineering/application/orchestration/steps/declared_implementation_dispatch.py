"""Declared Work implementation on the original dispatch/authorization owners.

No MethodRun, compiled recipe or checkout inspection participates in this path.
The immutable schema17 row is the retry authority; a retry never owns a send.
"""
import asyncio
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import asdict
import hashlib
import math
from uuid import uuid4

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.dispatch_identity import work_dispatch_key
from ...contracts.errors import ApplicationError
from ...contracts.work_context import WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding
from ...usecases.packages.authorization import resolve_work_package_authorization
from ....domain.approvals.implementation import WorkPackageAuthorizationIntent
from ....domain.approvals.scope import EnvironmentRef
from ....domain.changes.dispatch import DispatchBinding, package_ref_projection
from ....domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ....domain.common.models.values import Digest


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _existing(uow, key, step, attempt):
    try:
        return uow.work_dispatch.get(key, step, attempt, uow.scope)
    except ApplicationError as exc:
        if exc.code != 'NOT_FOUND':
            raise
    return None


def _view(owner, row, reason=None):
    value = owner._view(row, reason)
    value['identity'] = value.pop('run_id')
    value['params_assembly'] = 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT'
    return value


def _subject(uow, work_id):
    head = uow.workflow.head_ref(WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + work_id)
    if head is None:
        raise ApplicationError('WORK_NOT_FOUND')
    work = decode_work_binding(uow.workflow.read(head))
    packages = tuple(a.ref for a in work.associations if a.kind == 'package')
    if len(packages) != 1:
        raise ApplicationError('DISPATCH_DECLARED_WORK_SUBJECT_MATERIAL_UNAVAILABLE')
    return head, work, packages[0]


def _grant_facts(uow, work_id, action_id, step_id, now, *, binding=None):
    if binding is None:
        head, work, package_ref = _subject(uow, work_id)
        grants = uow.authorization.find_work_package_grants(
            work_id=work_id, work_revision=head.revision,
            work_digest=Digest('sha256', head.digest.removeprefix('sha256:')),
            action_id=action_id, step_id=step_id, package_ref=package_ref,
            method_ref=work.method_ref, now=now)
        if not grants:
            raise ApplicationError('DISPATCH_DECLARED_WORK_GRANT_UNAVAILABLE')
        if len(grants) != 1:
            raise ApplicationError('DISPATCH_DECLARED_WORK_GRANT_AMBIGUOUS')
        grant = grants[0]
    else:
        grant = uow.authorization.get_grant(binding.approval_ref)
    facts = _grant_facts_for_grant(uow, grant, work_id, action_id, step_id,
                                   binding=binding)
    if not grant.intent.not_before <= now < grant.intent.expires_at:
        raise ApplicationError('APPROVAL_CONTROL_CHANGED')
    return facts


def _grant_facts_for_grant(uow, grant, work_id, action_id, step_id, *,
                           binding=None):
    """Validate immutable binding/control facts shared by both time gates."""
    if type(grant.intent) is not WorkPackageAuthorizationIntent:
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    authorization = grant.intent.authorization
    if (authorization.work_id, authorization.action_id, authorization.step_id) != (
            work_id, action_id, step_id):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    facts = resolve_work_package_authorization(uow, authorization)
    control = uow.authorization.get_control(grant.ref)
    if (control['state'] != 'granted' or control.get('revoked_at') is not None
            or (binding is not None and (grant.ref != binding.approval_ref
                or grant.intent.digest != binding.intent_digest
                or control['version'] != binding.control_version))):
        raise ApplicationError('APPROVAL_CONTROL_CHANGED')
    return grant, facts, control


def _report_only_disposition_grant_facts(uow, work_id, action_id, step_id, now, *,
                                         binding, permit, context, work,
                                         submission_ref, review_ref):
    """The one disposition path allowed to finish under a successor permit.

    Every historical binding/control/consumption fact remains current. Only
    the old implementation Grant's expiry is replaced by the exact, typed
    report-only closeout permit.
    """
    from ..report_only_disposition import ReportOnlyDispositionPermit
    if type(permit) is not ReportOnlyDispositionPermit:
        raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
    grant = uow.authorization.get_grant(binding.approval_ref)
    _grant_facts_for_grant(uow, grant, work_id, action_id, step_id,
                           binding=binding)
    if now < grant.intent.not_before:
        raise ApplicationError('APPROVAL_CONTROL_CHANGED')
    budget = uow.authorization.action_budget(grant.ref)
    slots = {item['action']: item for item in budget['actions']}
    if any(slots.get(action, {}).get('limit') != 1
           or slots.get(action, {}).get('consumed') != 1
           for action, _instance in binding.action_instances):
        raise ApplicationError('APPROVAL_CONTROL_CHANGED')
    permit.validate(uow, context=context, work=work, binding=binding,
                    submission_ref=submission_ref, review_ref=review_ref, now=now)
    return grant


def _task(owner, context, facts, authorization, actions):
    """Only pinned method bytes and captured package documents become ACP input."""
    methods, sources = owner.method_guard, owner.source_materials
    if (getattr(methods, 'factory', None) is not owner.factory
            or getattr(sources, 'factory', None) is not owner.factory):
        raise ApplicationError('DISPATCH_WORK_INPUT_AUTHORITY_UNAVAILABLE')
    selected_profile = getattr(owner.selection, 'describe_work_profile', None)
    if not callable(selected_profile):
        raise ApplicationError('DISPATCH_WORK_PROFILE_AUTHORITY_UNAVAILABLE')
    profile = selected_profile(context, facts.package, authorization)
    if (type(profile) is not dict or set(profile) != {
            'environmentNamespace', 'profileId', 'manifestRevision', 'contentDigest'}
            or type(profile['manifestRevision']) is not int or profile['manifestRevision'] < 1):
        raise ApplicationError('DISPATCH_WORK_PROFILE_AUTHORITY_UNAVAILABLE')
    with methods.guard(context, facts.work.method_ref) as declaration:
        declared = next((a for a in declaration.actions if a.action_id == authorization.action_id), None)
        step = next((s for s in declared.steps if s.step_id == authorization.step_id), None) if declared else None
        if step is None or step.kind != 'invoke' or step.name != 'implement-approved-package':
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        resource_ids = tuple(i.source_name for i in step.inputs if i.source_kind == 'resource')
        # The result schema belongs to the same released action, not caller text.
        if any(resource.resource_id == 'implementation-report-schema' for resource in declared.resources):
            resource_ids += ('implementation-report-schema',)
        resources = {}
        for resource_id in resource_ids:
            ref = methods.resource_ref(context, facts.work.method_ref, resource_id)
            raw = methods.read_resource(context, ref)
            resources[resource_id] = {'ref': asdict(ref), 'text': raw.decode('utf-8')}
        with owner.factory.begin(context.scope, 'read') as uow:
            documents = [{'role': doc.role, 'source_ref': asdict(doc.source_ref),
                          'text': uow.implementation.read_prepared_document(
                              facts.package.ref, doc.role).decode('utf-8')}
                         for doc in facts.package.payload.documents]
        if not {'spec', 'plan', 'tasks'} <= {doc['role'] for doc in documents}:
            raise ApplicationError('DISPATCH_WORK_PACKAGE_DOCUMENTS_UNAVAILABLE')
        text = canonical_bytes({'package_ref': asdict(facts.package.ref), 'profile_ref': profile,
            'package': asdict(facts.package.payload), 'documents': documents,
            'method_ref': asdict(facts.work.method_ref), 'released_resources': resources,
            'authorization': asdict(authorization), 'requested_actions': list(actions)}).decode('utf-8')
        return {'prompt': [{'type': 'text', 'text': text}]}, tuple(step.outputs)


@contextmanager
def _guards(owner, context, grant, facts, unit, params, actions):
    authorization = grant.intent.authorization
    if not set(actions) <= set(authorization.actions):
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    selection = getattr(owner.selection, 'guard_work_selection', None)
    scope_guard = getattr(owner.selection, 'guard_work_scope', None)
    if not callable(selection) or owner.approvals is None:
        raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
    if not callable(scope_guard):
        raise ApplicationError('DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE')
    with ExitStack() as stack:
        admission = owner.approvals._admission()
        stack.enter_context(admission.guard_intent(context, grant.intent))
        stack.enter_context(admission.guard_evidence(context, grant.intent, grant.evidence))
        decisions = stack.enter_context(owner.approvals._gates(context, grant.intent))
        environment = stack.enter_context(selection(context, facts.package, unit, authorization, params))
        scopes = dict(authorization.scope_by_action)
        if (type(environment) is not EnvironmentRef
                or any(environment not in scopes[a].environment_refs for a in actions)
                or ('edit_repository' in actions and not scopes['edit_repository'].repository_scopes)):
            raise ApplicationError('ACTION_SCOPE_NOT_AUTHORIZED')
        # A prompt is no filesystem/effect fence. The original execution owner
        # must admit these exact scopes; absent capability is a named refusal.
        stack.enter_context(scope_guard(context, facts.package, unit, authorization, actions))
        yield decisions


def _capture_failure(owner, binding, error, stage):
    """Bounded, payload-free facts for one failure on this exact binding.

    The execution's own extractor is used when it is bound, so the trusted
    write-boundary snapshot keeps its usual binding checks. A refusal there is
    appended as a secondary failure instead of replacing the primary one.
    """
    from ...contracts.failure_diagnostic import FailureDiagnostic
    diagnostic = FailureDiagnostic.capture(error, stage)
    capture = getattr(owner.execution, 'failure_diagnostic', None)
    if not callable(capture):
        return diagnostic
    try:
        captured = capture(binding, error, stage)
        if type(captured) is not FailureDiagnostic:
            raise ApplicationError('DISPATCH_FAILURE_DIAGNOSTIC_INVALID')
        return captured
    except Exception as capture_error:
        return diagnostic.with_recording_failure(capture_error)


def _standalone(error, diagnostic):
    """Keep the facts on the refusal when no row/blob write is safe.

    An ``ApplicationError`` keeps its own code and retry and only gains the
    bounded diagnostic. Any other exception is reported as an unconfirmed
    diagnostic so the wire still receives a closed, payload-free record. No
    row, budget, blob or phase changes here.
    """
    if isinstance(error, ApplicationError):
        if error.failure_diagnostic is None:
            error.failure_diagnostic = diagnostic
        return error
    return ApplicationError('DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED',
                            retry='reconcile', failure_diagnostic=diagnostic)


def dispatch(owner, identity, work_id, action_id, step_id, attempt, unit_ref, params,
             actions, context, *, timeout, continuation=None):
    """Dispatch one attempt; `continuation` is an in-process draft, never JSON.

    The draft carries everything except the successor digest, which only exists
    once this attempt's binding is built. The value is sealed with the existing
    codec inside the same write transaction as the new row, so a sealing failure
    leaves no partial registration and no prompt is ever sent.
    """
    if (identity != work_dispatch_key(work_id, action_id, step_id)
            or type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 3600 or type(params) is not dict):
        raise ApplicationError('INVALID_ARGUMENT')
    unit_bytes = canonical_bytes(unit_ref)
    # Retry is read first, before current Work/Grant/selection/freeze/blob writes.
    with owner.factory.begin(context.scope, 'read') as uow:
        old = _existing(uow, identity, step_id, attempt)
        if old is not None:
            bound = decode_dispatch(old['binding_bytes'])
            if (bound.binding_version != 2 or bound.work != {
                    'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
                    'dispatch_key': identity} or bound.unit_ref_bytes != unit_bytes
                    or tuple(a for a, _ in bound.action_instances) != actions):
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            original = uow.authorization.get_grant(bound.approval_ref)
            if type(original.intent) is not WorkPackageAuthorizationIntent:
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            auth = original.intent.authorization
            if (bound.intent_digest != original.intent.digest
                    or auth.scope != bound.scope or auth.package_ref != bound.package_ref
                    or (auth.work_id, auth.action_id, auth.step_id) != (work_id, action_id, step_id)
                    or not set(actions) <= set(auth.actions)
                    or bound.subject != {'subject_kind': 'frozen_package',
                                         'subject_ref': package_ref_projection(auth.package_ref)}):
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            frozen = decode_json(uow.implementation.read_blob(bound.prompt_ref))
            if params and canonical_bytes(params) != canonical_bytes(frozen):
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            return _view(owner, old, 'ORIGINAL_ATTEMPT_NO_RESEND')
        grant, facts, _ = _grant_facts(uow, work_id, action_id, step_id, context.received_at)
    if owner.execution is None or owner.blobs is None:
        raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
    if not set(actions) <= set(grant.intent.actions):
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    task, required_results = _task(owner, context, facts, grant.intent.authorization, actions)
    if continuation is not None and _digest(canonical_bytes(task['prompt'])) != continuation['semantic_prompt_digest']:
        raise ApplicationError('CONTINUATION_SEMANTIC_PROMPT_CHANGED')
    raw, prompt_digest = owner.execution.freeze_input(unit_ref, task)
    frozen = decode_json(raw)
    if params and canonical_bytes(params) != raw:
        raise ApplicationError('DISPATCH_WORK_INPUT_CHANGED')
    prompt = owner.blobs.put_verified(raw, _digest(raw), 'application/json')
    bound = None
    try:
        with _guards(owner, context, grant, facts, unit_ref, frozen, actions) as decisions:
            with owner.factory.begin(context.scope) as uow:
                current, current_facts, control = _grant_facts(
                    uow, work_id, action_id, step_id, context.received_at)
                if current.ref != grant.ref or current_facts != facts:
                    raise ApplicationError('APPROVAL_CONTROL_CHANGED')
                owner.approvals._check_gates(uow, decisions)
                if _existing(uow, identity, step_id, attempt) is not None:
                    raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                operation = str(uuid4())
                if continuation is None:
                    instances = tuple((a, str(uuid4())) for a in actions)
                else:
                    # A continuation inherits the root's exact action-instance
                    # tuple: it never mints a new instance for the same action.
                    from ...usecases.changes.dispatch_continuation import verify_continuation_reservation
                    predecessor = decode_dispatch(uow.work_dispatch.get(
                        identity, step_id, attempt - 1, context.scope)['binding_bytes'])
                    root_binding = verify_continuation_reservation(uow, predecessor) or predecessor
                    uow.authorization.check_action_consumptions(root_binding.approval_ref,
                        intent_digest=root_binding.intent_digest, target_digest=root_binding.digest,
                        action_instances=root_binding.action_instances)
                    instances = root_binding.action_instances
                bound = DispatchBinding(context.scope, identity, step_id, attempt, 1,
                    facts.package.ref, grant.ref, grant.intent.digest, control['version'],
                    instances, unit_bytes, operation, prompt, prompt_digest,
                    owner.execution.query_digest(unit_ref, operation, prompt_digest), required_results,
                    binding_version=2, work={'work_id': work_id, 'action_id': action_id,
                        'step_id': step_id, 'dispatch_key': identity},
                    subject={'subject_kind': 'frozen_package',
                             'subject_ref': package_ref_projection(facts.package.ref)})
                encoded = encode_dispatch(bound)
                sealed = None
                if continuation is not None:
                    from ordessa_engineering.domain.changes.dispatch import DispatchContinuation
                    sealed = DispatchContinuation(
                        origin=continuation['origin'],
                        reservation_origin=continuation['reservation_origin'],
                        causal_operation_id=continuation['causal_operation_id'],
                        failure_evidence_ref=continuation['failure_evidence_ref'],
                        acp_observation_ref=continuation['acp_observation_ref'],
                        acp_revision=continuation['acp_revision'],
                        stop_proof_ref=continuation['stop_proof_ref'],
                        release_proof_ref=continuation['release_proof_ref'],
                        semantic_prompt_digest=continuation['semantic_prompt_digest'],
                        successor_binding_record_digest=bound.digest)
                if continuation is None:
                    for action, instance in instances:
                        uow.authorization.consume_action(grant.ref, action=action,
                            action_instance_id=instance, target_digest=bound.digest,
                            now=context.received_at)
                    row = uow.work_dispatch.reserve(identity, step_id, attempt, context.scope,
                                                   encoded, _digest(encoded), operation)
                else:
                    # A continuation never consumes again: the original root
                    # consumption is re-checked at the root's own record digest.
                    row = uow.work_dispatch.reserve_continuation(
                        identity, step_id, attempt, context.scope, encoded,
                        _digest(encoded), operation, sealed)
                    # Same transaction, before COMMIT: the new row's causal chain
                    # and the root consumption are verified once more.
                    from ...usecases.changes.dispatch_continuation import verify_continuation_reservation
                    verify_continuation_reservation(uow, bound)
                uow.commit()
        # The same Grant/gates/scope are re-checked under the second COMMIT.
        with _guards(owner, context, grant, facts, unit_ref, frozen, actions) as decisions:
            with owner.factory.begin(context.scope) as uow:
                _grant_facts(uow, work_id, action_id, step_id, context.received_at, binding=bound)
                owner.approvals._check_gates(uow, decisions)
                if bound is not None and continuation is not None:
                    from ...usecases.changes.dispatch_continuation import verify_continuation_reservation
                    verify_continuation_reservation(uow, bound)
                row = uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                    expected_version=0, fence=1, phase='possibly_written')
                uow.commit()
    except Exception as error:
        # The debit COMMIT (and, after the second COMMIT, the possibly_written
        # row) is already durable, but releasing either guard is still outside
        # any native frame. The row keeps its own state — no UNKNOWN, no result
        # blob, no refund, no second send — and the refusal carries the facts.
        if bound is None:
            raise
        diagnosed = _standalone(error, _capture_failure(owner, bound, error, 'pre_send'))
        if diagnosed is error:
            raise
        raise diagnosed from error
    stage = 'handoff_enter'
    try:
        with owner.execution.guard_effect_handoff(context, bound, access=owner.access, timeout=timeout):
            stage = 'native_send'
            owner.execution.send(bound, timeout=timeout)
            stage = 'handoff_exit'
    except Exception as error:
        from ...contracts.failure_diagnostic import FAILURE_MEDIA_TYPE
        diagnostic = _capture_failure(owner, bound, error, stage)
        verified_evidence = None
        try:
            # Preserve the original active-authority requirement. A diagnostic
            # never authorizes writing UNKNOWN after revocation.
            owner._access(context, 'engineering.executions.dispatch')
            evidence = owner.blobs.put_verified(diagnostic.encoded, _digest(diagnostic.encoded), FAILURE_MEDIA_TYPE)
            if owner.blobs.read_verified(evidence) != diagnostic.encoded:
                raise ApplicationError('DISPATCH_FAILURE_EVIDENCE_MISMATCH')
            verified_evidence = evidence
            with owner.factory.begin(context.scope) as uow:
                uow.implementation.read_blob(evidence)
                row = uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                    expected_version=row['dispatch_version'], fence=1, phase='unknown',
                    result_blob_ref=evidence)
                uow.commit()
        except Exception as recording_error:
            code = (recording_error.code if isinstance(recording_error, ApplicationError)
                    and recording_error.code.startswith('ACCESS_') else
                    'DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED')
            raise ApplicationError(code, retry='reconcile',
                failure_diagnostic=diagnostic.with_recording_failure(recording_error),
                failure_evidence_ref=verified_evidence, failure_evidence_linked=False) from error
        return _view(owner, row, 'NATIVE_SEND_OUTCOME_UNCONFIRMED')
    try:
        return reconcile(owner, bound, context)
    except Exception as error:
        # A cold read that cannot confirm the attempt leaves the original
        # `possibly_written` row untouched: no UNKNOWN transition, no refund
        # and no second send. The facts travel on the error instead.
        diagnosed = _standalone(error, _capture_failure(owner, bound, error, 'reconcile'))
        if diagnosed is error:
            raise
        raise diagnosed from error


def reconcile(owner, binding, context):
    """Authorized native cold read, never another dispatch or fresh Grant."""
    owner._access(context, 'engineering.executions.dispatch')
    with owner.factory.begin(context.scope, 'read') as uow:
        row = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, context.scope)
        if row['binding_bytes'] != encode_dispatch(binding):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        if row['dispatch_phase'] in {'reserved', 'completed', 'failed'}:
            return _view(owner, row)
    capture = owner.execution.capture(binding)
    if (capture.operation_ref != binding.execution_operation_ref
            or capture.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
            or capture.query_digest != binding.expected_query_digest):
        raise ApplicationError('DISPATCH_RECEIPT_BINDING_MISMATCH')
    phase = capture.state if capture.state in {'completed', 'failed'} else 'unknown'
    with owner.factory.begin(context.scope) as uow:
        uow.implementation.read_blob(capture.blob_ref)
        row = uow.work_dispatch.transition(binding.run_id, binding.step_id, binding.attempt,
            context.scope, expected_version=row['dispatch_version'], fence=binding.fence,
            phase=phase, result_blob_ref=capture.blob_ref)
        uow.commit()
    return _view(owner, row)


@asynccontextmanager
async def acquire_effect_cut(owner, context, binding, identity, deadline):
    """Revalidate the same Grant and its debit under the original write lock."""
    from ...usecases.support.clock import utc_now
    work = binding.work
    with owner.factory.begin(context.scope, 'read') as read:
        grant, facts, _ = _grant_facts(read, work['work_id'], work['action_id'],
            binding.step_id, utc_now(), binding=binding)
        params = decode_json(read.implementation.read_blob(binding.prompt_ref))
    actions = tuple(a for a, _ in binding.action_instances)
    unit = decode_json(binding.unit_ref_bytes)
    task, outputs = _task(owner, context, facts, grant.intent.authorization, actions)
    if params.get('prompt') != task['prompt'] or outputs != binding.required_results:
        raise ApplicationError('DISPATCH_WORK_INPUT_CHANGED')
    with _guards(owner, context, grant, facts, unit, params, actions) as decisions:
        loop = asyncio.get_running_loop()
        while True:
            if loop.time() >= deadline:
                raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
            uow = owner.factory.begin_effect_cut(context.scope)
            try:
                uow.__enter__()
                break
            except ApplicationError as exc:
                if exc.code != 'EFFECT_WRITE_BUSY':
                    raise
                await asyncio.sleep(min(.005, max(0, deadline - loop.time())))
        with ExitStack() as stack:
            stack.callback(uow.__exit__, None, None, None)
            _grant_facts(uow, work['work_id'], work['action_id'], binding.step_id,
                         utc_now(), binding=binding)
            owner.approvals._check_gates(uow, decisions)
            row = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, context.scope)
            if (row['binding_bytes'] != encode_dispatch(binding)
                    or row['dispatch_fence'] != binding.fence
                    or row['dispatch_phase'] != 'possibly_written'):
                raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
            from ...usecases.changes.dispatch_continuation import verify_continuation_reservation
            root = verify_continuation_reservation(uow, binding)
            if root is None:
                # Ordinary first attempt: its own consumption is the root.
                uow.authorization.check_action_consumptions(binding.approval_ref,
                    intent_digest=binding.intent_digest, target_digest=binding.digest,
                    action_instances=binding.action_instances)
            # A continuation was already checked against its root consumption by
            # the same verification, inside this original write transaction.
            if loop.time() >= deadline:
                raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
            yield
            uow.commit()


def _agent_contract(owner, context, method_ref, action_id, step_id):
    """Read the actual pinned v2 resource under the original Method guard."""
    from ..owner_capabilities import agent_dispatch_capability
    methods = owner.method_guard
    if getattr(methods, 'factory', None) is not owner.factory:
        raise ApplicationError('DISPATCH_WORK_INPUT_AUTHORITY_UNAVAILABLE')
    descriptor = agent_dispatch_capability()
    with methods.guard(context, method_ref) as declaration:
        action = next((a for a in declaration.actions if a.action_id == action_id), None)
        step = next((s for s in action.steps if s.step_id == step_id), None) if action else None
        if (step is None or step.kind != 'invoke' or step.name != 'implement-approved-package'
                or not any(i.source_kind == 'resource' and i.source_name == 'agent-dispatch-contract'
                           for i in step.inputs)
                or not any(r.resource_id == 'agent-dispatch-contract' for r in action.resources)):
            raise ApplicationError('AGENT_WORK_DISPATCH_CONTRACT_UNAVAILABLE')
        ref = methods.resource_ref(context, method_ref, 'agent-dispatch-contract')
        raw = methods.read_resource(context, ref)
        value = decode_json(raw)
        expected = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': descriptor.contract['input_schema_id'], **descriptor.contract['input_schema'],
            'x-ordessa-capability-binding': {k: getattr(descriptor, k) for k in
                ('capability_id', 'kind', 'interface_version', 'contract_digest')}}
        if value != expected:
            raise ApplicationError('AGENT_WORK_DISPATCH_CONTRACT_MISMATCH')
        return ref


def _agent_task(owner, context, facts, authorization, actions, params):
    _agent_contract(owner, context, facts.work.method_ref,
                    authorization.action_id, authorization.step_id)
    task, outputs = _task(owner, context, facts, authorization, actions)
    # Explicit caller session metadata is checked by the original Agent owner;
    # it never substitutes caller prompt text for the authored Work input.
    if (type(params) is not dict or set(params) != {'sessionId'}
            or type(params['sessionId']) is not str or not params['sessionId']):
        raise ApplicationError('AGENT_WORK_FIXED_SESSION_REQUIRED')
    return {**task, 'sessionId': params['sessionId']}, outputs


def _agent_work_view(owner, row, binding, reason=None):
    value = owner._agent_view(row, binding)
    value['identity'] = value.pop('run_id')
    value['binding_digest'] = asdict(binding.digest)
    value['action_instances'] = list(binding.action_instances)
    value['params_assembly'] = 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_AGENT'
    value['reason'] = reason
    return value


async def dispatch_agent_work(owner, identity, work_id, action_id, step_id, attempt,
                              agent_ref, params, actions, context, *, timeout):
    """Versioned original Work cuts and original Agent reservation/send once."""
    from ....domain.changes.agent_dispatch import AgentWorkDispatchBinding
    from ....domain.changes.agent_dispatch_codec import decode_agent_dispatch, encode_agent_dispatch
    from ....domain.common.models.execution_refs import agent_instance_ref_bytes
    if (identity != work_dispatch_key(work_id, action_id, step_id)
            or type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 60 or type(params) is not dict):
        raise ApplicationError('INVALID_ARGUMENT')
    agent_bytes = agent_instance_ref_bytes(agent_ref)
    # Stored immutable attempt wins before current Grant/source selection. It
    # never allocates another turn, consumes an action, or sends another frame.
    with owner.factory.begin(context.scope, 'read') as uow:
        old = _existing(uow, identity, step_id, attempt)
        if old is not None:
            bound = decode_agent_dispatch(old['binding_bytes'])
            if (type(bound) is not AgentWorkDispatchBinding or bound.work != {
                    'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
                    'dispatch_key': identity} or bound.agent_ref_bytes != agent_bytes
                    or tuple(a for a, _ in bound.action_instances) != actions):
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            grant = uow.authorization.get_grant(bound.approval_ref)
            if type(grant.intent) is not WorkPackageAuthorizationIntent:
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            auth = grant.intent.authorization
            if (bound.intent_digest != grant.intent.digest or auth.scope != bound.scope
                    or auth.package_ref != bound.package_ref
                    or (auth.work_id, auth.action_id, auth.step_id) != (work_id, action_id, step_id)
                    or not set(actions) <= set(auth.actions)
                    or bound.subject != {'subject_kind': 'frozen_package',
                        'subject_ref': package_ref_projection(auth.package_ref)}):
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            frozen = decode_json(uow.implementation.read_blob(bound.prompt_ref))
            if params != {'sessionId': frozen.get('sessionId')}:
                raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
            return _agent_work_view(owner, old, bound, 'ORIGINAL_ATTEMPT_NO_RESEND')
        grant, facts, _ = _grant_facts(uow, work_id, action_id, step_id, context.received_at)
    if (owner.execution is None or owner.blobs is None
            or not all(callable(getattr(owner.execution, n, None)) for n in
                       ('freeze_input', 'prepared_dispatch', 'send', 'capture'))):
        raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
    if not set(actions) <= set(grant.intent.actions):
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    task, results = _agent_task(owner, context, facts, grant.intent.authorization, actions, params)
    raw, prompt_digest = owner.execution.freeze_input(agent_ref, task)
    frozen = decode_json(raw)
    prompt = owner.blobs.put_verified(raw, _digest(raw), 'application/json')
    operation = str(uuid4())
    # No business/method/UoW lock crosses the awaited endpoint resolution. The
    # source owns reservation and abort revocation; no fresh capability is read
    # from a stored receipt, even when its state says reserved.
    preparation_wait = getattr(owner.access, 'guard_agent_preparation_wait', None)
    if not callable(preparation_wait):
        raise ApplicationError('AGENT_PREPARATION_WAIT_AUTHORITY_UNBOUND')
    async with owner.execution.prepared_dispatch(context, agent_ref, frozen,
            request_id=operation, engineering_attempt_ref=operation,
            preparation_wait=lambda:preparation_wait(context)) as flow:
        bound = None
        try:
            with _guards(owner, context, grant, facts, agent_ref, frozen, actions) as decisions:
                with owner.factory.begin(context.scope) as uow:
                    current, current_facts, control = _grant_facts(
                        uow, work_id, action_id, step_id, context.received_at)
                    if current.ref != grant.ref or current_facts != facts:
                        raise ApplicationError('APPROVAL_CONTROL_CHANGED')
                    owner.approvals._check_gates(uow, decisions)
                    if _existing(uow, identity, step_id, attempt) is not None:
                        raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                    instances = tuple((a, str(uuid4())) for a in actions)
                    bound = AgentWorkDispatchBinding(context.scope, identity, step_id, attempt, 1,
                        facts.package.ref, grant.ref, grant.intent.digest, control['version'], instances,
                        agent_bytes, operation, prompt, prompt_digest, flow.prepared.query_digest, results,
                        flow.prepared.turn_ref_bytes,
                        work={'work_id':work_id, 'action_id':action_id,
                              'step_id':step_id, 'dispatch_key':identity},
                        subject={'subject_kind':'frozen_package',
                                 'subject_ref':package_ref_projection(facts.package.ref)})
                    for action, instance in instances:
                        uow.authorization.consume_action(grant.ref, action=action,
                            action_instance_id=instance, target_digest=bound.digest, now=context.received_at)
                    encoded = encode_agent_dispatch(bound)
                    row = uow.work_dispatch.reserve(identity, step_id, attempt, context.scope,
                                                    encoded, _digest(encoded), operation)
                    uow.commit()
            with _guards(owner, context, grant, facts, agent_ref, frozen, actions) as decisions:
                with owner.factory.begin(context.scope) as uow:
                    _grant_facts(uow, work_id, action_id, step_id, context.received_at, binding=bound)
                    owner.approvals._check_gates(uow, decisions)
                    row = uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                        expected_version=0, fence=1, phase='possibly_written')
                    uow.commit()
        except Exception as error:
            if bound is None:
                raise
            diagnosed = _standalone(error, _capture_failure(owner, bound, error, 'pre_send'))
            if diagnosed is error:
                raise
            raise diagnosed from error
        try:
            await owner.execution.send(bound, flow, context, owner, timeout=timeout)
        except Exception as error:
            # Preserve the conservative durable row and debit on failed or
            # cancelled writes. No failure receipt restores send eligibility.
            diagnosed = _standalone(error, _capture_failure(owner, bound, error, 'native_send'))
            if diagnosed is error:
                raise
            raise diagnosed from error
    return reconcile_agent_work(owner, bound, context)


def reconcile_agent_work(owner, binding, context):
    """Original Agent read only, with exact stored Work/subject and CAS."""
    from ....domain.changes.agent_dispatch import AgentWorkDispatchBinding
    from ....domain.changes.agent_dispatch_codec import encode_agent_dispatch
    if type(binding) is not AgentWorkDispatchBinding:
        raise ApplicationError('AGENT_WORK_DISPATCH_BINDING_REQUIRED')
    with owner.factory.begin(context.scope, 'read') as uow:
        row = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, context.scope)
        if (row['binding_bytes'] != encode_agent_dispatch(binding)
                or row['execution_operation_ref'] != binding.engineering_attempt_ref
                or row['dispatch_fence'] != binding.fence):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        _head, work, package_ref = _subject(uow, binding.work['work_id'])
        if (package_ref != binding.package_ref or binding.subject != {
                'subject_kind':'frozen_package','subject_ref':package_ref_projection(package_ref)}):
            raise ApplicationError('DISPATCH_DECLARED_WORK_SUBJECT_MATERIAL_UNAVAILABLE')
        if row['dispatch_phase'] in {'reserved', 'completed', 'failed'}:
            return _agent_work_view(owner, row, binding)
    _agent_contract(owner, context, work.method_ref, binding.work['action_id'], binding.step_id)
    reference, capture = owner.execution.capture(binding)
    if (reference.agent_ref_bytes != binding.agent_ref_bytes
            or reference.turn_ref_bytes != binding.turn_ref_bytes
            or capture.agent_ref_bytes != binding.agent_ref_bytes
            or capture.turn_ref_bytes != binding.turn_ref_bytes
            or capture.engineering_attempt_ref != binding.engineering_attempt_ref
            or reference.engineering_attempt_ref != binding.engineering_attempt_ref
            or capture.operation_ref != reference.operation_ref
            or capture.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
            or capture.query_digest != binding.expected_query_digest):
        raise ApplicationError('DISPATCH_RECEIPT_BINDING_MISMATCH')
    phase = capture.state if capture.state in {'completed', 'failed'} else 'unknown'
    with owner.factory.begin(context.scope) as uow:
        _head, current_work, current_package = _subject(uow, binding.work['work_id'])
        if current_work != work or current_package != binding.package_ref:
            raise ApplicationError('DISPATCH_DECLARED_WORK_SUBJECT_MATERIAL_UNAVAILABLE')
        current = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, context.scope)
        if current['binding_bytes'] != row['binding_bytes'] or current['dispatch_version'] != row['dispatch_version']:
            raise ApplicationError('DISPATCH_CHANGED')
        uow.implementation.read_blob(capture.blob_ref)
        row = uow.work_dispatch.transition(binding.run_id, binding.step_id, binding.attempt,
            context.scope, expected_version=current['dispatch_version'], fence=binding.fence,
            phase=phase, result_blob_ref=capture.blob_ref)
        uow.commit()
    return _agent_work_view(owner, row, binding)


@contextmanager
def acquire_agent_work_effect_cut(owner, context, binding, deadline):
    """Fail-fast synchronous original SQLite cut at the Agent's first frame."""
    import time
    from ...usecases.support.clock import utc_now
    from ....domain.changes.agent_dispatch import AgentWorkDispatchBinding
    from ....domain.changes.agent_dispatch_codec import encode_agent_dispatch
    if type(binding) is not AgentWorkDispatchBinding:
        raise ApplicationError('AGENT_WORK_DISPATCH_BINDING_REQUIRED')
    work = binding.work
    with owner.factory.begin(context.scope, 'read') as read:
        grant, facts, _ = _grant_facts(read, work['work_id'], work['action_id'],
            binding.step_id, utc_now(), binding=binding)
        params = decode_json(read.implementation.read_blob(binding.prompt_ref))
    actions = tuple(a for a, _ in binding.action_instances)
    task, outputs = _agent_task(owner, context, facts, grant.intent.authorization,
                               actions, {'sessionId':params.get('sessionId')})
    if params != task or outputs != binding.required_results:
        raise ApplicationError('DISPATCH_WORK_INPUT_CHANGED')
    agent = decode_json(binding.agent_ref_bytes)
    with _guards(owner, context, grant, facts, agent, params, actions) as decisions:
        if time.monotonic() >= deadline:
            raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
        with owner.factory.begin_effect_cut(context.scope) as uow:
            _grant_facts(uow, work['work_id'], work['action_id'], binding.step_id,
                         utc_now(), binding=binding)
            owner.approvals._check_gates(uow, decisions)
            row = uow.work_dispatch.get(binding.run_id, binding.step_id, binding.attempt, context.scope)
            if (row['binding_bytes'] != encode_agent_dispatch(binding)
                    or row['dispatch_fence'] != binding.fence
                    or row['dispatch_phase'] != 'possibly_written'):
                raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
            # Agent continuations are not authorized by the old Unit proof
            # contract. This first-attempt path consumes its own original debit.
            uow.authorization.check_action_consumptions(binding.approval_ref,
                intent_digest=binding.intent_digest, target_digest=binding.digest,
                action_instances=binding.action_instances)
            if time.monotonic() >= deadline:
                raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
            yield
            uow.commit()

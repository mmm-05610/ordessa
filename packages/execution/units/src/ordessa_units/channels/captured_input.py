"""One captured input through the original fresh Unit and ACP records owner.

The original operation store owns request/capture fences. Original UnitRecords
owns native request/response evidence. A claimed attempt is never re-dispatched,
including the crash window before the ACP record exists. No runtime catalog,
Node adapter, replacement issuer, recovery process, or result store is created.
"""
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
from threading import RLock

from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_agents.harness.transport import EffectWriteGuard, EffectWriteRefused
from .reservations import CapturedInputRef
from .contracts import ManagedInputOutcome
from .captured_contracts import (
    UNIT_INPUT_VERSION, UnitTextCapture, UnitWorkspaceExecutionEvidence,
    UnitCapturedInputRefused, UnitCapturedInputPending)

_ATTEMPTS = 'units.captured-input-attempts'


def _digest(value):
    return 'sha256:' + hashlib.sha256(safe_json(value).encode()).hexdigest()


def _request(request):
    return {'environmentNamespace': request.environment_namespace,
            'principalScope': request.principal_scope, 'requestId': request.request_id}


class ManagedUnitInputs:
    """Explicit selection before Unit creation on an opted-in original owner.

    The owner must have requested deferred effect-write finalization. Binding
    selects trusted source ports; it grants no permission or launches a Unit.
    submit returns a stable acceptance receipt; query reads and publishes the
    original ACP terminal evidence. It never polls or sends a native prompt.
    """
    def __init__(self, owner, *, capture_content, workspace_execution):
        # Select the existing local-owner implementation only for this optional
        # host-bound composition; pure compiler imports need no host owner.
        from ordessa_units.assembly.local_owner import LocalUnitOwner
        if (type(owner) is not LocalUnitOwner or owner.acp_turn_opt_in is not True
                or not callable(getattr(capture_content, 'read_content', None))
                or any(not callable(getattr(workspace_execution, name, None))
                       for name in ('authorize_execute', 'guard_execute'))):
            raise UnitCapturedInputRefused('original capture-content and Workspace execute ports are required')
        self._owner, self._capture, self._workspace = owner, capture_content, workspace_execution
        self._admission = owner.admission
        self._store = owner.admission.store_port
        self.records = owner.records
        self.verifier = self.records.verifier
        self._lock = RLock()
        # Only active source fences live here. Durable recipes and native
        # truth stay in the two original stores. No handles can be recovered.
        self._active = {}
        self._factory = self._write_guard
        owner.bind_effect_write_guard_factory(self._factory)

    def _scope(self, request, authorization):
        if (type(request) is not RequestKey
                or request.environment_namespace != self._admission.environment_namespace
                or request.principal_scope != self._owner.permission.principal_scope):
            raise UnitCapturedInputRefused('captured input request differs from original Unit permission')
        self._admission.check_open()
        with self._owner.authority.guard('interaction', authorization):
            if self._owner.records is not self.records or self.records.verifier is not self.verifier:
                raise UnitCapturedInputRefused('original Unit records or verifier changed')

    def _capture_input(self, ref, unit_ref, principal):
        capture = self._capture.read_content(ref, principal)
        if (type(capture) is not UnitTextCapture or capture.ref != ref
                or safe_json(capture.unit_ref) != safe_json(unit_ref)):
            raise UnitCapturedInputRefused('capture owner did not return the exact Unit capture')
        capture.verify_digest()
        return capture

    def _evidence(self, evidence, request, unit_ref, operation_ref, ref):
        if (type(evidence) is not UnitWorkspaceExecutionEvidence
                or evidence.environment_namespace != request.environment_namespace
                or evidence.principal_scope != request.principal_scope
                or safe_json(evidence.unit_ref) != safe_json(unit_ref)
                or evidence.operation_ref != operation_ref or evidence.capture_ref != ref):
            raise UnitCapturedInputRefused('Workspace execute evidence differs from original Unit input')
        return evidence

    def _operation(self, request, unit_ref=None, captured_ref=None):
        operation = self._store.read_operation(request)
        if operation is None:
            return None
        context = operation.intent.context_ref
        if (operation.intent.kind != 'unit-captured-input'
                or context.get('ownerId') != self._owner.owner_id
                or context.get('permissionId') != self._owner.permission.identity
                or (unit_ref is not None and safe_json(context.get('unitRef')) != safe_json(unit_ref))
                or (captured_ref is not None and context.get('capturedInputRef') != captured_ref.to_dict())):
            raise UnitCapturedInputRefused('request key belongs to another captured Unit input')
        return operation

    def _outcome(self, operation, state='unknown', terminal=False):
        step = self._store.read_operation_step(operation.request, 'prompt')
        receipt = step.evidence.get('acceptedOutcome') if step is not None else None
        if receipt is not None and not terminal:
            return ManagedInputOutcome(**dict(receipt))
        ref = 'unit-acp-turn:' + operation.intent.operation_ref
        return ManagedInputOutcome(UNIT_INPUT_VERSION, operation.intent.operation_ref, state,
            ref + ':receipt' if state != 'unknown' else None,
            ref + ':terminal' if terminal else None)

    def _fence(self, unit_ref, capture):
        fence_id = 'capture-' + _digest({'unitRef': unit_ref, 'captureId': capture.ref.capture_id})[7:]
        prior = self._store.read_domain(self._admission.environment_namespace, _ATTEMPTS, fence_id)
        if prior is not None:
            old = prior['value']
            key = RequestKey(self._admission.environment_namespace, old['principalScope'], old['requestId'])
            operation = self._operation(key, unit_ref)
            if (operation is None or operation.intent.operation_ref != old['operationRef']
                    or operation.intent.context_ref['capturedInputRef']['captureId'] != capture.ref.capture_id
                    or operation.intent.context_ref['capturedInputRef']['captureRevision'] != old['captureRevision']):
                raise UnitCapturedInputRefused('original capture attempt fence is damaged')
            if operation.status != 'published':
                raise UnitCapturedInputPending('capture has an unresolved attempt; inspect its original request')
            if capture.ref.capture_revision <= old['captureRevision']:
                raise UnitCapturedInputRefused('capture revision already has a spent attempt')
        return fence_id, prior

    def submit(self, request, unit, captured_ref, authorization, *, timeout=60):
        self._scope(request, authorization)
        if (type(captured_ref) is not CapturedInputRef
                or captured_ref.environment_namespace != request.environment_namespace):
            raise UnitCapturedInputRefused('complete original captured Unit input reference required')
        instance = self._owner.native_unit(unit, authorization)
        unit_ref = unit.identity
        previous = self._operation(request, unit_ref, captured_ref)
        if previous is not None:
            return self._outcome(previous)
        capture = self._capture_input(captured_ref, unit_ref, request.principal_scope)
        fence_id, prior = self._fence(unit_ref, capture)
        operation_ref = 'unit-input-' + _digest(_request(request))[7:55]
        execution = self._evidence(self._workspace.authorize_execute(
            request, unit_ref, operation_ref, captured_ref), request, unit_ref, operation_ref, captured_ref)
        session = instance.projection.read_session(unit_ref)
        if session is None or session.state != 'confirmed':
            raise UnitCapturedInputRefused('original confirmed ACP Unit session required')
        params = {'sessionId': session.native_facts['sessionId'],
                  'prompt': [{'type': 'text', 'text': capture.envelope['text']}]}
        prompt_digest = self.records.acp_prompt_input_digest(unit_ref, params)
        context = {'environmentNamespace': request.environment_namespace,
            'ownerId': self._owner.owner_id, 'permissionId': self._owner.permission.identity,
            'unitRef': unit_ref, 'capturedInputRef': captured_ref.to_dict(),
            'workspaceExecutionEvidence': execution.to_dict(),
            'promptInputDigest': prompt_digest}
        marker = {'principalScope': request.principal_scope, 'requestId': request.request_id,
                  'operationRef': operation_ref, 'captureRevision': captured_ref.capture_revision}
        operation, claim = self._owner._reserve_captured_input(request, unit, authorization,
            operation_ref=operation_ref, binding=context, fence_id=fence_id,
            fence_revision=prior['revision'] if prior else 0, marker=marker)
        digest = operation.digest
        if not claim.claimed:
            return self._outcome(operation)
        entry = (request, unit, instance, authorization, capture, execution, prompt_digest, params)
        with self._lock:
            self._active[operation_ref] = entry
        try:
            lease = self._owner.authorize('interaction', unit, authorization)
            result = instance.prompt_recorded(unit_ref, lease, operation_ref=operation_ref,
                                              timeout=timeout, **params)
            if result['inputDigest'] != prompt_digest or result['state'] not in ('completed', 'failed'):
                raise UnitCapturedInputRefused('original ACP input receipt is unavailable')
            outcome = self._outcome(operation, 'accepted')
            with self._lock:
                current = self._store.read_operation_step(request, 'prompt')
                self._store.record_operation_step(request, digest, 'prompt', digest,
                    current.revision, 'concluded', {'acceptedOutcome': asdict(outcome),
                    'acpInputDigest': prompt_digest})
            return outcome
        except BaseException:
            with self._lock:
                current = self._store.read_operation_step(request, 'prompt')
                if current is not None and current.outcome == 'possibly-dispatched':
                    self._store.record_operation_step(request, digest, 'prompt', digest,
                        current.revision, 'unknown', {})
            raise
        finally:
            with self._lock:
                self._active.pop(operation_ref, None)

    def _write_guard(self, unit_ref, operation_ref, input_digest, params):
        with self._lock:
            entry = self._active.get(operation_ref)
        if (entry is None or safe_json(entry[1].identity) != safe_json(unit_ref)
                or entry[6] != input_digest or safe_json(entry[7]) != safe_json(params)):
            raise EffectWriteRefused('original captured Unit operation source is unavailable')

        @asynccontextmanager
        async def acquire(identity, deadline):
            request, unit, instance, authorization, capture, execution, _, _ = entry
            with self._owner.authority.guard('interaction', authorization):
                self._scope(request, authorization)
                if self._owner.native_unit(unit, authorization) is not instance:
                    raise UnitCapturedInputRefused('original retained Unit changed before write')
                current = self._capture_input(capture.ref, unit_ref, request.principal_scope)
                if current.canonical_bytes() != capture.canonical_bytes():
                    raise UnitCapturedInputRefused('captured content changed before write')
                with self._lock:
                    operation = self._operation(request, unit_ref, capture.ref)
                    step = self._store.read_operation_step(request, 'prompt')
                    if (self._active.get(operation_ref) is not entry or operation is None
                            or operation.intent.operation_ref != operation_ref
                            or operation.intent.context_ref['promptInputDigest'] != input_digest
                            or step is None or step.outcome != 'possibly-dispatched'):
                        raise EffectWriteRefused('original captured input dispatch claim changed')
                async with self._workspace.guard_execute(execution, identity, deadline) as proof:
                    self._evidence(proof, request, unit_ref, operation_ref, capture.ref)
                    if safe_json(proof.to_dict()) != safe_json(execution.to_dict()):
                        raise UnitCapturedInputRefused('Workspace execute authority changed before write')
                    # Cooperative acquisition may have waited. Recheck time,
                    # owner revocation and the retained Unit at the final cut.
                    self._scope(request, authorization)
                    if self._owner.native_unit(unit, authorization) is not instance:
                        raise UnitCapturedInputRefused('original retained Unit changed during admission')
                    # The capture authority is checked again after cooperative
                    # guard acquisition, immediately before the actual write.
                    if self._capture_input(capture.ref, unit_ref, request.principal_scope) != capture:
                        raise UnitCapturedInputRefused('original immutable capture changed at write')
                    yield
                    # A trusted callback on the SDK thread can reenter a
                    # synchronous host guard. If it revokes during an admitted
                    # write, bytes cannot be undone; preserve UNKNOWN rather
                    # than recording acceptance under that revoked authority.
                    self._scope(request, authorization)
        return EffectWriteGuard(unit_ref, operation_ref, input_digest, params, acquire)

    def query(self, request, authorization):
        """Read the original ACP receipt; no prompt, native lookup or relaunch."""
        self._scope(request, authorization)
        operation = self._operation(request)
        if operation is None:
            raise UnitCapturedInputRefused('original captured Unit operation is unavailable')
        context = operation.intent.context_ref
        query_request = RequestKey(request.environment_namespace, request.principal_scope,
            'unit-input-read-' + _digest(_request(request))[7:55])
        ticket = self._owner.authorize_acp_turn_query(authorization, query_request,
            context['unitRef'], operation.intent.operation_ref,
            expected_prompt_input_digest=context['promptInputDigest'])
        query_digest = self.records.acp_turn_query_digest(context['unitRef'],
            operation.intent.operation_ref, context['promptInputDigest'])
        receipt = self.records.query_acp_turn(context['unitRef'], operation.intent.operation_ref,
            ticket, input_digest=query_digest, expected_prompt_input_digest=context['promptInputDigest'],
            allow_absent=True)
        if receipt is None or receipt['state'] not in ('completed', 'failed'):
            return self._outcome(operation)
        terminal = self._outcome(operation, receipt['state'], terminal=True)
        with self._lock:
            step = self._store.read_operation_step(request, 'prompt')
            if step is None:
                raise UnitCapturedInputRefused('original captured input dispatch claim is missing')
            if step.outcome != 'concluded':
                accepted = self._outcome(operation, 'accepted')
                self._store.record_operation_step(request, operation.digest, 'prompt', operation.digest,
                    step.revision, 'concluded', {'acceptedOutcome': asdict(accepted),
                    'acpInputDigest': context['promptInputDigest']})
            current = self._store.read_operation(request)
            self._store.publish_operation(request, current.digest, current.revision,
                ('prompt',), (), (), asdict(terminal))
            return terminal

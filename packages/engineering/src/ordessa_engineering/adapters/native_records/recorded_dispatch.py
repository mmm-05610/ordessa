"""Narrow consumer over the original UnitInstance/UnitRecords owners.

This adapter adds no Execution store or retry/recovery path. A returned RPC
receipt is an ACP fact only; it says nothing about package correctness.
"""
from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import json
import math
from threading import current_thread
import time

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE

from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ...application.contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from ...application.usecases.changes.execution_capture import capture_execution_observation
from ...domain.changes.dispatch import DispatchBinding
from ...domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ...domain.common.models.values import Digest


_UNIT_FIELDS = {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
_CALLBACK_KEYS = {'on_request', 'before_write', 'on_observation'}
_MAX_PROMPT_BYTES = 589824


def _raise_capacity_error(error):
    # Observation failures may retain the original capacity refusal as a cause.
    # Convert it before an enclosing method guard interprets foreign exceptions
    # as an unavailable authority. This never changes the original journal state.
    seen = set()
    for _ in range(8):
        if error is None or id(error) in seen:
            return
        seen.add(id(error))
        if getattr(error, 'code', None) == 'ACP_EVIDENCE_CAPACITY_EXCEEDED':
            raise ApplicationError('EXECUTION_EVIDENCE_CAPACITY_EXCEEDED') from error
        error = error.__cause__ or error.__context__


def _plain(value, depth=0):
    if depth > 32:
        raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
    raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')


def _reject_callbacks(value):
    if isinstance(value, Mapping):
        if _CALLBACK_KEYS.intersection(value):
            raise ApplicationError('RECORDED_DISPATCH_CALLBACK_FORBIDDEN')
        for item in value.values():
            _reject_callbacks(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_callbacks(item)


def _decode_prompt(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON number')))
        if type(value) is not dict or canonical_bytes(value, profile=LIBRARY_JSON_PROFILE) != raw:
            raise ValueError('prompt JSON is not canonical')
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ApplicationError('RECORDED_DISPATCH_INPUT_NOT_CANONICAL') from exc


def effect_write_timeout(binding):
    """The host-selected effect-write budget from the binding's classification.

    A declared frozen-package Work re-reads the Grant/facts, rebuilds the task
    and re-enters admission/gates/selection/scope inside its effect cut; that
    prefix is measured at ~1.5 s, so this one branch selects the host's bounded
    8 s budget (the transport's existing legal range is (0, 10] s). Acquisition
    and the byte write still share ONE deadline. Every other binding returns
    ``None`` and keeps the transport default; the choice never comes from
    caller text or request params.
    """
    if (type(binding) is DispatchBinding and binding.binding_version == 2
            and type(binding.subject) is dict
            and binding.subject.get('subject_kind') == 'frozen_package'):
        return 8.0
    return None


def failure_diagnostic(binding, error, stage):
    """Bind trusted SDK seam facts to this exact original operation.

    A pure read of the recorded binding and the exception: it opens no store,
    consults no Unit/owner/factory state, and grants no permission. The snapshot
    is accepted only while it still names this binding's operation, input and
    Unit; anything else is reported without the write evidence.
    """
    from ordessa_agents.harness.transport import native_write_failure
    from ...application.contracts.failure_diagnostic import FailureDiagnostic
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    native = native_write_failure(error)
    if native is not None:
        expected_unit = 'sha256:' + hashlib.sha256(
            safe_json(decode_json(binding.unit_ref_bytes)).encode()).hexdigest()
        if (native['operation_ref'] != binding.execution_operation_ref
                or native['input_digest'] != 'sha256:' + binding.prompt_input_digest.hex
                or native['unit_ref_digest'] != expected_unit):
            return FailureDiagnostic.capture(error, stage).with_recording_failure(
                ApplicationError('NATIVE_WRITE_BOUNDARY_BINDING_MISMATCH'))
    return FailureDiagnostic.capture(error, stage, native_write=native)


class RecordedDispatchExecution:
    """Use original Records authorization and original UnitInstance write lease."""

    def __init__(self, records, unit_instance, authorized_lease, blobs, query_factory=None, *, effect_write_guard_factory=None):
        if (records is None or blobs is None
                or unit_instance is not None and getattr(unit_instance, 'records', None) is not records
                or not callable(getattr(records, 'acp_prompt_input_digest', None))
                or not callable(getattr(records, 'acp_turn_query_digest', None))
                or not callable(getattr(records, 'query_acp_turn', None))
                or not callable(getattr(records, 'validate_acp_prompt_capacity', None))
                or type(getattr(records, 'acp_turn_evidence_max_bytes', None)) is not int
                or not 0 < records.acp_turn_evidence_max_bytes <= MAX_EXECUTION_RECEIPT_BYTES
                or unit_instance is not None and not callable(getattr(unit_instance, 'prompt', None))
                or not callable(getattr(blobs, 'read_verified', None))
                or not callable(getattr(blobs, 'put_verified', None))):
            raise ApplicationError('RECORDED_DISPATCH_ORIGINAL_OWNER_REQUIRED')
        if query_factory is not None and not callable(query_factory):
            raise ApplicationError('RECORDED_DISPATCH_QUERY_AUTHORITY_REQUIRED')
        self.records = records
        self.unit_instance = unit_instance
        self.authorized_lease = authorized_lease
        self.blobs = blobs
        self.query_factory = query_factory
        self.effect_write_guard_factory = effect_write_guard_factory

    def _session_id(self, unit_ref):
        try:
            view = self.unit_instance.projection.read_session(unit_ref)
            native_facts = view.native_facts
            session_id = native_facts['sessionId']
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_FIXED_SESSION_UNAVAILABLE') from exc
        if type(session_id) is not str or not session_id or any(ord(c) < 32 for c in session_id):
            raise ApplicationError('RECORDED_DISPATCH_FIXED_SESSION_UNAVAILABLE')
        return session_id

    @staticmethod
    def _unit_ref(unit_ref):
        if not isinstance(unit_ref, Mapping) or set(unit_ref) != _UNIT_FIELDS:
            raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID')
        try:
            value = _plain(unit_ref)
            encoded = canonical_bytes(value, profile=LIBRARY_JSON_PROFILE)
            if len(encoded) > 4096:
                raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_TOO_LARGE')
            if not isinstance(value['ownerProviderRef'], dict):
                raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID')
            for key in ('environmentNamespace','unitId','sourceRevision'):
                item=value[key]
                if type(item) is not str or not item or len(item)>512 or any(ord(char)<32 for char in item):
                    raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID')
            return value, encoded
        except ApplicationError:
            raise
        except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
            raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID') from exc

    def _require_effect_owner(self):
        require = getattr(self.unit_instance, 'require_effect_write_guard', None)
        if self.effect_write_guard_factory is None or not callable(require):
            raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
        require(self.effect_write_guard_factory)

    def freeze_input(self, unit_ref, params):
        """Freeze exact JSON ACP params with the original fixed Run session."""
        self._require_effect_owner()  # Before the caller reserves any action budget.
        unit, _ = self._unit_ref(unit_ref)
        if not isinstance(params, Mapping):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        try:
            frozen = _plain(params)
            _reject_callbacks(frozen)
            session_id = self._session_id(unit)
            if frozen.get('sessionId', session_id) != session_id:
                raise ApplicationError('RECORDED_DISPATCH_SESSION_MISMATCH')
            frozen['sessionId'] = session_id
            raw = canonical_bytes(frozen, profile=LIBRARY_JSON_PROFILE)
            if len(raw) > _MAX_PROMPT_BYTES:
                raise ApplicationError('RECORDED_DISPATCH_INPUT_TOO_LARGE')
            self.records.validate_acp_prompt_capacity(unit, frozen)
            native_digest = self.records.acp_prompt_input_digest(unit, frozen)
        except ApplicationError:
            raise
        except Exception as exc:
            _raise_capacity_error(exc)
            if not isinstance(exc, (TypeError, ValueError, UnicodeError, OverflowError, RecursionError)):
                raise
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID') from exc
        if (type(native_digest) is not str or not native_digest.startswith('sha256:')
                or len(native_digest) != 71 or any(c not in '0123456789abcdef' for c in native_digest[7:])):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID')
        return raw, Digest('sha256', native_digest[7:])

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        """Compute the exact original UnitRecords query identity."""
        unit, _ = self._unit_ref(unit_ref)
        if type(prompt_digest) is not Digest:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID')
        expected = self.records.acp_turn_query_digest(
            unit, operation_ref, 'sha256:' + prompt_digest.hex)
        if type(expected) is not str or not expected.startswith('sha256:') or len(expected) != 71:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_INVALID')
        try:
            Digest('sha256', expected[7:])
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_INVALID') from exc
        return expected

    def _binding_values(self, binding, *, live_session=True):
        if type(binding) is not DispatchBinding:
            raise ApplicationError('RECORDED_DISPATCH_BINDING_REQUIRED')
        try:
            # The domain codec owns the closed v1/v2 field sets and recomputes
            # each version's digest during decode. Round-tripping its canonical
            # bytes preserves the historical v1 identity while accepting only
            # a complete, untampered v2 Work binding.
            encoded_binding = encode_dispatch(binding)
            verified_binding = decode_dispatch(encoded_binding)
            if verified_binding != binding:
                raise ValueError('dispatch binding round-trip changed identity')
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_BINDING_TAMPERED') from exc
        try:
            if type(binding.unit_ref_bytes) is not bytes or len(binding.unit_ref_bytes) > 4096:
                raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID')
            unit, canonical_unit = self._unit_ref(decode_json(binding.unit_ref_bytes))
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID') from exc
        if canonical_unit != binding.unit_ref_bytes:
            raise ApplicationError('RECORDED_DISPATCH_UNIT_REF_INVALID')
        if type(binding.prompt_input_digest) is not Digest:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID')
        expected_input = 'sha256:' + binding.prompt_input_digest.hex
        expected_query = self.records.acp_turn_query_digest(unit, binding.execution_operation_ref, expected_input)
        if type(expected_query) is not str or expected_query != binding.expected_query_digest:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_MISMATCH')
        if binding.prompt_ref.media_type != 'application/json':
            raise ApplicationError('RECORDED_DISPATCH_INPUT_MEDIA_TYPE_INVALID')
        try:
            raw = self.blobs.read_verified(binding.prompt_ref)
            if type(raw) is not bytes or len(raw) > _MAX_PROMPT_BYTES:
                raise ApplicationError('RECORDED_DISPATCH_INPUT_TOO_LARGE')
            params = _decode_prompt(raw)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_BLOB_UNAVAILABLE') from exc
        _reject_callbacks(params)
        session_id = self._session_id(unit) if live_session else params.get('sessionId')
        if type(session_id) is not str or not session_id or params.get('sessionId') != session_id:
            raise ApplicationError('RECORDED_DISPATCH_SESSION_MISMATCH')
        if live_session:
            try:
                self.records.validate_acp_prompt_capacity(unit, params)
            except Exception as exc:
                _raise_capacity_error(exc)
                raise
        actual = self.records.acp_prompt_input_digest(unit, params)
        if actual != expected_input:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_MISMATCH')
        if getattr(self.blobs, 'authority_id', None) is None:
            raise ApplicationError('RECORDED_DISPATCH_BLOB_AUTHORITY_REQUIRED')
        return unit, params, expected_input

    def send(self, binding, timeout=60):
        """Make one original-owner call; return its native receipt without interpretation."""
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ApplicationError('RECORDED_DISPATCH_TIMEOUT_INVALID')
        if self.unit_instance is None or self.authorized_lease is None:
            raise ApplicationError('RECORDED_DISPATCH_ORIGINAL_WRITER_REQUIRED')
        unit, params, _ = self._binding_values(binding)
        self._require_effect_owner()  # Original owner identity check, before reserve/write.
        try:
            return self.unit_instance.prompt(unit, self.authorized_lease,
                operation_ref=binding.execution_operation_ref, timeout=timeout, **params)
        except Exception as exc:
            # Original UnitRecords owns reserved/possibly-written/unknown
            # semantics. Never retry or create a parallel attempt here.
            _raise_capacity_error(exc)
            raise

    def failure_diagnostic(self, binding, error, stage):
        """Same bounded facts as the module extractor; kept for existing callers."""
        return failure_diagnostic(binding, error, stage)

    @contextmanager
    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        """Suspend the caller admission only across the original SDK send wait."""
        if self.unit_instance is None or self.authorized_lease is None:
            raise ApplicationError('RECORDED_DISPATCH_ORIGINAL_WRITER_REQUIRED')
        self._require_effect_owner()
        factory=self.effect_write_guard_factory
        guard=getattr(factory,'guard_effect_handoff',None)
        if not callable(guard):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_AUTHORITY_UNAVAILABLE')
        try:
            target=self.unit_instance.effect_write_thread
        except Exception as exc:
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_TARGET_UNAVAILABLE') from exc
        with guard(context,binding,access=access,timeout=timeout,target_thread=target):
            yield

    def capture(self, binding):
        """Cold-read through original UnitRecords authorization and capture its full receipt."""
        if self.query_factory is None:
            raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        unit, _, expected_prompt = self._binding_values(binding,live_session=False)
        invocation = self.query_factory(binding)
        if invocation is None:
            raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        return capture_execution_observation(self.records, self.blobs,
            authority_id=self.blobs.authority_id, unit_ref=unit,
            operation_ref=binding.execution_operation_ref,
            expected_prompt_digest=expected_prompt, query_invocation=invocation,
            max_receipt_bytes=self.records.acp_turn_evidence_max_bytes)


class _EngineeringEffectWriteGuardFactory:
    """Fixed per-request bridge for one exact handoff token and Unit binding."""

    def __init__(self, dispatch_owner, context, records, blobs, *, generation_dispatch=None):
        from threading import Lock
        if generation_dispatch is not None and (
                getattr(generation_dispatch, 'blobs', None) is not blobs
                or getattr(generation_dispatch, 'factory', None) is None
                or getattr(generation_dispatch.factory, 'authority_id', None) != getattr(blobs, 'authority_id', None)
                or not callable(getattr(generation_dispatch, '_access', None))
                or not callable(getattr(generation_dispatch, 'acquire_effect_write', None))
                or getattr(generation_dispatch, 'access', None) is None
                or not callable(getattr(generation_dispatch.access, 'handoff_effect_write', None))
                or not callable(getattr(generation_dispatch.access, 'consume_effect_write', None))
                or getattr(getattr(generation_dispatch, 'execution', None), 'records', None) is not records
                or (dispatch_owner is not None
                    and getattr(generation_dispatch, 'factory', None)
                        is not getattr(dispatch_owner, 'factory', None))):
            raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
        if (dispatch_owner is not None and (getattr(dispatch_owner,'blobs',None) is not blobs
                or getattr(dispatch_owner,'factory',None) is None
                or getattr(blobs,'authority_id',None)!=dispatch_owner.factory.authority_id
                or not callable(getattr(dispatch_owner,'acquire_effect_write',None))
                or getattr(dispatch_owner,'access',None) is None)):
            raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
        self.dispatch_owner=dispatch_owner
        self.generation_dispatch=generation_dispatch
        # Keep the constructor shape for trusted composition compatibility,
        # but never retain this one request's context. The live call context
        # is supplied and authenticated for each handoff below.
        self.records=records
        self.blobs=blobs
        self._send_lock=Lock()
        self._slot_lock=Lock()
        self._slot=None

    @contextmanager
    def guard_effect_handoff(self, context, binding, *, access, timeout, target_thread):
        from threading import Thread
        from ...application.contracts.commands import CommandContext
        from ...domain.changes.dispatch_codec import encode_dispatch
        if type(context) is not CommandContext or type(binding) is not DispatchBinding:
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        generation = (binding.subject is not None
                      and binding.subject.get('subject_kind') == 'reviewed_change')
        owner = self.generation_dispatch if generation else self.dispatch_owner
        if (owner is None or access is not owner.access
                or binding.scope!=context.scope
                or not isinstance(target_thread,Thread)
                or type(timeout) not in (int,float) or not math.isfinite(timeout)
                or timeout <= 0):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        if not self._send_lock.acquire(blocking=False):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BUSY')
        try:
            # Prepare and verify the immutable original dispatch before
            # suspending the caller's authority. Nothing below the handoff
            # factory callback opens a second Engineering transaction.
            owner._access(context, EXECUTION_DISPATCH)
            with owner.factory.begin(context.scope,'read') as uow:
                row=(uow.work_dispatch.get(binding.run_id,binding.step_id,binding.attempt,binding.scope)
                     if binding.work is not None else
                     uow.dispatch.get(binding.run_id,binding.step_id,binding.attempt,binding.scope))
                if (row['binding_bytes']!=encode_dispatch(binding)
                        or row['dispatch_phase']!='possibly_written'
                        or row['dispatch_fence']!=binding.fence):
                    raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
            deadline=time.monotonic()+min(float(timeout),60.0)
            with access.handoff_effect_write(context,
                    invocation_key=bytes.fromhex(binding.digest.hex),
                    action_instances=binding.action_instances,
                    target_thread=target_thread,expires_at=deadline) as handoff:
                slot=(context,binding,handoff,current_thread(),owner)
                with self._slot_lock:
                    if self._slot is not None:
                        raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BUSY')
                    self._slot=slot
                try:
                    yield
                finally:
                    with self._slot_lock:
                        if self._slot is slot:
                            self._slot=None
        finally:
            self._send_lock.release()

    def __call__(self, unit_ref, operation_ref, input_digest, params):
        """Validate the fixed binding during the original caller-side prep callback."""
        from ordessa_units.public import EffectWriteGuard
        with self._slot_lock:
            slot=self._slot
        if slot is None:
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_UNAVAILABLE')
        context,binding,handoff,caller_thread,owner=slot
        if current_thread() is not caller_thread:
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_CALLER_MISMATCH')
        unit=_plain(unit_ref);fixed=_plain(params)
        if (binding.unit_ref_bytes!=canonical_bytes(unit,profile=LIBRARY_JSON_PROFILE)
                or operation_ref!=binding.execution_operation_ref
                or input_digest!='sha256:'+binding.prompt_input_digest.hex
                or self.records.acp_prompt_input_digest(unit,fixed)!=input_digest
                or binding.prompt_ref.media_type!='application/json'
                or self.blobs.read_verified(binding.prompt_ref)!=canonical_bytes(fixed,profile=LIBRARY_JSON_PROFILE)):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        def acquire(identity,deadline):
            return owner.acquire_effect_write(
                context,binding,identity,deadline,handoff=handoff)
        timeout = effect_write_timeout(binding)
        if timeout is None:
            return EffectWriteGuard(unit,operation_ref,input_digest,fixed,acquire)
        return EffectWriteGuard(unit,operation_ref,input_digest,fixed,acquire,
                                timeout=timeout)


def engineering_effect_write_guard_factory(dispatch_owner, context, records, blobs, *, generation_dispatch=None):
    """Build the Unit hook from the canonical owner or its original dispatcher.

    With the canonical ``EngineeringOwnerOperations`` return, this adapter
    validates and unwraps its original dispatcher so composition callers need
    not reach through ``owner_operations.dispatch``. Existing callers that
    already hold the exact ``ImplementationDispatch`` remain on that same
    original mechanism. A malformed canonical owner is always rejected; it is
    never retried as a raw dispatcher. No authority, grant, action consumption,
    journal, callback, or retry path is created.
    """
    from ...application.orchestration.steps.implementation_dispatch import ImplementationDispatch
    from ...application.usecases.owner_operations import EngineeringOwnerOperations

    if dispatch_owner is None and generation_dispatch is not None:
        dispatch = None
    elif type(dispatch_owner) is EngineeringOwnerOperations:
        dispatch = getattr(dispatch_owner, 'dispatch', None)
        execution = getattr(dispatch, 'execution', None)
        factory = getattr(dispatch_owner, 'factory', None)
        access = getattr(dispatch_owner, 'access', None)
        if (type(dispatch) is not ImplementationDispatch
                or factory is None or getattr(dispatch, 'factory', None) is not factory
                or access is None or getattr(dispatch, 'access', None) is not access
                or getattr(dispatch_owner, 'records', None) is not records
                or getattr(execution, 'records', None) is not records
                or getattr(dispatch_owner, 'blobs', None) is not blobs
                or getattr(dispatch, 'blobs', None) is not blobs
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
                or not callable(getattr(dispatch, '_access', None))
                or not callable(getattr(dispatch, 'acquire_effect_write', None))
                or not callable(getattr(access, 'handoff_effect_write', None))
                or not callable(getattr(access, 'consume_effect_write', None))):
            raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
    elif type(dispatch_owner) is ImplementationDispatch:
        # Exact original-owner route retained for established callers. This is
        # not fallback for a failed canonical owner association check above.
        dispatch = dispatch_owner
    else:
        raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
    factory = getattr(dispatch, 'factory', None)
    access = getattr(dispatch, 'access', None)
    if dispatch is not None and (factory is None or access is None
            or getattr(dispatch, 'blobs', None) is not blobs
            or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
            or not callable(getattr(dispatch, '_access', None))
            or not callable(getattr(dispatch, 'acquire_effect_write', None))):
        raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
    return _EngineeringEffectWriteGuardFactory(dispatch, context, records, blobs,
                                               generation_dispatch=generation_dispatch)


class NativeDispatchSources:
    """Explicit timed-live and cold-read adapter over original UnitServices.

    binding_resolver belongs to trusted Product configuration. It returns the
    full original ProfileRevisionRef, DirectoryBindingRef, authorized query
    invocation and its input digest for this exact package/Unit. A wire label or
    copied grant is never a resolver. UnitServices repeats actual owner checks.
    """
    def __init__(self, services, binding_resolver, *, dispatch_input_guard=None):
        from ordessa_units.public import UnitServices
        if type(services) is not UnitServices or not callable(binding_resolver):
            raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
        self.services=services
        self.resolver=binding_resolver
        if dispatch_input_guard is not None and not callable(dispatch_input_guard):
            raise ApplicationError('DISPATCH_METHOD_INPUT_SOURCE_UNAVAILABLE')
        self.dispatch_input_guard=dispatch_input_guard

    @contextmanager
    def guard_dispatch_input(self,context,package,unit_ref,recipe):
        if self.dispatch_input_guard is None:
            raise ApplicationError('DISPATCH_METHOD_INPUT_SOURCE_UNAVAILABLE')
        with self.dispatch_input_guard(context,package,unit_ref,recipe):
            yield

    def _resolve(self,context,package,unit_ref):
        from ordessa_agents.profiles import ProfileRevisionRef
        from ordessa_units.bindings.contracts import DirectoryBindingRef
        profile,directory,invocation,digest=self.resolver(context,package,unit_ref)
        expected=package.payload.execution_profile_ref
        if (type(profile) is not ProfileRevisionRef or type(directory) is not DirectoryBindingRef
                or profile.environment_namespace!=expected.environment_id
                or profile.environment_namespace!=unit_ref['environmentNamespace']
                or profile.profile_id!=expected.profile_id
                or profile.digest!='sha256:'+expected.profile_digest.hex
                or directory.environment_namespace!=profile.environment_namespace):
            raise ApplicationError('DISPATCH_SOURCE_PROFILE_MISMATCH')
        return profile,directory,invocation,digest

    @contextmanager
    def guard_commit_snapshot(self,context,package,unit_ref):
        profile,directory,invocation,digest=self._resolve(context,package,unit_ref)
        # Original owner locks are intentionally released by this timed reader.
        # No external-COMMIT or checkout-isolation guarantee is substituted.
        snapshot=self.services.snapshot_live_unit_selection(unit_ref,
            expected_profile_revision=profile,expected_directory_binding_ref=directory,
            query_invocation=invocation,query_input_digest=digest)
        yield snapshot

    @contextmanager
    def guard_history_read(self,context,package,unit_ref):
        profile,_,invocation,digest=self._resolve(context,package,unit_ref)
        with self.services.guard_unit_selection(unit_ref,expected_profile_revision=profile,
                query_invocation=invocation,query_input_digest=digest,require_live=False) as receipt:
            yield receipt


__all__ = ['RecordedDispatchExecution', 'engineering_effect_write_guard_factory', 'NativeDispatchSources']


# ------------------------------------------------------- continuation evidence

class NativeContinuationEvidenceReader:
    """Read one origin attempt's affirmative pre-write evidence, read-only.

    This is the C-segment adapter over the original owners: the Engineering UoW
    row, the original UnitRecords ACP turn and the owner-read stop/release
    records, plus the Blob authority for the linked failure diagnostic. It
    returns evidence, never authority: no Grant, consumption, journal write or
    Unit selection happens here, and the caller cannot supply a root binding to
    inherit someone else's consumption.

    Refusals are explicit. An owner that cannot produce a verifiable
    termination proof, a diagnostic that does not prove the frame stayed before
    ``write_stdin``, or an ACP state that is not the unconfirmed one all raise
    instead of returning an optimistic record. Empty events, an operator JSON
    or a boolean "closed" claim are never accepted as proof.
    """

    def __init__(self, factory, records, blobs, query_factory):
        if (factory is None or records is None or blobs is None
                or not callable(query_factory)
                or not callable(getattr(records, 'query_acp_turn', None))
                or not callable(getattr(records, 'acp_turn_query_digest', None))
                or not callable(getattr(records, 'owner_read_termination', None))):
            raise ApplicationError('CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE')
        # The row and every blob this reader verifies must come from ONE
        # authority; a factory from another library would let a row and a
        # diagnostic be read across two graphs.
        if (getattr(factory, 'authority_id', None) is None
                or getattr(factory, 'authority_id', None) != getattr(blobs, 'authority_id', None)):
            raise ApplicationError('CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE')
        self.factory, self.records, self.blobs = factory, records, blobs
        self.query = query_factory

    def _row(self, context, origin):
        from ...application.contracts.commands import CommandContext
        from ...domain.changes.dispatch import DispatchOriginRef
        if type(context) is not CommandContext or type(origin) is not DispatchOriginRef:
            raise ApplicationError('CONTINUATION_ORIGIN_UNAVAILABLE')
        if ((context.scope.realm_id, context.scope.project_id)
                != (origin.scope.realm_id, origin.scope.project_id)):
            raise ApplicationError('CONTINUATION_ORIGIN_UNAVAILABLE')
        try:
            with self.factory.begin(context.scope, 'read') as uow:
                return uow.work_dispatch.get(origin.dispatch_key, origin.step_id,
                                             origin.attempt, context.scope)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('CONTINUATION_ORIGIN_UNAVAILABLE') from exc

    @staticmethod
    def _identity(row, origin):
        digest = hashlib.sha256(row['binding_bytes']).hexdigest()
        if (digest != origin.binding_bytes_digest.hex
                or row['execution_operation_ref'] != origin.execution_operation_ref):
            raise ApplicationError('CONTINUATION_ORIGIN_IDENTITY_MISMATCH')
        binding = decode_dispatch(row['binding_bytes'])
        if binding.digest != origin.binding_record_digest:
            # The bytes digest and the record digest are different facts; a
            # continuation may not swap one for the other.
            raise ApplicationError('CONTINUATION_ORIGIN_IDENTITY_MISMATCH')
        if row['dispatch_phase'] != 'unknown':
            raise ApplicationError('CONTINUATION_ORIGIN_NOT_PREWRITE')
        if row['dispatch_version'] != origin.expected_dispatch_version:
            raise ApplicationError('CONTINUATION_ORIGIN_IDENTITY_MISMATCH')
        if ((binding.scope.realm_id, binding.scope.project_id)
                != (origin.scope.realm_id, origin.scope.project_id)
                or binding.run_id != origin.dispatch_key
                or binding.step_id != origin.step_id
                or binding.attempt != origin.attempt
                or binding.execution_operation_ref != origin.execution_operation_ref):
            # The stored binding must name exactly the attempt the origin
            # reference pins: scope, dispatch key, step, attempt, operation.
            raise ApplicationError('CONTINUATION_ORIGIN_IDENTITY_MISMATCH')
        if (binding.binding_version != 2 or type(binding.subject) is not dict
                or binding.subject.get('subject_kind') != 'frozen_package'):
            # Only a frozen-package Work attempt is eligible; the value layer
            # never widens this by itself.
            raise ApplicationError('CONTINUATION_BINDING_NOT_ELIGIBLE')
        return binding

    def _diagnostic(self, row, binding):
        from ordessa_infrastructure.encoding.immutable_json import safe_json
        from ...domain.common.mechanisms.codec import decode_blob_ref
        from ...application.contracts.failure_diagnostic import (
            FAILURE_MEDIA_TYPE, FailureDiagnostic)
        if row.get('result_blob_json') is None:
            raise ApplicationError('CONTINUATION_DIAGNOSTIC_UNAVAILABLE')
        try:
            reference = decode_blob_ref(decode_json(row['result_blob_json']))
        except Exception as exc:
            raise ApplicationError('CONTINUATION_DIAGNOSTIC_UNAVAILABLE') from exc
        if reference.media_type != FAILURE_MEDIA_TYPE:
            raise ApplicationError('CONTINUATION_DIAGNOSTIC_UNAVAILABLE')
        try:
            raw = self.blobs.read_verified(reference)
            value = FailureDiagnostic.from_record(decode_json(raw)).to_dict()
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('CONTINUATION_DIAGNOSTIC_UNAVAILABLE') from exc
        native = value.get('native_write')
        expected_unit_digest = 'sha256:' + hashlib.sha256(
            safe_json(decode_json(binding.unit_ref_bytes)).encode()).hexdigest()
        if (type(native) is not dict
                or native.get('phase') != 'effect_guard_acquire'
                or native.get('before_write') != 'not_entered'
                or native.get('write_stdin') != 'not_entered'
                or native.get('acknowledged_bytes') is not None
                or native.get('operation_ref') != binding.execution_operation_ref
                or native.get('input_digest') != 'sha256:' + binding.prompt_input_digest.hex
                or native.get('unit_ref_digest') != expected_unit_digest):
            raise ApplicationError('CONTINUATION_ORIGIN_NOT_PREWRITE')
        if value.get('recording_failure') is not None:
            # A diagnostic that could not be fully recorded cannot prove the
            # frame stayed before the write.
            raise ApplicationError('CONTINUATION_DIAGNOSTIC_INCOMPLETE')
        return value

    def _observation(self, binding, origin):
        from ...application.contracts.execution_observations import ExecutionObservationRef
        unit = decode_json(binding.unit_ref_bytes)
        expected_prompt = 'sha256:' + binding.prompt_input_digest.hex
        invocation = self.query(binding)
        if invocation is None:
            raise ApplicationError('CONTINUATION_OBSERVATION_UNAVAILABLE')
        try:
            observation = capture_execution_observation(
                self.records, self.blobs, authority_id=self.blobs.authority_id,
                unit_ref=unit, operation_ref=binding.execution_operation_ref,
                expected_prompt_digest=expected_prompt, query_invocation=invocation,
                max_receipt_bytes=self.records.acp_turn_evidence_max_bytes)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('CONTINUATION_OBSERVATION_UNAVAILABLE') from exc
        if (type(observation) is not ExecutionObservationRef
                or observation.state != 'unknown'
                or observation.operation_ref != binding.execution_operation_ref
                or observation.unit_ref != unit
                or observation.revision != origin.expected_acp_revision
                or observation.query_digest != binding.expected_query_digest):
            raise ApplicationError('CONTINUATION_OBSERVATION_UNAVAILABLE')
        try:
            receipt = decode_json(self.blobs.read_verified(observation.blob_ref))
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('CONTINUATION_OBSERVATION_UNAVAILABLE') from exc
        if (not isinstance(receipt, Mapping)
                or receipt.get('state') != 'unknown'
                or receipt.get('revision') != origin.expected_acp_revision
                or receipt.get('request') is not None
                or receipt.get('response') is not None
                or receipt.get('events') != []):
            # The captured receipt must contradict a delivered frame: no
            # request, no response and no events. This check only carries weight
            # together with the affirmative pre-write diagnostic; empty events
            # alone never qualify an attempt.
            raise ApplicationError('CONTINUATION_OBSERVATION_UNAVAILABLE')
        return observation

    def _termination(self, binding, action):
        contract_version, projection = 'harness-unit-termination/1', 'owner-read'
        unit = decode_json(binding.unit_ref_bytes)
        try:
            record = self.records.owner_read_termination(unit['unitId'], action)
        except Exception as exc:
            # Owner refusal (including a fenced historical Unit) is an explicit
            # unavailability; no proof is synthesised from process state.
            raise ApplicationError('CONTINUATION_TERMINATION_UNAVAILABLE') from exc
        if (not isinstance(record, Mapping)
                or set(record) != {'version', 'projection', 'action', 'state',
                                   'sourceRevision', 'identity', 'outcome'}
                or record.get('version') != contract_version
                or record.get('projection') != projection
                or record.get('action') != action
                or record.get('state') != 'confirmed'
                or type(record.get('sourceRevision')) is not int
                or record.get('sourceRevision') < 1):
            # The owner-read record has one closed shape; an older or invented
            # version is refused rather than read as proof.
            raise ApplicationError('CONTINUATION_TERMINATION_UNAVAILABLE')
        outcome = record.get('outcome')
        if (not isinstance(outcome, Mapping) or not outcome
                or any(type(key) is not str or not key or type(value) is not str or not value
                       for key, value in outcome.items())):
            raise ApplicationError('CONTINUATION_TERMINATION_UNAVAILABLE')
        identity = record.get('identity')
        unit_ref = identity.get('unitRef') if isinstance(identity, Mapping) else None
        if not isinstance(unit_ref, Mapping) or dict(unit_ref) != unit:
            raise ApplicationError('CONTINUATION_TERMINATION_UNAVAILABLE')
        return dict(record)

    def read_origin(self, context, origin):
        """Return only the original owners' own evidence for this exact attempt."""
        from ...application.contracts.execution_observations import OriginPrewriteEvidence
        row = self._row(context, origin)
        binding = self._identity(row, origin)
        self._diagnostic(row, binding)
        observation = self._observation(binding, origin)
        stop = self._termination(binding, 'stop')
        release = self._termination(binding, 'release')
        return OriginPrewriteEvidence(acp_observation=observation,
                                     stop_record=stop, release_record=release)

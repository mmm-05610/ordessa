"""Narrow consumer over the original UnitInstance/UnitRecords owners.

This adapter adds no Execution store or retry/recovery path. A returned RPC
receipt is an ACP fact only; it says nothing about package correctness.
"""
from collections.abc import Mapping
from contextlib import contextmanager
import json
import math

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE

from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ...application.usecases.changes.execution_capture import capture_execution_observation
from ...domain.changes.dispatch import DispatchBinding
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.common.models.values import Digest


_UNIT_FIELDS = {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
_CALLBACK_KEYS = {'on_request', 'before_write', 'on_observation'}
_MAX_PROMPT_BYTES = 262144


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


class RecordedDispatchExecution:
    """Use original Records authorization and original UnitInstance write lease."""

    def __init__(self, records, unit_instance, authorized_lease, blobs, query_factory=None, *, effect_write_guard_factory=None):
        if (records is None or blobs is None
                or unit_instance is not None and getattr(unit_instance, 'records', None) is not records
                or not callable(getattr(records, 'acp_prompt_input_digest', None))
                or not callable(getattr(records, 'acp_turn_query_digest', None))
                or not callable(getattr(records, 'query_acp_turn', None))
                or unit_instance is not None and not callable(getattr(unit_instance, 'prompt_recorded', None))
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
            native_digest = self.records.acp_prompt_input_digest(unit, frozen)
        except ApplicationError:
            raise
        except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
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
        if binding.digest != record_digest('implementation-dispatch-binding-v1',binding.projection()):
            raise ApplicationError('RECORDED_DISPATCH_BINDING_TAMPERED')
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
            return self.unit_instance.prompt_recorded(unit, self.authorized_lease,
                operation_ref=binding.execution_operation_ref, timeout=timeout, **params)
        except Exception:
            # Original UnitRecords owns reserved/possibly-written/unknown
            # semantics. Never retry or create a parallel attempt here.
            raise

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
            expected_prompt_digest=expected_prompt, query_invocation=invocation)


def engineering_effect_write_guard_factory(dispatch_owner, context, records, blobs):
    """Trusted Unit composition hook; wire cannot choose an operation or guard.

    This resolves only an existing original Engineering step binding. No Grant,
    action consumption, Unit journal, callback or retry authority is created.
    """
    if (getattr(dispatch_owner,'blobs',None) is not blobs
            or getattr(dispatch_owner,'factory',None) is None
            or getattr(blobs,'authority_id',None)!=dispatch_owner.factory.authority_id
            or not callable(getattr(dispatch_owner,'acquire_effect_write',None))):
        raise ApplicationError('RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED')
    from ordessa_units.public import EffectWriteGuard
    def factory(unit_ref, operation_ref, input_digest, params):
        dispatch_owner._access(context, EXECUTION_DISPATCH)
        with dispatch_owner.factory.begin(context.scope,'read') as uow:
            row=uow.dispatch.by_operation(operation_ref,context.scope)
            from ...domain.changes.dispatch_codec import decode_dispatch
            binding=decode_dispatch(row['binding_bytes'])
        unit=_plain(unit_ref);fixed=_plain(params)
        if (row['dispatch_phase']!='possibly_written'
                or binding.unit_ref_bytes!=canonical_bytes(unit,profile=LIBRARY_JSON_PROFILE)
                or input_digest!='sha256:'+binding.prompt_input_digest.hex
                or records.acp_prompt_input_digest(unit,fixed)!=input_digest
                or blobs.read_verified(binding.prompt_ref)!=canonical_bytes(fixed,profile=LIBRARY_JSON_PROFILE)):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        def acquire(identity,deadline):
            return dispatch_owner.acquire_effect_write(context,binding,identity,deadline)
        return EffectWriteGuard(unit,operation_ref,input_digest,fixed,acquire)
    return factory


class NativeDispatchSources:
    """Explicit timed-live and cold-read adapter over original UnitServices.

    binding_resolver belongs to trusted Product configuration. It returns the
    full original ProfileRevisionRef, DirectoryBindingRef, authorized query
    invocation and its input digest for this exact package/Unit. A wire label or
    copied grant is never a resolver. UnitServices repeats actual owner checks.
    """
    def __init__(self, services, binding_resolver):
        from ordessa_units.public import UnitServices
        if type(services) is not UnitServices or not callable(binding_resolver):
            raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
        self.services=services
        self.resolver=binding_resolver

    def _resolve(self,context,package,unit_ref):
        from ordessa_execution_agents.profiles import ProfileRevisionRef
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

"""Bind Engineering dispatch reads to one existing LocalUnitOwner.

This is process composition over the original Unit owner and UnitServices. It
adds no profile, permission, query, retry, or receipt authority.
"""
from collections.abc import Mapping
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_agents.profiles import ProfileRevisionRef
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.public import UnitServices, unit_services

from ...application.contracts.commands import CommandContext
from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ...application.contracts.implementation_routes import IMPLEMENTATION_COMMANDS
from ...domain.approvals.scope import EnvironmentRef
from ...domain.changes.dispatch import DispatchBinding
from ...domain.common.models.values import Digest
from .recorded_dispatch import NativeDispatchSources, _plain, _reject_callbacks
from .selection import OriginalDispatchSelection


def _query_request_id(request_id, operation_ref, unit_ref, prompt_digest):
    """Map full caller/query pins to the bounded original Unit request key."""
    pinned = canonical_bytes({
        'request_id': request_id,
        'operation_ref': operation_ref,
        'unit_ref': _plain(unit_ref),
        'prompt_digest': 'sha256:' + prompt_digest.hex,
    })
    encoded = base64.b32encode(hashlib.sha256(pinned).digest()).decode('ascii')
    return 'query-' + encoded.rstrip('=').lower()


@dataclass(frozen=True, slots=True)
class _LocalDispatchQueryFactory:
    """A query callable captured from one validated original local owner."""

    _owner: object
    _access: object
    _records: object

    def _current(self, context):
        if type(context) is not CommandContext:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        if self._access.current_context() is not context:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        last_denial = None
        for operation in (EXECUTION_DISPATCH, IMPLEMENTATION_COMMANDS[0],
                          'engineering.submissions.record_report'):
            try:
                self._access.require(context, operation)
                break
            except ApplicationError as exc:
                last_denial = exc
        else:
            raise last_denial or ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        if (context.scope.realm_id != self._owner.permission.scope.realm_id
                or context.scope.project_id != self._owner.permission.scope.project_id):
            raise ApplicationError('SCOPE_MISMATCH')
        return context

    @staticmethod
    def _same_scope(left, right):
        return (getattr(left, 'realm_id', None) == getattr(right, 'realm_id', None)
                and getattr(left, 'project_id', None) == getattr(right, 'project_id', None)
                and bool(getattr(left, 'realm_id', None))
                and bool(getattr(left, 'project_id', None)))

    def _original_unit(self, unit_ref):
        if (not isinstance(unit_ref, Mapping)
                or set(unit_ref) != {'environmentNamespace', 'unitId',
                                     'ownerProviderRef', 'sourceRevision'}):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        try:
            value = dict(unit_ref)
            unit = self._owner.manager.get(value)
            if safe_json(unit.identity) != safe_json(value):
                raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
            snapshot = unit.snapshot()
            if (not isinstance(snapshot, Mapping)
                    or safe_json(snapshot.get('identity')) != safe_json(value)):
                raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
            return value, unit, snapshot
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID') from exc

    def _read_invocation(self, context, unit_ref, operation_ref, prompt_digest,
                         *, request_id):
        owner, records = self._owner, self._records
        try:
            # Keep existing native read identities unchanged. Engineering's
            # derived child IDs have a wider alphabet/length than RequestKey;
            # encode only those otherwise unrepresentable IDs at this boundary.
            request = RequestKey(owner.admission.environment_namespace,
                owner.permission.principal_scope, request_id)
        except ValueError:
            request = RequestKey(owner.admission.environment_namespace,
                owner.permission.principal_scope,
                _query_request_id(request_id, operation_ref, unit_ref, prompt_digest))
        invocation = owner.authorize_acp_turn_query(
            owner.authorization(), request, unit_ref, operation_ref,
            expected_prompt_input_digest='sha256:' + prompt_digest.hex)
        facts = invocation.facts
        input_digest = facts.get('inputDigest')
        try:
            expected_digest = records.acp_turn_query_digest(
                unit_ref, operation_ref, 'sha256:' + prompt_digest.hex)
            context_ref = facts['contextRef']
            directory = DirectoryBindingRef.from_dict(
                dict(context_ref['directoryBindingRef']))
        except Exception as exc:
            raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE') from exc
        if (type(input_digest) is not str or input_digest != expected_digest
                or directory.environment_namespace != owner.admission.environment_namespace):
            raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
        try:
            records.resolve_unit_reference(unit_ref, invocation,
                                           input_digest=input_digest)
        except Exception as exc:
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID') from exc
        return owner.permission.profile_revision, directory, invocation, input_digest

    def __call__(self, binding):
        if type(binding) is not DispatchBinding:
            raise ApplicationError('RECORDED_DISPATCH_BINDING_REQUIRED')
        context = self._current(self._access.current_context())
        if not self._same_scope(binding.scope, context.scope):
            raise ApplicationError('SCOPE_MISMATCH')
        try:
            unit_ref = decode_json(binding.unit_ref_bytes)
            expected_prompt = 'sha256:' + binding.prompt_input_digest.hex
            expected_query = self._records.acp_turn_query_digest(
                unit_ref, binding.execution_operation_ref, expected_prompt)
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_INVALID') from exc
        if expected_query != binding.expected_query_digest:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_MISMATCH')
        self._original_unit(unit_ref)
        invocation = self._read_invocation(context, unit_ref,
            binding.execution_operation_ref, binding.prompt_input_digest,
            request_id=context.request_id)
        if invocation[3] != binding.expected_query_digest:
            raise ApplicationError('RECORDED_DISPATCH_QUERY_DIGEST_MISMATCH')
        return invocation[2]


def _validated_local_owner(unit_owner, access):
    """Validate the original owner route and return its original services."""
    from ordessa_units.assembly.local_owner import LocalUnitOwner
    from ordessa_units.admission.owner_ports import AgentOwnerPorts

    if (type(unit_owner) is not LocalUnitOwner
            or not callable(getattr(access, 'current_context', None))
            or not callable(getattr(access, 'require', None))
            or getattr(access, 'authority', None) is not unit_owner.permission.access_authority
            or type(unit_owner.permission.profile_revision) is not ProfileRevisionRef
            or unit_owner.manager is None):
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    admission_ports = getattr(unit_owner.admission, 'owner_ports', None)
    assembled_owner = unit_owner.assembled_owner
    assembled_ports = None if assembled_owner is None else getattr(assembled_owner, 'ports', None)
    if (admission_ports is not None and assembled_owner is not None
            and assembled_ports is not admission_ports):
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    ports = admission_ports if admission_ports is not None else assembled_ports
    if type(ports) is not AgentOwnerPorts or ports.unit_manager is None:
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    original_manager = unit_owner.manager
    try:
        ports.validate_for(unit_owner.admission)
        manager = unit_owner.bind(ports)
    except Exception as exc:
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE') from exc
    if manager is None or manager is not original_manager or manager is not unit_owner.manager:
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    records = unit_owner.records
    services = unit_services(unit_owner.admission, owner_ports=ports)
    if (type(services) is not UnitServices
            or services.unit_manager is not ports.unit_manager
            or services.unit_manager.records is not records):
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    return records, services


def _build_local_dispatch_bindings(unit_owner, access, *, prompt_parameters,
                                   query_factory=None, workspace_scope_guard=None):
    """Return the original live selection, source and receipt-query ports.

    ``prompt_parameters`` supplies the exact caller's native ACP parameters for
    source preflight. The fixed session is read from the public Unit snapshot
    and normalized exactly as ``RecordedDispatchExecution.freeze_input`` does.
    """
    if not callable(getattr(prompt_parameters, '__call__', None)):
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
    records, services = _validated_local_owner(unit_owner, access)
    if query_factory is None:
        query_factory = _LocalDispatchQueryFactory(unit_owner, access, records)
    elif (type(query_factory) is not _LocalDispatchQueryFactory
            or query_factory._owner is not unit_owner
            or query_factory._access is not access
            or query_factory._records is not records):
        raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')

    dispatch_input = ContextVar('original-engineering-dispatch-input', default=None)

    def _prompt_digest(context, package, unit_ref):
        value, _unit, snapshot = query_factory._original_unit(unit_ref)
        recipe = dispatch_input.get()
        if recipe is None:
            # Explicit standalone source reads retain their configured input.
            # The actual dispatcher enters guard_dispatch_input below and
            # always passes its method-checked identity and native mapping.
            params = prompt_parameters(context, package, value)
        else:
            params = prompt_parameters(context, package, value, recipe)
        if not isinstance(params, Mapping):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        try:
            fixed = _plain(params)
            _reject_callbacks(fixed)
            session = snapshot.get('sessionId')
            if (type(session) is not str or not session
                    or fixed.get('sessionId', session) != session):
                raise ApplicationError('RECORDED_DISPATCH_SESSION_MISMATCH')
            fixed['sessionId'] = session
            native_digest = records.acp_prompt_input_digest(value, fixed)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_FIXED_SESSION_UNAVAILABLE') from exc
        if (type(native_digest) is not str or not native_digest.startswith('sha256:')
                or len(native_digest) != 71):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID')
        try:
            prompt_digest = Digest('sha256', native_digest[7:])
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID') from exc
        return value, prompt_digest

    def binding_resolver(context, package, unit_ref):
        context = query_factory._current(context)
        if (not query_factory._same_scope(package.scope, context.scope)
                or (package.scope.realm_id, package.scope.project_id)
                   != (unit_owner.permission.scope.realm_id,
                       unit_owner.permission.scope.project_id)
                or type(package.payload.execution_profile_ref) is not EnvironmentRef):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        if not isinstance(unit_ref, Mapping):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        unit = dict(unit_ref)
        _value, prompt_digest_key = _prompt_digest(context, package, unit)
        result = query_factory._read_invocation(context, unit, context.request_id,
                                  prompt_digest_key, request_id='dispatch-source-read-' + uuid4().hex)
        return result

    def work_binding_resolver(context, package, unit_ref, authorization, params):
        context = query_factory._current(context)
        if (not query_factory._same_scope(package.scope, context.scope)
                or authorization.scope != context.scope
                or authorization.package_ref != package.ref):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        value, _unit, snapshot = query_factory._original_unit(unit_ref)
        fixed = _plain(params)
        _reject_callbacks(fixed)
        if (not isinstance(fixed, Mapping) or not snapshot.get('sessionId')
                or fixed.get('sessionId') != snapshot['sessionId']):
            raise ApplicationError('RECORDED_DISPATCH_SESSION_MISMATCH')
        native = records.acp_prompt_input_digest(value, fixed)
        if type(native) is not str or not native.startswith('sha256:') or len(native) != 71:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_DIGEST_INVALID')
        return query_factory._read_invocation(context, value, context.request_id,
            Digest('sha256', native[7:]), request_id='dispatch-source-read-' + uuid4().hex)

    @contextmanager
    def guard_dispatch_input(context, package, unit_ref, recipe):
        query_factory._current(context)
        required = {'run_id', 'step_id', 'attempt', 'unit_ref', 'params', 'actions', 'timeout'}
        if (not isinstance(recipe, Mapping) or set(recipe) != required
                or recipe['unit_ref'] != _plain(unit_ref)
                or type(recipe['run_id']) is not str or not recipe['run_id']
                or type(recipe['step_id']) is not str or not recipe['step_id']
                or type(recipe['attempt']) is not int or recipe['attempt'] < 1
                or not query_factory._same_scope(package.scope, context.scope)):
            raise ApplicationError('DISPATCH_METHOD_INPUT_CHANGED')
        value = _plain(recipe)
        _reject_callbacks(value)
        # Per-cut transparent input scope, reset even on failure. No durable
        # table, future dispatch decision, claim or permission is cached here.
        token = dispatch_input.set(decode_json(canonical_bytes(value)))
        try:
            yield
        finally:
            dispatch_input.reset(token)

    selection = OriginalDispatchSelection(services,
        unit_owner.permission.profile_revision, binding_resolver=binding_resolver,
        work_binding_resolver=work_binding_resolver,
        workspace_scope_guard=workspace_scope_guard)
    sources = NativeDispatchSources(services, binding_resolver,
                                   dispatch_input_guard=guard_dispatch_input)
    return selection, sources, query_factory


def _historical_query_request(binding, records, *, environment_namespace, principal_scope):
    """Derive the exact historical read request from the frozen binding alone.

    The request identity comes from the stored binding bytes and the original
    records' own query digest — never from a live Unit, a caller-supplied id or
    the execution fence. This is a pure derivation: it authorizes nothing.
    """
    if (type(binding) is not DispatchBinding or binding.binding_version != 2
            or type(binding.subject) is not dict
            or binding.subject.get('subject_kind') != 'frozen_package'):
        raise ApplicationError('CONTINUATION_QUERY_BINDING_INVALID')
    try:
        unit = decode_json(binding.unit_ref_bytes)
    except Exception as exc:
        raise ApplicationError('CONTINUATION_QUERY_BINDING_INVALID') from exc
    expected = 'sha256:' + binding.prompt_input_digest.hex
    digest = records.acp_turn_query_digest(unit, binding.execution_operation_ref, expected)
    if type(digest) is not str or digest != binding.expected_query_digest:
        raise ApplicationError('CONTINUATION_QUERY_BINDING_INVALID')
    key = hashlib.sha256(canonical_bytes({
        'unit': unit, 'operation': binding.execution_operation_ref,
        'prompt': expected, 'binding_digest': binding.digest.hex})).hexdigest()
    return unit, RequestKey(environment_namespace, principal_scope,
                            'history-query-' + key[:48]), digest


def build_historical_dispatch_query_factory(unit_owner, access):
    """Authorized historical receipt reads for a frozen continuation origin.

    The origin Unit is normally closed and may be fenced as historical. This
    factory therefore derives the read request from the frozen binding and issues
    it through the original owner's ``authorize_acp_turn_query``; it never calls
    ``manager.get`` or ``resolve_unit_reference``, and it adds no authority.
    """
    records, _services = _validated_local_owner(unit_owner, access)

    def query(binding):
        unit, request, _query_digest = _historical_query_request(
            binding, records,
            environment_namespace=unit_owner.admission.environment_namespace,
            principal_scope=unit_owner.permission.principal_scope)
        return unit_owner.authorize_acp_turn_query(
            unit_owner.authorization(), request, unit,
            binding.execution_operation_ref,
            expected_prompt_input_digest='sha256:' + binding.prompt_input_digest.hex)

    return query


def build_local_dispatch_query_factory(unit_owner, access):
    """Capture the canonical native query for an already assembled owner.

    The returned callable is useful while the method producer is being
    assembled; it carries no authority beyond the exact owner/access/records
    objects validated here.
    """
    records, _services = _validated_local_owner(unit_owner, access)
    return _LocalDispatchQueryFactory(unit_owner, access, records)


def build_local_dispatch_bindings(unit_owner, access, *, prompt_parameters,
                                  query_factory=None, workspace_scope_guard=None):
    """Build dispatch ports and optionally reuse the previously captured query."""
    return _build_local_dispatch_bindings(
        unit_owner, access, prompt_parameters=prompt_parameters,
        query_factory=query_factory, workspace_scope_guard=workspace_scope_guard)


__all__ = ['build_local_dispatch_bindings', 'build_local_dispatch_query_factory',
           'build_historical_dispatch_query_factory']

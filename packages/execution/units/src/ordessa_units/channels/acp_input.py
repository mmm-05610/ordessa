"""Capture/Workspace coordination on the original fresh Unit ACP attempt.

Capture and Workspace remain external authorities. This adapter creates no
capture, permission, invocation issuer, operation store or result ledger.
"""
from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_agents.profiles import encode_revision_ref
from ordessa_units.errors import UnitApiRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable
from .contracts import WorkspaceExecutionEvidence
from .reservations import CapturedInputRef

CAPTURE_VERSION = 'managed-acp-capture/1'
BINDING_VERSION = 'unit-managed-acp-input/1'


@dataclass(frozen=True)
class ManagedAcpCapture:
    """Immutable native prompt payload supplied by the existing capture owner.

    The digest covers this complete envelope, including its original target.
    Session identity is added by Units, never selected by the capture caller.
    """
    ref: CapturedInputRef
    node_ref: Mapping
    unit_ref: Mapping
    params: Mapping

    def __post_init__(self):
        if type(self.ref) is not CapturedInputRef:
            raise UnitApiRefused('Complete original capture reference required')
        for field in ('node_ref', 'unit_ref', 'params'):
            if not isinstance(getattr(self, field), Mapping):
                raise UnitApiRefused('Complete ACP capture envelope required')
            object.__setattr__(self, field, sealed_mapping(getattr(self, field)))
        if ('sessionId' in self.params or set(self.node_ref) != {'environmentNamespace', 'nodeId', 'generation'}
                or self.node_ref['environmentNamespace'] != self.ref.environment_namespace
                or self.unit_ref.get('environmentNamespace') != self.ref.environment_namespace):
            raise UnitIdentityMismatch('Capture target differs from its original Unit scope')

    def canonical_bytes(self):
        return safe_json({'contractVersion': CAPTURE_VERSION, 'nodeRef': self.node_ref,
                         'unitRef': self.unit_ref, 'params': self.params}).encode('utf-8')

    def verify_digest(self):
        if 'sha256:' + hashlib.sha256(self.canonical_bytes()).hexdigest() != self.ref.content_digest:
            raise UnitIdentityMismatch('Original ACP capture content digest differs')


@dataclass(frozen=True)
class ManagedAcpInputPorts:
    """Deployment-frozen original capture-content and Workspace owner ports."""
    capture_content: object
    workspace_execution: object

    def __post_init__(self):
        if (not callable(getattr(self.capture_content, 'read_content', None))
                or any(not callable(getattr(self.workspace_execution, name, None))
                       for name in ('authorize_execute', 'revalidate_execute'))):
            raise UnitGuaranteeUnavailable('Original ACP capture and Workspace execute owners required')


def operation_reference(request):
    return 'unit-input/' + hashlib.sha256(safe_json(request_identity(request)).encode()).hexdigest()


def request_identity(request):
    if type(request) is not RequestKey:
        raise UnitApiRefused('Authenticated original RequestKey required')
    return {'environmentNamespace': request.environment_namespace,
            'principalScope': request.principal_scope, 'requestId': request.request_id}


class ManagedAcpInputs:
    def __init__(self, owner, ports):
        self.owner, self.ports = owner, ports

    def _request(self, request, captured_ref):
        identity = request_identity(request)
        if (type(captured_ref) is not CapturedInputRef
                or request.environment_namespace != self.owner.admission.environment_namespace
                or request.principal_scope != self.owner.permission.principal_scope
                or captured_ref.environment_namespace != request.environment_namespace):
            raise UnitIdentityMismatch('Managed ACP input differs from its original principal or Environment')
        return identity

    def _capture(self, request, captured_ref, unit_ref, node_ref):
        content = self.ports.capture_content.read_content(captured_ref, request.principal_scope)
        if (type(content) is not ManagedAcpCapture or content.ref != captured_ref
                or safe_json(content.unit_ref) != safe_json(unit_ref)
                or safe_json(content.node_ref) != safe_json(node_ref)):
            raise UnitIdentityMismatch('Original capture owner returned a different ACP target')
        content.verify_digest()
        return content

    def _existing(self, authorization, request, unit_ref, captured_ref):
        from ordessa_units.records import acp_turns
        owner = self.owner
        identity = self._request(request, captured_ref)
        with owner.authority.guard('interaction', authorization):
            ports = owner._bound()
            records = ports.provider_view.records
            operation = operation_reference(request)
            # Owner-only lookup locates the exact original attempt; the return
            # path below still performs the original issuer-authorized query.
            with records.journal._connect() as db:
                body = acp_turns._read(records, db, operation)
            if body is None:
                return None
            binding = body.get('managedInput')
            if (not isinstance(binding, Mapping) or binding['request'] != identity
                    or binding['capturedInputRef'] != captured_ref.to_dict()
                    or safe_json(body['unitRef']) != safe_json(unit_ref)
                    or safe_json(binding['issuerRef']) != safe_json(owner.authority.issuer_ref)
                    or safe_json(binding['profileRevision']) != safe_json(encode_revision_ref(owner.permission.profile_revision))):
                raise UnitIdentityMismatch('Spent request belongs to a different original managed input')
            query_request = RequestKey(request.environment_namespace, request.principal_scope,
                'managed-read-' + hashlib.sha256(safe_json(identity).encode()).hexdigest()[:48])
            invocation = owner.authorize_acp_turn_query(authorization, query_request, unit_ref,
                operation, expected_prompt_input_digest=body['inputDigest'])
            return records.query_acp_turn(unit_ref, operation, invocation,
                input_digest=records.acp_turn_query_digest(unit_ref, operation, body['inputDigest']),
                expected_prompt_input_digest=body['inputDigest'])

    def read(self, authorization, request, unit_ref, captured_ref):
        """Exact authorized read, including after disconnect/release; no send."""
        return self._existing(authorization, request, unit_ref, captured_ref)

    def submit(self, unit, authorization, request, captured_ref, *, timeout):
        owner = self.owner
        self._request(request, captured_ref)
        previous = self._existing(authorization, request, unit.identity, captured_ref)
        if previous is not None:
            return previous
        instance = owner.native_unit(unit, authorization)
        if (instance._effect_write_guard_factory is not None
                or instance._fixed_effect_write_guard_factory is not None):
            raise UnitApiRefused('Canonical effect-guarded prompts require their original Engineering binding')
        original = owner._bound()
        records = original.provider_view.records
        reservation = records.owner_read_unit(unit.identity['unitId'])
        node = reservation.facts['nodeRef']
        content = self._capture(request, captured_ref, unit.identity, node)
        operation = operation_reference(request)
        execution = self.ports.workspace_execution.authorize_execute(request, node, unit.identity,
            operation, captured_ref.to_dict(), captured_ref.content_digest, reservation.facts['managementEpoch'])
        if type(execution) is not WorkspaceExecutionEvidence:
            raise UnitGuaranteeUnavailable('Original Workspace execute authority unavailable')
        binding = {'contractVersion': BINDING_VERSION, 'request': request_identity(request),
            'capturedInputRef': captured_ref.to_dict(), 'contentDigest': captured_ref.content_digest,
            'unitRef': unit.identity, 'nodeRef': node, 'providerRef': reservation.facts['providerRef'],
            'managementEpoch': reservation.facts['managementEpoch'],
            'profileRevision': encode_revision_ref(owner.permission.profile_revision),
            'nativeSessionId': unit.snapshot()['sessionId'], 'issuerRef': owner.authority.issuer_ref,
            'workspaceExecutionEvidence': execution.to_dict()}
        binding = sealed_mapping(binding)
        lease = owner.authorize('interaction', unit, authorization)
        dispatch = _ManagedAcpDispatch(self, unit, authorization, request, captured_ref,
            instance, original, content, execution, binding)
        from ordessa_units.records import UnitRecordsRefused
        try:
            return instance.prompt(unit.identity, lease, operation_ref=operation, timeout=timeout,
                                   params=json.loads(safe_json(content.params)), managed_input=dispatch)
        except UnitRecordsRefused:
            # A simultaneous submit may have won the original SQLite reserve.
            # Return only its exact authorized record, never prepare/send again.
            previous = self._existing(authorization, request, unit.identity, captured_ref)
            if previous is not None:
                return previous
            raise


class _ManagedAcpDispatch:
    """Trusted per-submit hook; never carried in native ACP params."""
    def __init__(self, service, unit, authorization, request, capture, instance,
                 original_ports, content, execution, binding):
        self.service, self.unit, self.authorization = service, unit, authorization
        self.request, self.capture, self.instance = request, capture, instance
        self.original_ports, self.content, self.execution = original_ports, content, execution
        self.binding = binding

    def before_write(self, instance):
        owner = self.service.owner
        if (instance is not self.instance or owner._bound() is not self.original_ports
                or owner.native_unit(self.unit, self.authorization) is not instance
                or instance.records is not self.original_ports.provider_view.records
                or instance._verifier is not self.original_ports.provider_view.verifier):
            raise UnitIdentityMismatch('Managed ACP input lost its original Unit/issuer/records/verifier')
        current = self.service._capture(self.request, self.capture, self.unit.identity, self.content.node_ref)
        if current.canonical_bytes() != self.content.canonical_bytes():
            raise UnitIdentityMismatch('Captured ACP content changed before native write')
        proof = self.service.ports.workspace_execution.revalidate_execute(self.execution)
        if (type(proof) is not WorkspaceExecutionEvidence
                or safe_json(proof.to_dict()) != safe_json(self.binding['workspaceExecutionEvidence'])
                or self.unit.snapshot()['sessionId'] != self.binding['nativeSessionId']):
            raise UnitApiRefused('Original Workspace execute evidence changed before native write')

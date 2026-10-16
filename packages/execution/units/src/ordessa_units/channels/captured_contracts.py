"""Immutable captured text and Workspace proof for the formal Unit input owner.

These are source facts, never permission. The selected capture and Workspace
ports remain the authorities; no Node or legacy native-provider state is made.
"""
from dataclasses import dataclass
import hashlib
from collections.abc import Mapping
from typing import Protocol

from ordessa_units.api.errors import UnitApiRefused
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from .reservations import CapturedInputRef

UNIT_TEXT_CAPTURE_VERSION = 'unit-captured-text/1'
UNIT_INPUT_VERSION = 'unit-captured-input/1'


class UnitCapturedInputRefused(UnitApiRefused):
    code = 'UNIT_CAPTURED_INPUT_REFUSED'


class UnitCapturedInputPending(UnitCapturedInputRefused):
    code = 'UNIT_CAPTURED_INPUT_PENDING'


def _unit_reference(value, namespace):
    if (not isinstance(value, Mapping)
            or set(value) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
            or value.get('environmentNamespace') != namespace
            or not isinstance(value.get('ownerProviderRef'), Mapping)
            or any(type(value.get(k)) is not str or not value[k] for k in ('unitId', 'sourceRevision'))):
        raise UnitCapturedInputRefused('complete original Unit input reference required')
    return sealed_mapping(value)


@dataclass(frozen=True, repr=False)
class UnitTextCapture:
    """Read-only projection of one existing capture, with no normalization."""
    ref: CapturedInputRef
    unit_ref: Mapping
    envelope: Mapping
    metadata: Mapping

    def __post_init__(self):
        if type(self.ref) is not CapturedInputRef:
            raise UnitCapturedInputRefused('original captured input reference required')
        object.__setattr__(self, 'unit_ref', _unit_reference(self.unit_ref, self.ref.environment_namespace))
        object.__setattr__(self, 'envelope', sealed_mapping(self.envelope))
        object.__setattr__(self, 'metadata', sealed_mapping(self.metadata))

    def canonical_bytes(self):
        if (set(self.envelope) != {'schemaVersion', 'text'}
                or self.envelope.get('schemaVersion') != UNIT_TEXT_CAPTURE_VERSION
                or type(self.envelope.get('text')) is not str
                or set(self.metadata) != {'attachmentDigests', 'configOperationIds', 'handles', 'baseRevision'}
                or any(self.metadata[k] not in ((), []) for k in ('attachmentDigests', 'configOperationIds', 'handles'))
                or self.metadata['baseRevision'] is not None):
            raise UnitCapturedInputRefused('capture contains unsupported attachments or configuration')
        try:
            body = safe_json(self.envelope).encode('utf-8')
        except (TypeError, ValueError, UnicodeError):
            raise UnitCapturedInputRefused('canonical UTF-8 captured text required') from None
        if len(body) > 65536:
            # The original ACP evidence row has a 256 KiB total bound and
            # repeats prompt text in the frozen input and actual request frame.
            raise UnitCapturedInputRefused('captured text exceeds bounded ACP evidence capacity')
        return body

    def verify_digest(self):
        body = self.canonical_bytes()
        if 'sha256:' + hashlib.sha256(body).hexdigest() != self.ref.content_digest:
            raise UnitCapturedInputRefused('canonical capture digest differs from original reference')
        return body


class UnitCaptureContentPort(Protocol):
    def read_content(self, captured_ref: CapturedInputRef, principal: str) -> UnitTextCapture | None: ...


@dataclass(frozen=True)
class UnitWorkspaceExecutionEvidence:
    environment_namespace: str
    principal_scope: str
    unit_ref: Mapping
    operation_ref: str
    capture_ref: CapturedInputRef
    evidence_ref: str

    def __post_init__(self):
        if (type(self.capture_ref) is not CapturedInputRef
                or self.capture_ref.environment_namespace != self.environment_namespace
                or any(type(v) is not str or not v or len(v) > 256 or any(ord(c) < 32 for c in v)
                       for v in (self.environment_namespace, self.principal_scope, self.operation_ref, self.evidence_ref))):
            raise UnitCapturedInputRefused('original Unit Workspace execute evidence required')
        object.__setattr__(self, 'unit_ref', _unit_reference(self.unit_ref, self.environment_namespace))

    def to_dict(self):
        return {'contractVersion': 'unit-workspace-execute/1',
            'environmentNamespace': self.environment_namespace, 'principalScope': self.principal_scope,
            'unitRef': self.unit_ref, 'operationRef': self.operation_ref,
            'captureRef': self.capture_ref.to_dict(), 'evidenceRef': self.evidence_ref}


class UnitWorkspaceExecutionPort(Protocol):
    """Selected real authority, cooperatively held across the actual byte write.

    guard_execute must synchronize with this authority's revoke writer, yield
    the same evidence after current revalidation, and release on cancellation.
    Possession of an evidence DTO does not authorize a write.
    """
    def authorize_execute(self, request, unit_ref, operation_ref, capture_ref) -> UnitWorkspaceExecutionEvidence: ...
    def guard_execute(self, evidence, write_identity, deadline): ...

"""Ordessa F1 capability contracts (DESIGN §3.1).

This distribution is standard-library only. It defines the frozen capability
descriptor/result/envelope shapes and their validation; it contains no
registry, owner DTOs, policies or resource contracts.
"""
from .capability import (
    CAPABILITY_ENTRY_POINT_GROUP, CAPABILITY_FACTORY_ATTR, CLI_NARGS, CLI_TYPES,
    CONTRACT_REVISION, ERROR_CODES, MAX_EVIDENCE_REFS, MAX_ID_LENGTH,
    MAX_JSON_BYTES, MAX_JSON_DEPTH, MAX_MESSAGE_LENGTH, RENDER_KINDS, STATUSES,
    Capability, CapabilityDescriptor, CapabilityError, CapabilityFactory,
    ContractError, OperationContext, OperationDescriptor, OperationHandler,
    OperationResult, canonical_json, compute_descriptor_digest,
    descriptor_projection, ensure_json_value, validate_capability,
    validate_error, validate_result,
)
from .envelopes import (
    ENVELOPE_API_VERSION, EXIT_ACCEPTED, EXIT_COMPLETED, EXIT_CONFLICT,
    EXIT_REFUSED, EXIT_TIMEOUT, EXIT_UNKNOWN, EXIT_UNSUPPORTED,
    envelope_from_result, exit_code, make_envelope, validate_envelope,
)

__all__ = [
    'CONTRACT_REVISION', 'CAPABILITY_ENTRY_POINT_GROUP', 'CAPABILITY_FACTORY_ATTR',
    'MAX_JSON_BYTES', 'MAX_JSON_DEPTH', 'MAX_ID_LENGTH', 'MAX_MESSAGE_LENGTH',
    'MAX_EVIDENCE_REFS', 'STATUSES', 'ERROR_CODES', 'CLI_TYPES', 'CLI_NARGS',
    'RENDER_KINDS', 'ContractError',
    'ensure_json_value', 'canonical_json', 'descriptor_projection',
    'compute_descriptor_digest', 'validate_capability', 'validate_error',
    'validate_result',
    'OperationDescriptor', 'CapabilityDescriptor', 'CapabilityError',
    'OperationResult', 'OperationContext', 'OperationHandler', 'Capability',
    'CapabilityFactory',
    'ENVELOPE_API_VERSION', 'EXIT_COMPLETED', 'EXIT_REFUSED', 'EXIT_ACCEPTED',
    'EXIT_UNSUPPORTED', 'EXIT_CONFLICT', 'EXIT_UNKNOWN', 'EXIT_TIMEOUT',
    'make_envelope', 'envelope_from_result', 'validate_envelope', 'exit_code',
]

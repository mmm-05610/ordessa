"""Capture one authorized original UnitRecords ACP observation into Engineering's BlobStore."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from ordessa_infrastructure.encoding.canonical_json import canonical_bytes, LIBRARY_JSON_PROFILE

from ....application.contracts.errors import ApplicationError
from ....application.contracts.execution_observations import (
    ExecutionObservationRef, MAX_EXECUTION_RECEIPT_BYTES)
from ....domain.common.models.values import Digest
from ....domain.common.models.refs import BlobRef


_STATES = {'reserved', 'possibly-written', 'completed', 'failed', 'unknown'}
_DEFAULT_RECEIPT_MAX_BYTES = 262144


def _plain_view(value, depth=0):
    # Public Execution records are recursively sealed mapping/tuple views.
    # Preserve every JSON field while making those views encodable by the
    # original neutral canonical encoder; this performs no semantic projection.
    if depth > 32:
        raise ValueError('execution observation depth bound exceeded')
    if isinstance(value, Mapping):
        return {key: _plain_view(item, depth+1) for key,item in value.items()}
    if isinstance(value, (list,tuple)):
        return [_plain_view(item, depth+1) for item in value]
    return value


def capture_execution_observation(records, blobs, *, authority_id, unit_ref, operation_ref,
                                  expected_prompt_digest, query_invocation,
                                  max_receipt_bytes=_DEFAULT_RECEIPT_MAX_BYTES):
    """Authorized cold-read and byte capture only; no Submission or Grant.

    The original Records adapter passes its public finite receipt budget here;
    direct historical callers retain the former 256 KiB default.
    """
    if (type(max_receipt_bytes) is not int
            or not 1 <= max_receipt_bytes <= MAX_EXECUTION_RECEIPT_BYTES):
        raise ApplicationError('EXECUTION_RECEIPT_BOUND_INVALID')
    if (not isinstance(unit_ref, Mapping)
            or set(unit_ref) != {'environmentNamespace','unitId','ownerProviderRef','sourceRevision'}
            or type(operation_ref) is not str or not 0 < len(operation_ref) <= 256
            or any(ord(c) < 32 for c in operation_ref)):
        raise ApplicationError('EXECUTION_OBSERVATION_IDENTITY_REQUIRED')
    if type(expected_prompt_digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_prompt_digest):
        raise ApplicationError('EXECUTION_PROMPT_DIGEST_REQUIRED')
    if query_invocation is None:
        raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
    if type(authority_id) is not str or not authority_id or getattr(blobs, 'authority_id', None) != authority_id:
        raise ApplicationError('EXECUTION_BLOB_AUTHORITY_MISMATCH')

    query_digest = records.acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_digest)
    facts = getattr(query_invocation, 'facts', None)
    if not isinstance(facts, Mapping) or facts.get('inputDigest') != query_digest:
        raise ApplicationError('EXECUTION_QUERY_BINDING_MISMATCH')
    try:
        receipt = records.query_acp_turn(
            unit_ref, operation_ref, query_invocation, input_digest=query_digest,
            expected_prompt_input_digest=expected_prompt_digest)
    except Exception as exc:
        # Preserve the records authority's refusal; never turn it into an unauthorised read.
        raise ApplicationError('EXECUTION_QUERY_REFUSED') from exc

    if not isinstance(receipt, Mapping):
        raise ApplicationError('EXECUTION_RECEIPT_INVALID')
    state = receipt.get('state')
    revision = receipt.get('revision')
    if (receipt.get('contractVersion') != 'unit-acp-turn/1'
            or receipt.get('unitRef') != dict(unit_ref)
            or receipt.get('operationRef') != operation_ref
            or receipt.get('inputDigest') != expected_prompt_digest
            or state not in _STATES or type(revision) is not int or revision < 1):
        raise ApplicationError('EXECUTION_RECEIPT_BINDING_MISMATCH')
    try:
        encoded = canonical_bytes(_plain_view(receipt), profile=LIBRARY_JSON_PROFILE)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ApplicationError('EXECUTION_RECEIPT_NOT_CANONICAL') from exc
    digest = hashlib.sha256(encoded).hexdigest()
    if len(encoded) > max_receipt_bytes:
        raise ApplicationError('EXECUTION_RECEIPT_BOUND_EXCEEDED')
    expected = Digest('sha256', digest)
    blob_ref = blobs.put_verified(encoded, expected, 'application/json')
    if (type(blob_ref) is not BlobRef or blob_ref.digest != expected
            or blob_ref.byte_length != len(encoded) or blob_ref.media_type != 'application/json'
            or blobs.read_verified(blob_ref) != encoded):
        raise ApplicationError('EXECUTION_BLOB_CAPTURE_MISMATCH')
    if getattr(blobs, 'authority_id', None) != authority_id:
        raise ApplicationError('EXECUTION_BLOB_AUTHORITY_CHANGED')
    return ExecutionObservationRef(dict(unit_ref), operation_ref, expected_prompt_digest,
                                   query_digest, state, revision, blob_ref, authority_id)


__all__ = ['capture_execution_observation']

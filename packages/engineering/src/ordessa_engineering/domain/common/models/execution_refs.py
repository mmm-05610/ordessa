"""Execution-reference byte contracts; no runtime, grant or owner resolution.

New online references are AgentInstanceRef projections. Historical Unit data
has an explicitly separate read-only decoder; it is NEVER converted into an
Agent identity or accepted by the online encoder/validator.
"""
from collections.abc import Mapping
from types import MappingProxyType
import re

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..outcomes.diagnostics import ReferenceError
from .values import validate_id

AGENT_INSTANCE_SCHEMA = 'agent-instance/1'
_AGENT_FIELDS = frozenset({'schemaVersion', 'namespace', 'instanceId', 'bindingDigest'})
_HISTORICAL_FIELDS = frozenset({'environmentNamespace','unitId','ownerProviderRef','sourceRevision'})


def _decode_canonical(raw, maximum):
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise ReferenceError('INVALID_EXECUTION_REFERENCE')
    try:
        value = decode_json(raw)
        if type(value) is not dict or canonical_bytes(value) != raw:
            raise ValueError()
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise ReferenceError('INVALID_EXECUTION_REFERENCE') from None


def agent_instance_ref_bytes(value):
    """Validate only the closed NEW identity; data is not authorization."""
    if (not isinstance(value, Mapping) or set(value) != _AGENT_FIELDS
            or value['schemaVersion'] != AGENT_INSTANCE_SCHEMA):
        raise ReferenceError('INVALID_AGENT_INSTANCE_REFERENCE')
    validate_id(value['namespace'])
    validate_id(value['instanceId'])
    digest = value['bindingDigest']
    if type(digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ReferenceError('INVALID_AGENT_INSTANCE_REFERENCE')
    try:
        raw = canonical_bytes(dict(value))
    except (ValueError, TypeError, UnicodeError):
        raise ReferenceError('INVALID_AGENT_INSTANCE_REFERENCE') from None
    if len(raw) > 4096:
        raise ReferenceError('INVALID_AGENT_INSTANCE_REFERENCE')
    return raw


def read_agent_instance_ref(raw):
    """Read exact canonical bytes without importing an execution SDK."""
    value = _decode_canonical(raw, 4096)
    if agent_instance_ref_bytes(value) != raw:
        raise ReferenceError('INVALID_AGENT_INSTANCE_REFERENCE')
    return MappingProxyType(value)


def agent_instance_identity(value):
    """Role-distinction key: changing a binding digest cannot invent a new actor."""
    agent_instance_ref_bytes(value)
    return value['namespace'], value['instanceId']


def validate_agent_turn_query_bytes(raw,agent_raw,input_digest,query_digest):
    """Closed original TurnRef/query data, never an allocator or permission."""
    import hashlib
    agent=dict(read_agent_instance_ref(agent_raw))
    turn=_decode_canonical(raw,8192)
    if (set(turn)!={'schemaVersion','instanceRef','turnId'} or turn['schemaVersion']!='agent-turn-ref/1'
            or turn['instanceRef']!=agent):raise ReferenceError('INVALID_AGENT_TURN_REFERENCE')
    validate_id(turn['turnId'])
    if (type(input_digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}',input_digest)
            or type(query_digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}',query_digest)):
        raise ReferenceError('INVALID_AGENT_TURN_REFERENCE')
    projection={'schemaVersion':'agent-turn-query/1','turnRef':turn,'expectedInputDigest':input_digest}
    if 'sha256:'+hashlib.sha256(canonical_bytes(projection)).hexdigest()!=query_digest:
        raise ReferenceError('INVALID_AGENT_TURN_QUERY')


def read_historical_unit_ref(raw, *, maximum=8192):
    """Read old bytes only. No migration, live capability, grant or SDK alias.

    Callers may retain the original raw bytes/digest. This parser cannot supply
    an AgentInstanceRef to the new online path, even when string ids coincide.
    """
    if type(maximum) is not int or not 0 < maximum <= 8192:
        raise ReferenceError('INVALID_EXECUTION_REFERENCE')
    value = _decode_canonical(raw, maximum)
    if set(value) != _HISTORICAL_FIELDS or type(value['ownerProviderRef']) is not dict:
        raise ReferenceError('INVALID_HISTORICAL_UNIT_REFERENCE')
    for key in ('environmentNamespace','unitId','sourceRevision'):
        validate_id(value[key])
    # Deep-sealed metadata; the original canonical bytes remain the receipt.
    def seal(item):
        if type(item) is dict:return MappingProxyType({k:seal(v) for k,v in item.items()})
        if type(item) is list:return tuple(seal(v) for v in item)
        return item
    return seal(value)

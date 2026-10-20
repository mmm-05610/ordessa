"""Closed v2 codec and explicitly read-only historical v1 receipt access."""
from dataclasses import asdict, dataclass, fields
from collections.abc import Mapping
from types import MappingProxyType

from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import (canonical_value, require_object, decode_scope,
    decode_digest, decode_blob_ref, decode_tuple)
from ..common.models.execution_refs import agent_instance_ref_bytes
from ..common.models.values import Digest
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.ref_codec import decode_approval_ref
from ..packages.codec import decode_package_ref
from .agent_dispatch import (AgentDispatchBinding, AgentWorkDispatchBinding,
    SCHEMA_VERSION, PRE_F2_SCHEMA_VERSION, WORK_SCHEMA_VERSION)


def encode_agent_dispatch(binding):
    if type(binding) not in (AgentDispatchBinding, AgentWorkDispatchBinding):
        raise ReferenceError('AGENT_DISPATCH_BINDING_REQUIRED')
    return canonical_bytes(binding.projection() | {'digest': asdict(binding.digest)})


def decode_agent_dispatch(raw):
    value = canonical_value(raw, maximum=262144)
    if type(value) is not dict:raise ReferenceError('INVALID_AGENT_DISPATCH_BINDING')
    version=value.get('schemaVersion')
    kind = AgentWorkDispatchBinding if version == WORK_SCHEMA_VERSION else AgentDispatchBinding
    names={'schemaVersion', *(f.name for f in fields(kind))}
    if version==PRE_F2_SCHEMA_VERSION:names.remove('turn_ref_bytes')
    require_object(value,names,'INVALID_AGENT_DISPATCH_BINDING')
    if version not in (SCHEMA_VERSION,PRE_F2_SCHEMA_VERSION,WORK_SCHEMA_VERSION):
        raise ReferenceError('INVALID_AGENT_DISPATCH_VERSION')
    def pair(item):
        if type(item) is not list or len(item) != 2:
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        return tuple(item)
    kwargs = {k:v for k,v in value.items() if k not in ('schemaVersion', 'digest')}
    if version in (SCHEMA_VERSION, WORK_SCHEMA_VERSION):
        if type(value['turn_ref_bytes']) is not dict:raise ReferenceError('INVALID_AGENT_TURN_REFERENCE')
        kwargs['turn_ref_bytes']=canonical_bytes(value['turn_ref_bytes'])
    kwargs.update(scope=decode_scope(value['scope']), package_ref=decode_package_ref(value['package_ref']),
        approval_ref=decode_approval_ref(value['approval_ref']), intent_digest=decode_digest(value['intent_digest']),
        prompt_ref=decode_blob_ref(value['prompt_ref']), prompt_input_digest=decode_digest(value['prompt_input_digest']),
        agent_ref_bytes=agent_instance_ref_bytes(value['agent_ref_bytes']),
        action_instances=decode_tuple(value['action_instances'], pair, 'INVALID_DISPATCH_BINDING'),
        required_results=decode_tuple(value['required_results'], lambda x:x, 'INVALID_DISPATCH_BINDING'))
    binding = kind(**kwargs)
    if binding.digest != decode_digest(value['digest']) or encode_agent_dispatch(binding) != raw:
        raise ReferenceError('INVALID_AGENT_DISPATCH_BINDING')
    return binding


@dataclass(frozen=True)
class HistoricalDispatch:
    """Original v1 bytes/digest and sealed facts only; no online binding or grant."""
    raw_bytes: bytes
    original_digest: Digest
    facts: Mapping


def read_historical_dispatch(raw):
    # Local import makes the old-version decoder explicit. No v1 -> v2 conversion.
    from .dispatch_codec import decode_dispatch
    binding = decode_dispatch(raw)
    def seal(value):
        if type(value) is dict:
            return MappingProxyType({k:seal(v) for k,v in value.items()})
        if type(value) is list:
            return tuple(seal(v) for v in value)
        return value
    return HistoricalDispatch(raw, binding.digest, seal(canonical_value(raw)))

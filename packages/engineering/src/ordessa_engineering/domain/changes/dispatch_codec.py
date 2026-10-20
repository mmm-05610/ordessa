"""Exact immutable step binding codec; supplied digest is never trusted."""
from dataclasses import asdict,fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import canonical_value,require_object,decode_scope,decode_digest,decode_blob_ref,decode_tuple
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.ref_codec import decode_approval_ref
from ..packages.codec import decode_package_ref
from .dispatch import (CONTINUATION_SCHEMA_VERSION, DispatchBinding,
                       DispatchContinuation, DispatchOriginRef)


def encode_dispatch(binding):
    return canonical_bytes(binding.projection()|{'digest':asdict(binding.digest)})


def decode_dispatch(raw):
    value=canonical_value(raw)
    if type(value) is not dict:
        raise ReferenceError('INVALID_DISPATCH_BINDING')
    version=value.get('binding_version',1)
    if version not in (1,2):
        raise ReferenceError('INVALID_DISPATCH_BINDING')
    names={f.name for f in fields(DispatchBinding)}
    v2_only={'binding_version','work','subject'}
    expected=names if version==2 else names-v2_only
    require_object(value,expected,'INVALID_DISPATCH_BINDING')
    def pair(item):
        if type(item) is not list or len(item)!=2:raise ReferenceError('INVALID_DISPATCH_BINDING')
        return tuple(item)
    kwargs=dict(value);kwargs.pop('digest')
    if version==2:
        # A generation binding carries no approval, intent digest or control
        # version; the fields are present and must be null, never fabricated.
        kwargs['package_ref']=(None if value['package_ref'] is None
                               else decode_package_ref(value['package_ref']))
        kwargs.update(scope=decode_scope(value['scope']),
            approval_ref=(None if value['approval_ref'] is None
                          else decode_approval_ref(value['approval_ref'])),
            intent_digest=(None if value['intent_digest'] is None
                           else decode_digest(value['intent_digest'])),
            control_version=(None if value['control_version'] is None
                             else value['control_version']),
            prompt_ref=decode_blob_ref(value['prompt_ref']),prompt_input_digest=decode_digest(value['prompt_input_digest']),
            unit_ref_bytes=canonical_bytes(value['unit_ref_bytes']),
            action_instances=decode_tuple(value['action_instances'],pair,'INVALID_DISPATCH_BINDING'),
            required_results=decode_tuple(value['required_results'],lambda x:x,'INVALID_DISPATCH_BINDING'))
        binding=DispatchBinding(**kwargs)
        if binding.digest!=decode_digest(value['digest']) or encode_dispatch(binding)!=raw:raise ReferenceError('INVALID_DISPATCH_BINDING')
        return binding
    kwargs.update(scope=decode_scope(value['scope']),package_ref=decode_package_ref(value['package_ref']),
        approval_ref=decode_approval_ref(value['approval_ref']),intent_digest=decode_digest(value['intent_digest']),
        prompt_ref=decode_blob_ref(value['prompt_ref']),prompt_input_digest=decode_digest(value['prompt_input_digest']),
        unit_ref_bytes=canonical_bytes(value['unit_ref_bytes']),
        action_instances=decode_tuple(value['action_instances'],pair,'INVALID_DISPATCH_BINDING'),
        required_results=decode_tuple(value['required_results'],lambda x:x,'INVALID_DISPATCH_BINDING'))
    if version==2:
        kwargs.update(package_ref=kwargs.get('package_ref'))
    binding=DispatchBinding(**kwargs)
    if binding.digest!=decode_digest(value['digest']) or encode_dispatch(binding)!=raw:raise ReferenceError('INVALID_DISPATCH_BINDING')
    return binding


# ---- continuation codec --------------------------------------------------
# The continuation has its own closed shape and version. It is deliberately not
# a variant of the dispatch binding: encode/decode_dispatch above stay byte for
# byte what they were, and an unknown continuation version or field is refused
# instead of being read as a binding or a v1 marker.
_ORIGIN_FIELDS = frozenset({
    'scope', 'dispatch_key', 'step_id', 'attempt', 'execution_operation_ref',
    'binding_bytes_digest', 'binding_record_digest',
    'expected_dispatch_version', 'expected_acp_revision'})
_CONTINUATION_FIELDS = frozenset({
    'schema_version', 'origin', 'reservation_origin', 'causal_operation_id',
    'failure_evidence_ref', 'acp_observation_ref', 'acp_revision',
    'stop_proof_ref', 'release_proof_ref', 'semantic_prompt_digest',
    'successor_binding_record_digest', 'digest'})


def _continuation_refused():
    raise ReferenceError('INVALID_DISPATCH_CONTINUATION')


def _decode_origin(value):
    require_object(value, _ORIGIN_FIELDS, 'INVALID_DISPATCH_CONTINUATION')
    # Version fields are strict ints here; a bool or a float is refused rather
    # than coerced (the value layer checks the range).
    for key in ('attempt', 'expected_dispatch_version', 'expected_acp_revision'):
        if type(value[key]) is not int:
            _continuation_refused()
    return DispatchOriginRef(
        scope=decode_scope(value['scope']),
        dispatch_key=value['dispatch_key'],
        step_id=value['step_id'],
        attempt=value['attempt'],
        execution_operation_ref=value['execution_operation_ref'],
        binding_bytes_digest=decode_digest(value['binding_bytes_digest']),
        binding_record_digest=decode_digest(value['binding_record_digest']),
        expected_dispatch_version=value['expected_dispatch_version'],
        expected_acp_revision=value['expected_acp_revision'])


def encode_continuation(continuation):
    if type(continuation) is not DispatchContinuation:
        _continuation_refused()
    return canonical_bytes(continuation.projection() | {'digest': asdict(continuation.digest)})


def decode_continuation(raw):
    value = canonical_value(raw)
    if type(value) is not dict:
        _continuation_refused()
    version = value.get('schema_version')
    if type(version) is not int or version != CONTINUATION_SCHEMA_VERSION:
        _continuation_refused()
    require_object(value, _CONTINUATION_FIELDS, 'INVALID_DISPATCH_CONTINUATION')
    if type(value['acp_revision']) is not int:
        _continuation_refused()
    continuation = DispatchContinuation(
        origin=_decode_origin(value['origin']),
        reservation_origin=_decode_origin(value['reservation_origin']),
        causal_operation_id=value['causal_operation_id'],
        failure_evidence_ref=decode_blob_ref(value['failure_evidence_ref']),
        acp_observation_ref=decode_blob_ref(value['acp_observation_ref']),
        acp_revision=value['acp_revision'],
        stop_proof_ref=value['stop_proof_ref'],
        release_proof_ref=value['release_proof_ref'],
        semantic_prompt_digest=decode_digest(value['semantic_prompt_digest']),
        successor_binding_record_digest=decode_digest(value['successor_binding_record_digest']))
    if continuation.digest != decode_digest(value['digest']) or encode_continuation(continuation) != raw:
        _continuation_refused()
    return continuation

"""Exact immutable step binding codec; supplied digest is never trusted."""
from dataclasses import asdict,fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import canonical_value,require_object,decode_scope,decode_digest,decode_blob_ref,decode_tuple
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.ref_codec import decode_approval_ref
from ..packages.codec import decode_package_ref
from .dispatch import DispatchBinding


def encode_dispatch(binding):
    return canonical_bytes(binding.projection()|{'digest':asdict(binding.digest)})


def decode_dispatch(raw):
    value=canonical_value(raw);require_object(value,{f.name for f in fields(DispatchBinding)},'INVALID_DISPATCH_BINDING')
    def pair(item):
        if type(item) is not list or len(item)!=2:raise ReferenceError('INVALID_DISPATCH_BINDING')
        return tuple(item)
    kwargs=dict(value);kwargs.pop('digest')
    kwargs.update(scope=decode_scope(value['scope']),package_ref=decode_package_ref(value['package_ref']),
        approval_ref=decode_approval_ref(value['approval_ref']),intent_digest=decode_digest(value['intent_digest']),
        prompt_ref=decode_blob_ref(value['prompt_ref']),prompt_input_digest=decode_digest(value['prompt_input_digest']),
        unit_ref_bytes=canonical_bytes(value['unit_ref_bytes']),
        action_instances=decode_tuple(value['action_instances'],pair,'INVALID_DISPATCH_BINDING'),
        required_results=decode_tuple(value['required_results'],lambda x:x,'INVALID_DISPATCH_BINDING'))
    binding=DispatchBinding(**kwargs)
    if binding.digest!=decode_digest(value['digest']) or encode_dispatch(binding)!=raw:raise ReferenceError('INVALID_DISPATCH_BINDING')
    return binding

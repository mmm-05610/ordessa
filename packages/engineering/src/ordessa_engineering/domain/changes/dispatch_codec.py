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

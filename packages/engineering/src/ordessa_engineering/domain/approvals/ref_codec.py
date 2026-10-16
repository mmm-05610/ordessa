"""Closed exact approval grant-reference decoder."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ApprovalRef

def decode_approval_ref(value):
    require_object(value, {'kind','realm_id','project_id','approval_id','grant_digest'}, 'INVALID_SCHEMA')
    if value['kind'] != 'approval':
        raise ReferenceError('INVALID_SCHEMA')
    return ApprovalRef(value['realm_id'], value['project_id'], value['approval_id'],
                       decode_digest(value['grant_digest']))

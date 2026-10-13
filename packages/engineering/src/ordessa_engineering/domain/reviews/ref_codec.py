"""Closed exact review-reference decoder."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ReviewRef

def decode_review_ref(value):
    require_object(value, {'kind','realm_id','project_id','review_id','digest'}, 'INVALID_SCHEMA')
    if value['kind'] != 'review':
        raise ReferenceError('INVALID_SCHEMA')
    return ReviewRef(value['realm_id'], value['project_id'], value['review_id'], decode_digest(value['digest']))

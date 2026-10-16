"""Closed exact proposal-reference decoder."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ProposalRef

def decode_proposal_ref(value):
    require_object(value, {'kind','realm_id','project_id','change_id','proposal_id','digest'}, code='INVALID_REVISION')
    if value['kind'] != 'proposal':
        raise ReferenceError('INVALID_SCHEMA')
    return ProposalRef(value['realm_id'],value['project_id'],value['change_id'],value['proposal_id'],decode_digest(value['digest']))

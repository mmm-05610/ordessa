"""Closed review target decoders; accepted representation is not resolver support."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.artifacts.ref_codec import decode_artifact_ref
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.changes.baseline_codec import decode_repository_ref
from .refs import SubmissionRef
from .targets import Target, TargetSet

def decode_subject_ref(value):
    if type(value) is not dict or type(value.get('kind')) is not str:
        raise ReferenceError('INVALID_SCHEMA')
    parsers = {'artifact_revision': decode_artifact_ref, 'proposal': decode_proposal_ref,
               'repository_snapshot': decode_repository_ref}
    if value['kind'] == 'submission':
        require_object(value, {'kind','realm_id','project_id','submission_id','digest'}, 'INVALID_SCHEMA')
        return SubmissionRef(value['realm_id'], value['project_id'], value['submission_id'], decode_digest(value['digest']))
    parser = parsers.get(value['kind'])
    if parser is None:
        raise ReferenceError('INVALID_SCHEMA')
    return parser(value)


def decode_target(value):
    require_object(value, {'role','ref'}, 'INVALID_SCHEMA')
    return Target(value['role'], decode_subject_ref(value['ref']))


def decode_target_set(value):
    require_object(value, {'targets','digest'}, 'INVALID_SCHEMA')
    result = TargetSet(decode_tuple(value['targets'], decode_target, 'INVALID_SCHEMA', maximum=None))
    if result.digest != decode_digest(value['digest']):
        raise ReferenceError('DIGEST_MISMATCH')
    return result

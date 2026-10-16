"""Closed captured repository-baseline decoder; no repository access."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .baselines import RepositorySnapshotRef

def decode_repository_ref(value):
    require_object(value, {'kind','realm_id','project_id','repository_id','vcs','commit_id','tree_digest','dirty_overlay_digest'}, code='INVALID_REVISION')
    if value['kind'] != 'repository_snapshot':
        raise ReferenceError('INVALID_SCHEMA')
    return RepositorySnapshotRef(value['realm_id'],value['project_id'],value['repository_id'],value['vcs'],
        value['commit_id'],decode_digest(value['tree_digest']),None if value['dirty_overlay_digest'] is None else decode_digest(value['dirty_overlay_digest']))

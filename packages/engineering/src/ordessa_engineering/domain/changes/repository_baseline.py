"""Finite content manifest for an Engineering repository baseline.

The tree digest is Ordessa's manifest digest, not a Git-native tree object ID.
This domain value does not inspect a checkout or verify blob bytes; the calling
application must read bytes through the same BlobStore authority and verify each
BlobRef digest and byte length before sealing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Literal

from ordessa_infrastructure.encoding import canonical_bytes

from ..common.models.identity import Scope
from ..common.models.refs import BlobRef
from ..common.models.values import Digest, normalized_path, validate_id, validate_items
from ..common.outcomes.diagnostics import ReferenceError
from .baselines import RepositoryId, RepositorySnapshotRef


MAX_REPOSITORY_FILES = 4096
TREE_MANIFEST_SCHEMA = 'ordessa.repository-file-manifest/1'


@dataclass(frozen=True)
class RepositoryFile:
    """One normalized path and its content-addressed file blob."""
    path: str
    blob_ref: BlobRef

    def __post_init__(self):
        normalized_path(self.path)
        if type(self.blob_ref) is not BlobRef:
            raise ReferenceError('INVALID_REPOSITORY_FILE')


@dataclass(frozen=True)
class RepositoryBaseline:
    """Exact existing snapshot ref plus the finite manifest that defines its tree digest."""
    ref: RepositorySnapshotRef
    files: tuple[RepositoryFile, ...]

    def __post_init__(self):
        if type(self.ref) is not RepositorySnapshotRef:
            raise ReferenceError('INVALID_REPOSITORY_BASELINE')
        validate_items(self.files, RepositoryFile)
        if len(self.files) > MAX_REPOSITORY_FILES:
            raise ReferenceError('REPOSITORY_MANIFEST_TOO_LARGE')
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(paths)):
            raise ReferenceError('REPOSITORY_MANIFEST_NOT_SORTED')
        if len(paths) != len(set(paths)):
            raise ReferenceError('REPOSITORY_PATH_DUPLICATE')
        if _has_file_prefix_conflict(paths):
            raise ReferenceError('REPOSITORY_PATH_FILE_PREFIX_CONFLICT')
        _validate_content_metadata(self.files)
        expected = _tree_digest(self.files)
        if self.ref.tree_digest != expected:
            raise ReferenceError('REPOSITORY_TREE_DIGEST_MISMATCH')


def _validate_content_metadata(files: tuple[RepositoryFile, ...]) -> None:
    """The same content digest cannot carry contradictory size/media metadata."""
    by_digest: dict[tuple[str, str], tuple[int, str]] = {}
    for item in files:
        blob = item.blob_ref
        key = (blob.digest.algorithm, blob.digest.hex)
        metadata = (blob.byte_length, blob.media_type)
        previous = by_digest.setdefault(key, metadata)
        if previous != metadata:
            raise ReferenceError('REPOSITORY_BLOB_METADATA_MISMATCH')


def _has_file_prefix_conflict(paths: tuple[str, ...]) -> bool:
    present = set(paths)
    return any('/'.join(path.split('/')[:index]) in present
               for path in paths for index in range(1, len(path.split('/'))))


def _manifest_projection(files: tuple[RepositoryFile, ...]) -> dict:
    return {
        'schema': TREE_MANIFEST_SCHEMA,
        'files': [
            {'path': item.path,
             'digest': {'algorithm': item.blob_ref.digest.algorithm,
                        'hex': item.blob_ref.digest.hex},
             'byte_length': item.blob_ref.byte_length,
             'media_type': item.blob_ref.media_type}
            for item in files
        ],
    }


def _tree_digest(files: tuple[RepositoryFile, ...]) -> Digest:
    payload = canonical_bytes(_manifest_projection(files))
    return Digest('sha256', hashlib.sha256(payload).hexdigest())


def seal_repository_baseline(scope: Scope, repository_id: str, vcs: Literal['git', 'none'],
                             commit_id: str | None, files: tuple[RepositoryFile, ...],
                             dirty_overlay_digest: Digest | None = None) -> RepositoryBaseline:
    """Build the current RepositorySnapshotRef from a sorted content manifest.

    ``dirty_overlay_digest`` is caller-supplied evidence identity; this pure rule
    preserves it and does not infer whether a Git worktree is dirty.
    """
    if type(scope) is not Scope:
        raise ReferenceError('REPOSITORY_SCOPE_REQUIRED')
    validate_id(repository_id)
    if type(vcs) is not str or vcs not in {'git', 'none'}:
        raise ReferenceError('INVALID_REPOSITORY_VCS')
    if vcs == 'none' and commit_id is not None:
        raise ReferenceError('INVALID_REPOSITORY_COMMIT')
    if commit_id is not None and (type(commit_id) is not str
                                  or re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit_id) is None):
        raise ReferenceError('INVALID_REPOSITORY_COMMIT')
    if dirty_overlay_digest is not None and type(dirty_overlay_digest) is not Digest:
        raise ReferenceError('INVALID_REPOSITORY_OVERLAY_DIGEST')
    validate_items(files, RepositoryFile)
    if len(files) > MAX_REPOSITORY_FILES:
        raise ReferenceError('REPOSITORY_MANIFEST_TOO_LARGE')
    _validate_content_metadata(files)
    ordered = tuple(sorted(files, key=lambda item: item.path))
    paths = tuple(item.path for item in ordered)
    if len(paths) != len(set(paths)):
        raise ReferenceError('REPOSITORY_PATH_DUPLICATE')
    if _has_file_prefix_conflict(paths):
        raise ReferenceError('REPOSITORY_PATH_FILE_PREFIX_CONFLICT')
    ref = RepositorySnapshotRef(
        scope.realm_id, scope.project_id, RepositoryId(repository_id), vcs,
        commit_id, _tree_digest(ordered), dirty_overlay_digest)
    return RepositoryBaseline(ref, ordered)


__all__ = ['RepositoryFile', 'RepositoryBaseline', 'seal_repository_baseline',
           'MAX_REPOSITORY_FILES', 'TREE_MANIFEST_SCHEMA']

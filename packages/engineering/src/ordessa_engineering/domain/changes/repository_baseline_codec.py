"""Closed canonical codec for RepositoryBaseline; no repository access."""
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes

from ..common.mechanisms.codec import canonical_value, decode_blob_ref, require_object
from ..common.outcomes.diagnostics import ReferenceError
from .baseline_codec import decode_repository_ref
from .repository_baseline import RepositoryBaseline, RepositoryFile


MAX_REPOSITORY_BASELINE_BYTES = 2 * 1024 * 1024


def repository_baseline_projection(value: RepositoryBaseline) -> dict:
    if type(value) is not RepositoryBaseline:
        raise ReferenceError('INVALID_REPOSITORY_BASELINE')
    return {
        'schema': 'ordessa.repository-baseline/1',
        'ref': asdict(value.ref),
        'files': [{'path': item.path, 'blob_ref': asdict(item.blob_ref)} for item in value.files],
    }


def encode_repository_baseline(value: RepositoryBaseline) -> bytes:
    raw = canonical_bytes(repository_baseline_projection(value))
    if len(raw) > MAX_REPOSITORY_BASELINE_BYTES:
        raise ReferenceError('REPOSITORY_BASELINE_TOO_LARGE')
    return raw


def decode_repository_baseline(raw: bytes) -> RepositoryBaseline:
    try:
        value = canonical_value(raw, maximum=MAX_REPOSITORY_BASELINE_BYTES)
        require_object(value, {'schema', 'ref', 'files'}, 'INVALID_REPOSITORY_BASELINE')
        if value['schema'] != 'ordessa.repository-baseline/1':
            raise ReferenceError('INVALID_REPOSITORY_BASELINE')
        files = value['files']
        if type(files) is not list or len(files) > 4096:
            raise ReferenceError('INVALID_REPOSITORY_BASELINE')
        decoded = []
        for item in files:
            require_object(item, {'path', 'blob_ref'}, 'INVALID_REPOSITORY_FILE')
            decoded.append(RepositoryFile(item['path'], decode_blob_ref(item['blob_ref'])))
        record = RepositoryBaseline(decode_repository_ref(value['ref']), tuple(decoded))
        if encode_repository_baseline(record) != raw:
            raise ReferenceError('INVALID_REPOSITORY_BASELINE')
        return record
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise ReferenceError('INVALID_REPOSITORY_BASELINE') from None


__all__ = ['repository_baseline_projection', 'encode_repository_baseline',
           'decode_repository_baseline', 'MAX_REPOSITORY_BASELINE_BYTES']

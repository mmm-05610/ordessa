"""Pure repository baseline manifest rules; blob bytes are verified by the application."""
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.domain.changes.repository_baseline import (
    RepositoryBaseline, RepositoryFile, seal_repository_baseline,
)
from ordessa_engineering.domain.changes.repository_baseline_codec import (
    decode_repository_baseline, encode_repository_baseline,
)
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError


SCOPE = Scope('realm-a', 'project-a')


def _blob(data: bytes, *, media_type='application/octet-stream', locator='fixture'):
    return BlobRef(Digest('sha256', hashlib.sha256(data).hexdigest()), len(data), media_type, locator)


def _file(path, data, *, media_type='application/octet-stream', locator='fixture'):
    return RepositoryFile(path, _blob(data, media_type=media_type, locator=locator))


def test_manifest_is_sorted_and_digest_ignores_blob_locator():
    first = seal_repository_baseline(SCOPE, 'repo-a', 'git', 'a' * 40,
                                     (_file('z.txt', b'z'), _file('a.txt', b'a', locator='one')))
    second = seal_repository_baseline(SCOPE, 'repo-a', 'git', 'a' * 40,
                                      (_file('a.txt', b'a', locator='moved'), _file('z.txt', b'z')))
    assert tuple(item.path for item in first.files) == ('a.txt', 'z.txt')
    assert first.ref.tree_digest == second.ref.tree_digest
    assert first.ref.commit_id == 'a' * 40


def test_tree_digest_changes_with_file_content_or_media_type():
    baseline = seal_repository_baseline(SCOPE, 'repo-a', 'git', None, (_file('a.txt', b'a'),))
    changed_bytes = seal_repository_baseline(SCOPE, 'repo-a', 'git', None, (_file('a.txt', b'b'),))
    changed_media = seal_repository_baseline(SCOPE, 'repo-a', 'git', None,
        (_file('a.txt', b'a', media_type='text/plain'),))
    assert baseline.ref.tree_digest != changed_bytes.ref.tree_digest
    assert baseline.ref.tree_digest != changed_media.ref.tree_digest


def test_duplicate_and_non_normalized_paths_are_rejected():
    with pytest.raises(ReferenceError, match='REPOSITORY_PATH_DUPLICATE'):
        seal_repository_baseline(SCOPE, 'repo-a', 'none', None,
                                 (_file('same', b'a'), _file('same', b'b')))
    with pytest.raises(ReferenceError, match='INVALID_PATH'):
        RepositoryFile('../escape', _blob(b'x'))
    with pytest.raises(ReferenceError, match='INVALID_PATH'):
        RepositoryFile('a\\b', _blob(b'x'))
    with pytest.raises(ReferenceError, match='REPOSITORY_PATH_FILE_PREFIX_CONFLICT'):
        seal_repository_baseline(SCOPE, 'repo-a', 'none', None,
                                 (_file('a', b'a'), _file('a/b', b'b')))


def test_empty_manifest_is_a_valid_empty_tree():
    baseline = seal_repository_baseline(SCOPE, 'repo-a', 'git', None, ())
    assert baseline.files == ()
    assert baseline.ref.tree_digest.algorithm == 'sha256'


def test_same_content_digest_with_inconsistent_blob_metadata_is_rejected():
    content = b'same bytes'
    original = _blob(content, media_type='text/plain')
    contradictory = BlobRef(original.digest, original.byte_length, 'application/octet-stream', 'other')
    with pytest.raises(ReferenceError, match='REPOSITORY_BLOB_METADATA_MISMATCH'):
        seal_repository_baseline(SCOPE, 'repo-a', 'none', None,
            (RepositoryFile('a.txt', original), RepositoryFile('b.txt', contradictory)))


def test_snapshot_ref_tree_digest_cannot_be_self_asserted():
    baseline = seal_repository_baseline(SCOPE, 'repo-a', 'git', None, (_file('a', b'a'),))
    forged = replace(baseline.ref, tree_digest=Digest('sha256', 'f' * 64))
    with pytest.raises(ReferenceError, match='REPOSITORY_TREE_DIGEST_MISMATCH'):
        RepositoryBaseline(forged, baseline.files)


def test_vcs_commit_and_dirty_overlay_keep_distinct_meanings():
    overlay = Digest('sha256', 'b' * 64)
    baseline = seal_repository_baseline(SCOPE, 'repo-a', 'git', 'c' * 40,
                                        (_file('a', b'a'),), overlay)
    assert baseline.ref.commit_id == 'c' * 40
    assert baseline.ref.dirty_overlay_digest == overlay
    with pytest.raises(ReferenceError, match='INVALID_REPOSITORY_COMMIT'):
        seal_repository_baseline(SCOPE, 'repo-a', 'none', 'c' * 40, ())
    with pytest.raises(ReferenceError, match='INVALID_REPOSITORY_COMMIT'):
        seal_repository_baseline(SCOPE, 'repo-a', 'git', 'not-a-commit', ())


def test_closed_codec_roundtrips_and_recomputes_manifest_digest():
    original = seal_repository_baseline(SCOPE, 'repo-a', 'git', None,
                                        (_file('src/main.py', b'print(1)'),))
    raw = encode_repository_baseline(original)
    restored = decode_repository_baseline(raw)
    assert restored == original
    tampered = raw.replace(b'"hex":"' + original.ref.tree_digest.hex.encode(),
                           b'"hex":"' + ('f' * 64).encode())
    with pytest.raises(ReferenceError):
        decode_repository_baseline(tampered)

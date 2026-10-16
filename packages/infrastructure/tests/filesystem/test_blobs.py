import hashlib
import os
from pathlib import Path

import pytest

from ordessa_infrastructure.filesystem.blobs import ObjectStore
from ordessa_infrastructure.filesystem import blobs


@pytest.mark.parametrize('content', [b'', b'\x00\xffsynthetic', '中文\n'.encode()])
def test_explicit_root_shard_roundtrip_and_repeat_publish(tmp_path, content):
    root = tmp_path / 'caller-choice'
    store = ObjectStore(root)
    assert store.root == root.resolve() and not root.exists()
    result = store.publish(content)
    expected = 'sha256:' + hashlib.sha256(content).hexdigest()
    assert (result.digest, result.size) == (expected, len(content))
    assert result.path == root / expected[7:9] / expected[7:]
    assert store.path_for(expected) == result.path
    assert store.read(expected) == content
    assert ObjectStore(root).publish(content) == result
    assert list(result.path.parent.glob('publish-*')) == []


def test_existing_corruption_is_refused_without_overwrite(tmp_path):
    store = ObjectStore(tmp_path)
    result = store.publish(b'original')
    result.path.write_bytes(b'changed')
    with pytest.raises(IOError, match='existing immutable object failed digest verification'):
        store.publish(b'original')
    with pytest.raises(IOError, match='immutable object digest mismatch'):
        store.read(result.digest)
    assert result.path.read_bytes() == b'changed'


@pytest.mark.parametrize('digest', ['', 'sha1:' + '0'*64, 'sha256:' + '0'*63])
def test_original_invalid_digest_errors_are_preserved(tmp_path, digest):
    with pytest.raises(ValueError, match='invalid object digest'):
        ObjectStore(tmp_path).path_for(digest)


def test_replace_failure_closes_fd_preserves_target_absence_and_cleans_owned_temp(tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    opened = []
    original = blobs.tempfile.mkstemp

    def capture(*args, **kwargs):
        fd, path = original(*args, **kwargs)
        opened.append(fd)
        return fd, path

    def fail(*args):
        raise OSError('controlled replace failure')

    monkeypatch.setattr(blobs.tempfile, 'mkstemp', capture)
    monkeypatch.setattr(blobs.os, 'replace', fail)
    with pytest.raises(OSError, match='controlled replace failure'):
        store.publish(b'synthetic')
    for fd in opened:
        with pytest.raises(OSError): os.fstat(fd)
    assert list(tmp_path.rglob('publish-*')) == []
    assert not store.path_for('sha256:' + hashlib.sha256(b'synthetic').hexdigest()).exists()


def test_postreplace_verification_failure_retains_target(tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    replace = os.replace

    def corrupt(temporary, target):
        replace(temporary, target)
        Path(target).write_bytes(b'corrupted')

    monkeypatch.setattr(blobs.os, 'replace', corrupt)
    with pytest.raises(IOError, match='published immutable object failed verification'):
        store.publish(b'original')
    target = store.path_for('sha256:' + hashlib.sha256(b'original').hexdigest())
    assert target.read_bytes() == b'corrupted'


@pytest.mark.parametrize('digest', [None, 17, b'sha256:' + b'0' * 64, 'sha256:' + 'A' * 64, 'sha256:/' + 'x' * 63])
def test_nonhex_type_or_pathlike_digest_cannot_escape_storage_root(tmp_path, digest):
    store = ObjectStore(tmp_path / 'explicit-root')
    with pytest.raises(ValueError, match='invalid object digest'):
        store.path_for(digest)
    assert not store.root.exists()

import os
import stat

import pytest

from ordessa_infrastructure.filesystem import (
    PublicationError,
    PublicationStage,
    UnsafePathError,
    open_directory_nofollow,
    publish_file,
)
from ordessa_infrastructure.filesystem import publication as publication_module


def _root(tmp_path):
    return open_directory_nofollow(tmp_path)


def test_publish_creates_target_and_cleans_temp(tmp_path):
    root = _root(tmp_path)
    try:
        result = publish_file(root, "final.json", b'{"ok":true}', temp_name="final.tmp", mode=0o600)
        assert result.target == "final.json"
        assert (tmp_path / "final.json").read_bytes() == b'{"ok":true}'
        assert not (tmp_path / "final.tmp").exists()
        assert stat.S_IMODE((tmp_path / "final.json").stat().st_mode) == 0o600
    finally:
        os.close(root)


def test_publish_replaces_existing_target_atomically(tmp_path):
    root = _root(tmp_path)
    (tmp_path / "final").write_bytes(b"old")
    try:
        publish_file(root, "final", b"new", temp_name="final.tmp")
        assert (tmp_path / "final").read_bytes() == b"new"
        assert not (tmp_path / "final.tmp").exists()
    finally:
        os.close(root)


def test_write_failure_leaves_target_unchanged(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (tmp_path / "final").write_bytes(b"old")
    try:
        def fail_write(fd, data):
            raise OSError("controlled write failure")

        monkeypatch.setattr(publication_module.os, "write", fail_write)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"new", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.WRITE.value
        assert error.value.target_may_have_changed is False
        assert (tmp_path / "final").read_bytes() == b"old"
        assert (tmp_path / "final.tmp").read_bytes() == b""
    finally:
        os.close(root)


def test_file_fsync_failure_leaves_target_unchanged(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (tmp_path / "final").write_bytes(b"old")
    real_fsync = os.fsync
    try:
        def fail_file_fsync(fd):
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("controlled file fsync failure")
            real_fsync(fd)

        monkeypatch.setattr(publication_module.os, "fsync", fail_file_fsync)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"new", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.FILE_FSYNC.value
        assert error.value.target_may_have_changed is False
        assert (tmp_path / "final").read_bytes() == b"old"
        assert (tmp_path / "final.tmp").read_bytes() == b"new"
    finally:
        monkeypatch.undo()
        os.close(root)


def test_replace_failure_leaves_target_unchanged(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (tmp_path / "final").write_bytes(b"old")
    try:
        def fail_rename(*args, **kwargs):
            raise OSError("controlled rename failure")

        monkeypatch.setattr(publication_module.os, "rename", fail_rename)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"new", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.REPLACE.value
        assert error.value.target_may_have_changed is False
        assert (tmp_path / "final").read_bytes() == b"old"
        assert (tmp_path / "final.tmp").read_bytes() == b"new"
    finally:
        os.close(root)


def test_directory_fsync_failure_after_replace_is_unknown_and_not_rolled_back(tmp_path, monkeypatch):
    """Replace succeeds, then directory fsync fails: target is changed, kept.

    The mechanism must not claim a rollback and must not delete the final file.
    """
    root = _root(tmp_path)
    (tmp_path / "final").write_bytes(b"old")
    real_fsync = os.fsync
    try:
        def fail_dir_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("controlled directory fsync failure")
            real_fsync(fd)

        monkeypatch.setattr(publication_module.os, "fsync", fail_dir_fsync)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"new", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.DIRECTORY_FSYNC.value
        assert error.value.target_may_have_changed is True
        # The final file is NOT deleted and carries the new content.
        assert (tmp_path / "final").exists()
        assert (tmp_path / "final").read_bytes() == b"new"
        assert not (tmp_path / "final.tmp").exists()
    finally:
        monkeypatch.undo()
        os.close(root)


def test_invalid_names_are_refused_before_any_io(tmp_path):
    root = _root(tmp_path)
    try:
        for bad in ("/abs", "..", "a/b", "a\x00b", "", "."):
            with pytest.raises(UnsafePathError):
                publish_file(root, bad, b"x", temp_name="t.tmp")
            with pytest.raises(UnsafePathError):
                publish_file(root, "final", b"x", temp_name=bad)
        with pytest.raises(ValueError):
            publish_file(root, "same", b"x", temp_name="same")
        # nothing was created by any refused call
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(root)


def test_cleanup_never_deletes_someone_elses_replaced_temp(tmp_path, monkeypatch):
    """If a same-named file is swapped in before our failure cleanup runs, it
    must survive: failure paths never remove a name."""
    root = _root(tmp_path)
    try:
        def swap_then_fail(src, dst, *args, **kwargs):
            # Someone removes our temp and puts a different inode in its place.
            os.unlink(tmp_path / "final.tmp")
            (tmp_path / "final.tmp").write_bytes(b"theirs")
            raise OSError("controlled rename failure")

        monkeypatch.setattr(publication_module.os, "rename", swap_then_fail)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"ours", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.REPLACE.value
        assert (tmp_path / "final.tmp").read_bytes() == b"theirs"
        assert not (tmp_path / "final").exists()
    finally:
        os.close(root)


def test_zero_byte_write_does_not_spin(tmp_path, monkeypatch):
    root = _root(tmp_path)
    try:
        monkeypatch.setattr(publication_module.os, "write", lambda fd, data: 0)
        with pytest.raises(PublicationError) as error:
            publish_file(root, "final", b"payload", temp_name="final.tmp")
        assert error.value.stage == PublicationStage.WRITE.value
        assert not (tmp_path / "final").exists()
        assert (tmp_path / "final.tmp").read_bytes() == b""
    finally:
        os.close(root)


def test_short_writes_are_completed_and_empty_payload_is_valid(tmp_path, monkeypatch):
    root = _root(tmp_path)
    real_write = os.write
    try:
        monkeypatch.setattr(publication_module.os, 'write', lambda fd, data: real_write(fd, data[:2]))
        publish_file(root, 'final', b'abcdef', temp_name='temp')
        assert (tmp_path / 'final').read_bytes() == b'abcdef'
        publish_file(root, 'empty', b'', temp_name='empty.tmp')
        assert (tmp_path / 'empty').read_bytes() == b''
        assert not (tmp_path / 'temp').exists()
        assert not (tmp_path / 'empty.tmp').exists()
        os.fstat(root)  # borrowed root is still open
    finally:
        os.close(root)


def test_interrupted_write_is_staged_and_releases_owned_fd(tmp_path, monkeypatch):
    root = _root(tmp_path)
    created = []
    original_create = publication_module.create_exclusive_at

    def capture(*args, **kwargs):
        fd = original_create(*args, **kwargs)
        created.append(fd)
        return fd

    def interrupt(fd, data):
        raise KeyboardInterrupt('controlled interruption')

    try:
        monkeypatch.setattr(publication_module, 'create_exclusive_at', capture)
        monkeypatch.setattr(publication_module.os, 'write', interrupt)
        with pytest.raises(PublicationError) as error:
            publish_file(root, 'final', b'new', temp_name='temp')
        assert error.value.stage == PublicationStage.WRITE.value
        assert error.value.target_may_have_changed is False
        assert isinstance(error.value.__cause__, KeyboardInterrupt)
        assert (tmp_path / 'temp').read_bytes() == b''
        assert not (tmp_path / 'final').exists()
        with pytest.raises(OSError):
            os.fstat(created[0])
        os.fstat(root)
    finally:
        os.close(root)


def test_removed_stat_unlink_cleanup_race_is_unreachable(tmp_path, monkeypatch):
    """Original failing schedule: replace temp after stat, before unlink.

    The repaired failure path has no name lookup/delete, eliminating the
    scheduling point; a second inode check would still fail this counterexample.
    """
    root = _root(tmp_path)
    real_stat = os.stat
    real_unlink = os.unlink
    observations = []
    removed = []

    def stat_then_swap(name, *args, **kwargs):
        info = real_stat(name, *args, **kwargs)
        if name == 'temp' and kwargs.get('dir_fd') == root:
            observations.append(name)
            real_unlink(tmp_path / 'temp')
            (tmp_path / 'temp').write_bytes(b'theirs')
        return info

    def observe_unlink(name, *args, **kwargs):
        removed.append(name)
        return real_unlink(name, *args, **kwargs)

    try:
        monkeypatch.setattr(publication_module.os, 'stat', stat_then_swap)
        monkeypatch.setattr(publication_module.os, 'unlink', observe_unlink)
        monkeypatch.setattr(publication_module.os, 'write', lambda *args: (_ for _ in ()).throw(OSError('controlled write failure')))
        with pytest.raises(PublicationError) as error:
            publish_file(root, 'final', b'ours', temp_name='temp')
        assert error.value.stage == PublicationStage.WRITE.value
        assert error.value.target_may_have_changed is False
        assert (tmp_path / 'temp').exists(), 'cleanup deleted replacement between stat and unlink'
        assert observations == [] and removed == []
        assert (tmp_path / 'temp').read_bytes() == b''
        assert not (tmp_path / 'final').exists()
    finally:
        monkeypatch.undo()
        os.close(root)


@pytest.mark.parametrize('failure_stage', ['write', 'file_fsync', 'replace'])
def test_failure_never_deletes_or_renames_a_replaced_temporary(tmp_path, monkeypatch, failure_stage):
    root = _root(tmp_path)
    (tmp_path / 'final').write_bytes(b'old')
    real_unlink = os.unlink
    real_stat = os.stat
    real_rename = os.rename
    real_fsync = os.fsync
    opened = []
    original_create = publication_module.create_exclusive_at

    def capture_create(*args, **kwargs):
        fd = original_create(*args, **kwargs)
        opened.append(fd)
        return fd

    def swap_and_fail():
        real_unlink(tmp_path / 'temp')
        (tmp_path / 'temp').write_bytes(b'theirs')
        raise OSError('controlled failure with replacement')

    def forbid_name_cleanup(*args, **kwargs):
        raise AssertionError('failure performed pathname cleanup')

    def guard_stat(name, *args, **kwargs):
        if name == 'temp' and kwargs.get('dir_fd') == root:
            forbid_name_cleanup()
        return real_stat(name, *args, **kwargs)

    def controlled_fsync(fd):
        if failure_stage == 'file_fsync':
            swap_and_fail()
        real_fsync(fd)

    def controlled_rename(src, dst, *args, **kwargs):
        if failure_stage == 'replace':
            swap_and_fail()
        return real_rename(src, dst, *args, **kwargs)

    try:
        monkeypatch.setattr(publication_module, 'create_exclusive_at', capture_create)
        monkeypatch.setattr(publication_module.os, 'stat', guard_stat)
        monkeypatch.setattr(publication_module.os, 'unlink', forbid_name_cleanup)
        monkeypatch.setattr(publication_module.os, 'fsync', controlled_fsync)
        monkeypatch.setattr(publication_module.os, 'rename', controlled_rename)
        if failure_stage == 'write':
            monkeypatch.setattr(publication_module.os, 'write', lambda *args: swap_and_fail())
        with pytest.raises(PublicationError) as error:
            publish_file(root, 'final', b'ours', temp_name='temp')
        assert error.value.stage == failure_stage
        assert error.value.target_may_have_changed is False
        assert isinstance(error.value.__cause__, OSError)
        assert (tmp_path / 'temp').read_bytes() == b'theirs'
        assert (tmp_path / 'final').read_bytes() == b'old'
        with pytest.raises(OSError):
            os.fstat(opened[0])
        os.fstat(root)
    finally:
        monkeypatch.undo()
        os.close(root)


def test_partial_write_residue_blocks_same_name_retry_without_changing_target(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (tmp_path / 'final').write_bytes(b'old')
    real_write = os.write
    writes = []

    def partial_then_fail(fd, data):
        if not writes:
            writes.append(True)
            return real_write(fd, data[:2])
        raise OSError('controlled interrupted partial write')

    try:
        monkeypatch.setattr(publication_module.os, 'write', partial_then_fail)
        with pytest.raises(PublicationError) as error:
            publish_file(root, 'final', b'abcdef', temp_name='temp')
        assert error.value.stage == 'write'
        assert error.value.target_may_have_changed is False
        assert (tmp_path / 'temp').read_bytes() == b'ab'
        assert (tmp_path / 'final').read_bytes() == b'old'
        monkeypatch.undo()
        with pytest.raises(PublicationError) as retry:
            publish_file(root, 'final', b'new', temp_name='temp')
        assert retry.value.stage == 'write'
        assert retry.value.target_may_have_changed is False
        assert (tmp_path / 'temp').read_bytes() == b'ab'
        assert (tmp_path / 'final').read_bytes() == b'old'
    finally:
        monkeypatch.undo()
        os.close(root)


def test_existing_temporary_is_preserved_when_exclusive_create_refuses(tmp_path):
    root = _root(tmp_path)
    (tmp_path / 'temp').write_bytes(b'theirs')
    (tmp_path / 'final').write_bytes(b'old')
    try:
        with pytest.raises(PublicationError) as error:
            publish_file(root, 'final', b'ours', temp_name='temp')
        assert error.value.stage == 'write'
        assert error.value.target_may_have_changed is False
        assert (tmp_path / 'temp').read_bytes() == b'theirs'
        assert (tmp_path / 'final').read_bytes() == b'old'
    finally:
        os.close(root)

from pathlib import Path
import pytest

from ordessa_harness.server_acp.instance_directory import allocate_instance_directory


def test_two_allocations_are_private_distinct_and_preserve_existing_state(tmp_path):
    first = allocate_instance_directory(tmp_path)
    (first / "settings.json").write_text('{"fixture":true}')
    second = allocate_instance_directory(tmp_path)
    assert first != second
    assert first.stat().st_mode & 0o077 == second.stat().st_mode & 0o077 == 0
    assert (first / "settings.json").read_text() == '{"fixture":true}'
    assert list(second.iterdir()) == []


def test_allocator_rejects_symlink_and_shared_roots(tmp_path):
    parent = tmp_path / "harness-instances"
    parent.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        allocate_instance_directory(tmp_path)
    parent.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        allocate_instance_directory(tmp_path)
    assert list(outside.iterdir()) == []


def test_allocator_rejects_missing_and_symlinked_data_root(tmp_path):
    with pytest.raises(ValueError):
        allocate_instance_directory(tmp_path / "missing")
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        allocate_instance_directory(link)
    with pytest.raises(ValueError):
        allocate_instance_directory(Path("relative"))

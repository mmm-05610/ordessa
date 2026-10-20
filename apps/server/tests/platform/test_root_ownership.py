from pathlib import Path
import os

import pytest

from ordessa_server.composition.root_ownership import DataRootOwner, DataRootPathUnsafeError
from server_plugin_api import RootOwnershipError


def _binding(owner, root):
    store = root / "state" / "core.sqlite"
    child = root / "state" / "agent-owner" / "operations.sqlite"
    return owner.bind_owned_root(root_path=root, store_path=store, child_path=child), store, child


def test_host_refuses_existing_unmarked_root_without_adopting_it(tmp_path):
    root = tmp_path / "foreign"
    root.mkdir()
    sentinel = root / "sentinel"
    sentinel.write_bytes(b"foreign root")
    owner = DataRootOwner(root)
    with pytest.raises(RuntimeError, match="DATA_ROOT_UNOWNED"):
        owner.acquire()
    assert sentinel.read_bytes() == b"foreign root"
    assert not (root / ".agentbox-server-root").exists()
    assert not (root / "server.lock").exists()


def test_host_root_binding_tracks_marker_lock_and_path_identity(tmp_path):
    root = tmp_path / "owned"
    owner = DataRootOwner(root)
    owner.acquire()
    try:
        binding, store, child = _binding(owner, root)
        binding.validate_for(root_path=root, store_path=store, child_path=child)
        with pytest.raises(AttributeError, match="immutable"):
            binding.root_path = root / "forged"
        with pytest.raises(RootOwnershipError, match="does not match"):
            binding.validate_for(root_path=root / "other", store_path=store,
                                 child_path=child)
        with pytest.raises(DataRootPathUnsafeError):
            owner.bind_owned_root(root_path=root, store_path=store, child_path=store)

        marker = root / ".agentbox-server-root"
        replacement = root / "marker-replacement"
        replacement.write_bytes(marker.read_bytes())
        os.replace(replacement, marker)
        with pytest.raises(Exception, match="no longer current"):
            binding.validate_for(root_path=root, store_path=store, child_path=child)
    finally:
        owner.release()


def test_host_cannot_issue_binding_before_acquiring_existing_root_owner(tmp_path):
    root = tmp_path / "unacquired"
    owner = DataRootOwner(root)
    with pytest.raises(DataRootPathUnsafeError, match="not bound to this owner"):
        _binding(owner, root)
    assert not root.exists()


def test_host_root_binding_rejects_replaced_lock_path(tmp_path):
    root = tmp_path / "owned"
    owner = DataRootOwner(root)
    owner.acquire()
    binding, store, child = _binding(owner, root)
    try:
        replacement = root / "lock-replacement"
        replacement.write_bytes(b"replacement")
        os.replace(replacement, root / "server.lock")
        with pytest.raises(Exception, match="no longer current"):
            binding.validate_for(root_path=root, store_path=store, child_path=child)
    finally:
        owner.release()


def test_host_root_binding_rejects_wrong_path_and_released_lock(tmp_path):
    root = tmp_path / "owned"
    owner = DataRootOwner(root)
    owner.acquire()
    binding, store, child = _binding(owner, root)
    try:
        with pytest.raises(DataRootPathUnsafeError):
            owner.bind_owned_root(root_path=root / "other", store_path=store,
                                  child_path=child)
    finally:
        owner.release()
    with pytest.raises(Exception, match="no longer current"):
        binding.validate_for(root_path=root, store_path=store, child_path=child)


def test_host_root_binding_rechecks_store_and_child_symlink_components(tmp_path):
    root = tmp_path / "owned"
    owner = DataRootOwner(root)
    owner.acquire()
    (root / "state").mkdir(parents=True)
    binding, store, child = _binding(owner, root)
    try:
        (root / "state" / "agent-owner").symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(Exception, match="no longer current"):
            binding.validate_for(root_path=root, store_path=store, child_path=child)
    finally:
        owner.release()

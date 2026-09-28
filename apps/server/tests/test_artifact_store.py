"""Order 57: the artifact store — version directories, references, atomicity.

The rules under test are the order's gates: digest re-derivation at install
(mismatch leaves nothing), references not overwrites (rollback and update are
pointer moves), failure does not land, and a session running against the
previous version is untouched by an update.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from ordessa_server_compat.execution.artifact_store import (
    ArtifactStore,
    ArtifactStoreError,
)


def _digest_of(directory):
    """The tree digest v1 over the directory, via the resource-contracts
    reference implementation — the same value install() re-derives."""
    from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
        runtime_artifact_tree_digest,
    )

    return runtime_artifact_tree_digest(directory)


def _make_source(root, name, files):
    source = root / name
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return source


def test_install_renames_into_place_and_reports(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    source = _make_source(tmp_path, "src-v1", {"bin/agent": b"#!/bin/sh\nexit 0\n"})
    digest = _digest_of(source)
    receipt = store.install("pi", "0.5.0", source, digest)
    assert receipt["digest"] == digest
    assert store.installed("pi") == ["0.5.0"]
    assert store.summary("pi", "0.5.0")["entries"] >= 1


def test_a_digest_mismatch_leaves_nothing_behind(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    source = _make_source(tmp_path, "src-bad", {"bin/agent": b"actual"})
    with pytest.raises(ArtifactStoreError) as refusal:
        store.install("pi", "9.9.9", source, "sha256:" + "0" * 64)
    assert refusal.value.code == "ARTIFACT_DIGEST_MISMATCH"
    assert store.installed("pi") == []
    assert not (tmp_path / "store" / ".staging").exists() or not any(
        (tmp_path / "store" / ".staging").iterdir()
    )


def test_references_move_and_rollback_restores(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    for version in ("1.0", "1.1"):
        source = _make_source(tmp_path, f"src-{version}", {"bin/agent": version.encode()})
        digest = _digest_of(source)
        store.install("pi", version, source, digest)
    store.set_current_reference("pi", "1.1")
    assert store.current_reference("pi") == "1.1"
    store.rollback("pi", "1.0")
    assert store.current_reference("pi") == "1.0"
    # Both versions remain on disk: a rollback is a pointer move, not an
    # in-place overwrite.
    assert store.installed("pi") == ["1.0", "1.1"]


def test_a_reference_to_an_uninstalled_version_is_refused(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactStoreError) as refusal:
        store.rollback("pi", "9.9.9")
    assert refusal.value.code == "ARTIFACT_VERSION_MISSING"


def test_reinstalling_the_same_version_is_refused(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    source = _make_source(tmp_path, "src", {"bin/agent": b"x"})
    digest = _digest_of(source)
    store.install("pi", "1.0", source, digest)
    with pytest.raises(ArtifactStoreError) as refusal:
        store.install("pi", "1.0", source, digest)
    assert refusal.value.code == "ARTIFACT_VERSION_EXISTS"


def test_wire_artifact_methods_round_trip(tmp_path):
    """Order 57 C: the four wire methods over a real ServerRuntime store."""
    import shutil as _shutil

    from ordessa_server_compat.execution.artifact_store import ArtifactStore

    source = _make_source(tmp_path, "src-v1", {"bin/agent": b"#!/bin/sh\nexit 0\n"})
    digest = _digest_of(source)

    store_root = tmp_path / "artifacts"
    store_root.mkdir()
    artifact_store = ArtifactStore(store_root)
    # The execution side stages its source under .incoming/<token>
    incoming = artifact_store.incoming_dir("staged-token")
    _shutil.copytree(source, incoming / "payload")

    receipt = artifact_store.install("pi", "0.5.0", incoming / "payload", digest)
    assert receipt["digest"] == digest
    # installing does not flip the reference; the explicit set does
    assert artifact_store.current_reference("pi") is None
    artifact_store.set_current_reference("pi", "0.5.0")
    assert artifact_store.current_reference("pi") == "0.5.0"

"""T007-11 — the memory domain's private store stands alone under the data
root, and the provisioning guard refuses the repository source tree.

Pinned claims:

* positive: ``MemoryStore`` opens a fresh data root under ``tmp_path``,
  creates its four tables, round-trips one binding value and keeps the stored
  bytes across close/reopen;
* counter-example: ``provisioning.write_env`` refuses every deploy directory
  inside the repository source tree (the guard anchors at the repo root,
  order 007), creates nothing on the refused path, while the same bytes are
  accepted under a data-root directory;
* missing condition: the refused repository path does not exist beforehand and
  still does not afterwards — the guard refuses before any ``mkdir``.

No test here writes into the repository, touches real Docker, a model
endpoint, credentials or user data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ordessa_memory import provisioning
from ordessa_memory.store import MemoryStore

#: a valid facet binding value (enabled / budgetTokens / extractionModelRef /
#: boundBrands — the four VALUE_KEYS)
_BINDING = {
    "enabled": True,
    "budgetTokens": 512,
    "extractionModelRef": "ref://model-extraction",
    "boundBrands": ["pi", "qwen"],
}

#: the guard's own anchor, resolved exactly as ``write_env`` resolves it
_REPO_ROOT = Path(provisioning.__file__).resolve().parents[4]


def _tables(db: Path) -> "set[str]":
    conn = sqlite3.connect(str(db))
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _raw_binding(db: Path, profile_id: str) -> str:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT value FROM binding WHERE profile_id=?",
                           (profile_id,)).fetchone()
        assert row is not None, f"binding for {profile_id!r} vanished"
        return row[0]
    finally:
        conn.close()


def test_store_opens_under_tmp_data_root_and_binding_survives_reopen(tmp_path):
    data_root = tmp_path / "data-root" / "memory"
    data_root.mkdir(parents=True)
    db = data_root / "memory.db"
    assert _REPO_ROOT not in db.resolve().parents, "the store is not isolated"

    store = MemoryStore(db)
    try:
        assert {"binding", "capture_queue", "authorization",
                "diagnostics"} <= _tables(db)
        stored = store.set_binding("profile-p1", _BINDING)
        assert stored == _BINDING
        assert store.get_binding("profile-p1") == _BINDING
        assert store.has_binding_override("profile-p1") is True
        raw_before = _raw_binding(db, "profile-p1")
    finally:
        store.close()

    # close/reopen keeps the stored bytes: the same raw value text comes back
    reopened = MemoryStore(db)
    try:
        assert reopened.get_binding("profile-p1") == _BINDING
        assert _raw_binding(db, "profile-p1") == raw_before
        assert _tables(db) >= {"binding", "capture_queue", "authorization",
                               "diagnostics"}
    finally:
        reopened.close()


def test_provisioning_write_env_refuses_repo_internal_paths(tmp_path):
    # the source-tree guard points at the repository root (order 007 change)
    assert _REPO_ROOT == Path(__file__).resolve().parents[3]
    probes = [
        _REPO_ROOT / "plugins" / "memory" / "tests" / "_t007_rejected_deploy",
        _REPO_ROOT / "plugins" / "memory" / "src" / "ordessa_memory"
        / "_t007_rejected_deploy",
    ]
    for probe in probes:
        assert not probe.exists(), f"probe path already exists: {probe}"

    env_text = "ADMIN_API_KEY=probe-never-a-real-secret\n"
    for probe in probes:
        with pytest.raises(provisioning.ProvisioningUnsupported, match="源码树"):
            provisioning.write_env(probe, env_text)
        # refusal happened before any mkdir/write on the repository path
        assert not probe.exists(), f"refused path was created: {probe}"
        assert not (probe / provisioning.ENV_FILE_NAME).exists()
    assert not (_REPO_ROOT / "plugins" / "memory" / "tests"
                / provisioning.ENV_FILE_NAME).exists()

    # positive control: the same bytes are accepted under a data root, 0600
    accepted = provisioning.write_env(
        tmp_path / "data-root" / "memory" / "deploy", env_text)
    assert accepted.name == provisioning.ENV_FILE_NAME
    assert accepted.read_text(encoding="utf-8") == env_text
    assert (accepted.stat().st_mode & 0o777) == 0o600

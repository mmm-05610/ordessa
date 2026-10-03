"""G03: the import session is a state machine, and only one act publishes.

The legacy port (test_import_session.py) keeps the drift, atomicity and TTL
assertions; this file adds the remaining G03 counter-examples from
verification.md: 断块 (a session that never finished transferring),
重复 commit, and a sweep that must not eat a live or fresh session — checked
in both directions, because a sweep that deletes everything would pass the
「超时残留永久不清」 test just as well as the correct one.
"""
from __future__ import annotations

import hashlib
import os
import time

import pytest

from ordessa_skills.api.errors import ImportError_, SkillAssetError
from ordessa_skills.library.import_transfer import (
    MAX_CHUNK_BYTES,
    SESSION_TTL_SECONDS,
    ImportService,
)
from ordessa_skills.library.store import SkillRevisionStore

ASSET = "demo-skill"
MANIFEST = b"---\nname: demo-skill\ndescription: A demo.\n---\nbody\n"
SCRIPT = b"#!/bin/sh\necho never-run\n"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _files():
    return {"SKILL.md": MANIFEST, "scripts/run.sh": SCRIPT}


def _begin(service, files=None):
    files = files or _files()
    declared = [{"path": path, "bytes": len(data), "sha256": _digest(data)}
                for path, data in sorted(files.items())]
    return service.begin(request_id="r", files=declared,
                         total_bytes=sum(item["bytes"] for item in declared))


def _send(service, import_id, files=None, *, through=None):
    files = files or _files()
    for index, path in enumerate(sorted(files)):
        if through is not None and index > through:
            break
        service.chunk(import_id, index=index, payload=files[path],
                      sha256=_digest(files[path]))


# -- 断块: a session that never finished transferring -------------------------

def test_prepare_before_the_last_chunk_is_refused(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"], through=0)  # one chunk short
    with pytest.raises(ImportError_) as refusal:
        service.prepare(opened["importId"], source={"type": "local-transfer"})
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    with pytest.raises(ImportError_) as refusal:
        service.commit(opened["importId"], asset_id=ASSET, revision=1)
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    assert not (tmp_path / "assets" / "skill" / ASSET / "1").exists()


def test_commit_without_a_preview_is_refused(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"])
    with pytest.raises(ImportError_) as refusal:
        service.commit(opened["importId"], asset_id=ASSET, revision=1)
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    with pytest.raises(ImportError_) as refusal:
        service.preview(opened["importId"])
    assert refusal.value.code == "IMPORT_SESSION_INVALID"


def test_a_second_chunk_after_the_transfer_completed_is_refused(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"])
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=MANIFEST,
                      sha256=_digest(MANIFEST))
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    staged = tmp_path / "assets" / "import" / opened["importId"] / "payload"
    assert sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*")
                  if p.is_file()) == ["SKILL.md", "scripts/run.sh"]


def test_an_unknown_chunk_index_and_a_wrong_size_are_typed_refusals(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=9, payload=MANIFEST,
                      sha256=_digest(MANIFEST))
    assert refusal.value.code == "IMPORT_PATH_INVALID"
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=MANIFEST[:-1],
                      sha256=_digest(MANIFEST[:-1]))
    assert refusal.value.code == "IMPORT_DIGEST_MISMATCH"
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=b"short",
                      sha256=_digest(MANIFEST))
    assert refusal.value.code == "IMPORT_DIGEST_MISMATCH"
    _send(service, opened["importId"])  # the refusals above changed nothing
    preview = service.prepare(opened["importId"], source={"type": "local-transfer"})
    assert preview["treeDigest"].startswith("sha256:")


def test_a_declared_size_that_does_not_match_the_payload_is_refused(tmp_path):
    """The digest cannot lie about its own length, so bytes are checked too."""
    service = ImportService(root=tmp_path / "assets")
    declared = [{"path": "SKILL.md", "bytes": len(MANIFEST) + 1,
                 "sha256": _digest(MANIFEST)}]
    opened = service.begin(request_id="r", files=declared,
                           total_bytes=len(MANIFEST) + 1)
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=MANIFEST,
                      sha256=_digest(MANIFEST))
    assert refusal.value.code == "IMPORT_BOUNDS_EXCEEDED"


def test_a_single_chunk_beyond_the_transfer_bound_is_refused(tmp_path):
    payload = b"x" * (MAX_CHUNK_BYTES + 1)
    service = ImportService(root=tmp_path / "assets")
    opened = service.begin(request_id="r",
                           files=[{"path": "SKILL.md", "bytes": len(payload),
                                   "sha256": _digest(payload)}],
                           total_bytes=len(payload))
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=payload,
                      sha256=_digest(payload))
    assert refusal.value.code == "IMPORT_BOUNDS_EXCEEDED"


# -- 重复 commit --------------------------------------------------------------

def test_a_second_commit_of_the_same_session_publishes_nothing(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"])
    service.prepare(opened["importId"], source={"type": "local-transfer"})
    first = service.commit(opened["importId"], asset_id=ASSET, revision=1)
    assert first["effect"] == "stored"
    store = SkillRevisionStore(tmp_path / "assets")
    digest = store.revision_digest(asset_id=ASSET, revision=1)
    with pytest.raises(ImportError_) as refusal:
        service.commit(opened["importId"], asset_id=ASSET, revision=2)
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    assert not (tmp_path / "assets" / "skill" / ASSET / "2").exists()
    assert store.revision_digest(asset_id=ASSET, revision=1) == digest
    # the prepared preview is gone with the session, and so is its staging
    with pytest.raises(ImportError_):
        service.preview(None)
    assert not (tmp_path / "assets" / "import" / opened["importId"]).exists()


def test_committing_onto_an_existing_revision_is_refused_and_cleans_up(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(MANIFEST)
    installed = store.install(source, asset_id=ASSET, revision=1)
    service = ImportService(root=tmp_path / "assets", store=store)
    opened = _begin(service)
    _send(service, opened["importId"])
    service.prepare(opened["importId"], source={"type": "local-transfer"})
    with pytest.raises(SkillAssetError) as refusal:
        service.commit(opened["importId"], asset_id=ASSET, revision=1)
    assert refusal.value.code == "SKILL_REVISION_EXISTS"
    # the failed publish aborted the session and left the old revision intact
    assert store.revision_digest(asset_id=ASSET,
                                 revision=1) == installed["tree_digest"]
    assert not (tmp_path / "assets" / "import" / opened["importId"]).exists()
    with pytest.raises(ImportError_):
        service.commit(opened["importId"], asset_id=ASSET, revision=3)


def test_abort_then_commit_and_abort_of_an_unknown_session(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"])
    service.abort(opened["importId"])
    with pytest.raises(ImportError_) as refusal:
        service.commit(opened["importId"], asset_id=ASSET, revision=1)
    assert refusal.value.code == "IMPORT_SESSION_INVALID"
    service.abort("import_never_existed")  # idempotent, never raises
    service.abort(opened["importId"])


# -- TTL sweep, both directions ----------------------------------------------

def test_a_fresh_session_survives_the_orphan_sweep(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    opened = _begin(service)
    _send(service, opened["importId"])
    survivor = tmp_path / "assets" / "import" / opened["importId"]
    assert survivor.is_dir()
    ImportService(root=tmp_path / "assets")  # sweeps only expired areas
    assert survivor.is_dir()
    # and the second service really can still use its own session
    second = ImportService(root=tmp_path / "assets")
    other = _begin(second)
    _send(second, other["importId"])
    assert second.prepare(other["importId"],
                          source={"type": "local-transfer"})["name"] == ASSET


def test_the_sweep_removes_only_stale_transfer_staging(tmp_path):
    stale = tmp_path / "assets" / "import" / "import_old" / "payload"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_bytes(MANIFEST)
    fresh = tmp_path / "assets" / "import" / "import_new" / "payload"
    fresh.mkdir(parents=True)
    (fresh / "SKILL.md").write_bytes(MANIFEST)
    store = SkillRevisionStore(tmp_path / "assets")
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(MANIFEST)
    store.install(source, asset_id=ASSET, revision=1)

    old = time.time() - SESSION_TTL_SECONDS - 1
    os.utime(tmp_path / "assets" / "import" / "import_old", (old, old))
    ImportService(root=tmp_path / "assets")

    assert not (tmp_path / "assets" / "import" / "import_old").exists()
    assert fresh.is_dir()  # the young session stays
    assert store.revision_dir(ASSET, 1).is_dir()  # installed content is untouchable

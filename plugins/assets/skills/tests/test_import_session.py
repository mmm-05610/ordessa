"""AC-3 / AC-4: the bounded import session — chunks, preview, drift refusal.

Wire-level protocol text: specs/003-assets-skills/contracts/import-protocol.md.
A commit reports effect "stored"; nothing in this path may claim "loaded".

Ported from `plugins/assets/tests/test_import_session.py` @ 752f148b1b with
every assertion intact (verification.md G03: chunk-digest refusal,
preview-then-commit drift, atomic failure, TTL sweep of a dead process's
staging area).
"""
from __future__ import annotations

import hashlib

import pytest

from ordessa_skills.api.errors import ImportError_


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _skill_files(body="v1", scripts=True):
    manifest = f"---\nname: demo-skill\ndescription: A demo.\n---\n\n{body}\n".encode()
    files = [{"path": "SKILL.md", "bytes": len(manifest), "sha256": _digest(manifest)}]
    payloads = {"SKILL.md": manifest}
    if scripts:
        run = b"#!/bin/sh\necho never-run\n"
        files.append({"path": "scripts/run.sh", "bytes": len(run), "sha256": _digest(run)})
        payloads["scripts/run.sh"] = run
    total = sum(item["bytes"] for item in files)
    return files, payloads, total


def _begin(service, files, total):
    return service.begin(request_id="r1", files=files, total_bytes=total)


def _send(service, import_id, payloads):
    for index, (path, data) in enumerate(sorted(payloads.items())):
        service.chunk(import_id, index=index, payload=data, sha256=_digest(data))


def test_happy_path_imports_atomically_and_reports_stored(tmp_path):
    from ordessa_skills.library.import_transfer import ImportService

    service = ImportService(root=tmp_path / "assets")
    files, payloads, total = _skill_files()
    opened = _begin(service, files, total)
    _send(service, opened["importId"], payloads)
    preview = service.prepare(opened["importId"],
                              source={"type": "local-transfer", "origin": "desktop:local"})
    assert preview["name"] == "demo-skill"
    assert preview["treeDigest"].startswith("sha256:")
    assert preview["scripts"] == ["scripts/run.sh"]
    assert {item["path"] for item in preview["files"]} == {"SKILL.md", "scripts/run.sh"}

    result = service.commit(opened["importId"], asset_id="demo-skill", revision=1)
    assert result["effect"] == "stored"
    assert "loaded" not in result
    stored = (tmp_path / "assets" / "skill" / "demo-skill" / "1" / "SKILL.md").read_bytes()
    assert stored == payloads["SKILL.md"]


def test_a_bad_chunk_digest_refuses_and_cleans(tmp_path):
    from ordessa_skills.library.import_transfer import ImportService

    service = ImportService(root=tmp_path / "assets")
    files, payloads, total = _skill_files()
    opened = _begin(service, files, total)
    first_path = sorted(payloads)[0]
    with pytest.raises(ImportError_) as refusal:
        service.chunk(opened["importId"], index=0, payload=b"tampered",
                      sha256=_digest(payloads[first_path]))
    assert refusal.value.code == "IMPORT_DIGEST_MISMATCH"
    service.abort(opened["importId"])
    assert not (tmp_path / "assets" / "import").exists() or \
        not any((tmp_path / "assets" / "import").iterdir())


@pytest.mark.parametrize("mutation", [
    "duplicate-path", "absolute-path", "traversal", "nul-path", "too-many", "too-big",
])
def test_declared_bounds_and_paths_are_validated_at_begin(tmp_path, mutation):
    from ordessa_skills.library.import_transfer import ImportService

    service = ImportService(root=tmp_path / "assets")
    files, _payloads, total = _skill_files(scripts=False)
    if mutation == "duplicate-path":
        files.append({"path": "SKILL.md", "bytes": files[0]["bytes"],
                      "sha256": files[0]["sha256"]})
        total += files[0]["bytes"]
    elif mutation == "absolute-path":
        files[0]["path"] = "/etc/SKILL.md"
    elif mutation == "traversal":
        files[0]["path"] = "../SKILL.md"
    elif mutation == "nul-path":
        files[0]["path"] = "SKILL\x00.md"
    elif mutation == "too-many":
        files = [{"path": f"f{i}", "bytes": 1, "sha256": _digest(b"x")}
                 for i in range(513)]
        total = 513
    elif mutation == "too-big":
        files = [{"path": "big.bin", "bytes": 32 * 1024 * 1024 + 1,
                  "sha256": _digest(b"x")}]
        total = 32 * 1024 * 1024 + 1
    with pytest.raises(ImportError_) as refusal:
        _begin(service, files, total)
    assert refusal.value.code in {"IMPORT_BOUNDS_EXCEEDED", "IMPORT_PATH_INVALID"}


def test_content_drift_between_preview_and_commit_is_refused(tmp_path):
    from ordessa_skills.library.import_transfer import ImportService

    service = ImportService(root=tmp_path / "assets")
    files, payloads, total = _skill_files()
    opened = _begin(service, files, total)
    _send(service, opened["importId"], payloads)
    preview = service.prepare(opened["importId"],
                              source={"type": "local-transfer", "origin": "desktop"})
    # Someone rewrites the staged tree after the user saw the preview.
    staged = tmp_path / "assets" / "import" / opened["importId"] / "payload" / "SKILL.md"
    staged.write_text("---\nname: evil\ndescription: swapped\n---\n")
    with pytest.raises(ImportError_) as refusal:
        service.commit(opened["importId"], asset_id="demo-skill", revision=1)
    assert refusal.value.code == "IMPORT_CONTENT_DRIFTED"
    assert refusal.value.detail  # the UI must be able to say preview vs commit digest
    assert not staged.exists()
    assert preview["treeDigest"].startswith("sha256:")


def test_failure_keeps_the_old_revision_binding_and_snapshot(tmp_path):
    from ordessa_skills.library.import_transfer import ImportService
    from ordessa_skills.library.records import AssetRecords
    from pacthold_runtime_compat.storage import Database

    database = Database(tmp_path / "data")
    database.initialize()
    records = AssetRecords(database)
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_a',1,'role','pi',1,0,'sha256:x','t','t')")
    records.publish(kind="skill", name="demo-skill", revision=1,
                    digest="sha256:" + "1" * 64, asset_id="demo-skill")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)

    service = ImportService(root=tmp_path / "assets", records=records)
    files, payloads, total = _skill_files()
    opened = _begin(service, files, total)
    _send(service, opened["importId"], payloads)
    service.prepare(opened["importId"], source={"type": "local-transfer", "origin": "d"})
    staged = tmp_path / "assets" / "import" / opened["importId"] / "payload" / "SKILL.md"
    staged.write_text("---\nname: evil\ndescription: swapped\n---\n")
    with pytest.raises(ImportError_):
        service.commit(opened["importId"], asset_id="demo-skill", revision=2)

    assert records.get("demo-skill")["latest_revision"] == 1
    assert records.bindings("profile_a")[0]["revision"] == 1
    assert not staged.exists()


def test_abort_is_idempotent_and_cleans_the_staging_area(tmp_path):
    from ordessa_skills.library.import_transfer import ImportService

    service = ImportService(root=tmp_path / "assets")
    files, payloads, total = _skill_files()
    opened = _begin(service, files, total)
    _send(service, opened["importId"], payloads)
    service.abort(opened["importId"])
    service.abort(opened["importId"])
    assert not (tmp_path / "assets" / "import" / opened["importId"]).exists()


def test_staging_from_a_dead_previous_process_is_swept(tmp_path):
    import os
    import time as time_module

    from ordessa_skills.library.import_transfer import SESSION_TTL_SECONDS, ImportService

    orphan = tmp_path / "assets" / "import" / "import_dead" / "payload"
    orphan.mkdir(parents=True)
    (orphan / "SKILL.md").write_bytes(b"leftover")
    stale = time_module.time() - SESSION_TTL_SECONDS - 60
    os.utime(tmp_path / "assets" / "import" / "import_dead", (stale, stale))

    ImportService(root=tmp_path / "assets")  # constructor sweeps expired areas

    assert not (tmp_path / "assets" / "import" / "import_dead").exists()

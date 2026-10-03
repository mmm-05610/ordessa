"""T16 最小数据恢复演示 — the minimal data-restore demonstration required
by docs/design/skills-v2/tasks.md T16 and verification.md G08/G22
(数据备份恢复一致; plan.md 原有 Assets-Skill 迁移: 若需要修改真实用户数据，
另给备份/恢复和用户确认).

What this proves and what it does NOT (state this wording when quoting the
evidence): it proves that on a SYNTHETIC data root — product SQLite file +
immutable ``skill/<assetId>/<revision>`` trees + a few foreign-kind rows —
:meth:`ordessa_skills.migration.restore.snapshot` + ``restore`` round-trip
the Skills slice byte-for-byte across realistic damage
(migration.apply rows, a rewritten skill tree file, a deleted revision
dir, a flipped ``server_profile_assets.enabled`` bit), that the restore is
idempotent, that a restore re-establishes the G08 mapping (the re-run plan
digests identically and applies to the same three writes), and that the
non-skill bytes the snapshot recorded stay byte-identical — or the restore
refuses with zero writes. It does NOT prove anything about real user data:
no production root was touched, the "damage" was scripted, and the
backup/restore guards enforce a path-shape rule only (same honesty as the
migration's ``allow_user_data`` flag; AGENTS.md rules 5/7).

Quiescence note: ``Database.initialize()`` leaves its schema connection
referenced only by CPython's cycle collector, keeping the WAL sidecar hot;
the demo calls ``gc.collect()`` before snapshot/restore — the documented
"root at rest" prerequisite of the tool, exercised the only way a
single-process test can.

Literal pins (G01 「旧 Skill ID/修订/摘要逐字节一致」 + 拼写不静默改变):
every EXPECTED_* constant below was derived from THIS fixed synthetic
fixture (fixed file contents, fixed row timestamps) at authoring time and
is asserted as a literal — if the digest spelling, the tree layout or the
plan encoding changes silently, these pins fail instead of the test
recomputing its own expectation at runtime.
"""
from __future__ import annotations

import gc
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from ordessa_skills.library.records import AssetRecords  # noqa: E402
from ordessa_skills.library.revisions import RevisionApprovalStore  # noqa: E402
from ordessa_skills.library.store import SkillRevisionStore  # noqa: E402
from ordessa_skills.migration import profile_bindings as mig  # noqa: E402
from ordessa_skills.migration import restore as rst  # noqa: E402

from pacthold_runtime_compat.storage import Database  # noqa: E402

T0 = "2026-01-01T00:00:00+00:00"
FOREIGN_KINDS = ("mcp", "command", "plugin")
REPO_ROOT = Path(__file__).resolve().parents[4]

SKILL_BODIES = {
    ("skill-alpha", 1): ("---\nname: skill-alpha\n"
                         "description: A demo skill.\n---\n\n"
                         "Body skill-alpha r1.\n"),
    ("skill-alpha", 2): ("---\nname: skill-alpha\n"
                         "description: A demo skill.\n---\n\n"
                         "Body skill-alpha r2.\n"),
    ("skill-beta", 1): ("---\nname: skill-beta\n"
                        "description: A demo skill.\n---\n\n"
                        "Body skill-beta r1.\n"),
}

# -- pinned round-trip evidence (derived from the fixed fixture above) --------

EXPECTED_FILE_SHA = {
    "assets/skill/skill-alpha/1/SKILL.md":
        "sha256:78c1087682ae61a959dd8435ccbf9871fc8c47a51733c3cc30bc8661607e13d9",
    "assets/skill/skill-alpha/2/SKILL.md":
        "sha256:f3ded098831efe02d6e5e789d219dce8a11254db9f2dfa19746d87c947e36fd5",
    "assets/skill/skill-beta/1/SKILL.md":
        "sha256:2534f5f96ae893894b1865800afd6c665d3c052c22208e76997ad0758bfbd5fd",
}

EXPECTED_TREE_DIGEST = {
    "assets/skill/skill-alpha/1":
        "sha256:17cd043c94f2e4711a3aff00e0f09399d7fdf210baf0a7cb5611cd901aae00c2",
    "assets/skill/skill-alpha/2":
        "sha256:fc2c34c8535d1ae44e581735302d3df2889815436dcda0ec4af4b413168c05d2",
    "assets/skill/skill-beta/1":
        "sha256:c6b1240a2edb56b728ee0643688da8f4480e78086812259a139f308865e8f9f0",
}

# G08 「字节/ID 样本」: the exact legacy binding rows (profile|asset|revision|
# enabled) and the exact plan digest of this fixture.
EXPECTED_BINDING_BYTES = (
    "profile_a|foreign-command|2|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-mcp|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-plugin|3|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-alpha|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-beta|1|0|" + T0 + "|" + T0 + "\n"
    "profile_c|skill-alpha|2|1|" + T0 + "|" + T0
)
EXPECTED_PLAN_DIGEST = (
    "sha256:00bcb3824efc6653917c24d32072f6662c44f2827f26ed99cf6e8d361b6a8a19")


# -- synthetic data root ---------------------------------------------------------


def _build(tmp_path: Path):
    """One synthetic product root, laid out like the real one:
    ``<root>/state/agentbox.sqlite`` (data-model via Database) plus
    ``<root>/assets/`` (server-compat plugin.py: assets_root =
    data_root / "assets") with 3 skill revisions over 2 assets, foreign-kind
    rows and a catalogs index."""
    root = tmp_path / "data"
    database = Database(root)
    database.initialize()
    assets = root / "assets"
    store = SkillRevisionStore(assets)
    records = AssetRecords(database)
    approvals = RevisionApprovalStore(assets, store=store)
    for (asset, revision), body in SKILL_BODIES.items():
        staging = tmp_path / "src" / asset / str(revision)
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text(body, encoding="utf-8")
        facts = store.install(staging, asset_id=asset, revision=revision)
        records.publish(kind="skill", name=facts["name"], revision=revision,
                        digest=facts["tree_digest"],
                        description=facts["description"], asset_id=asset)
        approvals.approve(asset_id=asset, revision=revision,
                          approved_by="tester")
    with database.transaction() as conn:
        for pid in ("profile_a", "profile_c"):
            conn.execute(
                "INSERT INTO server_profiles(id,version,name,harness_type,"
                "config_revision,native_generation,config_object_digest,"
                "created_at,updated_at) VALUES (?,1,'role','pi',1,0,'sha256:x',?,?)",
                (pid, T0, T0))
        for index, kind in enumerate(FOREIGN_KINDS):
            conn.execute(
                "INSERT INTO server_assets(id,kind,name,description,"
                "latest_revision,digest,source,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"foreign-{kind}", kind, f"name-{kind}", "not a skill",
                 index + 1, "sha256:" + "f" * 64, "legacy:server-compat",
                 T0, T0))
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,"
                "revision,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("profile_a", f"foreign-{kind}", index + 1, 1, T0, T0))
        # mix: enabled=1 pinned revision, enabled=0 pinned, cross-profile pin
        for pid, asset, revision, enabled in (
                ("profile_a", "skill-alpha", 1, 1),
                ("profile_a", "skill-beta", 1, 0),
                ("profile_c", "skill-alpha", 2, 1)):
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,"
                "revision,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (pid, asset, revision, enabled, T0, T0))
    (assets / "catalogs" / "cat-1").mkdir(parents=True)
    (assets / "catalogs" / "cat-1" / "index.json").write_text(
        '{"id": "cat-1", "entries": []}\n', encoding="utf-8")
    (assets / "mcp" / "mcp-demo").mkdir(parents=True)
    (assets / "mcp" / "mcp-demo" / "config.json").write_text(
        '{"kind":"mcp","name":"mcp-demo"}\n', encoding="utf-8")
    (assets / "plugin" / "plugin-demo").mkdir(parents=True)
    (assets / "plugin" / "plugin-demo" / "manifest.json").write_text(
        '{"kind":"plugin","name":"plugin-demo"}\n', encoding="utf-8")
    return {"root": root, "database": database, "gate": approvals}


@pytest.fixture()
def env(tmp_path):
    e = _build(tmp_path)
    e["backup_parent"] = tmp_path / "backups"
    gc.collect()  # quiesce the root: see the module docstring
    return e


def _quiesced_snapshot(e):
    gc.collect()
    return rst.snapshot(e["root"], backup_parent=e["backup_parent"])


def binding_bytes(database) -> str:
    with database.read() as conn:
        rows = conn.execute(
            "SELECT profile_id,asset_id,revision,enabled,created_at,updated_at"
            " FROM server_profile_assets ORDER BY profile_id,asset_id").fetchall()
    return "\n".join("|".join(str(value) for value in tuple(row)) for row in rows)


def foreign_asset_bytes(database) -> str:
    with database.read() as conn:
        rows = conn.execute(
            "SELECT id,kind,latest_revision,digest FROM server_assets"
            " WHERE kind!='skill' ORDER BY id").fetchall()
    return "\n".join("|".join(str(value) for value in tuple(row)) for row in rows)


def table_rows(database, table) -> list[tuple]:
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if present is None:
            return []
        return [tuple(row) for row in conn.execute(
            f"SELECT * FROM {table}").fetchall()]


def destination_shas(root: Path) -> dict[str, str]:
    """sha256 of every file under assets/skill, keyed by root-relative path."""
    out = {}
    for path in sorted((root / "assets" / "skill").rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            digest, _ = rst._file_sha256(path)
            out[rel] = digest
    return out


def manifest_section(backup: Path, section) -> dict[str, dict]:
    data = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    key = "path"
    return {item[key]: item for item in data[section]}


# -- tests -----------------------------------------------------------------------


def test_snapshot_copies_skills_slice_and_records_foreign_bytes(env):
    summary = _quiesced_snapshot(env)
    assert summary["dataRoot"] == str(env["root"].resolve())
    backup = Path(summary["backup"])
    assert env["root"] not in backup.parents and backup.is_dir()

    database_files = manifest_section(backup, "database")
    assert set(database_files) == {"state/agentbox.sqlite"}
    assert summary["databaseFiles"] == 1

    skill_files = manifest_section(backup, "skillFiles")
    assert set(skill_files) == set(EXPECTED_FILE_SHA)
    assert summary["skillFiles"] == 3
    # the copied bytes exist inside the backup, outside the root
    for rel in skill_files:
        assert (backup / rel).is_file()

    trees = manifest_section(backup, "skillTrees")
    assert set(trees) == set(EXPECTED_TREE_DIGEST)

    foreign = manifest_section(backup, "foreignFiles")
    assert {"assets/catalogs/cat-1/index.json", "assets/mcp/mcp-demo/config.json",
            "assets/plugin/plugin-demo/manifest.json"} <= set(foreign)
    # recorded, not copied: no foreign file body stands in the backup
    for rel in foreign:
        assert not (backup / rel).exists()
    assert summary["foreignFiles"] == len(foreign)

    report = rst.verify_backup(backup)
    assert report["ok"] is True


def test_snapshot_refuses_backups_inside_the_root_and_inside_the_repo(env):
    with pytest.raises(rst.RestoreError) as inside:
        rst.snapshot(env["root"], backup_parent=env["root"] / "backups")
    assert inside.value.code == "RESTORE_BACKUP_INSIDE_ROOT"

    with pytest.raises(rst.RestoreError) as repo:
        rst.snapshot(env["root"], backup_parent=REPO_ROOT / "tmp-backups")
    assert repo.value.code == "RESTORE_BACKUP_INSIDE_REPO"
    # all-or-nothing: no partial backup dir was created anywhere
    assert not (REPO_ROOT / "tmp-backups").exists()
    if env["backup_parent"].exists():
        assert list(env["backup_parent"].iterdir()) == []


def test_snapshot_refuses_symlink_in_the_skill_tree_leaving_no_backup(env):
    link = env["root"] / "assets" / "skill" / "skill-beta" / "1" / "evil.md"
    link.symlink_to(link.parent / "SKILL.md")
    with pytest.raises(rst.RestoreError) as refused:
        _quiesced_snapshot(env)
    assert refused.value.code == "RESTORE_ENTRY_INVALID"
    assert not env["backup_parent"].exists() or list(env["backup_parent"].iterdir()) == []


def test_snapshot_and_restore_refuse_non_synthetic_paths(env):
    fake = Path("/home/real-user/.ordessa/data")
    with pytest.raises(rst.RestoreError) as snap:
        rst.snapshot(fake)
    assert snap.value.code == "RESTORE_USER_DATA_CONFIRMATION_REQUIRED"

    backup = Path(_quiesced_snapshot(env)["backup"])
    with pytest.raises(rst.RestoreError) as res:
        rst.restore(backup, fake, allow_foreign_root=True)
    assert res.value.code == "RESTORE_USER_DATA_CONFIRMATION_REQUIRED"


def test_verify_backup_detects_tampered_copies(env):
    backup = Path(_quiesced_snapshot(env)["backup"])
    assert rst.verify_backup(backup)["ok"] is True

    victim = backup / "assets/skill/skill-alpha/1/SKILL.md"
    victim.write_text("tampered backup copy\n", encoding="utf-8")
    with pytest.raises(rst.RestoreError) as mismatch:
        rst.verify_backup(backup)
    assert mismatch.value.code == "RESTORE_MANIFEST_MISMATCH"
    assert "skill-alpha/1/SKILL.md" in mismatch.value.detail

    (backup / "assets/skill/skill-beta/1/extra.md").write_text(
        "grown tree\n", encoding="utf-8")
    # the file-level section still matches; the tree digest catches it too
    with pytest.raises(rst.RestoreError) as tree:
        rst.verify_backup(backup)
    assert tree.value.code == "RESTORE_MANIFEST_MISMATCH"
    assert "skill-beta/1" in tree.value.detail


def test_restore_round_trip_survives_apply_plus_scripted_damage(env):
    database, root = env["database"], env["root"]
    backup = Path(_quiesced_snapshot(env)["backup"])

    plan_before = mig.plan(database, approvals=env["gate"])
    applied = mig.apply(database, plan_before, operation_key="op-mig",
                       approvals=env["gate"])
    assert len(applied["written"]) == 3

    # damage the way it actually looks: rewritten tree file, deleted
    # revision dir, mutated legacy binding row
    victim = root / "assets/skill/skill-alpha/1/SKILL.md"
    victim.write_text("CORRUPTED AFTER SNAPSHOT\n", encoding="utf-8")
    shutil.rmtree(root / "assets/skill/skill-alpha/2")
    with database.transaction() as conn:
        conn.execute("UPDATE server_profile_assets SET enabled=1"
                     " WHERE profile_id='profile_a' AND asset_id='skill-beta'")
    assert victim.read_text(encoding="utf-8").startswith("CORRUPTED")
    assert table_rows(database, "skill_assignments") != []
    assert binding_bytes(database) != EXPECTED_BINDING_BYTES  # damage is real

    report = rst.restore(backup, root)
    assert report["manifestOk"] is True
    assert all(item["match"] for item in report["skillTrees"])
    assert report["foreignVerified"] is True and report["foreignFilesChecked"] >= 3

    # per-file sha256 equality against the manifest, and byte revival
    actual = destination_shas(root)
    expected_files = manifest_section(backup, "skillFiles")
    assert {rel: expected_files[rel]["sha256"] for rel in expected_files} == actual
    assert victim.read_text(encoding="utf-8") == SKILL_BODIES["skill-alpha", 1]
    assert (root / "assets/skill/skill-alpha/2/SKILL.md").is_file()

    # DB rows are back at the pre-snapshot state…
    assert binding_bytes(database) == EXPECTED_BINDING_BYTES
    assert table_rows(database, "skill_assignments") == []
    assert table_rows(database, "skill_assignment_operations") == []
    # …and the non-skill rows inside the restored file are byte-identical
    assert foreign_asset_bytes(database) == (
        "foreign-command|command|2|sha256:" + "f" * 64 + "\n"
        "foreign-mcp|mcp|1|sha256:" + "f" * 64 + "\n"
        "foreign-plugin|plugin|3|sha256:" + "f" * 64)

    # G08 forward/backward after restore: the identical plan re-forms…
    plan_after = mig.plan(database, approvals=env["gate"])
    assert plan_after.digest == plan_before.digest
    # …and re-applying reproduces exactly the same three writes
    reapplied = mig.apply(database, plan_after, operation_key="op-mig",
                          approvals=env["gate"])
    assert [w["assetId"] for w in reapplied["written"]] == \
        [w["assetId"] for w in applied["written"]]
    assert mig.verify(database, plan_after)["equivalent"] is True


def test_plan_digests_recompute_identically_after_restore(env):
    """The G08 sample digests for THIS fixture are the literals below —
    pinned at authoring time from the fixed synthetic content, so a silent
    change in the digest spelling, the tree layout or the plan encoding
    fails here (G01 「拼写不静默改变」)."""
    database = env["database"]
    plan = mig.plan(database, approvals=env["gate"])
    assert plan.digest == EXPECTED_PLAN_DIGEST
    assert binding_bytes(database) == EXPECTED_BINDING_BYTES

    backup = Path(_quiesced_snapshot(env)["backup"])
    files = manifest_section(backup, "skillFiles")
    assert {rel: files[rel]["sha256"] for rel in files} == EXPECTED_FILE_SHA
    trees = manifest_section(backup, "skillTrees")
    assert {rel: trees[rel]["digest"] for rel in trees} == EXPECTED_TREE_DIGEST

    rst.restore(backup, env["root"])
    gc.collect()
    assert mig.plan(database, approvals=env["gate"]).digest == EXPECTED_PLAN_DIGEST


def test_restore_is_idempotent(env):
    root, database = env["root"], env["database"]
    backup = Path(_quiesced_snapshot(env)["backup"])
    victim = root / "assets/skill/skill-alpha/1/SKILL.md"
    victim.write_text("damage\n", encoding="utf-8")

    first = rst.restore(backup, root)
    gc.collect()
    shas_after_first = destination_shas(root)
    db_sha = rst._file_sha256(root / "state/agentbox.sqlite")[0]
    plan_digests = mig.plan(database, approvals=env["gate"]).digest

    gc.collect()
    second = rst.restore(backup, root)
    assert all(item["match"] for item in second["skillTrees"])
    assert destination_shas(root) == shas_after_first
    assert (rst._file_sha256(root / "state/agentbox.sqlite")[0] == db_sha
            == manifest_section(backup, "database")["state/agentbox.sqlite"]["sha256"])
    gc.collect()
    assert mig.plan(database, approvals=env["gate"]).digest == plan_digests


def test_restore_refuses_foreign_root_unless_explicitly_allowed(env):
    backup = Path(_quiesced_snapshot(env)["backup"])
    other = env["root"].parent / "unrelated-root"
    other.mkdir()

    with pytest.raises(rst.RestoreError) as refused:
        rst.restore(backup, other)
    assert refused.value.code == "RESTORE_FOREIGN_ROOT"
    assert list(other.iterdir()) == []  # zero writes into an unrelated root

    report = rst.restore(backup, other, allow_foreign_root=True)
    assert report["foreignVerified"] is False
    assert all(item["match"] for item in report["skillTrees"])
    assert destination_shas(other) == {
        rel: EXPECTED_FILE_SHA[rel] for rel in EXPECTED_FILE_SHA}
    assert (other / "state/agentbox.sqlite").is_file()
    # the source root is untouched by the foreign-root restore
    assert (env["root"] / "assets/skill/skill-alpha/2/SKILL.md").is_file()


def test_restore_refuses_when_recorded_foreign_bytes_drifted(env):
    root = env["root"]
    backup = Path(_quiesced_snapshot(env)["backup"])
    # damage the Skills slice AND a recorded foreign byte
    (root / "assets/skill/skill-alpha/1/SKILL.md").write_text(
        "corrupted\n", encoding="utf-8")
    shutil.rmtree(root / "assets/skill/skill-alpha/2")
    (root / "assets/catalogs/cat-1/index.json").write_text(
        '{"id": "cat-1", "entries": ["injected"]}\n', encoding="utf-8")

    with pytest.raises(rst.RestoreError) as drift:
        rst.restore(backup, root)
    assert drift.value.code == "RESTORE_FOREIGN_DRIFT"
    assert "catalogs" in drift.value.detail
    # zero writes: the skill damage is still exactly as the incident left it
    assert not (root / "assets/skill/skill-alpha/2/SKILL.md").exists()
    assert (root / "assets/skill/skill-alpha/1/SKILL.md").read_text(
        encoding="utf-8") == "corrupted\n"


def test_snapshot_and_restore_refuse_hot_wal_sidecar(env):
    """Pins the quiescence refusal in ``_db_files`` (module docstring:
    「a non-empty sidecar refuses the snapshot」; restore guard 4 「the
    destination database must be at rest」). The guard's real condition is
    ``sidecar.stat().st_size != 0`` for every ``-wal``/``-shm`` sibling of
    ``state/agentbox.sqlite``, so the test drives a REAL hot WAL: a live
    sqlite connection in WAL journal mode with un-checkpointed committed
    frames, kept open across the call (closing the last connection
    checkpoints and deletes the sidecar — that is exactly the quiescence
    the other tests gc.collect() into)."""
    root = env["root"]
    db = root / "state" / "agentbox.sqlite"
    wal = Path(str(db) + "-wal")

    hot = sqlite3.connect(db)
    try:
        hot.execute("PRAGMA journal_mode=WAL")
        hot.execute("CREATE TABLE IF NOT EXISTS wal_at_rest_probe(v TEXT)")
        hot.execute("INSERT INTO wal_at_rest_probe VALUES (?)", ("x" * 4096,))
        hot.commit()
        # precondition: the sidecar really carries un-checkpointed bytes
        assert wal.is_file() and wal.stat().st_size > 0

        with pytest.raises(rst.RestoreError) as refused:
            rst.snapshot(root, backup_parent=env["backup_parent"])
        assert refused.value.code == "RESTORE_DATA_ROOT_INVALID"
        assert "agentbox.sqlite-wal" in refused.value.detail
        # all-or-nothing: the guard fires before any backup dir exists
        assert not env["backup_parent"].exists() or \
            list(env["backup_parent"].iterdir()) == []
    finally:
        hot.close()  # last connection: checkpoints and retires the WAL
    gc.collect()

    # a quiet root snapshots fine (the refusal is about the sidecar, not
    # the root); then re-heat it and prove the restore entry point refuses
    # with zero writes as well
    backup = Path(rst.snapshot(root, backup_parent=env["backup_parent"])["backup"])
    victim = root / "assets/skill/skill-beta/1/SKILL.md"
    original = victim.read_text(encoding="utf-8")
    victim.write_text("damage awaiting restore\n", encoding="utf-8")

    hot = sqlite3.connect(db)
    try:
        hot.execute("PRAGMA journal_mode=WAL")
        hot.execute("INSERT INTO wal_at_rest_probe VALUES (?)", ("y" * 4096,))
        hot.commit()
        assert wal.is_file() and wal.stat().st_size > 0
        with pytest.raises(rst.RestoreError) as refused:
            rst.restore(backup, root)
        assert refused.value.code == "RESTORE_DATA_ROOT_INVALID"
        # zero writes: the damage is untouched — restore refused pre-flight
        assert victim.read_text(encoding="utf-8") == "damage awaiting restore\n"
    finally:
        hot.close()
    gc.collect()
    # and the same restore succeeds once the root is truly at rest again
    report = rst.restore(backup, root)
    assert report["manifestOk"] is True
    assert victim.read_text(encoding="utf-8") == original


def test_restore_detects_corrupted_backup_bytes_after_write(env):
    """Pins the post-restore write verification in ``restore`` (docstring:
    「After the staged write the function re-hashes every restored file
    … RESTORE_MANIFEST_MISMATCH on any surprise」). Corruption route is
    reachable in reality: a backup volume that ends up holding bytes which
    no longer match the manifest written alongside it — a partially written
    backup file, or 介质损坏 on the backup medium after snapshot completed.
    restore never re-trusts the copy; the destination is re-hashed against
    the manifest and the mismatch is RAISED, not returned as success. No
    production-code monkeypatch is needed: corrupting the backup copy after
    snapshot is exactly what such media damage looks like to this tool."""
    backup = Path(_quiesced_snapshot(env)["backup"])
    victim_in_backup = backup / "assets/skill/skill-beta/1/SKILL.md"
    victim_in_backup.write_bytes(victim_in_backup.read_bytes() + b"grown by the medium\n")

    with pytest.raises(rst.RestoreError) as mismatch:
        rst.restore(backup, env["root"])
    assert mismatch.value.code == "RESTORE_MANIFEST_MISMATCH"
    # the file-level re-hash caught it, and the tree digest corroborates
    assert "assets/skill/skill-beta/1/SKILL.md: destination is" in mismatch.value.detail
    assert "assets/skill/skill-beta/1:" in mismatch.value.detail
    # the failure is surfaced, not a silently green report: no dict returned,
    # the backup remains present and untouched (docstring invariant)
    assert victim_in_backup.read_bytes().endswith(b"grown by the medium\n")
    assert (backup / "manifest.json").is_file()

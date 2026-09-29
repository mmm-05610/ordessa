"""T04 — explicit approval, fixed-version semantics, and premature-GC refusal.

Authoritative text: docs/design/skills-v2/README.md §内容修订与使用修订
(「安装新版不会自动更新分配；用户批准更新某范围绑定时，该绑定才指向新版」),
data-model.md §内容与版本 + §存储升级, verification.md G04/G06/G08.

Every assertion here is a counter-example from verification.md's G-table:
自动移动 latest (G04), 启用未批准版 (G06), 旧版提早 GC (G04), 远端 tag 改动
影响运行 (G04).
"""
from __future__ import annotations

import json

import pytest

from pacthold_runtime_compat.storage import Database

from ordessa_skills.api.errors import SkillAssetError
from ordessa_skills.api.evidence import LOADED, PROJECTED, STORED, USED
from ordessa_skills.library.records import AssetRecords
from ordessa_skills.library.revisions import (
    APPROVALS_DIRECTORY,
    RevisionApprovalStore,
    RevisionRetention,
    git_source,
    local_source,
    parse_source,
    publish_revision,
    revision_view,
)
from ordessa_skills.library.store import SkillRevisionStore

ASSET = "demo-skill"


def _write_skill(root, body: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {ASSET}\ndescription: A demo.\n---\n\n{body}\n", encoding="utf-8")
    (root / "references").mkdir(exist_ok=True)
    (root / "references" / "deep.md").write_text(f"# {body}\n", encoding="utf-8")
    return root


@pytest.fixture()
def env(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_a',1,'role','pi',1,0,'sha256:x','t','t')")
    records = AssetRecords(database)
    store = SkillRevisionStore(tmp_path / "assets")
    approvals = RevisionApprovalStore(tmp_path / "assets", store=store)
    return {"tmp": tmp_path, "database": database, "records": records,
            "store": store, "approvals": approvals}


def _install(env, revision: int, *, body="v", source_ref=local_source()):
    return publish_revision(store=env["store"], records=env["records"],
                            source=_write_skill(env["tmp"] / f"src-{revision}",
                                                f"{body}{revision}"),
                            asset_id=ASSET, revision=revision, source_ref=source_ref)


def _binding_revision(env):
    rows = env["records"].bindings("profile_a")
    return {row["assetId"]: row["revision"] for row in rows}


# -- installing a revision moves nothing ------------------------------------

def test_publishing_a_new_revision_moves_only_latest_installed(env):
    first = _install(env, 1)
    env["records"].bind(profile_id="profile_a", asset_id=ASSET, revision=1)
    second = _install(env, 2)

    assert _binding_revision(env) == {ASSET: 1}  # G04: no automatic move
    assert second["latestInstalledRevision"] == 2
    assert second["approvalRecord"] is None      # installed is not approved
    assert env["records"].get(ASSET)["latest_revision"] == 2
    # the old revision stays fully readable and digest-identical
    assert first["facts"]["tree_digest"] == env["store"].revision_digest(
        asset_id=ASSET, revision=1)
    assert (env["store"].revision_dir(ASSET, 1) / "SKILL.md").read_text(
        encoding="utf-8").endswith("v1\n")


def test_publish_reports_stored_and_nothing_stronger(env):
    result = _install(env, 1)
    assert result["effect"] == STORED
    rendered = repr(sorted(result))
    for overclaim in (LOADED, PROJECTED, USED):
        assert overclaim not in rendered


def test_the_revision_view_carries_the_approval_record_and_lineage(env):
    _install(env, 1)
    env["records"].bind(profile_id="profile_a", asset_id=ASSET, revision=1)
    _install(env, 2, source_ref=git_source("https://example.test/s.git",
                                           ref="main", commit="c2"))
    unapproved = revision_view(env["store"], asset_id=ASSET, revision=2,
                              records=env["records"], approvals=env["approvals"])
    assert unapproved["approvalRecord"] is None
    assert unapproved["latestInstalledRevision"] == 2
    assert unapproved["provenance"] == {
        "type": "git", "url": "https://example.test/s.git", "ref": "main",
        "commit": "c2"}
    # the legacy camelCase fact keys are untouched around the new fields
    assert list(unapproved)[:11] == [
        "assetId", "revision", "treeDigest", "name", "description", "metadata",
        "retainedFields", "fileCount", "totalBytes", "scripts", "source"]
    approved = env["approvals"].approve(asset_id=ASSET, revision=2)
    seen = revision_view(env["store"], asset_id=ASSET, revision=2,
                         records=env["records"], approvals=env["approvals"])
    assert seen["approvalRecord"] == approved
    assert _binding_revision(env) == {ASSET: 1}  # a view read moves nothing


# -- approval ----------------------------------------------------------------

def test_an_unapproved_revision_cannot_be_referenced_by_an_assignment(env):
    _install(env, 1)
    with pytest.raises(SkillAssetError) as refusal:
        env["approvals"].assert_usable_for_assignment(ASSET, 1)
    assert refusal.value.code == "SKILL_APPROVAL_MISSING"  # G06 「启用未批准版」
    record = env["approvals"].approve(asset_id=ASSET, revision=1, approved_by="user")
    assert env["approvals"].assert_usable_for_assignment(ASSET, 1) == record
    assert record["treeDigest"] == env["store"].revision_digest(
        asset_id=ASSET, revision=1)


def test_a_missing_revision_cannot_be_approved(env):
    with pytest.raises(SkillAssetError) as refusal:
        env["approvals"].approve(asset_id=ASSET, revision=9)
    assert refusal.value.code == "SKILL_ASSET_MISSING"
    assert env["approvals"].approvals(ASSET) == []


def test_approving_is_durable_idempotent_and_lives_in_the_asset_tree(env):
    _install(env, 1)
    _install(env, 2)
    first = env["approvals"].approve(asset_id=ASSET, revision=1)
    again = env["approvals"].approve(asset_id=ASSET, revision=1)
    assert first == again  # the original record stands; no duplicate approval
    path = env["tmp"] / "assets" / APPROVALS_DIRECTORY / f"{ASSET}.json"
    assert path.is_file()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["assetId"] == ASSET
    assert [item["revision"] for item in document["approvals"]] == [1]
    env["approvals"].approve(asset_id=ASSET, revision=2)
    assert [item["revision"] for item in env["approvals"].approvals(ASSET)] == [1, 2]
    assert env["approvals"].latest_approved(ASSET)["revision"] == 2


def test_an_approval_never_moves_an_existing_binding(env):
    _install(env, 1)
    env["records"].bind(profile_id="profile_a", asset_id=ASSET, revision=1)
    _install(env, 2)
    env["approvals"].approve(asset_id=ASSET, revision=2)
    assert _binding_revision(env) == {ASSET: 1}
    # only the explicit upgrade act moves it, and only to the approved version
    env["approvals"].assert_usable_for_assignment(ASSET, 2)
    env["records"].update_binding(profile_id="profile_a", asset_id=ASSET, revision=2)
    assert _binding_revision(env) == {ASSET: 2}
    assert env["store"].revision_dir(ASSET, 1).is_dir()  # old revision survives


def test_a_moving_remote_ref_never_changes_what_is_installed_or_pinned(env):
    """G04 「远端 tag 改动影响运行」: only the fixed commit is provenance."""
    first_source = git_source("https://example.test/s.git", ref="v1", commit="aaaa")
    _install(env, 1, source_ref=first_source)
    env["approvals"].approve(asset_id=ASSET, revision=1, source=first_source)
    env["records"].bind(profile_id="profile_a", asset_id=ASSET, revision=1)
    digest_before = env["store"].revision_digest(asset_id=ASSET, revision=1)
    # the same tag later points somewhere else, published as a new revision
    _install(env, 2, source_ref=git_source("https://example.test/s.git",
                                           ref="v1", commit="bbbb"))
    assert env["store"].revision_digest(asset_id=ASSET, revision=1) == digest_before
    assert _binding_revision(env) == {ASSET: 1}
    # the asset row carries only the newest source string (the legacy schema
    # has one `source` column per asset); per-revision provenance is pinned in
    # the approval record, and it still names the commit that was reviewed.
    assert env["approvals"].approval_for(ASSET, 1)["provenance"]["commit"] == "aaaa"
    assert parse_source(env["records"].get(ASSET)["source"])["commit"] == "bbbb"


def test_approval_records_the_source_it_was_granted_against(env):
    source = git_source("https://example.test/s.git", ref="release/2", commit="c9")
    _install(env, 1, source_ref=source)
    record = env["approvals"].approve(asset_id=ASSET, revision=1, source=source)
    assert record["source"] == source
    assert record["provenance"] == {"type": "git", "url": "https://example.test/s.git",
                                    "ref": "release/2", "commit": "c9"}


def test_an_approval_is_refused_when_the_installed_tree_is_not_what_was_reviewed(env):
    _install(env, 1)
    with pytest.raises(SkillAssetError) as refusal:
        env["approvals"].approve(asset_id=ASSET, revision=1,
                                 expected_digest="sha256:" + "0" * 64)
    assert refusal.value.code == "SKILL_APPROVAL_DIGEST_MISMATCH"
    assert env["approvals"].approvals(ASSET) == []


def test_tampering_after_approval_breaks_the_usability_gate(env):
    _install(env, 1)
    env["approvals"].approve(asset_id=ASSET, revision=1)
    (env["store"].revision_dir(ASSET, 1) / "SKILL.md").write_text("tampered",
                                                                  encoding="utf-8")
    with pytest.raises(SkillAssetError) as refusal:
        env["approvals"].assert_usable_for_assignment(ASSET, 1)
    assert refusal.value.code == "SKILL_APPROVAL_DIGEST_MISMATCH"


def test_the_approval_tree_refuses_an_escapin_asset_id(env):
    with pytest.raises(SkillAssetError) as refusal:
        env["approvals"].approval_file("../elsewhere")
    assert refusal.value.code == "SKILL_ASSET_INVALID"


# -- retention / premature GC -------------------------------------------------

def test_a_revision_a_runtime_instance_still_uses_cannot_be_collected(env):
    """G04 「旧版提早 GC」, with the runtime reference as an injected predicate.

    The three guards are checked one at a time so each refusal is provably its
    own: a live instance first, then a pin, then an approval record.
    """
    live = {(ASSET, 1)}
    _install(env, 1)
    env["approvals"].approve(asset_id=ASSET, revision=1)
    env["records"].bind(profile_id="profile_a", asset_id=ASSET, revision=1)
    _install(env, 2)
    retention = RevisionRetention(
        store=env["store"], approvals=env["approvals"],
        in_use=lambda asset_id, revision: (asset_id, revision) in live,
        pinned=lambda asset_id: {row["revision"]
                                 for row in env["records"].bindings("profile_a")
                                 if row["assetId"] == asset_id})
    digest_one = env["store"].revision_digest(asset_id=ASSET, revision=1)

    with pytest.raises(SkillAssetError) as refusal:
        retention.remove(ASSET, 1)
    assert refusal.value.code == "SKILL_IN_USE"
    assert retention.refusal_reason(ASSET, 1) == "in-use"
    assert retention.removable(ASSET, 1) is False

    live.clear()  # the instance closed; the pin still holds
    with pytest.raises(SkillAssetError) as refusal:
        retention.remove(ASSET, 1)
    assert refusal.value.code == "SKILL_PINNED"
    assert retention.refusal_reason(ASSET, 1) == "pinned"

    env["records"].unbind(profile_id="profile_a", asset_id=ASSET)
    with pytest.raises(SkillAssetError) as refusal:
        retention.remove(ASSET, 1)
    assert refusal.value.code == "SKILL_APPROVED"
    assert retention.refusal_reason(ASSET, 1) == "approved"
    assert env["store"].revision_digest(asset_id=ASSET, revision=1) == digest_one

    # a candidate that nothing references is collectable, and collecting it
    # leaves the referenced revision byte-identical
    assert retention.removable(ASSET, 2) is True
    assert retention.remove(ASSET, 2) == {"assetId": ASSET, "revision": 2,
                                          "removed": True}
    assert not env["store"].revision_dir(ASSET, 2).exists()
    assert env["store"].revision_digest(asset_id=ASSET, revision=1) == digest_one
    with pytest.raises(SkillAssetError) as gone:
        retention.remove(ASSET, 2)
    assert gone.value.code == "SKILL_ASSET_MISSING"


def test_retention_asks_only_the_injected_predicates_and_nothing_else(env):
    """No hidden reachability: with no references injected, nothing is refused.

    The composition root (the Harness/assignment side, T05/T11) owns supplying
    the real runtime and pin predicates; this module never guesses that a
    revision is free — and equally never claims a reference it was not told.
    """
    _install(env, 1)
    always_live = RevisionRetention(store=env["store"],
                                    in_use=lambda asset_id, revision: True)
    with pytest.raises(SkillAssetError) as refusal:
        always_live.remove(ASSET, 1)
    assert refusal.value.code == "SKILL_IN_USE"

    unguarded = RevisionRetention(store=env["store"])
    assert unguarded.refusal_reason(ASSET, 1) is None
    assert unguarded.remove(ASSET, 1)["removed"] is True
    assert not env["store"].revision_dir(ASSET, 1).exists()
    with pytest.raises(SkillAssetError) as missing:
        env["store"].revision_digest(asset_id=ASSET, revision=1)
    assert missing.value.code == "SKILL_ASSET_MISSING"

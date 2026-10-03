"""AC-3 / INV-1: the revision store installs atomically and never half-way.
Ported from `plugins/assets/tests/test_store_atomic.py` @ 752f148b1b with
every assertion intact; only the import paths moved (verification.md G01,
research-and-reuse.md 不可变修订仓 row).
"""
from __future__ import annotations

import pytest

from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)

from ordessa_skills.api.errors import SkillAssetError
from ordessa_skills.library.store import SkillRevisionStore


def _write_skill(root, body="v1"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: A demo.\n---\n\n{body}\n")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    return root


def test_install_publishes_one_revision_whose_digest_is_the_tree_digest(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    facts = store.install(_write_skill(tmp_path / "src"), asset_id="demo-skill", revision=1)
    assert facts["tree_digest"].startswith("sha256:")
    assert facts["tree_digest"] == "sha256:" + runtime_artifact_tree_digest(
        store.revision_dir("demo-skill", 1)).split(":", 1)[1]
    assert facts["name"] == "demo-skill"
    assert facts["scripts"] == ("scripts/run.sh",)
    assert store.verify(asset_id="demo-skill", revision=1,
                        expected_digest=facts["tree_digest"])


def test_verify_detects_tampering(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    facts = store.install(_write_skill(tmp_path / "src"), asset_id="demo-skill", revision=1)
    stored = store.revision_dir("demo-skill", 1) / "SKILL.md"
    stored.write_text("tampered")
    assert store.verify(asset_id="demo-skill", revision=1,
                        expected_digest=facts["tree_digest"]) is False


def test_a_second_install_at_the_same_number_is_refused_and_changes_nothing(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    first = store.install(_write_skill(tmp_path / "src"), asset_id="demo-skill", revision=1)
    before = sorted((p.relative_to(store.revision_dir("demo-skill", 1)), p.read_bytes())
                    for p in store.revision_dir("demo-skill", 1).rglob("*") if p.is_file())
    with pytest.raises(SkillAssetError) as refusal:
        store.install(_write_skill(tmp_path / "src", body="v2"),
                      asset_id="demo-skill", revision=1)
    assert refusal.value.code == "SKILL_REVISION_EXISTS"
    after = sorted((p.relative_to(store.revision_dir("demo-skill", 1)), p.read_bytes())
                   for p in store.revision_dir("demo-skill", 1).rglob("*") if p.is_file())
    assert before == after and first["tree_digest"]


def test_a_failed_install_leaves_no_staging_and_the_previous_revision_intact(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    store.install(_write_skill(tmp_path / "src"), asset_id="demo-skill", revision=1)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "not-a-skill.txt").write_text("no manifest")
    with pytest.raises(SkillAssetError):
        store.install(bad, asset_id="demo-skill", revision=2)
    assert store.verify(asset_id="demo-skill", revision=1,
                        expected_digest=_digest(store, "demo-skill", 1))
    leftovers = [p for p in (tmp_path / "assets" / "skill" / "demo-skill").iterdir()
                 if p.name.startswith("skill-staging-")]
    assert leftovers == []
    assert not (tmp_path / "assets" / "skill" / "demo-skill" / "2").exists()


def _digest(store, asset_id, revision):
    from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
        runtime_artifact_tree_digest as digest_of)
    return digest_of(store.revision_dir(asset_id, revision))


def test_a_missing_revision_is_a_typed_refusal(tmp_path):
    store = SkillRevisionStore(tmp_path / "assets")
    with pytest.raises(SkillAssetError) as refusal:
        store.read_metadata(asset_id="demo-skill", revision=7)
    assert refusal.value.code == "SKILL_ASSET_MISSING"

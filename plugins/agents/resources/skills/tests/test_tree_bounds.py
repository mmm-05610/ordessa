"""AC-2: bounded, link-free directory scanning for one skill tree.

Ported from `plugins/assets/tests/test_tree_bounds.py` @ 752f148b1b
(imports repointed `ordessa_assets.contracts` -> `ordessa_skills.api`; every
assertion unchanged).
"""
from __future__ import annotations

import os

import pytest

from ordessa_skills.api.errors import SkillAssetError
from ordessa_skills.formats.agent_skills.tree import scan_tree


def _make_skill(root, files=({"SKILL.md"},), bytes_map=None):
    for relative in sorted(set().union(*files)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        size = (bytes_map or {}).get(relative, len(relative))
        path.write_bytes(b"x" * size)


def test_a_plain_tree_is_listed_sorted_with_sizes(tmp_path):
    _make_skill(tmp_path, files=({"SKILL.md", "scripts/run.sh", "references/deep.md"},))
    entries = scan_tree(tmp_path)
    assert [entry.relative for entry in entries] == [
        "SKILL.md", "references/deep.md", "scripts/run.sh"]
    assert all(entry.size == len(entry.relative) for entry in entries)


def test_symlinked_files_and_directories_are_refused(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    _make_skill(tmp_path, files=({"SKILL.md"},))
    (tmp_path / "link.txt").symlink_to(outside)
    with pytest.raises(SkillAssetError) as refusal:
        scan_tree(tmp_path)
    assert refusal.value.code == "SKILL_ASSET_INVALID"
    (tmp_path / "link.txt").unlink()

    (tmp_path / "linked-dir").symlink_to(tmp_path / "references" if
                                          (tmp_path / "references").exists()
                                          else tmp_path)
    with pytest.raises(SkillAssetError):
        scan_tree(tmp_path)


def test_fifo_entries_are_refused(tmp_path):
    _make_skill(tmp_path, files=({"SKILL.md"},))
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(SkillAssetError):
        scan_tree(tmp_path)


def test_entry_and_byte_bounds_are_enforced(tmp_path):
    from ordessa_skills.api.identity import MAX_ASSET_BYTES, MAX_ASSET_ENTRIES

    names = {f"f{i:03d}.txt" for i in range(MAX_ASSET_ENTRIES + 1)}
    names.add("SKILL.md")
    for name in names:
        (tmp_path / name).write_text("x")
    with pytest.raises(SkillAssetError) as refusal:
        scan_tree(tmp_path)
    assert refusal.value.code == "SKILL_ASSET_OUTSIDE_BOUNDS"

    small = tmp_path.parent / "small-skill"
    small.mkdir(exist_ok=True)
    (small / "SKILL.md").write_bytes(b"\0")
    (small / "big.bin").write_bytes(b"\0" * (MAX_ASSET_BYTES + 1))
    with pytest.raises(SkillAssetError) as refusal:
        scan_tree(small)
    assert refusal.value.code == "SKILL_ASSET_OUTSIDE_BOUNDS"

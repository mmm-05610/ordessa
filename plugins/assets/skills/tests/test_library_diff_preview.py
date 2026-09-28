"""Revision diff + bounded preview (library/diff.py).

Part of `plugins/assets/tests/test_discovery_view.py` @ 752f148b1b ports here:
its diff and preview assertions belonged to the legacy `AssetsService`, which
plan.md 原有 Assets-Skill 迁移 splits — the generic discovery/external rows stay
with the service slice, the skill-content reads land in `library/diff.py`.

Plus the G02 preview counter-examples (verification.md: 「preview 读任意文
件」, 「导入即执行脚本」).
"""
from __future__ import annotations

import hashlib
import os

import pytest

from ordessa_skills.api.errors import AssetDomainError, PreviewError
from ordessa_skills.library import diff as diff_module
from ordessa_skills.library.diff import (
    MAX_PREVIEW_BYTES,
    diff_revisions,
    file_map,
    preview_file,
    read_revision_text,
    text_diff,
)
from ordessa_skills.library.import_transfer import ImportService
from ordessa_skills.library.store import SkillRevisionStore

ASSET = "demo-skill"


def _import(env, files: dict[str, bytes], *, revision: int) -> dict:
    """Stage a package through the real bounded-transfer path."""
    service, records = env["service"], env["records"]
    opened = service.begin(request_id="r", files=[
        {"path": path, "bytes": len(data),
         "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        for path, data in sorted(files.items())],
        total_bytes=sum(len(data) for data in files.values()))
    for index, path in enumerate(sorted(files)):
        data = files[path]
        service.chunk(opened["importId"], index=index, payload=data,
                      sha256="sha256:" + hashlib.sha256(data).hexdigest())
    service.prepare(opened["importId"],
                    source={"type": "local-transfer", "origin": "desktop"})
    return service.commit(opened["importId"], asset_id=ASSET, revision=revision)


@pytest.fixture()
def env(tmp_path):
    """Records-free import service over a store, plus one installed revision."""
    store = SkillRevisionStore(tmp_path / "assets")
    service = ImportService(root=tmp_path / "assets", store=store)
    return {"tmp": tmp_path, "store": store, "service": service, "records": None,
           "root": tmp_path / "assets"}


V1 = {
    "SKILL.md": b"---\nname: demo-skill\ndescription: A demo skill.\n---\n\n# v1 body\n",
    "references/deep.md": b"# Deep reference material that must not be injected either\n",
}
V2 = {
    "SKILL.md": b"---\nname: demo-skill\ndescription: A demo skill.\n---\n\n# v2 body\n",
    "references/deep.md": b"# Deep reference material that must not be injected either\n",
    "references/extra.md": b"# added in v2\n",
}


# -- the ported legacy assertions --------------------------------------------

def test_diff_summarises_two_revisions_without_executing_content(env):
    _import(env, V1, revision=1)
    _import(env, V2, revision=2)
    report = diff_revisions(env["store"], asset_id=ASSET, from_revision=1,
                            to_revision=2)
    assert report["changed"] == ["SKILL.md"]
    assert report["added"] == ["references/extra.md"]
    assert report["removed"] == []
    assert report["assetId"] == ASSET and report["fromRevision"] == 1 \
        and report["toRevision"] == 2


def test_preview_is_textual_and_bounded_and_flags_scripts(env):
    _import(env, dict(V1, **{"scripts/run.sh": b"#!/bin/sh\nexit 42\n"}), revision=1)
    preview = preview_file(env["store"], asset_id=ASSET, revision=1, path="SKILL.md")
    assert preview["text"].startswith("---")
    assert preview["script"] is False
    assert preview["bytes"] == len(V1["SKILL.md"])
    # the legacy test carried this row behind an `if False` dead branch; here
    # it is a real assertion (see the slice report).
    script = preview_file(env["store"], asset_id=ASSET, revision=1,
                          path="scripts/run.sh")
    assert script["script"] is True
    assert script["text"] == "#!/bin/sh\nexit 42\n"
    # the stored copy keeps the bytes and loses the executable bit
    stored = env["store"].revision_dir(ASSET, 1) / "scripts" / "run.sh"
    assert not os.access(stored, os.X_OK)
    with pytest.raises(PreviewError):
        preview_file(env["store"], asset_id=ASSET, revision=1, path="missing.md")


def test_file_map_carries_bytes_and_content_digests(env):
    _import(env, V1, revision=1)
    mapping = file_map(env["store"], ASSET, 1)
    assert sorted(mapping) == sorted(V1)
    for path, (size, digest) in mapping.items():
        assert (size, digest) == (len(V1[path]),
                                  hashlib.sha256(V1[path]).hexdigest())


# -- the bounded text diff ----------------------------------------------------

def test_text_diff_shows_the_changed_lines_between_revisions(env):
    _import(env, V1, revision=1)
    _import(env, V2, revision=2)
    report = text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=2)
    assert report["changed"] is True
    assert report["path"] == "SKILL.md"
    body = "\n".join(report["unified"])
    assert "-# v1 body" in body and "+# v2 body" in body
    assert "references/deep.md" not in body  # only the asked-for file is read
    assert report["truncated"] is False


def test_text_diff_handles_a_file_present_in_one_revision_only(env):
    _import(env, V1, revision=1)
    _import(env, V2, revision=2)
    added = text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=2,
                      path="references/extra.md")
    assert added["changed"] is True
    assert any(line.startswith("+") for line in added["unified"])
    removed = text_diff(env["store"], asset_id=ASSET, from_revision=2, to_revision=1,
                        path="references/extra.md")
    assert any(line.startswith("-") for line in removed["unified"])
    same = text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=1,
                     path="SKILL.md")
    assert same["changed"] is False and same["unified"] == []


def test_the_text_preview_is_size_bounded_and_says_so(env):
    _import(env, V1, revision=1)
    _import(env, V2, revision=2)
    report = text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=2,
                       max_bytes=16)
    assert report["truncated"] is True
    assert report["bytes"] > 16
    assert sum(len(line) for line in report["unified"]) <= 16


# -- G02 counter-examples: the preview reads nothing arbitrary -----------------

@pytest.mark.parametrize("path", [
    "/etc/passwd",
    "../../../etc/passwd",
    "references/../../../etc/passwd",
    "SKILL.md\x00",
    "",
    "./../../etc/shadow",
])
def test_preview_refuses_every_shape_that_leaves_the_revision(env, path):
    _import(env, V1, revision=1)
    with pytest.raises(PreviewError) as refusal:
        preview_file(env["store"], asset_id=ASSET, revision=1, path=path)
    assert refusal.value.code == "PREVIEW_REFUSED"
    assert "root:" not in refusal.value.message
    with pytest.raises((PreviewError, AssetDomainError)):
        read_revision_text(env["store"], asset_id=ASSET, revision=1, path=path)
    with pytest.raises((PreviewError, AssetDomainError)):
        text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=1,
                  path=path)


def test_a_link_planted_in_a_revision_tree_is_refused_not_read(env):
    """The stored tree is read-only, but a hostile filesystem is still checked."""
    _import(env, V1, revision=1)
    directory = env["store"].revision_dir(ASSET, 1)
    os.symlink("/etc/passwd", directory / "escape.md")
    with pytest.raises(PreviewError):
        preview_file(env["store"], asset_id=ASSET, revision=1, path="escape.md")
    with pytest.raises(PreviewError):
        read_revision_text(env["store"], asset_id=ASSET, revision=1, path="escape.md")
    with pytest.raises(PreviewError):
        text_diff(env["store"], asset_id=ASSET, from_revision=1, to_revision=1,
                  path="escape.md")
    os.unlink(directory / "escape.md")


def test_an_oversized_or_binary_file_is_refused(env):
    # built straight into the store: a 256 KiB+1 file cannot even be transferred
    # as one chunk (MAX_CHUNK_BYTES), which is the other half of the bound.
    source = env["tmp"] / "big-src"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(V1["SKILL.md"])
    (source / "references").mkdir()
    (source / "references" / "big.txt").write_bytes(b"x" * (MAX_PREVIEW_BYTES + 1))
    env["store"].install(source, asset_id=ASSET, revision=1)
    with pytest.raises(PreviewError) as oversized:
        preview_file(env["store"], asset_id=ASSET, revision=1, path="references/big.txt")
    assert "preview bound" in oversized.value.message
    binary = dict(V1, **{"references/blob.bin": bytes(range(256))})
    _import(env, binary, revision=2)
    with pytest.raises(PreviewError) as not_text:
        preview_file(env["store"], asset_id=ASSET, revision=2,
                     path="references/blob.bin")
    assert not_text.value.code == "PREVIEW_REFUSED"


def test_a_missing_revision_is_a_typed_refusal(env):
    with pytest.raises(AssetDomainError) as refusal:
        diff_revisions(env["store"], asset_id=ASSET, from_revision=1, to_revision=2)
    assert refusal.value.code == "SKILL_ASSET_MISSING"
    with pytest.raises(AssetDomainError):
        file_map(env["store"], ASSET, 1)
    assert diff_module.MAX_PREVIEW_BYTES == 256 * 1024  # the legacy service bound

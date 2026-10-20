"""G02 at the library layer: links, size, hostile frontmatter, no execution.

verification.md G02 counter-examples: symlink/穿越, 过量包, 导入即执行脚本,
preview 读任意文件 (the preview half ports with `library/diff.py` and is covered
in test_library_diff_preview.py). These are the content-library halves, run
through the real install and bounded-transfer paths.
"""
from __future__ import annotations

import ast
import hashlib
import os
import stat
from pathlib import Path

import pytest

from ordessa_skills.api.errors import ImportError_, SkillAssetError
from ordessa_skills.library.import_transfer import ImportService
from ordessa_skills.library.store import SkillRevisionStore

ASSET = "demo-skill"
MANIFEST = b"---\nname: demo-skill\ndescription: A demo.\n---\nbody\n"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _transfer(service: ImportService, files: dict[str, bytes], *, revision: int):
    opened = service.begin(request_id="r", files=[
        {"path": path, "bytes": len(data), "sha256": _digest(data)}
        for path, data in sorted(files.items())],
        total_bytes=sum(len(data) for data in files.values()))
    for index, path in enumerate(sorted(files)):
        service.chunk(opened["importId"], index=index, payload=files[path],
                      sha256=_digest(files[path]))
    service.prepare(opened["importId"],
                    source={"type": "local-transfer", "origin": "desktop"})
    return service.commit(opened["importId"], asset_id=ASSET, revision=revision)


# -- symlink / escape --------------------------------------------------------

def test_a_symlinked_file_never_installs(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(MANIFEST)
    os.symlink("/etc/passwd", source / "escape.md")
    store = SkillRevisionStore(tmp_path / "assets")
    with pytest.raises(SkillAssetError) as refusal:
        store.install(source, asset_id=ASSET, revision=1)
    assert refusal.value.code == "SKILL_ASSET_INVALID"
    assert not (tmp_path / "assets" / "skill" / ASSET / "1").exists()
    # nothing outside the source was copied anywhere under the assets root
    assert not (tmp_path / "assets" / "escape.md").exists()


def test_a_symlinked_directory_never_installs(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(MANIFEST)
    os.symlink("/etc", source / "elsewhere")
    store = SkillRevisionStore(tmp_path / "assets")
    with pytest.raises(SkillAssetError) as refusal:
        store.install(source, asset_id=ASSET, revision=1)
    assert refusal.value.code == "SKILL_ASSET_INVALID"


def test_a_declared_escape_path_never_reaches_the_transfer(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    for path in ("/etc/passwd", "../outside.md", "a/../../b.md", "x\x00.md"):
        with pytest.raises(ImportError_) as refusal:
            service.begin(request_id="r",
                          files=[{"path": path, "bytes": len(MANIFEST),
                                  "sha256": _digest(MANIFEST)}],
                          total_bytes=len(MANIFEST))
        assert refusal.value.code == "IMPORT_PATH_INVALID"
    assert not (tmp_path / "assets" / "import").exists()


# -- oversized package -------------------------------------------------------

def test_too_many_entries_refuse_the_install_and_leave_nothing(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(MANIFEST)
    for index in range(513):  # MAX_ASSET_ENTRIES is 512
        (source / f"file-{index}.md").write_bytes(b"x")
    store = SkillRevisionStore(tmp_path / "assets")
    with pytest.raises(SkillAssetError) as refusal:
        store.install(source, asset_id=ASSET, revision=1)
    assert refusal.value.code == "SKILL_ASSET_OUTSIDE_BOUNDS"
    # the budget is charged while walking, so nothing lands at all: not the
    # revision, not a staging directory beside it
    assert not (tmp_path / "assets" / "skill" / ASSET / "1").exists()
    asset_root = tmp_path / "assets" / "skill" / ASSET
    leftovers = ([] if not asset_root.is_dir() else
                 [p.name for p in asset_root.iterdir()
                  if p.name.startswith("skill-staging-")])
    assert leftovers == []


def test_the_transfer_declared_bounds_are_checked_before_any_write(tmp_path):
    service = ImportService(root=tmp_path / "assets")
    files = [{"path": f"f{i}", "bytes": 1, "sha256": _digest(b"x")}
             for i in range(513)]
    with pytest.raises(ImportError_) as refusal:
        service.begin(request_id="r", files=files, total_bytes=513)
    assert refusal.value.code == "IMPORT_BOUNDS_EXCEEDED"
    assert not (tmp_path / "assets" / "import").exists()


# -- nothing executes --------------------------------------------------------

def test_a_bundled_script_is_stored_as_bytes_and_never_run(tmp_path):
    sentinel = tmp_path / "SENTINEL"
    script = f"#!/bin/sh\ntouch {sentinel}\n".encode()
    service = ImportService(root=tmp_path / "assets")
    result = _transfer(service, {"SKILL.md": MANIFEST, "scripts/run.sh": script},
                       revision=1)
    assert result["effect"] == "stored"
    stored = SkillRevisionStore(tmp_path / "assets").revision_dir(ASSET, 1)
    assert (stored / "scripts" / "run.sh").read_bytes() == script
    assert not (stored / "scripts" / "run.sh").stat().st_mode & (
        stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # the only thing the manifest ever earns is a name in the script list
    assert not sentinel.exists()
    assert hashlib.sha256((stored / "scripts" / "run.sh").read_bytes()).hexdigest() \
        == hashlib.sha256(script).hexdigest()


def test_a_yaml_payload_that_would_execute_is_refused_by_the_parser(tmp_path):
    """`!!python/object/apply` cannot reach an object constructor here."""
    sentinel = tmp_path / "SENTINEL-YAML"
    hostile = (f"---\nname: demo-skill\ndescription: A demo.\n"
               f"payload: !!python/object/apply:os.system {[str(sentinel)]!r}\n---\n"
               ).encode()
    store = SkillRevisionStore(tmp_path / "assets")
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_bytes(hostile)
    with pytest.raises(SkillAssetError) as refusal:
        store.install(source, asset_id=ASSET, revision=1)
    assert refusal.value.code == "SKILL_FRONTMATTER_INVALID"
    assert not sentinel.exists()


def test_the_no_execution_sweep_actually_covers_the_library_area():
    """Guards test_no_execution.py: its AST sweep really sees `library/`.

    A sweep that silently matched no files would be vacuously green, so the
    module set is asserted first and each module is then re-checked for the
    spawn/exec primitives this domain must never reach for.
    """
    library = (Path(__file__).resolve().parents[1] / "src" / "ordessa_skills"
               / "library")
    modules = sorted(path.name for path in library.glob("*.py"))
    assert {"__init__.py", "store.py", "records.py", "catalog.py",
            "import_transfer.py", "revisions.py", "diff.py"} <= set(modules), modules
    for path in sorted(library.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        attribute_calls = {node.func.attr for node in ast.walk(tree)
                           if isinstance(node, ast.Call)
                           and isinstance(node.func, ast.Attribute)}
        assert not {"system", "popen", "execv", "execve", "execvp", "spawnl",
                    "spawnv", "Popen", "kill", "fork"} & attribute_calls, path.name
        bare_calls = {node.func.id for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not {"exec", "eval", "compile", "__import__"} & bare_calls, path.name
        imported = {alias.name.split(".")[0]
                    for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.level == 0}
        assert not {"subprocess", "pty", "multiprocessing", "socket", "ctypes"} \
            & imported, (path.name, imported)

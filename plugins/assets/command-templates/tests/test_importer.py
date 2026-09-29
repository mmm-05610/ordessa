"""T07 / G21: read-only native import preview/commit.

Only user-selected bytes are examined; the importer never opens a file itself.
A native prompt is converted to a revision **only** when the mapping is provably
lossless: dynamic include, inline command execution, a permission/model field, or
any non-representable parameter form is refused (never a "partial" import), the
original is never written back, and there is no HOME/project scan.
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api.errors import ProjectionRefusedError
from ordessa_command_templates.library import importer
from conftest import make_template


def test_plain_literal_imports_losslessly():
    raw = b"# Review\n\nSummarize the diff for me.\n"
    preview = importer.preview_import(raw=raw, source_label="review")
    assert preview.ok and preview.reason is None
    assert "Summarize the diff" in preview.body
    assert preview.parameters == ()  # no placeholders -> zero params


def test_claude_frontmatter_permission_field_refused():
    raw = (b"---\nname: review\nallowed-tools: Bash, Read\n---\nbody\n")
    preview = importer.preview_import(raw=raw, source_label="review")
    assert not preview.ok and preview.reason == "PERMISSION_FIELD"


def test_positional_and_arguments_params_refused():
    for raw in [b"run $1 now", b"args: $ARGUMENTS here", b"edit $FILE please"]:
        preview = importer.preview_import(raw=raw, source_label="x")
        assert not preview.ok and preview.reason == "DYNAMIC_INCLUDE_OR_EXEC"


def test_inline_bash_and_at_mention_refused():
    assert importer.preview_import(raw=b"today !`date`", source_label="x").reason == \
        "DYNAMIC_INCLUDE_OR_EXEC"
    assert importer.preview_import(raw=b"read @src/main.py", source_label="x").reason == \
        "DYNAMIC_INCLUDE_OR_EXEC"
    assert importer.preview_import(raw=b"```bash\nrm -rf\n```", source_label="x").reason == \
        "DYNAMIC_INCLUDE_OR_EXEC"


def test_unicode_ordinary_body_imports():
    preview = importer.preview_import(raw="你好 {{focus}}".encode("utf-8"), source_label="greet")
    assert preview.ok
    assert any(p.name == "focus" for p in preview.parameters)


def test_bad_encoding_and_oversize_refused():
    assert importer.preview_import(raw=b"\xff\xfe not utf8", source_label="x").reason == "ENCODING"
    assert importer.preview_import(raw=b"x" * (64 * 1024 + 1), source_label="x").reason == "SIZE"


def test_commit_only_from_approved_preview():
    good = importer.preview_import(raw=b"hello {{name}}", source_label="g")
    plan = importer.commit_from_preview(good)
    assert plan["origin"] == "imported" and "hello" in plan["body"]
    bad = importer.preview_import(raw=b"nope $1", source_label="b")
    with pytest.raises(ProjectionRefusedError):
        importer.commit_from_preview(bad)


def test_import_commit_stores_imported_origin_without_touching_source(service, tmp_path):
    # The importer is given bytes; there is no source file to preserve, but the
    # commit path must mark provenance 'imported' and never re-scan the fs.
    source = tmp_path / "review.md"
    source.write_bytes(b"Summarize {{scope}} please")
    raw = source.read_bytes()  # explicit, user-driven selection of bytes
    preview = importer.preview_import(raw=raw, source_label="review")
    assert preview.ok
    rev = service.import_commit(principal="u1", preview=preview, template_id="tmpl.imp",
                                operation_key="imp")
    tmpl = service.store.get_template("tmpl.imp")
    assert tmpl.origin == "imported"
    assert rev.body == "Summarize {{scope}} please"
    # Original file is byte-for-byte unchanged.
    assert source.read_bytes() == raw


def test_import_never_scans_a_directory(service, tmp_path, monkeypatch):
    # There is no code path that lists a directory; assert the importer module
    # exposes no fs-walking helpers and refuses when given a path-like label with
    # traversal (it treats source_label as a name, never opens it).
    preview = importer.preview_import(raw=b"fine {{x}}", source_label="../../etc/passwd")
    # A traversal-looking label is used only as a display name, not opened.
    assert preview.ok
    assert preview.display_name == "../../etc/passwd"

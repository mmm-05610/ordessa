"""Exact, fail-closed local SourceMaterialPort behavior."""
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest


SCOPE = Scope("project-source-realm", "project-source-project")
ACTOR = ActorRef("local-capture", "service", "trusted-local-composition")
NOW = "2026-10-14T10:00:00.000000Z"


def _source(document_id, raw, *, source_id="source-one", version="captured-v1"):
    return SourceRef(source_id, "document",
        SourceLocator("document", provider="project-files", document_id=document_id),
        VersionCapture(version, Digest("sha256", hashlib.sha256(raw).hexdigest())),
        NOW, ACTOR, "text/markdown", len(raw))


def _context(scope=SCOPE):
    return CommandContext(scope, "local-principal", ACTOR, "source-read", NOW, "source-test")


@pytest.mark.parametrize("field,expected", [
    ("digest", "SOURCE_VERSION_MISMATCH"),
    ("length", "SOURCE_VERSION_MISMATCH"),
    ("media_type", "SOURCE_VERSION_MISMATCH"),
    ("captured_by", "SOURCE_VERSION_MISMATCH"),
    ("captured_at", "SOURCE_VERSION_MISMATCH"),
    ("original_url", "SOURCE_VERSION_MISMATCH"),
    ("locator", "SOURCE_UNAVAILABLE"),
])
def test_every_source_ref_field_is_part_of_the_exact_pin(tmp_path, field, expected):
    raw = b"DID: exact source reference\n"
    (tmp_path / "design.md").write_bytes(raw)
    source = _source("design.md", raw)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path,
        source_mappings=((source, "design.md"),))
    changed = {
        "digest": replace(source, capture=VersionCapture(source.capture.upstream_version,
            Digest("sha256", hashlib.sha256(b"other content").hexdigest()))),
        "length": replace(source, byte_length=source.byte_length + 1),
        "media_type": replace(source, media_type="text/plain"),
        "captured_by": replace(source, captured_by=ActorRef("other-capture", "service", "trusted-local-composition")),
        "captured_at": replace(source, captured_at="2026-10-14T10:01:00.000000Z"),
        "original_url": replace(source, original_url="https://example.com/source"),
        "locator": replace(source, locator=SourceLocator("document", provider="project-files", document_id="other.md")),
    }[field]
    try:
        with pytest.raises(ApplicationError, match=expected):
            reader.read(_context(), changed)
    finally:
        reader.close()


def test_reads_only_exact_configured_scope_source_version_and_bytes(tmp_path):
    raw = b"DID: pinned local source\n"
    document = tmp_path / "docs" / "design.md"
    document.parent.mkdir()
    document.write_bytes(raw)
    source = _source("docs/design.md", raw)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((source, "docs/design.md"),))
    try:
        assert reader.read(_context(), source) == raw
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(_context(Scope("other-realm", SCOPE.project_id)), source)
        newer_version = replace(source, capture=VersionCapture("captured-v2", source.capture.content_digest))
        with pytest.raises(ApplicationError, match="SOURCE_VERSION_MISMATCH"):
            reader.read(_context(), newer_version)
        changed_metadata = replace(source, captured_at="2026-10-14T10:01:00.000000Z")
        with pytest.raises(ApplicationError, match="SOURCE_VERSION_MISMATCH"):
            reader.read(_context(), changed_metadata)
        unknown_source = replace(source, source_id="unconfigured-source")
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(_context(), unknown_source)
    finally:
        reader.close()


def test_same_document_versions_require_distinct_explicit_files(tmp_path):
    old = b"DID: old revision\n"
    new = b"DID: new revision\n"
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "v1.md").write_bytes(old)
    (tmp_path / "current.md").write_bytes(new)
    old_ref = _source("design.md", old, version="v1")
    new_ref = _source("design.md", new, version="v2")
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path,
        source_mappings=((old_ref, "archive/v1.md"), (new_ref, "current.md")))
    try:
        assert reader.read(_context(), old_ref) == old
        assert reader.read(_context(), new_ref) == new
        missing = _source("design.md", b"unavailable", version="v3")
        with pytest.raises(ApplicationError, match="SOURCE_VERSION_MISMATCH"):
            reader.read(_context(), missing)
    finally:
        reader.close()


def test_two_versions_cannot_share_one_mutable_path(tmp_path):
    raw = b"DID: same bytes\n"
    (tmp_path / "design.md").write_bytes(raw)
    first = _source("design.md", raw, version="v1")
    second = _source("design.md", raw, version="v2")
    with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
        ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path,
            source_mappings=((first, "design.md"), (second, "design.md")))


def test_same_version_cannot_name_two_content_identities(tmp_path):
    first_bytes = b"DID: first content\n"
    second_bytes = b"DID: second content\n"
    first = _source("design.md", first_bytes, version="v1")
    second = _source("design.md", second_bytes, version="v1")
    with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
        ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path,
            source_mappings=((first, "v1-a.md"), (second, "v1-b.md")))


def test_configured_but_missing_file_is_unavailable(tmp_path):
    source = _source("design.md", b"DID: absent\n")
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path,
        source_mappings=((source, "archive/v1.md"),))
    try:
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(_context(), source)
    finally:
        reader.close()


def test_changed_local_bytes_are_content_mismatch_not_a_new_version(tmp_path):
    original = b"DID: same length old\n"
    document = tmp_path / "design.md"
    document.write_bytes(original)
    source = _source("design.md", original)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((source, "design.md"),))
    try:
        document.write_bytes(b"DID: same length new\n")
        with pytest.raises(ApplicationError, match="SOURCE_CONTENT_MISMATCH"):
            reader.read(_context(), source)
    finally:
        reader.close()


@pytest.mark.parametrize("document_id", ("../outside.md", "/outside.md", "docs//design.md", "docs\\design.md"))
def test_rejects_unsafe_relative_document_ids_at_configuration(tmp_path, document_id):
    source = _source(document_id, b"x")
    with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
        ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((source, "design.md"),))


def test_rejects_symlinked_intermediate_and_final_paths(tmp_path):
    raw = b"DID: pinned\n"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_bytes(raw)
    (tmp_path / "link.md").symlink_to(outside)
    source = _source("link.md", raw)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((source, "link.md"),))
    try:
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(_context(), source)
    finally:
        reader.close()

    (tmp_path / "linked-dir").symlink_to(outside.parent, target_is_directory=True)
    nested = _source("linked-dir/" + outside.name, raw)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((nested, "linked-dir/" + outside.name),))
    try:
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(_context(), nested)
    finally:
        reader.close()


def test_rejects_symlinked_configured_root(tmp_path):
    real_root = tmp_path / "real-project"
    real_root.mkdir()
    root_link = tmp_path / "project-link"
    root_link.symlink_to(real_root, target_is_directory=True)
    raw = b"DID: pinned\n"
    source = _source("design.md", raw)
    with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
        ProjectSourceMaterials(object(), scope=SCOPE, root=root_link, source_mappings=((source, "design.md"),))


def test_closed_reader_refuses_further_reads(tmp_path):
    raw = b"DID: pinned\n"
    (tmp_path / "design.md").write_bytes(raw)
    source = _source("design.md", raw)
    reader = ProjectSourceMaterials(object(), scope=SCOPE, root=tmp_path, source_mappings=((source, "design.md"),))
    reader.close()
    with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
        reader.read(_context(), source)

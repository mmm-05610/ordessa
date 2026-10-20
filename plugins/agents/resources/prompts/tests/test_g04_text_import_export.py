"""T05 / G04 — UTF-8 import and export boundaries.

Positive: a user-uploaded single UTF-8 text becomes an ordinary prompt and
exports back byte-for-byte. Required counter-examples
(verification.md G04, data-model.md limits): invalid encoding, NUL,
whitespace-only, over 128 KiB, over 32 supplemental instructions, a
snapshot over 1 MiB refused *before* application (never truncated), a
leading BOM stripped only at the very start and reported, directory /
absolute-path dereferencing refused (the service takes uploaded bytes,
never a path) and dangerous export filenames neutralised.

Gates: G04. Requirements: FR09, FR14, FR15.
"""
from __future__ import annotations

import base64

import pytest

from ordessa_prompts.api import (
    BODY_MAX_BYTES,
    IMPORT_MAX_BYTES,
    InvalidContentError,
    LimitExceededError,
    PromptError,
    PromptSelection,
    SNAPSHOT_MAX_TOTAL_BODY_BYTES,
    body_digest,
)
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.textio import (
    decode_import_bytes,
    export_filename,
    suggested_title_from_hint,
)

CANARY = "CANARY-IMPORT-SECRET-must-not-appear-in-errors"


# -- the happy path ------------------------------------------------------------

def test_a_uploaded_utf8_text_becomes_an_ordinary_prompt_and_exports_byte_exact(
        library_service):
    text = "# 中文指令\nBe concise.\n".encode("utf-8")
    imported = library_service.import_text(text, filename_hint="concise.md",
                                           operation_key="k-imp")
    assert imported["kind"] == "instruction"
    assert imported["scope"] == {"kind": "library"}
    assert imported["bomStripped"] is False
    assert imported["title"] == "concise"
    exported = library_service.export_text(imported["id"])
    assert base64.b64decode(exported["bodyBase64"]) == text
    assert exported["sha256"] == body_digest(text)
    assert exported["revision"] == 1
    assert exported["suggestedFilename"] == "concise.prompt1.md"


def test_decode_import_is_pure_and_reports_the_final_saved_bytes():
    imported = decode_import_bytes("héllo → 世界".encode("utf-8"))
    assert imported.body.decode("utf-8") == "héllo → 世界"
    assert imported.bom_stripped is False


# -- encoding and capacity refusals -------------------------------------------

@pytest.mark.parametrize("content,expected_code", [
    (b"\xff\xfe not utf-8", "INVALID_CONTENT"),
    (b"valid prefix \x80\x80 trailing", "INVALID_CONTENT"),
    (b"has\x00nul", "INVALID_CONTENT"),
    (b"", "INVALID_CONTENT"),
    (b"   \n\t  ", "INVALID_CONTENT"),
    (b" \x00 ", "INVALID_CONTENT"),
    ((CANARY + " tail").encode("utf-8") + b"\x80", "INVALID_CONTENT"),
])
def test_badly_encoded_nul_and_blank_imports_refuse_without_storing_anything(
        library_service, store, db_rows, content, expected_code):
    with pytest.raises(PromptError) as exc:
        library_service.import_text(content, filename_hint="bad.md",
                                    operation_key=f"k-bad-{abs(hash(content))}")
    assert exc.value.code == expected_code
    assert CANARY not in str(exc.value), (
        f"the refusal echoed the uploaded content: {exc.value}")
    assert db_rows(store, "SELECT * FROM prompt_records") == []
    assert db_rows(store, "SELECT * FROM prompt_revisions") == []
    assert db_rows(store, "SELECT * FROM prompt_idempotency") == []


def test_a_predecoded_string_is_refused_before_decoding():
    with pytest.raises(InvalidContentError):
        decode_import_bytes("already a string")  # type: ignore[arg-type]


def test_import_at_exactly_the_capacity_is_accepted_and_one_byte_more_is_refused(
        library_service, store, db_rows):
    assert IMPORT_MAX_BYTES == BODY_MAX_BYTES
    at_limit = b"x" * BODY_MAX_BYTES
    created = library_service.import_text(at_limit, operation_key="k-at-limit")
    assert created["latestRevision"] == 1
    over = b"x" * (BODY_MAX_BYTES + 1)
    with pytest.raises(LimitExceededError) as exc:
        library_service.import_text(over, operation_key="k-over-limit")
    assert exc.value.code == "LIMIT_EXCEEDED"
    assert exc.value.details["limit"] == IMPORT_MAX_BYTES
    # nothing was truncated into storage: the only record is the full-size one
    rows = db_rows(store, "SELECT length(body) FROM prompt_revisions")
    assert [int(row[0]) for row in rows] == [BODY_MAX_BYTES]
    assert library_service.get(created["id"])["bodyByteSize"] == BODY_MAX_BYTES


def test_an_over_capacity_import_never_creates_a_partial_record(store):
    """The refusal happens before the create is attempted, so a too-large
    document cannot leave a truncated prompt behind."""
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    with pytest.raises(LimitExceededError):
        service.import_text(b"y" * (BODY_MAX_BYTES + 4096), operation_key="k-none")
    assert list(store.connection.execute("SELECT * FROM prompt_records")) == []
    assert list(store.connection.execute("SELECT * FROM prompt_idempotency")) == []


# -- BOM rules ------------------------------------------------------------------

def test_a_leading_bom_is_stripped_only_at_the_start_and_reported(library_service):
    imported = library_service.import_text(b"\xef\xbb\xbfhello",
                                           filename_hint="bom.md",
                                           operation_key="k-bom")
    assert imported["bomStripped"] is True
    exported = library_service.export_text(imported["id"])
    assert base64.b64decode(exported["bodyBase64"]) == b"hello"
    # the stored digest is over the final saved bytes, not the uploaded ones
    assert exported["sha256"] == body_digest(b"hello")
    assert exported["sha256"] != body_digest(b"\xef\xbb\xbfhello")


def test_interior_and_double_boms_are_not_silently_mangled():
    interior = decode_import_bytes(b"a\xef\xbb\xbfb")
    assert interior.body == "a\ufeffb".encode("utf-8")
    assert interior.bom_stripped is False, "only the very first BOM is stripped"

    with pytest.raises(InvalidContentError):
        decode_import_bytes(b"\x00\xef\xbb\xbfleading nul")


def test_a_second_leading_bom_refuses_the_whole_create_without_storing_it(
        library_service, store, db_rows):
    """textio strips one BOM and says so; a body that still *starts* with a
    BOM is an encoding ambiguity the repository refuses rather than saving
    half-normalised bytes (data-model: the digest is over the final bytes)."""
    with pytest.raises(InvalidContentError) as exc:
        library_service.import_text(b"\xef\xbb\xbf\xef\xbb\xbfbody",
                                    operation_key="k-double-bom")
    assert exc.value.code == "INVALID_CONTENT"
    assert db_rows(store, "SELECT * FROM prompt_records") == []


def test_import_never_truncates_a_whitespace_padded_document():
    """No implicit trim: spaces and newlines around real content survive."""
    padded = b"  \n keep me exactly \t\n"
    imported = decode_import_bytes(padded)
    assert imported.body == padded


# -- no path dereferencing, no dangerous names ---------------------------------

def test_import_never_reads_the_path_a_filename_hint_points_at(
        monkeypatch, library_service, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"DIFFERENT ON-DISK CONTENT")
    opened: list[str] = []

    def guarded_open(*args, **kwargs):
        opened.append(str(args[0]))
        raise AssertionError(f"the import path opened a file: {args[0]!r}")

    monkeypatch.setattr("builtins.open", guarded_open)
    created = library_service.import_text(b"uploaded bytes",
                                          filename_hint=str(victim),
                                          operation_key="k-nopath")
    assert opened == []
    assert base64.b64decode(library_service.export_text(created["id"])
                            ["bodyBase64"]) == b"uploaded bytes"
    assert created["title"] == "victim"
    assert victim.read_bytes() == b"DIFFERENT ON-DISK CONTENT"


@pytest.mark.parametrize("hint,expected", [
    ("/etc/passwd", "passwd"),
    ("..\\..\\windows\\system32\\config", "config"),
    ("../../evil", "evil"),
    ("nested/deep/name.txt", "name"),
    (".hidden", "hidden"),
    ("tar.gz", "tar"),
    ("", "Imported prompt"),
    (None, "Imported prompt"),
    ("weird \x00 name.md", "weird name"),
])
def test_a_hint_never_becomes_a_path_in_the_suggested_title(hint, expected):
    title = suggested_title_from_hint(hint)
    assert title == expected
    assert "/" not in title and "\\" not in title and "\x00" not in title


@pytest.mark.parametrize("title", [
    "../../etc/passwd", "a/b/c", "..\\..\\evil", "\x00nul",
    "..", ".", "  ", "中文名", "quote'\"`and $() {} ; rm -rf /",
])
def test_export_filenames_are_safe_hints_never_host_paths(tmp_path, library_service,
                                                          title):
    created = library_service.create(kind="instruction", scope={"kind": "library"},
                                     title=title, description=None,
                                     body=b"body text",
                                     operation_key=f"k-t-{abs(hash(title))}")
    exported = library_service.export_text(created["id"])
    name = exported["suggestedFilename"]
    assert "/" not in name and "\\" not in name and "\x00" not in name
    assert ".." not in name
    assert name.endswith(".prompt1.md")
    assert len(name) <= 96
    # the Server writes nothing: the client's own save dialog owns the target
    assert [path for path in tmp_path.rglob("*") if path.name == name] == []


def test_export_of_an_old_revision_returns_that_revision_and_its_digest(
        library_service):
    created = library_service.create(kind="instruction", scope={"kind": "library"},
                                     title="history", description=None,
                                     body=b"revision one", operation_key="k-h1")
    library_service.update(created["id"], expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"revision two"}, operation_key="k-h2")
    old = library_service.export_text(created["id"], 1)
    assert base64.b64decode(old["bodyBase64"]) == b"revision one"
    assert old["sha256"] == body_digest(b"revision one")
    assert old["suggestedFilename"] == "history.prompt1.md"
    latest = library_service.export_text(created["id"])
    assert base64.b64decode(latest["bodyBase64"]) == b"revision two"
    assert latest["suggestedFilename"] == "history.prompt2.md"


def test_export_filename_helper_keeps_kind_and_revision_out_of_the_path():
    name = export_filename("instruction", "../sneaky title", 12)
    assert "/" not in name and ".." not in name
    assert name == "sneaky title.prompt12.md"


# -- selection and snapshot capacity ------------------------------------------

def _instructions_ids(service, count: int, body: bytes = b"b") -> "list[str]":
    return [service.create(kind="instruction", scope={"kind": "library"},
                           title=f"i{index}", description=None,
                           body=body, operation_key=f"k-i{index}")["id"]
            for index in range(count)]


def test_more_than_32_supplemental_instructions_refuse_before_resolution(
        library_service, store, db_rows):
    ids = _instructions_ids(library_service, 33)
    selection = {"instructions": [{"promptId": pid} for pid in ids]}
    with pytest.raises(PromptError) as exc:
        library_service.resolve_snapshot(selection)
    assert exc.value.code == "INVALID_CONTENT"
    assert "32" in exc.value.message
    # refusal is pre-application: no snapshot artefact, nothing truncated to
    # the first 32 — the 33 records are all still intact
    assert len(db_rows(store, "SELECT * FROM prompt_records")) == 33
    with pytest.raises(PromptError) as preview_exc:
        library_service.preview(selection)
    assert preview_exc.value.code == "INVALID_CONTENT"


def test_exactly_32_instructions_are_allowed():
    refs = [{"promptId": f"prompt_{index:04d}"} for index in range(32)]
    parsed = PromptSelection.parse({"instructions": refs})
    assert len(parsed.instructions) == 32


def test_a_snapshot_over_one_mebibyte_is_refused_before_application_and_nothing_is_cut(
        library_service, records):
    bodies = [b"z" * BODY_MAX_BYTES for _ in range(8)]
    ids = [library_service.create(kind="instruction", scope={"kind": "library"},
                                  title=f"big{index}", description=None,
                                  body=body, operation_key=f"k-big{index}")["id"]
           for index, body in enumerate(bodies)]
    assert sum(len(body) for body in bodies) == SNAPSHOT_MAX_TOTAL_BODY_BYTES
    exact = library_service.resolve_snapshot(
        {"instructions": [{"promptId": pid} for pid in ids]})
    assert exact.total_body_bytes() == SNAPSHOT_MAX_TOTAL_BODY_BYTES

    extra = library_service.create(kind="instruction", scope={"kind": "library"},
                                   title="one more", description=None,
                                   body=b"z" * BODY_MAX_BYTES,
                                   operation_key="k-big-extra")["id"]
    over_selection = {"instructions": [{"promptId": pid}
                                       for pid in [*ids, extra]]}
    with pytest.raises(LimitExceededError) as exc:
        library_service.resolve_snapshot(over_selection)
    assert exc.value.code == "LIMIT_EXCEEDED"
    assert exc.value.details["totalBytes"] == 9 * BODY_MAX_BYTES
    # no truncation anywhere: every stored body is still the full 128 KiB
    for prompt_id in [*ids, extra]:
        assert len(records.get_revision(prompt_id).body) == BODY_MAX_BYTES


def test_persona_and_replacement_bodies_count_toward_the_snapshot_limit(
        library_service):
    ids = [library_service.create(kind=kind, scope={"kind": "library"},
                                  title=f"{kind} body", description=None,
                                  body=b"q" * BODY_MAX_BYTES,
                                  operation_key=f"k-{kind}")["id"]
           for kind in ("instruction", "persona", "system-replacement")]
    # 3 x 128 KiB is under the cap: it resolves
    ok = library_service.resolve_snapshot(
        {"instructions": [{"promptId": ids[0]}],
         "persona": {"promptId": ids[1]},
         "systemReplacement": {"promptId": ids[2]}})
    assert ok.total_body_bytes() == 3 * BODY_MAX_BYTES
    big = [library_service.create(kind="instruction", scope={"kind": "library"},
                                  title=f"pad{index}", description=None,
                                  body=b"p" * BODY_MAX_BYTES,
                                  operation_key=f"k-pad{index}")["id"]
           for index in range(6)]
    with pytest.raises(LimitExceededError):
        library_service.resolve_snapshot(
            {"instructions": [{"promptId": pid} for pid in [ids[0], *big]],
             "persona": {"promptId": ids[1]},
             "systemReplacement": {"promptId": ids[2]}})

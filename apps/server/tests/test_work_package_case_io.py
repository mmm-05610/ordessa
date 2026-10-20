"""Controlled tests for the minimal work-package case IO.

These tests exercise the case-IO surfaces with fabricated manifests and source
files written into temporary directories: the exact manifest shape, per-entry
path/digest verification, the immediate named refusal on any source drift, and
the finite projection that preserves the original references while never
carrying material, credentials or environment values.

No test here calls a model, opens a listener, touches the process environment or
reads `.env`/credentials; every input is a fake or a controlled temporary file.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

MODULE_PATH = (Path(__file__).resolve().parents[3]
               / "tooling/checks/server_product/work_package_case_io.py")

CASE_REF = "case/2026-10-17/alpha"
FAKE_SECRET = "sk-fake-not-a-real-credential-0123456789"
FAKE_PATH = "/home/example/projects/ordessa/.env"
FAKE_ENDPOINT = "https://api.example.invalid"


def _load_module():
    spec = importlib.util.spec_from_file_location("work_package_case_io_under_test",
                                                  MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


case_io = _load_module()


def _entry(entry_id, source_path, data, **overrides):
    entry = {"entry_id": entry_id, "source_path": source_path,
             "sha256": hashlib.sha256(data).hexdigest(), "byte_length": len(data)}
    entry.update(overrides)
    return entry


def _manifest(entries, *, case_ref=CASE_REF, schema=case_io.SCHEMA, **overrides):
    manifest = {"schema": schema, "case_ref": case_ref, "entries": list(entries)}
    manifest.update(overrides)
    return manifest


def _write(root, source_path, data):
    target = root / source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _record_reads(monkeypatch):
    """Patch Path.read_bytes to record every call, proving no read happened."""
    reads = []
    real_read_bytes = Path.read_bytes

    def _recording_read_bytes(self):
        reads.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _recording_read_bytes)
    return reads


def _loaded_entry(source_path, data):
    return case_io.load_manifest(_manifest([_entry("m", source_path, data)]))["entries"][0]


def _source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


# --- finite-projection primitive ----------------------------------------------

def test_bounded_projection_keeps_only_declared_fields_in_order():
    fields = {"a": 1, "b": 2, "leaked": FAKE_SECRET}
    assert case_io.bounded(fields, ("b", "a")) == {"b": 2, "a": 1}
    assert tuple(case_io.bounded(fields, ("b", "a"))) == ("b", "a")
    assert "leaked" not in case_io.bounded(fields, ("a", "b"))


def test_bounded_projection_refuses_a_missing_declared_field():
    with pytest.raises(KeyError):
        case_io.bounded({"a": 1}, ("a", "missing"))


# --- exact manifest shape -----------------------------------------------------

def test_manifest_accepts_the_declared_shape():
    loaded = case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a")]))
    assert tuple(loaded) == case_io.MANIFEST_FIELDS
    assert tuple(loaded["entries"][0]) == case_io.ENTRY_FIELDS


def test_manifest_refuses_an_unknown_key_so_it_cannot_carry_material():
    manifest = _manifest([_entry("a", "a.txt", b"a")])
    manifest["material"] = FAKE_SECRET
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(manifest)
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_an_unknown_entry_key_so_it_cannot_carry_content():
    entry = _entry("a", "a.txt", b"a")
    entry["content"] = FAKE_SECRET
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([entry]))
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_a_missing_required_field():
    manifest = _manifest([_entry("a", "a.txt", b"a")])
    del manifest["case_ref"]
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(manifest)
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_an_unsupported_schema():
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a")], schema="other/9"))
    assert excinfo.value.code == "unsupported_schema"


def test_manifest_refuses_an_empty_entry_list():
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([]))
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_a_duplicate_entry_id():
    entries = [_entry("dup", "a.txt", b"a"), _entry("dup", "b.txt", b"b")]
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest(entries))
    assert excinfo.value.code == "manifest_shape"


@pytest.mark.parametrize("source_path", ["/etc/passwd", "../outside.txt", "a/../../b"])
def test_manifest_refuses_an_absolute_or_escaping_source_path(source_path):
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([_entry("a", source_path, b"a")]))
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_a_malformed_sha256():
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a", sha256="not-a-digest")]))
    assert excinfo.value.code == "manifest_shape"


def test_manifest_refuses_a_negative_byte_length():
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a", byte_length=-1)]))
    assert excinfo.value.code == "manifest_shape"


# --- per-entry path and digest verification -----------------------------------

def test_verify_entry_accepts_a_matching_source(tmp_path):
    data = b"controlled material bytes\n"
    _write(tmp_path, "m.txt", data)
    entry = _loaded_entry("m.txt", data)
    verified = case_io.verify_entry(entry, tmp_path)
    assert verified == entry
    assert set(verified) == set(case_io.ENTRY_FIELDS)


def test_verify_entry_refuses_a_missing_source(tmp_path):
    entry = _loaded_entry("gone.txt", b"x")
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, tmp_path)
    assert excinfo.value.code == "source_missing"
    assert excinfo.value.source_path == "gone.txt"


def test_verify_entry_refuses_a_changed_digest(tmp_path):
    _write(tmp_path, "m.txt", b"changed")
    entry = _loaded_entry("m.txt", b"declared")
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, tmp_path)
    assert excinfo.value.code == "source_changed"


def test_verify_entry_refuses_a_changed_byte_length(tmp_path):
    data = b"abc"
    _write(tmp_path, "m.txt", data)
    entry = _loaded_entry("m.txt", data)
    entry = {**entry, "byte_length": len(data) + 1}
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, tmp_path)
    assert excinfo.value.code == "source_changed"


def test_verify_entry_refuses_a_symlinked_source(tmp_path):
    _write(tmp_path, "real.txt", b"x")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    entry = _loaded_entry("link.txt", b"x")
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, tmp_path)
    assert excinfo.value.code == "source_not_regular"


def test_verify_entry_refuses_a_directory_source(tmp_path):
    (tmp_path / "dir.txt").mkdir()
    entry = _loaded_entry("dir.txt", b"")
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, tmp_path)
    assert excinfo.value.code == "source_not_regular"


def test_verify_entry_refuses_a_symlinked_parent_directory(tmp_path, monkeypatch):
    # A symlinked parent directory inside the root must not carry the read out
    # of the root -- even when the outside file matches the declared digest, and
    # before any byte of it is read.
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"outside material\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    entry = _entry("a", "escape/secret.txt", secret.read_bytes())

    reads = _record_reads(monkeypatch)
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, root)
    assert excinfo.value.code == "source_escapes_root"
    assert excinfo.value.entry_id == "a"
    assert excinfo.value.source_path == "escape/secret.txt"
    assert reads == []  # refused before any byte was read


def test_verify_entry_refuses_a_symlinked_intermediate_segment(tmp_path, monkeypatch):
    # The symlink is not the immediate parent but a segment above it; the walk
    # still refuses it before reading anything.
    outside = tmp_path / "outside"
    (outside / "nested").mkdir(parents=True)
    secret = outside / "nested" / "secret.txt"
    secret.write_bytes(b"nested material\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    entry = _entry("a", "escape/nested/secret.txt", secret.read_bytes())

    reads = _record_reads(monkeypatch)
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, root)
    assert excinfo.value.code == "source_escapes_root"
    assert reads == []


def test_verify_entry_refuses_a_parent_replaced_by_a_symlink_at_open(tmp_path, monkeypatch):
    # The exact TOCTOU the old check-then-read had: the parent directory is a
    # real directory when the walk starts, then is swapped for a symlink to an
    # outside directory at the last critical moment -- right before that parent
    # is opened. The dirfd walk must refuse (never follow the swapped symlink)
    # and must never open, let alone read, the outside file.
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"outside material that must never be read\n")
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "secret.txt").write_bytes(b"declared\n")
    entry = _entry("a", "sub/secret.txt", b"declared\n")

    real_open_directory_relative = case_io.open_directory_relative

    def _swap_parent_then_open(parent_fd, name):
        target = root / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
            target.symlink_to(outside, target_is_directory=True)
        return real_open_directory_relative(parent_fd, name)

    opened_files = []
    real_open_regular_at = case_io.open_regular_at

    def _recording_open_regular_at(directory_fd, name):
        opened_files.append(name)
        return real_open_regular_at(directory_fd, name)

    monkeypatch.setattr(case_io, "open_directory_relative", _swap_parent_then_open)
    monkeypatch.setattr(case_io, "open_regular_at", _recording_open_regular_at)

    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(entry, root)

    # Refused as an escape, before the final file was ever opened: had the
    # outside file been read its bytes differ from the declared digest, so the
    # refusal would have been `source_changed` instead.
    assert excinfo.value.code == "source_escapes_root"
    assert excinfo.value.entry_id == "a"
    assert excinfo.value.source_path == "sub/secret.txt"
    assert opened_files == []  # never opened, so no byte -- and no partial read
    record = case_io.error_record(excinfo.value)
    assert secret.read_bytes().decode() not in json.dumps(record)
    # The outside file is untouched and nothing of it entered any projection.
    assert secret.read_bytes() == b"outside material that must never be read\n"


@pytest.mark.parametrize("source_path", ["/etc/passwd", "../outside.txt", "a/../../b"])
def test_verify_entry_refuses_an_escaping_source_path(tmp_path, monkeypatch, source_path):
    reads = _record_reads(monkeypatch)
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_entry(_entry("a", source_path, b"x"), tmp_path)
    assert excinfo.value.code == "source_escapes_root"
    assert reads == []


def test_verify_manifest_refuses_a_non_directory_root(tmp_path):
    manifest = case_io.load_manifest(_manifest([_entry("m", "m.txt", b"x")]))
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_manifest(manifest, tmp_path / "nope")
    assert excinfo.value.code == "root_refused"


def test_verify_manifest_refuses_at_the_first_drift_without_continuing(tmp_path):
    # first.txt exists but has drifted; second.txt is missing entirely. A
    # fail-fast verification reports the first drift, never the later absence.
    _write(tmp_path, "first.txt", b"changed")
    entries = [_entry("first", "first.txt", b"declared-first"),
               _entry("second", "second.txt", b"declared-second")]
    manifest = case_io.load_manifest(_manifest(entries))
    with pytest.raises(case_io.CaseIOError) as excinfo:
        case_io.verify_manifest(manifest, tmp_path)
    assert excinfo.value.code == "source_changed"
    assert excinfo.value.entry_id == "first"


def test_verify_manifest_refuses_repeatedly_without_healing_the_drift(tmp_path):
    _write(tmp_path, "m.txt", b"changed")
    manifest = case_io.load_manifest(_manifest([_entry("m", "m.txt", b"declared")]))
    for _ in range(2):
        with pytest.raises(case_io.CaseIOError) as excinfo:
            case_io.verify_manifest(manifest, tmp_path)
        assert excinfo.value.code == "source_changed"


# --- finite projection preserving the original references ---------------------

def test_projection_is_exactly_the_declared_case_io_fields(tmp_path):
    _write(tmp_path, "a.txt", b"a")
    manifest = case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a")]))
    projection = case_io.project_case_io(manifest, tmp_path, manifest_ref="case.manifest.json")
    assert tuple(projection) == case_io.CASE_IO_FIELDS


def test_projection_preserves_the_original_case_and_manifest_references(tmp_path):
    _write(tmp_path, "a.txt", b"a")
    manifest = case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a")]))
    projection = case_io.project_case_io(manifest, tmp_path, manifest_ref="case.manifest.json")
    assert projection["case_ref"] == CASE_REF
    assert projection["manifest_ref"] == "case.manifest.json"
    assert projection["manifest_sha256"] == case_io.manifest_digest(manifest)


def test_projection_carries_each_entry_path_digest_and_length(tmp_path):
    first, second = b"first\n", b"second\n"
    _write(tmp_path, "a.txt", first)
    _write(tmp_path, "nested/b.txt", second)
    entries = [_entry("a", "a.txt", first), _entry("b", "nested/b.txt", second)]
    manifest = case_io.load_manifest(_manifest(entries))
    projection = case_io.project_case_io(manifest, tmp_path, manifest_ref="case.manifest.json")
    assert projection["entries"] == [
        {"entry_id": "a", "source_path": "a.txt",
         "sha256": hashlib.sha256(first).hexdigest(), "byte_length": len(first)},
        {"entry_id": "b", "source_path": "nested/b.txt",
         "sha256": hashlib.sha256(second).hexdigest(), "byte_length": len(second)},
    ]


def test_projection_never_carries_material_credentials_or_environment(tmp_path):
    material = (f"AKIA-FAKE {FAKE_SECRET} DATABASE_URL=postgres://fake\n"
                f"{FAKE_PATH} {FAKE_ENDPOINT}\n").encode()
    _write(tmp_path, "materials/notes.txt", material)
    manifest = case_io.load_manifest(_manifest([_entry("notes", "materials/notes.txt", material)]))
    projection = case_io.project_case_io(manifest, tmp_path, manifest_ref="case.manifest.json")
    text = case_io.serialize_projection(projection)
    for marker in (FAKE_SECRET, "AKIA-FAKE", "DATABASE_URL", "postgres://fake",
                   FAKE_PATH, FAKE_ENDPOINT):
        assert marker not in text
    assert projection["entries"][0]["sha256"] == hashlib.sha256(material).hexdigest()


def test_projection_serialization_is_bounded_and_canonical(tmp_path):
    _write(tmp_path, "a.txt", b"a")
    manifest = case_io.load_manifest(_manifest([_entry("a", "a.txt", b"a")]))
    projection = case_io.project_case_io(manifest, tmp_path, manifest_ref="case.manifest.json")
    text = case_io.serialize_projection(projection)
    assert json.loads(text) == projection
    assert text == case_io.serialize_projection(projection)
    assert case_io.serialize_projection(dict(reversed(list(projection.items())))) == text
    assert len(text.encode("utf-8")) <= case_io.RESULT_MAX_BYTES


# --- named errors -------------------------------------------------------------

def test_error_codes_are_the_declared_named_set():
    assert set(case_io.ERROR_SUMMARIES) == {
        "manifest_shape", "unsupported_schema", "source_missing", "source_not_regular",
        "source_unreadable", "source_changed", "source_escapes_root", "root_refused",
        "unexpected"}


def test_error_record_reports_a_bounded_named_code():
    record = case_io.error_record(case_io.CaseIOError("source_changed"))
    assert set(record) == {"error_code", "error_summary", "error_class"}
    assert record["error_code"] == "source_changed"
    assert record["error_summary"] == case_io.ERROR_SUMMARIES["source_changed"]
    assert record["error_class"] == "CaseIOError"


def test_error_record_never_echoes_raw_error_text():
    error = RuntimeError(f"read {FAKE_SECRET} from {FAKE_PATH} via {FAKE_ENDPOINT}")
    record = case_io.error_record(error)
    text = json.dumps(record)
    for marker in (FAKE_SECRET, FAKE_PATH, FAKE_ENDPOINT, "RuntimeError:", "read "):
        assert marker not in text
    assert record["error_code"] == "unexpected"


def test_error_record_class_name_is_a_bounded_identifier():
    dynamic = type("sk-" + "FAKE" * 4, (Exception,), {})
    assert case_io.error_record(dynamic("x"))["error_class"] == "UnclassifiedError"

    class Outer:
        class InnerError(Exception):
            pass

    assert case_io.error_record(Outer.InnerError("x"))["error_class"] == "InnerError"


# --- controlled end-to-end check ----------------------------------------------

def test_main_reports_a_projection_for_a_controlled_manifest(tmp_path, capsys):
    data = b"controlled material\n"
    _write(tmp_path, "a.txt", data)
    manifest_path = tmp_path / "case.manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_entry("a", "a.txt", data)])), encoding="utf-8")
    assert case_io.main(["--manifest", str(manifest_path), "--root", str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["manifest_ref"] == str(manifest_path)
    assert printed["entries"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_main_preserves_the_complete_manifest_reference(tmp_path, capsys):
    # Two manifests sharing a file name in different directories must not
    # collapse to one identity: the default reference keeps the full path.
    data = b"a\n"
    refs = []
    for label in ("alpha", "beta"):
        case_dir = tmp_path / label
        case_dir.mkdir()
        _write(case_dir, "a.txt", data)
        manifest_path = case_dir / "case.manifest.json"
        manifest_path.write_text(json.dumps(_manifest([_entry("a", "a.txt", data)])),
                                 encoding="utf-8")
        assert case_io.main(["--manifest", str(manifest_path), "--root", str(case_dir)]) == 0
        refs.append(json.loads(capsys.readouterr().out)["manifest_ref"])
    assert refs == [str(tmp_path / "alpha" / "case.manifest.json"),
                    str(tmp_path / "beta" / "case.manifest.json")]
    assert refs[0] != refs[1]


def test_main_passes_through_an_explicit_manifest_reference(tmp_path, capsys):
    data = b"a\n"
    _write(tmp_path, "a.txt", data)
    manifest_path = tmp_path / "case.manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_entry("a", "a.txt", data)])), encoding="utf-8")
    explicit = "refs/2026-10-17/alpha.manifest.json"
    assert case_io.main(["--manifest", str(manifest_path), "--root", str(tmp_path),
                         "--manifest-ref", explicit]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["manifest_ref"] == explicit


def test_main_refuses_an_empty_explicit_manifest_reference(tmp_path, capsys):
    # An explicitly empty reference is refused, never silently replaced by a
    # derived default: the missing-reference behaviour is fully defined.
    data = b"a\n"
    _write(tmp_path, "a.txt", data)
    manifest_path = tmp_path / "case.manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_entry("a", "a.txt", data)])), encoding="utf-8")
    assert case_io.main(["--manifest", str(manifest_path), "--root", str(tmp_path),
                         "--manifest-ref", ""]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error_code"] == "manifest_shape"


def test_main_reports_a_named_error_when_a_source_changed(tmp_path, capsys):
    _write(tmp_path, "a.txt", b"changed")
    manifest_path = tmp_path / "case.manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_entry("a", "a.txt", b"declared")])),
                             encoding="utf-8")
    assert case_io.main(["--manifest", str(manifest_path), "--root", str(tmp_path)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error_code"] == "source_changed"


# --- source hygiene -----------------------------------------------------------

def test_module_reads_no_process_environment():
    source = _source()
    for forbidden in ("os.environ", "getenv", "environ.get", "dotenv", "load_dotenv"):
        assert forbidden not in source


def test_module_starts_no_network_or_subprocess():
    source = _source()
    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "asyncio"):
        assert forbidden not in source


def test_module_does_not_retry_or_sleep():
    source = _source()
    assert "while " not in source
    assert "for attempt" not in source
    assert "sleep" not in source

"""Durable summary-only evidence: cross-process read, tamper, conflict, secrets."""
import subprocess
import sys

import pytest

from ordessa_decision import DecisionError, FilesystemEvidenceStore

SUMMARY = {"job_digest": "a" * 64, "usage": {"step": {"status": "unknown"}}}


def test_durable_read_across_processes(tmp_path):
    root = tmp_path / "evidence"
    ref = FilesystemEvidenceStore(root).put(SUMMARY)
    code = ("import sys; from ordessa_decision import FilesystemEvidenceStore; "
            f"s=FilesystemEvidenceStore({str(root)!r}).get({ref.digest!r}); "
            "print(s['job_digest'])")
    finished = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip() == "a" * 64


def test_tampered_or_conflicting_files_are_refused(tmp_path):
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    ref = store.put(SUMMARY)
    path = tmp_path / "evidence" / (ref.digest + ".json")
    path.write_bytes(path.read_bytes().replace(b"a" * 64, b"b" * 64))
    with pytest.raises(DecisionError) as refused:
        store.get(ref.digest)
    assert refused.value.code == "evidence_tampered"
    other = dict(SUMMARY, job_digest="c" * 64)
    same = FilesystemEvidenceStore(tmp_path / "evidence2")
    ref2 = same.put(other)
    (tmp_path / "evidence2" / (ref2.digest + ".json")).write_bytes(b'{"job_digest":"' + b"d" * 64 + b'"}')
    with pytest.raises(DecisionError):
        same.get(ref2.digest)


def test_evidence_rejects_secret_and_forbidden_fields(tmp_path):
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    for key in ("prompt", "response", "text", "secret", "api_key"):
        with pytest.raises(DecisionError):
            store.put(dict(SUMMARY, **{key: "x"}))
    with pytest.raises(DecisionError):
        store.put({"job_digest": "a" * 64, "unknown_field": 1})


def test_writes_are_atomic_and_fsynced(tmp_path, monkeypatch):
    import os
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    calls = []
    real_fsync = os.fsync

    def counting_fsync(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    ref = store.put(SUMMARY)
    assert len(calls) >= 2  # file data + directory entry
    assert store.get(ref.digest)["job_digest"] == "a" * 64
    # A crash after the temp write but before replace leaves no visible record.
    real_replace = os.replace

    def failing_replace(source, target):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.put(dict(SUMMARY, job_digest="b" * 64))
    monkeypatch.setattr(os, "replace", real_replace)
    assert not any(path.name.endswith(".json")
                   for path in (tmp_path / "evidence").iterdir()
                   if path.name != ref.digest + ".json")


def test_reader_ignores_temporary_and_truncated_files(tmp_path):
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    ref = store.put(SUMMARY)
    (tmp_path / "evidence" / ".pending-abc").write_bytes(b'{"job_digest":')
    assert store.get(ref.digest)["job_digest"] == "a" * 64
    (tmp_path / "evidence" / (ref.digest + ".json")).write_bytes(b'{"job_digest":')
    with pytest.raises((DecisionError,)) as refused:
        store.get(ref.digest)
    assert refused.value.code in {"evidence_tampered", "invalid_json"}


def test_directory_sync_failure_reports_written_bytes_without_deleting(tmp_path, monkeypatch):
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    real = store._fsync_directory

    def failing():
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(store, "_fsync_directory", failing)
    ref = store.put(SUMMARY)
    assert ref.durability == "directory_sync_unknown"
    monkeypatch.setattr(store, "_fsync_directory", real)
    assert store.get(ref.digest)["job_digest"] == "a" * 64
    # an already-correct record is not deleted by a later failed directory sync
    monkeypatch.setattr(store, "_fsync_directory", failing)
    again = store.put(SUMMARY)
    assert again.digest == ref.digest
    monkeypatch.setattr(store, "_fsync_directory", real)
    assert store.get(ref.digest)["job_digest"] == "a" * 64


def test_concurrent_identical_put_is_idempotent(tmp_path):
    import threading
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    refs, errors = [], []

    def worker():
        try:
            refs.append(store.put(SUMMARY))
        except Exception as exc:  # pragma: no cover - only on a real defect
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert {ref.digest for ref in refs} == {refs[0].digest}
    assert all(ref.durability == "durable" for ref in refs)
    assert store.get(refs[0].digest)["job_digest"] == "a" * 64
    files = [p.name for p in (tmp_path / "evidence").iterdir()]
    assert files == [refs[0].digest + ".json"]

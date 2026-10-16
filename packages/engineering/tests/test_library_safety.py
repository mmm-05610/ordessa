"""Synthetic schema2 fixtures for the bounded SQLite storage safety contract.

These tests do not attest SQLite's native FD, malicious OS-level ABA safety,
hot-journal recovery, or support for uncheckpointed WAL. All databases are
created beneath pytest's temporary directory; no production data is consulted.
"""
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from pathlib import Path
import sqlite3
import stat
from threading import Event

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:safety"


def create_closed(path: Path) -> None:
    library = Library.create(path, library_id=LIBRARY_ID)
    library.close()


def assert_code(caught, code: str) -> None:
    assert caught.value.code == code


def assert_no_stage(path: Path) -> None:
    assert not tuple(path.parent.glob(".ordessa-library-*"))


def forbid_sqlite_open(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("preflight rejection must precede any SQLite connection")

    monkeypatch.setattr(storage.sqlite3, "connect", forbidden)


def synthetic_schema(path: Path, schema: str) -> None:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.executescript(schema)
        connection.execute("INSERT INTO library_meta VALUES (1, ?, 2)", (LIBRARY_ID,))
        connection.execute("PRAGMA user_version=2")
    finally:
        connection.close()


def test_create_private_stage_and_published_permissions(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    original_connect = sqlite3.connect
    stages = []

    def inspect_connect(database, *args, **kwargs):
        # The infrastructure connection primitive stringifies its location, so
        # the staged path arrives here as ``str`` (not ``Path``).
        candidate = Path(database) if isinstance(database, (str, Path)) else None
        if candidate is not None and candidate.parent.name.startswith(".ordessa-library-"):
            stages.append(candidate)
            assert stat.S_IMODE(candidate.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(candidate.stat().st_mode) == 0o600
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(storage.sqlite3, "connect", inspect_connect)
    library = Library.create(path, library_id=LIBRARY_ID)
    try:
        ref = library.import_material(kind="source-fact", stable_id="fact:1", body={"text": "事实"})
        assert material_ref_to_dict(ref) == {
            "library_id": LIBRARY_ID, "kind": "source-fact", "stable_id": "fact:1",
            "revision": 1, "digest": storage.content_digest({"text": "事实"}),
        }
        assert library.read(ref) == {"text": "事实"}
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
        assert len(stages) == 1
        assert_no_stage(path)
    finally:
        library.close()


def test_create_link_collision_preserves_new_existing_target(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    original_link = os.link
    sentinel = b"another creator owns this pathname"

    def collide(source, destination, **kwargs):
        Path(destination).write_bytes(sentinel)
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(storage.os, "link", collide)
    with pytest.raises(EngineeringError) as caught:
        Library.create(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_already_exists")
    assert path.read_bytes() == sentinel
    assert_no_stage(path)


def test_create_initialization_failure_cleans_only_owned_stage(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    original_connect = sqlite3.connect
    sentinel = b"independent path installed while staging"

    class BrokenStage(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT INTO library_meta"):
                path.write_bytes(sentinel)
                raise sqlite3.OperationalError("synthetic stage failure")
            return super().execute(sql, *args, **kwargs)

    def broken_connect(database, *args, **kwargs):
        candidate = Path(database) if isinstance(database, (str, Path)) else None
        if candidate is not None and candidate.parent.name.startswith(".ordessa-library-"):
            kwargs["factory"] = BrokenStage
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(storage.sqlite3, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError, match="synthetic stage failure"):
        Library.create(path, library_id=LIBRARY_ID)
    assert path.read_bytes() == sentinel
    assert_no_stage(path)


def test_published_complete_library_survives_failed_open(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    failure = EngineeringError("synthetic_open_failure")

    def refuse_open(cls, *args, **kwargs):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(Library, "open", classmethod(refuse_open))
        with pytest.raises(EngineeringError) as caught:
            Library.create(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_created_open_failed")
    assert caught.value.__cause__ is failure
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert_no_stage(path)
    library = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert library.head("source-fact", "missing") is None
    finally:
        library.close()


def test_future_version_rejected_before_sqlite_and_bytes_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE library_meta SET schema_version=99")
        connection.execute("PRAGMA user_version=99")
        connection.commit()
    finally:
        connection.close()
    before = path.read_bytes()
    entries = tuple(sorted(item.name for item in tmp_path.iterdir()))
    forbid_sqlite_open(monkeypatch)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_identity_or_schema_mismatch")
    assert path.read_bytes() == before
    assert tuple(sorted(item.name for item in tmp_path.iterdir())) == entries


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("kind", ["regular", "symlink", "directory", "fifo", "hardlink"])
def test_sidecars_of_all_types_rejected_before_sqlite(tmp_path, monkeypatch, suffix, kind):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    sidecar = Path(str(path) + suffix)
    if kind == "regular":
        sidecar.write_bytes(b"synthetic sidecar")
    elif kind == "symlink":
        sidecar.symlink_to(tmp_path / "missing-target")
    elif kind == "directory":
        sidecar.mkdir()
    elif kind == "fifo":
        os.mkfifo(sidecar)
    else:
        source = tmp_path / "sidecar-source"
        source.write_bytes(b"hardlinked sidecar")
        os.link(source, sidecar)
    before = path.read_bytes()
    sidecar_identity = sidecar.lstat()
    sidecar_bytes = sidecar.read_bytes() if kind in {"regular", "hardlink"} else None
    forbid_sqlite_open(monkeypatch)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_sidecar_preflight_unavailable")
    assert path.read_bytes() == before
    assert sidecar.lstat().st_ino == sidecar_identity.st_ino
    assert sidecar.lstat().st_mode == sidecar_identity.st_mode
    if sidecar_bytes is not None:
        assert sidecar.read_bytes() == sidecar_bytes
    if kind == "symlink":
        assert sidecar.readlink() == tmp_path / "missing-target"


def test_hardlinked_main_file_rejected_before_sqlite(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    alias = tmp_path / "alias.sqlite"
    os.link(path, alias)
    before = path.read_bytes()
    forbid_sqlite_open(monkeypatch)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_path_unsafe")
    assert path.read_bytes() == alias.read_bytes() == before
    assert path.stat().st_nlink == 2


def test_preflight_header_read_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    original_read = os.read
    requests = []

    def bounded_read(descriptor, size):
        requests.append(size)
        assert size <= 100
        return original_read(descriptor, size)

    monkeypatch.setattr(storage.os, "read", bounded_read)
    Library._preflight_storage(path, Library._file_identity(path))
    assert requests == [100]


def test_uncheckpointed_future_wal_rejected_without_touching_any_bytes(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    writer = sqlite3.connect(path, isolation_level=None)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE library_meta SET schema_version=99")
        writer.execute("PRAGMA user_version=99")
        writer.commit()
        paths = (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
        before = {item: item.read_bytes() for item in paths}
        # The main header does not contain the version committed into WAL.
        assert int.from_bytes(before[path][60:64], "big") == 2
        forbid_sqlite_open(monkeypatch)
        with pytest.raises(EngineeringError) as caught:
            Library.open(path, library_id=LIBRARY_ID)
        assert_code(caught, "library_sidecar_preflight_unavailable")
        assert {item: item.read_bytes() for item in paths} == before
    finally:
        writer.close()


def test_checkpointed_wal_header_still_requires_explicit_support(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    writer = sqlite3.connect(path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    finally:
        writer.close()
    assert not Path(str(path) + "-wal").exists()
    before = path.read_bytes()
    assert before[18:20] == b"\x02\x02"
    forbid_sqlite_open(monkeypatch)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_wal_preflight_unavailable")
    assert path.read_bytes() == before


def test_failed_readonly_probe_is_closed(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    create_closed(path)
    before = path.read_bytes()
    original_connect = sqlite3.connect
    closed = []

    class BrokenProbe(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("synthetic probe failure")

        def close(self):
            closed.append(self)
            return super().close()

    def probe_connect(database, *args, **kwargs):
        if str(database).endswith("?mode=ro"):
            kwargs["factory"] = BrokenProbe
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(storage.sqlite3, "connect", probe_connect)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "foreign_or_invalid_library")
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
    assert len(closed) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        sqlite3.Connection.execute(closed[0], "SELECT 1")
    assert path.read_bytes() == before


def test_replacement_after_probe_is_not_admitted(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    original = tmp_path / "original.sqlite"
    create_closed(path)
    create_closed(replacement)
    replacement_bytes = replacement.read_bytes()
    original_connect = sqlite3.connect
    closed = []

    class ReplacingProbe(sqlite3.Connection):
        def close(self):
            super().close()
            closed.append(self)
            path.rename(original)
            replacement.rename(path)

    def probe_connect(database, *args, **kwargs):
        if str(database).endswith("?mode=ro"):
            kwargs["factory"] = ReplacingProbe
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(storage.sqlite3, "connect", probe_connect)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_replaced_during_open")
    assert len(closed) == 1
    assert path.read_bytes() == replacement_bytes


def test_constructor_does_not_repin_replaced_path(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    original = tmp_path / "original.sqlite"
    create_closed(path)
    create_closed(replacement)
    replacement_bytes = replacement.read_bytes()
    original_init = Library.__init__
    opened = []

    def replace_before_init(self, selected, connection, library_id):
        opened.append(connection)
        selected.rename(original)
        replacement.rename(selected)
        original_init(self, selected, connection, library_id)

    monkeypatch.setattr(Library, "__init__", replace_before_init)
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_replaced_during_open")
    assert path.read_bytes() == replacement_bytes
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize("mutation", ["trigger", "view", "missing_unique", "missing_fk"])
def test_full_schema_rejects_objects_and_constraint_changes(tmp_path, mutation):
    path = tmp_path / "library.sqlite"
    schema = storage._SCHEMA
    if mutation == "trigger":
        schema += "CREATE TRIGGER extra AFTER INSERT ON materials BEGIN SELECT 1; END;"
    elif mutation == "view":
        schema += "CREATE VIEW extra AS SELECT * FROM materials;"
    elif mutation == "missing_unique":
        schema = schema.replace(
            "PRIMARY KEY (kind, stable_id, revision),\n  UNIQUE (kind, stable_id, digest)",
            "PRIMARY KEY (kind, stable_id, revision)")
    else:
        schema = schema.replace(
            "PRIMARY KEY (kind, stable_id),\n  FOREIGN KEY (kind, stable_id, revision)\n"
            "    REFERENCES materials(kind, stable_id, revision)",
            "PRIMARY KEY (kind, stable_id)")
    assert schema != storage._SCHEMA
    synthetic_schema(path, schema)
    before = path.read_bytes()
    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    assert_code(caught, "library_identity_or_schema_mismatch")
    assert path.read_bytes() == before
    assert set(item.name for item in tmp_path.iterdir()) == {path.name}


def test_exact_schema_comparison_accepts_case_and_layout_changes(tmp_path):
    path = tmp_path / "library.sqlite"
    synthetic_schema(path, "\n".join("   " + line.lower() for line in storage._SCHEMA.splitlines()))
    library = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert library.head("source-fact", "missing") is None
    finally:
        library.close()


@pytest.mark.parametrize("reader", ["read", "head", "run_row", "step_rows", "lookup_idempotency"])
def test_public_reads_recheck_schema(tmp_path, reader):
    path = tmp_path / "library.sqlite"
    library = Library.create(path, library_id=LIBRARY_ID)
    try:
        ref = library.import_material(kind="source-fact", stable_id="fact:1", body={"value": 1})
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE VIEW schema_drift AS SELECT * FROM materials")
            connection.commit()
        finally:
            connection.close()
        calls = {
            "read": lambda: library.read(ref),
            "head": lambda: library.head(ref.kind, ref.stable_id),
            "run_row": lambda: library.run_row("missing"),
            "step_rows": lambda: library.step_rows("missing"),
            "lookup_idempotency": lambda: library.lookup_idempotency("missing", "hash"),
        }
        with pytest.raises(EngineeringError) as caught:
            calls[reader]()
        assert_code(caught, "library_identity_or_schema_mismatch")
    finally:
        library.close()


def test_business_refusal_rolls_back_but_keeps_connection_usable(tmp_path):
    library = Library.create(tmp_path / "library.sqlite", library_id=LIBRARY_ID)
    try:
        ref = library.import_material(kind="source-fact", stable_id="fact:1", body={"value": 1})
        with pytest.raises(EngineeringError) as caught:
            library.import_material(kind=ref.kind, stable_id=ref.stable_id, body={"value": 2})
        assert_code(caught, "head_conflict")
        assert not library._closed
        assert library.head(ref.kind, ref.stable_id) == ref
        assert library.read(ref) == {"value": 1}
        with library.transaction() as connection:
            library.require_current(connection, ref)
        assert library.head(ref.kind, ref.stable_id) == ref
    finally:
        library.close()


def test_schema_upgrade_while_begin_waits_is_rechecked_after_lock(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    attempted_begin = Event()
    base_connection = storage._LibraryConnection

    class ObservedConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "BEGIN IMMEDIATE":
                attempted_begin.set()
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", ObservedConnection)
    library = Library.create(path, library_id=LIBRARY_ID)
    identity = Library._file_identity(path)
    writer = sqlite3.connect(path, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        # Hold a reserved rollback-mode lock without writing a journal yet.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(library.import_material, kind="source-fact", stable_id="fact:1", body={})
            try:
                assert attempted_begin.wait(3), "worker did not reach BEGIN"
                writer.execute("UPDATE library_meta SET schema_version=99")
                writer.execute("PRAGMA user_version=99")
                writer.commit()
                with pytest.raises(EngineeringError) as caught:
                    future.result(timeout=3)
                assert_code(caught, "library_identity_or_schema_mismatch")
            finally:
                if writer.in_transaction:
                    writer.rollback()
        assert Library._file_identity(path) == identity
        assert writer.execute("SELECT count(*) FROM materials").fetchone() == (0,)
        assert writer.execute("PRAGMA user_version").fetchone() == (99,)
        assert library._closed
    finally:
        writer.close()
        library.close()


def test_future_schema_before_commit_rolls_back_and_invalidates_connection(tmp_path):
    path = tmp_path / "library.sqlite"
    library = Library.create(path, library_id=LIBRARY_ID)
    try:
        with pytest.raises(EngineeringError) as caught:
            with library.transaction() as connection:
                library._write_material(connection, kind="source-fact", stable_id="fact:1",
                                        revision=1, body={}, generated=False)
                connection.execute("UPDATE library_meta SET schema_version=99")
                connection.execute("PRAGMA user_version=99")
        assert_code(caught, "library_identity_or_schema_mismatch")
        assert library._closed
        reopened = Library.open(path, library_id=LIBRARY_ID)
        try:
            assert reopened.head("source-fact", "fact:1") is None
        finally:
            reopened.close()
    finally:
        library.close()


def test_path_replacement_before_commit_never_commits_to_replacement(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    original = tmp_path / "original.sqlite"
    commits = []
    base_connection = storage._LibraryConnection

    class ObservedConnection(base_connection):
        def commit(self):
            commits.append(self)
            return super().commit()

    monkeypatch.setattr(storage, "_LibraryConnection", ObservedConnection)
    library = Library.create(path, library_id=LIBRARY_ID)
    create_closed(replacement)
    replacement_bytes = replacement.read_bytes()
    try:
        with pytest.raises(EngineeringError) as caught:
            with library.transaction() as connection:
                library._write_material(connection, kind="source-fact", stable_id="fact:1",
                                        revision=1, body={}, generated=False)
                path.rename(original)
                replacement.rename(path)
        # This is an observed substitution, not a proof against an ABA attack.
        if caught.value.code == "library_rollback_failed":
            assert isinstance(caught.value.__cause__, EngineeringError)
            assert caught.value.__cause__.code == "library_replaced"
            assert caught.value.rollback_error is not None
        else:
            assert_code(caught, "library_replaced")
        assert commits == []
        assert library._closed
        assert path.read_bytes() == replacement_bytes
    finally:
        library.close()


@pytest.mark.parametrize("rollback", [False, True], ids=["commit", "rollback"])
def test_head_and_read_wait_for_transaction_outcome(tmp_path, rollback):
    library = Library.create(tmp_path / "library.sqlite", library_id=LIBRARY_ID)
    ready = Event()
    release = Event()
    head_attempt = Event()
    read_attempt = Event()
    refs = []
    refusal = EngineeringError("synthetic_business_refusal")

    def write():
        with library.transaction() as connection:
            refs.append(library._write_material(connection, kind="source-fact", stable_id="fact:1",
                                                revision=1, body={"value": 1}, generated=False))
            ready.set()
            assert release.wait(5), "test did not release writer"
            if rollback:
                raise refusal

    def head():
        head_attempt.set()
        return library.head("source-fact", "fact:1")

    def read():
        read_attempt.set()
        return library.read(refs[0])

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            writer_future = executor.submit(write)
            try:
                assert ready.wait(3), "writer did not enter transaction"
                head_future = executor.submit(head)
                read_future = executor.submit(read)
                assert head_attempt.wait(3)
                assert read_attempt.wait(3)
                for future in (head_future, read_future):
                    with pytest.raises(TimeoutError):
                        future.result(timeout=0.1)
            finally:
                release.set()
            if rollback:
                with pytest.raises(EngineeringError) as caught:
                    writer_future.result(timeout=3)
                assert caught.value is refusal
                assert head_future.result(timeout=3) is None
                with pytest.raises(EngineeringError) as caught:
                    read_future.result(timeout=3)
                assert_code(caught, "material_reference_unresolved")
            else:
                writer_future.result(timeout=3)
                assert head_future.result(timeout=3) == refs[0]
                assert read_future.result(timeout=3) == {"value": 1}
        assert not library._closed
        assert library.head("source-fact", "fact:1") == (None if rollback else refs[0])
    finally:
        release.set()
        library.close()


def test_rollback_failure_keeps_original_cause_and_closes_connection(tmp_path):
    library = Library.create(tmp_path / "library.sqlite", library_id=LIBRARY_ID)
    original_connection = library._connection
    original_error = RuntimeError("synthetic body failure")
    rollback_error = OSError("synthetic rollback failure")
    closes = []

    class BrokenRollback:
        def __getattr__(self, name):
            return getattr(original_connection, name)

        def rollback(self):
            raise rollback_error

        def close(self):
            closes.append(True)
            original_connection.close()

    library._connection = BrokenRollback()
    try:
        with pytest.raises(EngineeringError) as caught:
            with library.transaction():
                raise original_error
        assert_code(caught, "library_rollback_failed")
        assert caught.value.__cause__ is original_error
        assert caught.value.rollback_error is rollback_error
        assert caught.value.close_error is None
        assert closes == [True]
        assert library._closed
        with pytest.raises(EngineeringError) as closed:
            library.head("source-fact", "missing")
        assert_code(closed, "library_closed")
    finally:
        library.close()

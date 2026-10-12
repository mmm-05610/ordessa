import sqlite3

import pytest

from ordessa_infrastructure.database import SQLiteConfigurationError, SQLiteOptions, create_connection


def test_returns_native_connection_with_explicit_contract(tmp_path):
    db = tmp_path / "contract.sqlite"
    conn = create_connection(
        SQLiteOptions(
            location=db,
            timeout=5.0,
            row_factory=sqlite3.Row,
            foreign_keys=True,
            busy_timeout=5000,
        )
    )
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        conn.execute("CREATE TABLE t(a)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        assert conn.execute("SELECT a FROM t").fetchone()["a"] == 1
    finally:
        conn.close()


def test_explicit_busy_timeout_wins_over_connect_timeout(tmp_path):
    """The final ``PRAGMA busy_timeout`` is the explicit value, not ``timeout``.

    ``sqlite3.connect(timeout=1.0)`` installs a 1000 ms busy handler; an
    explicit ``busy_timeout=5000`` must override it, so the effective busy
    handler is 5000 ms regardless of the connect timeout.
    """
    db = tmp_path / "busy.sqlite"
    conn = create_connection(SQLiteOptions(location=db, timeout=1.0, busy_timeout=5000))
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_omitting_transaction_control_matches_plain_connect(tmp_path):
    """Unset ``isolation_level``/``autocommit`` reproduce plain ``connect``."""
    db = tmp_path / "txn.sqlite"
    conn = create_connection(SQLiteOptions(location=db))
    plain = sqlite3.connect(str(db))
    try:
        assert conn.isolation_level == plain.isolation_level == ""
        assert conn.autocommit == plain.autocommit == sqlite3.LEGACY_TRANSACTION_CONTROL
    finally:
        conn.close()
        plain.close()


def test_explicit_isolation_and_autocommit_are_forwarded(tmp_path):
    db = tmp_path / "explicit.sqlite"
    conn = create_connection(SQLiteOptions(location=db, isolation_level=None))
    try:
        assert conn.isolation_level is None
    finally:
        conn.close()
    autocommit = create_connection(SQLiteOptions(location=db, autocommit=True))
    try:
        assert autocommit.autocommit is True
    finally:
        autocommit.close()


def test_initialisation_failure_closes_the_new_connection(tmp_path, monkeypatch):
    import sqlite3 as real_sqlite3

    from ordessa_infrastructure.database import sqlite as sqlite_module

    closed = []

    class FakeConnection:
        row_factory = None

        def execute(self, *args, **kwargs):
            raise real_sqlite3.OperationalError("controlled pragma failure")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sqlite_module.sqlite3, "connect", lambda *a, **k: FakeConnection())
    try:
        create_connection(SQLiteOptions(location=tmp_path / "x.sqlite", foreign_keys=True))
    except real_sqlite3.OperationalError:
        pass
    else:  # pragma: no cover - the failure is the point
        raise AssertionError("expected the pragma failure to propagate")
    assert closed == [True]


def test_autocommit_false_with_foreign_keys_is_refused(tmp_path):
    """``autocommit=False`` starts inside a transaction, so ``PRAGMA
    foreign_keys`` is a silent no-op. The contract must refuse rather than
    return a connection that silently left foreign keys off."""
    db = tmp_path / "ac.sqlite"
    with pytest.raises(SQLiteConfigurationError):
        create_connection(SQLiteOptions(location=db, autocommit=False, foreign_keys=True))


def test_autocommit_false_without_foreign_keys_is_allowed(tmp_path):
    db = tmp_path / "ac2.sqlite"
    conn = create_connection(SQLiteOptions(location=db, autocommit=False))
    try:
        assert conn.autocommit is False
    finally:
        conn.close()


def test_autocommit_false_with_foreign_keys_off_is_allowed(tmp_path):
    """Requesting OFF while already off is satisfied, so it is not refused."""
    db = tmp_path / "ac3.sqlite"
    conn = create_connection(SQLiteOptions(location=db, autocommit=False, foreign_keys=False))
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        conn.close()


def test_autocommit_true_and_legacy_enable_foreign_keys(tmp_path):
    for opts in ({"autocommit": True}, {}):
        db = tmp_path / f"fk-{len(str(opts))}.sqlite"
        conn = create_connection(SQLiteOptions(location=db, foreign_keys=True, **opts))
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()


def test_native_default_dml_transaction_and_rollback_are_preserved(tmp_path):
    db = tmp_path / 'native.sqlite'
    conn = create_connection(SQLiteOptions(location=db))
    observer = sqlite3.connect(str(db))
    try:
        conn.execute('CREATE TABLE t(a)')
        conn.execute('INSERT INTO t VALUES (1)')
        assert conn.in_transaction
        assert observer.execute('SELECT a FROM t').fetchall() == []
        conn.rollback()
        assert conn.execute('SELECT a FROM t').fetchall() == []
        with conn:
            conn.execute('INSERT INTO t VALUES (2)')
        assert observer.execute('SELECT a FROM t').fetchall() == [(2,)]
        with pytest.raises(RuntimeError):
            with conn:
                conn.execute('INSERT INTO t VALUES (3)')
                raise RuntimeError('owner failed')
        assert observer.execute('SELECT a FROM t').fetchall() == [(2,)]
        assert conn.execute('SELECT 1').fetchone() == (1,)  # with did not close
    finally:
        observer.close()
        conn.close()


def test_nonlegacy_autocommit_ignores_isolation_level_as_native_python_does():
    conn = create_connection(SQLiteOptions(location=':memory:', autocommit=True, isolation_level='EXCLUSIVE'))
    try:
        assert conn.autocommit is True
        assert conn.isolation_level == 'EXCLUSIVE'
        conn.execute('CREATE TABLE t(a)')
        conn.execute('INSERT INTO t VALUES (1)')
        assert not conn.in_transaction
    finally:
        conn.close()


@pytest.mark.parametrize('busy_timeout', [-1, 2**31, 2**32])
def test_invalid_effective_busy_timeout_is_refused_by_sqlite_readback(tmp_path, busy_timeout):
    """SQLite can silently turn out-of-range PRAGMA values into zero."""
    with pytest.raises(SQLiteConfigurationError):
        create_connection(SQLiteOptions(location=tmp_path / 'invalid-busy.sqlite',
                                        busy_timeout=busy_timeout))


@pytest.mark.parametrize('busy_timeout', [0, 2**31 - 1])
def test_supported_busy_timeout_values_remain_effective(tmp_path, busy_timeout):
    conn = create_connection(SQLiteOptions(location=tmp_path / 'valid-busy.sqlite',
                                           busy_timeout=busy_timeout))
    try:
        assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == busy_timeout
    finally:
        conn.close()


def test_busy_timeout_readback_mismatch_closes_connection_and_refuses_handoff(monkeypatch):
    from ordessa_infrastructure.database import sqlite as sqlite_module

    class Cursor:
        def fetchone(self):
            return (0,)

    class FakeConnection:
        row_factory = None

        def __init__(self):
            self.closed = False

        def execute(self, statement):
            return Cursor()

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(sqlite_module.sqlite3, 'connect', lambda *args, **kwargs: connection)

    with pytest.raises(SQLiteConfigurationError):
        create_connection(SQLiteOptions(location='controlled.sqlite', busy_timeout=5000))
    assert connection.closed

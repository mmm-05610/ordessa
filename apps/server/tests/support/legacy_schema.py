"""Fixture-only replay of sealed historical SQL."""
import sqlite3
from pathlib import Path
from ordessa_server.bootstrap.migrations.legacy_reader import LegacySchemaError

def replay_archived_migrations(target: Path, migrations_dir: Path) -> int:
    """Fixture helper: build a legacy database by replaying the SEALED SQL,
    byte-for-byte, in file order. Test-only; real user data is never touched."""
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise LegacySchemaError(f"no archived migrations in {migrations_dir}")
    conn = sqlite3.connect(str(target))
    try:
        for sql_file in files:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return len(files)


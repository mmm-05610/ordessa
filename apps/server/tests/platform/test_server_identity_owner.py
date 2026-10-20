"""Real original database identity survives owner reopen; temporary data only."""
from ordessa_server.bootstrap.server_identity import _server_id
from ordessa_server.bootstrap.storage.product_database import Database


def test_original_server_id_is_single_and_stable_after_database_reopen(tmp_path):
    path=tmp_path/'original.sqlite'
    database=Database(path);database.initialize()
    first=_server_id(database)
    assert first.startswith('server_') and len(first)==39
    assert _server_id(database)==first
    reopened=Database(path);reopened.initialize()
    assert _server_id(reopened)==first
    with reopened.transaction() as connection:
        rows=connection.execute('SELECT singleton,server_id FROM server_bootstrap').fetchall()
        assert len(rows)==1 and rows[0]['singleton']==1 and rows[0]['server_id']==first


def test_existing_original_identity_and_creation_time_are_read_without_upgrade(tmp_path):
    database=Database(tmp_path/'original.sqlite');database.initialize()
    with database.transaction() as connection:
        connection.execute('INSERT INTO server_bootstrap VALUES (1,?,?)',
                           ('server_original_exact_identity','original-creation-time'))
    assert _server_id(database)=='server_original_exact_identity'
    with database.transaction() as connection:
        row=connection.execute('SELECT server_id,created_at FROM server_bootstrap WHERE singleton=1').fetchone()
        assert dict(row)=={'server_id':'server_original_exact_identity','created_at':'original-creation-time'}

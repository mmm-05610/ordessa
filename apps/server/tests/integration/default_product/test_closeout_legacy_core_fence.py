from ordessa_server_product.composition import ProductCompositionUnavailable
import hashlib
import sqlite3
import pytest
from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition

def test_old_core_effect_tombstone_is_not_new_environment_or_migrated(tmp_path):
    path = tmp_path/'core.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE core_operation(request_key TEXT, outcome TEXT)')
        connection.execute("INSERT INTO core_operation VALUES('old-request','unknown')")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ProductCompositionUnavailable, match='tombstones'):
        create_composition().environment_factory(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT * FROM core_operation').fetchall() == [('old-request','unknown')]
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE name='env_requests'").fetchone()[0] == 0

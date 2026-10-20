"""Old runner absent; original C09 bytes remain cold-readable, never resumed."""
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary

ROOT = Path(__file__).parents[3]


def test_old_catalog_and_execution_modules_are_absent_and_not_packaged_sources():
    for name in ('workflow', 'registry', 'fixture', 'resources', 'models'):
        assert importlib.util.find_spec('ordessa_engineering.' + name) is None
        assert not (ROOT/'packages/engineering/src/ordessa_engineering'/f'{name}.py').exists()
    archive = ROOT/'docs/migration/engineering-c09-retirement-20261019'
    older = json.loads((archive/'operation_registry.v1.json').read_bytes())
    assert len(older['operations']) == 9
    for name in ('source-first.v1.json', 'standard-first.v1.json'):
        value = json.loads((archive/name).read_bytes())
        assert value['registry_ref']['digest'] == older['registry_digest']


def test_original_schema2_c09_ref_and_run_are_cold_readable_without_new_registry(tmp_path):
    path = (tmp_path/'historical-c09.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='c09-read-only-fixture', schema_version=2)
    archived = json.loads((ROOT/'docs/migration/engineering-c09-retirement-20261019/operation_registry.v1.json').read_bytes())
    registry_ref = {'registry_id': archived['registry_id'], 'revision': archived['revision'],
                    'digest': archived['registry_digest']}
    method = library.import_material(kind='method', stable_id='original-method',
                                     body={'historical_fixture_only': True})
    ref_bytes = canonical_bytes(asdict(method)).decode()
    registry_bytes = canonical_bytes(registry_ref).decode()
    inputs = {'refs': {'did': asdict(method)}, 'historical_fixture_only': True}
    inputs_bytes = canonical_bytes(inputs).decode()
    with library.transaction() as connection:
        connection.execute('INSERT INTO runs (run_id,method_ref_json,registry_ref_json,input_json,status,cursor,wait_reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            ('original-run', ref_bytes, registry_bytes, inputs_bytes, 'WAITING_FOR_ACCEPTANCE', 3,
             'original-wait', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z'))
    library.close()
    cold = EngineeringLibrary.open(path, library_id='c09-read-only-fixture')
    try:
        before = cold._connection.execute('SELECT * FROM runs').fetchall()
        changes = cold._connection.total_changes
        row = cold.run_row('original-run')
        assert asdict(row['method_ref']) == asdict(method)
        assert row['registry_ref'] == registry_ref and row['inputs'] == inputs
        assert row['status'] == 'WAITING_FOR_ACCEPTANCE' and row['cursor'] == 3
        assert cold.step_rows('original-run') == []
        assert cold._connection.execute('SELECT * FROM runs').fetchall() == before
        assert cold._connection.total_changes == changes
        assert importlib.util.find_spec('ordessa_engineering.workflow') is None
    finally:
        cold.close()

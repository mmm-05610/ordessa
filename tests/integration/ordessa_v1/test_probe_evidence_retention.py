"""No model calls: persistent SQLite and original Local/Unit cleanup faults."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

import pytest

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[2]
sys.path.insert(0, str(DIRECTORY))
from probe_evidence import retained_attempt_root, cleanup_attempt


@pytest.fixture(scope='module')
def evidence_root():
    # This root deliberately outlives pytest and is never removed by a fixture.
    return Path(tempfile.mkdtemp(prefix='ordessa-v1-probe-regression-'))


@pytest.mark.parametrize('exit_kind', ['normal', 'exception', 'interrupt'])
def test_all_exits_keep_original_databases_and_refuse_reusing_locator(evidence_root, exit_kind):
    output = evidence_root/exit_kind/'receipt.json'
    root = None
    try:
        with retained_attempt_root(output) as root:
            for name in ('original.sqlite', 'environment.sqlite'):
                with sqlite3.connect(root/name) as connection:
                    connection.execute('CREATE TABLE exact_attempt (identity TEXT)')
                    connection.execute('INSERT INTO exact_attempt VALUES (?)', (exit_kind,))
            if exit_kind == 'exception':
                raise RuntimeError('controlled evidence failure')
            if exit_kind == 'interrupt':
                raise KeyboardInterrupt()
    except (RuntimeError, KeyboardInterrupt):
        pass
    locator = json.loads(output.with_suffix('.root.json').read_text())
    assert locator['root'] == str(root)
    assert locator['cleanup_requires_separate_authorization'] is True
    for name in ('original.sqlite', 'environment.sqlite'):
        with sqlite3.connect(f'file:{root/name}?mode=ro', uri=True) as connection:
            assert connection.execute('SELECT identity FROM exact_attempt').fetchall() == [(exit_kind,)]
    with pytest.raises(FileExistsError):
        with retained_attempt_root(output):
            pytest.fail('duplicate locator allocated another attempt')


def original_helpers():
    spec = importlib.util.spec_from_file_location('probe_retention_controlled_owner',
        ROOT/'packages/execution/units/tests/test_unit_instance.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('fault', ['before_spawn', 'attach'])
def test_original_unknown_and_cleanup_evidence_survive_exit(evidence_root, monkeypatch, fault):
    helpers = original_helpers()
    output = evidence_root/fault/'receipt.json'
    with retained_attempt_root(output) as root:
        fixture = helpers.flow.__wrapped__(root, monkeypatch)
        flow = next(fixture)
        try:
            prepared = flow.instance.prepare(flow.plan, flow.authority.issue('prepare'))
            if fault == 'attach':
                def fail(*args, **kwargs):
                    raise RuntimeError('controlled attach failure; no model')
                monkeypatch.setattr(helpers.ProcessChannel, 'attach', fail)
            else:
                def revoked(*args, **kwargs):
                    raise helpers.UnitLifecycleRefused('controlled before-spawn revocation')
                flow.evidence.start_authority = revoked
            with pytest.raises(helpers.UnitLifecycleRefused, match='creation unknown'):
                flow.instance.start(prepared, flow.authority.issue('start'))
            unit_id = prepared['unitRef']['unitId']
            assert flow.records.owner_read_session(unit_id).state == 'unknown'
            assert flow.events.count('spawn') == (1 if fault == 'attach' else 0)
            report = cleanup_attempt(flow.instance, flow.authority, prepared=prepared)
            report['active_uses'] = flow.environments.instance.snapshot.active_uses
            output.with_suffix('.cleanup.json').write_text(json.dumps(report, indent=2)+'\n')
            assert report['use_release_confirmed'] is True
            assert report['active_uses'] == 0
            if fault == 'attach':
                assert report['owner_release_confirmed'] is True
                assert report['cleanup_completed'] is True
            else:
                assert report['owner_release_confirmed'] is False
                assert report['cleanup_completed'] is False
                assert report['errors']['unit_owner']['error_type'] == 'UnitLifecycleRefused'
            assert flow.records.owner_read_session(unit_id).state == 'unknown'
            with pytest.raises(helpers.UnitRecordsRefused, match='existing native creation cannot be dispatched again'):
                flow.instance.start(prepared, flow.authority.issue('start'))
            assert flow.events.count('spawn') == (1 if fault == 'attach' else 0)
        finally:
            fixture.close()
    assert (root/'original.sqlite').is_file()
    assert (root/'environment.sqlite').is_file()
    assert output.with_suffix('.cleanup.json').is_file()

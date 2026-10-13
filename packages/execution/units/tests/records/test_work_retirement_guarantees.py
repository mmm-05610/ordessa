"""Retained guarantees on the real UnitRecords owner, not a recreated Work API.

Controlled authority/native proof fixtures and real temporary SQLite. Stop's
native effect is outside this recorder; no native process or model is called.
"""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from agent_tools_fixtures.unit_records import parts, reserve, TermEvidence
from ordessa_units.records.unit_records import UnitRecordsRefused


def opening(tmp_path):
    p = parts(tmp_path, termination=TermEvidence())
    unit, _ = reserve(p)
    ticket = p[0].begin_termination(unit.unit_ref, p[2].issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    p[0].record_termination(ticket, expected_source_revision=1, state='unknown')
    return p, unit, ticket


def test_original_unit_unknown_survives_failure_inside_termination_transaction(tmp_path):
    p, unit, ticket = opening(tmp_path)
    service, journal, *_ = p
    with journal._connect() as db:
        db.execute("CREATE TRIGGER reject_confirmation BEFORE UPDATE ON harness_unit_terminations WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT, 'controlled before commit'); END")
        db.commit()
    before = service.owner_read_termination(unit.unit_ref, 'stop')
    with pytest.raises(sqlite3.IntegrityError, match='controlled before commit'):
        service.record_termination(ticket, expected_source_revision=2, state='confirmed',
                                   evidence={'terminationEvidenceRef': 'original-native-proof'})
    assert service.owner_read_termination(unit.unit_ref, 'stop') == before
    assert before['state'] == 'unknown' and before['sourceRevision'] == 2
    with journal._connect() as db:
        row = db.execute('SELECT * FROM harness_unit_terminations WHERE unit_ref=?', (unit.unit_ref,)).fetchone()
        assert row['state'] == 'unknown' and row['source_revision'] == 2
        assert row['outcome_json'] is None and row['outcome_digest'] is None
        db.execute('DROP TRIGGER reject_confirmation')
        db.commit()
    confirmed = service.record_termination(ticket, expected_source_revision=2, state='confirmed',
                                           evidence={'terminationEvidenceRef': 'original-native-proof'})
    assert confirmed['state'] == 'confirmed' and confirmed['sourceRevision'] == 3
    assert service.owner_read_termination(unit.unit_ref, 'stop') == confirmed
    # A concluded ticket cannot manufacture a different terminal result.
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=3, state='unknown')


def test_actual_unit_final_confirmation_has_one_concurrent_winner(tmp_path):
    p, unit, ticket = opening(tmp_path)
    service, journal, *_ = p
    def conclude(_):
        try:
            return service.record_termination(ticket, expected_source_revision=2, state='confirmed',
                evidence={'terminationEvidenceRef': 'original-native-proof'})
        except UnitRecordsRefused:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(conclude, (1, 2)))
    winners = [x for x in outcomes if x is not None]
    assert len(winners) == 1
    assert service.owner_read_termination(unit.unit_ref, 'stop') == winners[0]
    assert winners[0]['state'] == 'confirmed' and winners[0]['sourceRevision'] == 3
    with journal._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_terminations WHERE unit_ref=?', (unit.unit_ref,)).fetchone()[0] == 1

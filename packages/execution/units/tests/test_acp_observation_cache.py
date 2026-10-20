"""Committed observation reuse preserves the original durable/cold checks."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding.canonical_json import CanonicalJSONError
from ordessa_units.records import UnitRecordsRefused
from ordessa_units.records import acp_turns
from test_acp_durable_turn import recorded, start


def dispatched(flow):
    ref, _ = start(flow)
    params = {'sessionId': 'controlled-native-session', 'prompt': []}
    acp_turns.reserve(flow.records, ref, 'cache-turn', params)
    acp_turns.dispatch(flow.records, 'cache-turn',
        {'jsonrpc': '2.0', 'id': 'cache-rpc', 'method': 'session/prompt', 'params': params})
    return flow.records


def event(text='text'):
    return {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
        'sessionId': 'controlled-native-session', 'update': {
            'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}}}}


def row(owner):
    with owner.journal._connect() as db:
        return tuple(db.execute('SELECT * FROM harness_acp_turn_attempts').fetchone())


def cold(owner):
    with owner.journal._connect() as db:
        return acp_turns._read(owner, db, 'cache-turn')


def test_private_copy_exact_canonical_bytes_and_cold_validation(recorded, monkeypatch):
    owner = dispatched(recorded)
    original = event('原文')
    acp_turns.observe(owner, 'cache-turn', original)
    original['params']['update']['content']['text'] = 'changed alias'
    full = acp_turns._check
    def forbidden(*args):
        raise AssertionError('identical committed row must reuse validated prefix')
    monkeypatch.setattr(acp_turns, '_check', forbidden)
    acp_turns.observe(owner, 'cache-turn', event('next'))
    monkeypatch.setattr(acp_turns, '_check', full)
    body = cold(owner)
    assert body['events'][0]['raw']['params']['update']['content']['text'] == '原文'
    stored = row(owner)
    assert stored == owner._acp_observation_cache[0]
    assert stored[4] == acp_turns._json(body)
    assert stored[5] == acp_turns.digest(body)
    assert body['eventsDigest'] == acp_turns.digest(body['events'])


@pytest.mark.parametrize('column,value', [
    ('operation_ref', 'changed-op'), ('unit_ref', 'changed-unit'),
    ('state', 'unknown'), ('revision', 12345),
    ('body_json', '{}'), ('body_digest', 'sha256:changed')])
def test_any_row_column_change_reenters_complete_check(recorded, monkeypatch, column, value):
    owner = dispatched(recorded)
    acp_turns.observe(owner, 'cache-turn', event())
    cached = owner._acp_observation_cache
    with owner.journal._connect() as db:
        # FK damage is deliberately injected only in this isolated fixture.
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute(f'UPDATE harness_acp_turn_attempts SET {column}=?', (value,))
        db.commit()
    original = acp_turns._check
    calls = []
    def checked(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(acp_turns, '_check', checked)
    with pytest.raises((UnitRecordsRefused, KeyError)):
        acp_turns.observe(owner, 'cache-turn', event())
    assert calls and owner._acp_observation_cache is cached


@pytest.mark.parametrize('damage', ['unit', 'session', 'scope'])
def test_cache_hit_rechecks_original_external_provenance(recorded, monkeypatch, damage):
    owner = dispatched(recorded)
    acp_turns.observe(owner, 'cache-turn', event())
    before = row(owner)
    if damage == 'scope':
        monkeypatch.setattr(owner.scope_authority, 'verify_scope', lambda *args: False)
    else:
        with owner.journal._connect() as db:
            if damage == 'unit':
                db.execute("UPDATE harness_unit_reservations SET intent_digest='changed'")
            else:
                db.execute("UPDATE harness_unit_sessions SET state='unknown'")
            db.commit()
    with pytest.raises(UnitRecordsRefused):
        acp_turns.observe(owner, 'cache-turn', event())
    assert row(owner) == before


def test_depth_wrapper_nonfinite_and_capacity_keep_committed_prefix(recorded, monkeypatch):
    owner = dispatched(recorded)
    acp_turns.observe(owner, 'cache-turn', event())
    before = row(owner)
    cached = owner._acp_observation_cache
    # Exact acceptance is established by the ORIGINAL full body/digest path.
    accepted = rejected = 0
    for depth in range(25, 34):
        raw = {'jsonrpc': '2.0'}
        nested = 'leaf'
        for _ in range(depth):
            nested = [nested]
        raw['extra'] = nested
        body = cold(owner)
        full_event = {'sequence': len(body['events'])+1, 'sessionMatched': False, 'raw': raw}
        prospective = dict(body, events=body['events']+[full_event])
        try:
            acp_turns.digest(prospective)
            valid = True
        except CanonicalJSONError:
            valid = False
        if valid:
            acp_turns.observe(owner, 'cache-turn', raw)
            cold(owner)
            accepted += 1
        else:
            previous = row(owner)
            with pytest.raises(CanonicalJSONError):
                acp_turns.observe(owner, 'cache-turn', raw)
            assert row(owner) == previous
            rejected += 1
    assert accepted and rejected
    with pytest.raises(CanonicalJSONError):
        acp_turns.observe(owner, 'cache-turn', {'extra': float('nan')})
    previous = row(owner)
    monkeypatch.setattr(acp_turns, 'MAX_EVIDENCE_BYTES', len(previous[4].encode()))
    with pytest.raises(UnitRecordsRefused, match='capacity'):
        acp_turns.observe(owner, 'cache-turn', event('capacity'))
    assert row(owner) == previous
    assert before == cached[0]


def test_failed_commit_does_not_advance_cache(recorded, monkeypatch):
    owner = dispatched(recorded)
    acp_turns.observe(owner, 'cache-turn', event())
    cached, before = owner._acp_observation_cache, row(owner)
    original = owner.journal._connect
    class FailingCommit:
        def __enter__(self):
            self.db = original()
            return self
        def __exit__(self, *args):
            self.db.rollback()
            self.db.close()
        def execute(self, *args):
            return self.db.execute(*args)
        def commit(self):
            raise OSError('controlled uncommitted write')
    monkeypatch.setattr(owner.journal, '_connect', FailingCommit)
    with pytest.raises(OSError):
        acp_turns.observe(owner, 'cache-turn', event('must roll back'))
    monkeypatch.setattr(owner.journal, '_connect', original)
    assert owner._acp_observation_cache is cached and row(owner) == before
    acp_turns.observe(owner, 'cache-turn', event('committed'))
    assert len(cold(owner)['events']) == 2


@pytest.mark.parametrize('invalid', [False, True])
def test_finish_uses_full_check_and_clears_cache_on_every_outcome(recorded, invalid):
    owner = dispatched(recorded)
    terminal = {'jsonrpc': '2.0', 'id': 'cache-rpc', 'result': {'stopReason': 'end_turn'}}
    acp_turns.observe(owner, 'cache-turn', terminal)
    if invalid:
        with owner.journal._connect() as db:
            db.execute("UPDATE harness_acp_turn_attempts SET body_digest='changed'")
            db.commit()
        with pytest.raises(UnitRecordsRefused):
            acp_turns.finish(owner, 'cache-turn', 'completed', terminal)
    else:
        assert acp_turns.finish(owner, 'cache-turn', 'completed', terminal)['state'] == 'completed'
        assert cold(owner)['state'] == 'completed'
    assert owner._acp_observation_cache is None


def test_concurrent_append_serializes_commit_and_cache_publication(recorded):
    owner = dispatched(recorded)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: acp_turns.observe(owner, 'cache-turn', event(str(i))), range(16)))
    body = cold(owner)
    assert [item['sequence'] for item in body['events']] == list(range(1, 17))
    assert {item['raw']['params']['update']['content']['text'] for item in body['events']} == {str(i) for i in range(16)}
    assert row(owner) == owner._acp_observation_cache[0]

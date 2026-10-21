"""Read a frozen 031 evidence chain without rewriting its archived bytes."""
import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ordessa_decision.historical import ReadContext, FileEvidenceReader

ROOT = Path(__file__).resolve().parents[5]
RUN_ID = '0cf02263-2bbf-4e92-b604-a7184c1a6442'
HISTORY = (ROOT / 'docs/implementation/specifications/031-jev-decision-module/evidence'
           / 'adversarial-20261005/live-injection/durable' / RUN_ID)


def test_historical_reader_has_no_writer_and_foreign_read_authority_is_refused(tmp_path):
    import ordessa_decision.historical as historical
    root, copy = _copy_for_reader(tmp_path)
    original = {p.name:p.read_bytes() for p in copy.iterdir() if p.is_file()}
    authority = object()
    context = ReadContext(authority, 'history.031')
    reader = FileEvidenceReader(root, read_context=context)
    try:
        assert not hasattr(historical, 'FileEvidenceSink')
        for name in ('start', 'append_durable', 'finish'):
            assert not hasattr(reader, name)
        assert asyncio.run(reader.read(RUN_ID, ReadContext(object(), 'history.031')))=={'status':'refused'}
        assert asyncio.run(reader.read(RUN_ID, ReadContext(authority, 'foreign-scope')))=={'status':'refused'}
    finally:
        asyncio.run(reader.close())
    assert {p.name:p.read_bytes() for p in copy.iterdir() if p.is_file()}==original


def test_frozen_031_fixture_is_locatable_with_original_bytes():
    """The archived fixture must be locatable at its real docs path, unchanged."""
    assert HISTORY.is_dir()
    events = (HISTORY / 'events.jsonl')
    terminal = (HISTORY / 'terminal.json')
    assert events.is_file() and terminal.is_file()
    assert hashlib.sha256(events.read_bytes()).hexdigest() == \
        '23fbb738779715f73e87c7e07eb158d12eb9e68405d3a9f84f49b078ea194ad8'
    assert hashlib.sha256(terminal.read_bytes()).hexdigest() == \
        '0ade1ebbf4c124cc4e15d83619198180e40e5289e920bdc082077481f1cbaa92'


def _copy_for_reader(tmp_path):
    root = tmp_path / 'tampered-copy'
    root.mkdir(mode=0o700)
    copy = root / RUN_ID
    shutil.copytree(HISTORY, copy)
    copy.chmod(0o700)
    for child in copy.iterdir():
        child.chmod(0o600)
    return root, copy


def _write_json(path, value):
    path.write_text(json.dumps(value, separators=(',', ':'), sort_keys=True) + '\n')


def test_frozen_031_chain_reads_as_committed_without_source_mutation(tmp_path):
    events = (HISTORY / 'events.jsonl').read_bytes()
    terminal_record = (HISTORY / 'terminal.json').read_bytes()
    assert hashlib.sha256(events).hexdigest() == '23fbb738779715f73e87c7e07eb158d12eb9e68405d3a9f84f49b078ea194ad8'
    assert hashlib.sha256(terminal_record).hexdigest() == '0ade1ebbf4c124cc4e15d83619198180e40e5289e920bdc082077481f1cbaa92'

    root = tmp_path / 'durable-copy'
    root.mkdir(mode=0o700)
    copy = root / RUN_ID
    shutil.copytree(HISTORY, copy)
    copy.chmod(0o700)
    for child in copy.iterdir():
        child.chmod(0o600)
    context = ReadContext(object(), 'history.031')
    reader = FileEvidenceReader(root, read_context=context)
    try:
        observed = asyncio.run(reader.read(RUN_ID, context))
    finally:
        asyncio.run(reader.close())

    assert (HISTORY / 'events.jsonl').read_bytes() == events
    assert (HISTORY / 'terminal.json').read_bytes() == terminal_record
    assert observed['status'] == 'completed'
    assert len(observed['events']) == 14
    assert observed['terminal']['run_id'] == RUN_ID
    assert observed['terminal']['terminal_digest'] == 'sha256:cf54c89b8abfd45d4edd8e628c471ef2d292b13bc2566c34b31c0008cb7b40ac'
    assert observed['terminal']['result']['call_evidence'] == 'unknown'
    assert observed['call_evidence'] == 'recorded'


@pytest.mark.parametrize('tamper', (
    'event-digest',
    'event-previous-digest',
    'terminal-result',
    'terminal-result-digest',
    'terminal-envelope-digest',
))
def test_parseable_digest_tampering_never_reads_as_completed(tmp_path, tamper):
    original_events = (HISTORY / 'events.jsonl').read_bytes()
    original_terminal = (HISTORY / 'terminal.json').read_bytes()
    root, copy = _copy_for_reader(tmp_path)
    if tamper in ('event-digest', 'event-previous-digest'):
        lines = (copy / 'events.jsonl').read_text().splitlines()
        record = json.loads(lines[1])
        field = 'digest' if tamper == 'event-digest' else 'prev_digest'
        record[field] = 'sha256:' + ('0' * 64)
        lines[1] = json.dumps(record, separators=(',', ':'), sort_keys=True)
        (copy / 'events.jsonl').write_text('\n'.join(lines) + '\n')
    else:
        envelope = json.loads((copy / 'terminal.json').read_text())
        if tamper == 'terminal-result':
            envelope['terminal']['result']['request_id'] = 'tampered-request'
        elif tamper == 'terminal-result-digest':
            envelope['terminal']['terminal_digest'] = 'sha256:' + ('0' * 64)
        else:
            envelope['digest'] = 'sha256:' + ('0' * 64)
        _write_json(copy / 'terminal.json', envelope)

    context = ReadContext(object(), 'history.031')
    reader = FileEvidenceReader(root, read_context=context)
    try:
        observed = asyncio.run(reader.read(RUN_ID, context))
    finally:
        asyncio.run(reader.close())

    assert observed['status'] == 'unknown'
    assert observed['status'] != 'completed'
    assert (HISTORY / 'events.jsonl').read_bytes() == original_events
    assert (HISTORY / 'terminal.json').read_bytes() == original_terminal

"""C: original UnitRecords configuration binding and actual guarded pipe.

Original SQLite journal; authority/native owner are controlled. RPC ACK alone
never creates configuration-applied/effect proof or releases the scope fence.
"""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'plugins/harness/tests'))
from test_unit_configuration_records import setup, opening, query, context, DIGEST
from ordessa_environment_api.operations import safe_json
from ordessa_harness_codex.client import CodexAppServerClient
from ordessa_harness_records.unit_records import UnitRecordsRefused
from ordessa_harness_transport import LaunchSpec, ProcessChannel, RequestTimeout, WriterLeaseRefused


@pytest.mark.parametrize('scenario', ['ack-only', 'receipt-lost', 'bind-then-fence'])
def test_original_configuration_journal_binds_at_actual_write_barrier(tmp_path, scenario):
    p, unit = setup(tmp_path)
    ticket = opening(p, unit)
    script, transcript = tmp_path / 'configuration-C.py', tmp_path / 'native-configuration-C.jsonl'
    script.write_text('import sys,json\nfor wire in sys.stdin.buffer:\n p=json.loads(wire)\n with open(sys.argv[1],"ab") as f: f.write(wire)\n if sys.argv[2]!="receipt-lost": print(json.dumps({"id":p["id"],"result":{"status":"ok","version":"controlled-v2"}}),flush=True)\n')
    channel = ProcessChannel.launch(LaunchSpec.build([sys.executable, str(script), str(transcript), scenario],
        home=str(tmp_path / 'controlled-home'), cwd=str(tmp_path)), name='configuration-journal-C', managed=True)
    client = CodexAppServerClient(channel.bind_writer(channel.acquire_writer()))
    captured = []
    def bind(native):
        digest = 'sha256:' + hashlib.sha256(safe_json(native).encode()).hexdigest()
        attempt = p[0].bind_configuration_dispatch(ticket, native_request_id=native['id'], native_request_digest=digest)
        assert attempt.source_revision == 2
        # Independent journal read inside actual guard sees committed original
        # identity before any native frame is written.
        assert query(p, unit).native_request_id == native['id']
        assert not transcript.exists()
        captured.append((native, digest))
        if scenario == 'bind-then-fence': channel.fence_all()
    try:
        if scenario == 'ack-only':
            assert client.command_once('config/batchWrite', {'edits': [], 'expectedVersion': 'controlled-v1'}, before_send=bind) == {'status': 'ok', 'version': 'controlled-v2'}
        else:
            with pytest.raises(RequestTimeout if scenario == 'receipt-lost' else WriterLeaseRefused):
                client.command_once('config/batchWrite', {'edits': [], 'expectedVersion': 'controlled-v1'}, before_send=bind, timeout=.2)
        assert len(captured) == 1
        original, digest = captured[0]
        attempt = query(p, unit)
        assert attempt.state == 'opening' and attempt.native_request_id == 'req-1' and attempt.native_request_digest == digest
        assert attempt.identity['unitRef'] == unit.public_ref and attempt.identity['scopeRef'] == unit.configuration_target_ref
        if scenario == 'bind-then-fence':
            assert not transcript.exists() and channel.poll_message(timeout=.02) is None
        else:
            assert json.loads(transcript.read_bytes()) == original
        result = p[0].record_configuration_change(ticket, expected_source_revision=2, state='unknown')
        assert result.state == 'unknown' and result.source_revision == 3 and result.confirmation is None
        assert query(p, unit).native_request_id == original['id']
        with pytest.raises(UnitRecordsRefused):
            p[0].begin_configuration_change(unit.unit_ref, context(p, unit, step='different-request'), input_digest=DIGEST, expected_revision='controlled-v2')
        if scenario != 'ack-only':
            with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
        with p[1]._connect() as db:
            assert db.execute('SELECT count(*) FROM harness_unit_configuration_attempts').fetchone()[0] == 1
    finally:
        client.close(); channel.close(timeout=2)
        assert channel._process.poll() is not None

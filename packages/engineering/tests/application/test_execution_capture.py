"""Explicit records fixture tests; these are not original Execution integration tests."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.domain.common.models.values import Digest


UNIT = {'environmentNamespace':'fixture-environment', 'unitId': 'fixture-unit',
        'ownerProviderRef': {'fixture':'explicit'}, 'sourceRevision':'sha256:'+'b'*64}
PROMPT = 'sha256:' + 'a' * 64


class ExplicitRecordsFixture:
    """Synthetic fixture implementing the public query shape, never the original issuer/verifier."""
    def __init__(self, state='unknown'):
        self.receipt = {'contractVersion': 'unit-acp-turn/1', 'operationRef': 'op-1',
                        'unitRef': dict(UNIT), 'inputDigest': PROMPT, 'state': state,
                        'revision': 3, 'nativeBinding': {'sessionId': 's'}, 'request': None,
                        'frameDigest': None, 'events': [], 'eventsDigest': 'sha256:events',
                        'response': None, 'responseDigest': 'sha256:null', 'summary': None}
        self.calls = []

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest):
        return 'query:' + json.dumps([unit_ref, operation_ref, expected_prompt_input_digest], sort_keys=True)

    def query_acp_turn(self, unit_ref, operation_ref, context, *, input_digest, expected_prompt_input_digest):
        self.calls.append((dict(unit_ref), operation_ref, input_digest, expected_prompt_input_digest))
        assert context.facts['inputDigest'] == input_digest
        return self.receipt


class ExplicitBlobFixture:
    """Synthetic same-authority store with verified-byte semantics for this test."""
    def __init__(self, authority_id='library-1'):
        self.authority_id = authority_id
        self.data = {}

    def put_verified(self, raw_bytes, expected_digest, media_type):
        assert hashlib.sha256(raw_bytes).hexdigest() == expected_digest.hex
        self.data[expected_digest.hex] = raw_bytes
        from ordessa_engineering.domain.common.models.refs import BlobRef
        return BlobRef(expected_digest, len(raw_bytes), media_type, 'fixture:' + expected_digest.hex)

    def read_verified(self, ref):
        return self.data[ref.digest.hex]


def _invocation(records, prompt=PROMPT):
    return SimpleNamespace(facts={'inputDigest': records.acp_turn_query_digest(UNIT, 'op-1', prompt)})


def test_capture_preserves_unknown_record_and_exact_bindings():
    records = ExplicitRecordsFixture('unknown')
    blobs = ExplicitBlobFixture()
    result = capture_execution_observation(records, blobs, authority_id='library-1',
        unit_ref=UNIT, operation_ref='op-1', expected_prompt_digest=PROMPT,
        query_invocation=_invocation(records))
    stored = blobs.data[result.blob_ref.digest.hex]
    assert json.loads(stored)['state'] == 'unknown'
    assert result.state == 'unknown' and result.operation_ref == 'op-1'
    assert records.calls == [(UNIT, 'op-1', result.query_digest, PROMPT)]


def test_wrong_query_digest_refuses_before_read():
    records = ExplicitRecordsFixture()
    with pytest.raises(ApplicationError, match='EXECUTION_QUERY_BINDING_MISMATCH'):
        capture_execution_observation(records, ExplicitBlobFixture(), authority_id='library-1',
            unit_ref=UNIT, operation_ref='op-1', expected_prompt_digest=PROMPT,
            query_invocation=SimpleNamespace(facts={'inputDigest': 'wrong'}))
    assert records.calls == []


def test_receipt_binding_and_blob_authority_are_enforced():
    records = ExplicitRecordsFixture('completed')
    records.receipt['operationRef'] = 'other'
    with pytest.raises(ApplicationError, match='EXECUTION_RECEIPT_BINDING_MISMATCH'):
        capture_execution_observation(records, ExplicitBlobFixture(), authority_id='library-1',
            unit_ref=UNIT, operation_ref='op-1', expected_prompt_digest=PROMPT,
            query_invocation=_invocation(records))
    with pytest.raises(ApplicationError, match='EXECUTION_BLOB_AUTHORITY_MISMATCH'):
        capture_execution_observation(ExplicitRecordsFixture(), ExplicitBlobFixture('other'),
            authority_id='library-1', unit_ref=UNIT, operation_ref='op-1',
            expected_prompt_digest=PROMPT, query_invocation=_invocation(ExplicitRecordsFixture()))


@pytest.mark.parametrize('state',['reserved','possibly-written','failed','completed'])
def test_capture_does_not_reclassify_rpc_or_unresolved_state(state):
    records = ExplicitRecordsFixture(state)
    result = capture_execution_observation(records, ExplicitBlobFixture(), authority_id='library-1',
        unit_ref=UNIT, operation_ref='op-1', expected_prompt_digest=PROMPT,
        query_invocation=_invocation(records))
    assert result.state == state
    assert not hasattr(result,'implementation_completed') and not hasattr(result,'grant')


def test_actual_public_records_cold_read_captured_in_original_sqlite_blob(tmp_path):
    """Original selected Units/Local/SDK, controlled peer/issuer, no model.

    The original Execution test scaffolding creates its own pristine journals.
    Engineering reads the public cold port and writes its original BlobStore;
    this does not qualify a production issuer or an implementation Submission.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path
    import ordessa_engineering
    import ordessa_units
    root = Path(__file__).resolve().parents[4]
    units_import_root = Path(ordessa_units.__file__).resolve().parent.parent
    script = r'''
import sys,json,faulthandler
faulthandler.dump_traceback_later(8,repeat=False)
from pathlib import Path
sys.path.insert(0,sys.argv[1])
sys.path.insert(0,sys.argv[2])
sys.path.insert(0,sys.argv[3])
import pytest
import test_acp_durable_turn as original
from types import SimpleNamespace
from ordessa_units.records import UnitRecords,OperationJournal
import ordessa_units
assert str(Path(ordessa_units.__file__).resolve()).startswith(sys.argv[2])
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.application.contracts.errors import ApplicationError
directory=Path(sys.argv[4]); monkey=pytest.MonkeyPatch()
generator=original.recorded.__wrapped__(directory,monkey)
flow=next(generator)
library=EngineeringLibrary.create((directory/'engineering.sqlite').resolve(),library_id='capture-original',schema_version=7)
try:
 ref,lease=original.start(flow)
 result=flow.instance.prompt_recorded(ref,lease,operation_ref='capture-1',timeout=2,prompt=[])
 def forbidden(*args,**kwargs):raise AssertionError('cold read cannot open a live channel')
 cold=UnitRecords(OperationJournal(flow.records.journal.path),scope_authority=original.helpers.Scope(),
   native_evidence=SimpleNamespace(verify_binding=forbidden),verifier=flow.authority,
   epoch_port=SimpleNamespace(current_epoch=lambda node:0))
 def invocation(prompt):
  value=flow.authority.issue('query');value.facts['query']=True
  value.facts['inputDigest']=cold.acp_turn_query_digest(ref,'capture-1',prompt)
  return value
 blobs=SQLiteBlobStore(library)
 captured=capture_execution_observation(cold,blobs,authority_id=library.library_id,
   unit_ref=ref,operation_ref='capture-1',expected_prompt_digest=result['inputDigest'],
   query_invocation=invocation(result['inputDigest']))
 assert json.loads(blobs.read_verified(captured.blob_ref))==json.loads(json.dumps(result,default=dict))
 assert captured.state=='completed' and flow.events.count('spawn')==1
 try:
  capture_execution_observation(cold,blobs,authority_id=library.library_id,
   unit_ref=ref,operation_ref='capture-1',expected_prompt_digest='sha256:'+'0'*64,
   query_invocation=invocation('sha256:'+'0'*64))
 except ApplicationError as exc:assert exc.code=='EXECUTION_QUERY_REFUSED'
 else:raise AssertionError('wrong expected prompt digest accepted')
 print('original-authorized-cold-read-original-blob-confirmed')
finally:
 library.close()
 try:next(generator)
 except StopIteration:pass
 monkey.undo()
'''
    result = subprocess.run([sys.executable,'-B','-c',script,
        str(root/'packages/execution/units/tests'),str(units_import_root),
        str(Path(ordessa_engineering.__file__).resolve().parent.parent),str(tmp_path)],
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'original-authorized-cold-read-original-blob-confirmed'

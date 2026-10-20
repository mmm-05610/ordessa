"""Read a real local UnitRecords ACP receipt through the declared port reader.

The ACP peer is a deterministic local protocol script. It makes no model call;
the LocalUnitOwner, UnitManager, UnitInstance, ACP journal, and receipt are real.
"""
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
    DeclaredGenerationPort)
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest

ROOT = Path(__file__).resolve().parents[3]
UNIT_TESTS = ROOT / "packages/execution/units/tests"
if str(UNIT_TESTS) not in sys.path:
    sys.path.insert(0, str(UNIT_TESTS))
from test_local_owner import live_owner


OUTPUT_TEXT = '{"controlled":"unit-records-output"}'
PEER = r'''import json,sys
options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low','options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
session_id='local-owner-'+__import__('os').path.basename(__import__('os').path.dirname(__import__('os').getcwd()))
for line in sys.stdin:
 q=json.loads(line); method=q['method']; p=q.get('params',{})
 if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
 elif method=='session/new': r={'sessionId':session_id,'configOptions':options}
 elif method=='session/load': r={}
 elif method=='_ordessa/session/configuration': r={'sessionId':session_id,'configOptions':options}
 elif method=='session/prompt':
  event={'jsonrpc':'2.0','method':'session/update','params':{'sessionId':p.get('sessionId'),'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'{"controlled":"unit-records-output"}'}}}}
  print(json.dumps(event),flush=True)
  r={'stopReason':'end_turn'}
 elif method=='session/cancel': continue
 else: r={}
 print(json.dumps({'jsonrpc':'2.0','id':q.get('id'),'result':r}),flush=True)
'''


class _Blobs:
    def __init__(self):
        self.values = {}

    def put_verified(self, raw, expected_digest, media_type):
        assert hashlib.sha256(raw).hexdigest() == expected_digest.hex
        ref = BlobRef(expected_digest, len(raw), media_type,
                      "controlled-" + expected_digest.hex)
        self.values[ref.storage_object_id] = raw
        return ref

    def read_verified(self, ref):
        raw = self.values[ref.storage_object_id]
        assert hashlib.sha256(raw).hexdigest() == ref.digest.hex
        assert len(raw) == ref.byte_length
        return raw


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "preparation_peer": PEER,
}], indirect=True)
def test_original_unit_records_receipt_is_the_declared_port_output_source(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    try:
        instance = world.owner.native_unit(unit, authorization)
        lease = world.owner.authorize("interaction", unit, authorization)
        operation = "declared-generation-controlled-acp"
        prompt = {"prompt": [{"type": "text", "text": "native generation input" * 7000}]}
        receipt = instance.prompt(
            unit.identity, lease, operation_ref=operation, timeout=5, **prompt)

        assert receipt["contractVersion"] == "unit-acp-turn/1"
        assert receipt["state"] == "completed"
        plain_unit_ref = decode_json(safe_json(unit.identity).encode("utf-8"))
        assert receipt["unitRef"] == plain_unit_ref
        assert receipt["operationRef"] == operation
        assert receipt["summary"]["text"] == OUTPUT_TEXT
        assert receipt["summary"]["successfulRpcResponse"] is True
        assert receipt["summary"]["modelQualityVerified"] is False
        assert receipt["events"]

        # Feed the exact original receipt bytes to the same read-side parser the
        # formal port uses, without fabricating a package-shaped result blob.
        maximum = world.owner.records.acp_turn_evidence_max_bytes
        raw = safe_json(receipt, max_bytes=maximum).encode("utf-8")
        assert 262144 < len(raw) <= maximum
        blobs = _Blobs()
        ref = blobs.put_verified(raw, Digest("sha256", hashlib.sha256(raw).hexdigest()),
                                 "application/json")
        port = object.__new__(DeclaredGenerationPort)
        port.blobs = blobs
        binding = SimpleNamespace(
            unit_ref_bytes=canonical_bytes(plain_unit_ref),
            execution_operation_ref=operation,
            prompt_input_digest=Digest("sha256", receipt["inputDigest"].removeprefix("sha256:")),
        )
        assert port._receipt_text(ref, binding) == OUTPUT_TEXT
    finally:
        unit.close(authorization)

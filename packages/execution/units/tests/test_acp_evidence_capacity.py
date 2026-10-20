"""Real LocalUnit/SDK coverage for bounded durable ACP prompt evidence."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_unit_instance as helpers
from test_acp_durable_turn import query, recorded, start
from ordessa_units.records import (
    AcpEvidenceCapacityRefused,
    OperationJournal,
    UnitRecords,
    acp_turns,
)
from ordessa_infrastructure.encoding.immutable_json import safe_json


def _record_peer_prompts(monkeypatch):
    peer = helpers.PEER.replace(
        "elif method=='session/prompt':",
        "elif method=='session/prompt':\n"
        "        with open(os.environ['FIXTURE_CONFIG']+'.prompt-calls','a') as log:"
        " log.write('prompt\\n')",
    )
    monkeypatch.setattr(helpers, "PEER", peer)


def _prompt_log(flow):
    profile = flow.plan["context"]["privateRootFacts"]["profile"]
    return Path(profile) / "settings.json.prompt-calls"


def _prompt_params(text):
    return {
        "prompt": [{"type": "text", "text": text}],
        "sessionId": "controlled-native-session",
    }


def _prompt_input_bytes(params):
    """Measure the complete prompt input under this module's own evidence budget.

    ``safe_json``'s shared default is the 256KiB report budget, which is smaller
    than a complete prompt here (these reach ~460KiB). Measuring under that
    default refuses to encode the value at all, so it can neither confirm nor
    deny the 576KiB prompt cap. Measure under the 2.5MiB complete-evidence
    budget instead; the assertions below still compare against the real caps.
    """
    return len(safe_json(params, max_bytes=acp_turns.MAX_EVIDENCE_BYTES).encode("utf-8"))


def test_three_document_native_stream_fits_and_receipt_bound_still_refuses():
    # Measured original event shape: four-byte chunks, not a single synthetic
    # bulk update. Keep the full 536KB prompt in input/raw/frame, as production
    # does. This is a bounded serialization check, not a model/dispatch result.
    prompt = 'p' * 536_518
    events = [{'sequence':i + 1, 'sessionMatched':True, 'raw':{
        'jsonrpc':'2.0', 'method':'session/update', 'params':{
            'sessionId':'original-session-' + 's' * 40,
            'update':{'sessionUpdate':'agent_message_chunk',
                      'content':{'type':'text','text':'abcd'}}}}} for i in range(9000)]
    envelope = {'input':prompt, 'request':{'raw':prompt, 'frameUtf8':prompt},
                'events':events, 'summary':{'text':'abcd' * 9000}}
    encoded = acp_turns._json(envelope).encode()
    assert 2_621_440 < len(encoded) < acp_turns.MAX_EVIDENCE_BYTES == 8_388_608
    with pytest.raises(AcpEvidenceCapacityRefused):
        acp_turns._json({'text':'x' * acp_turns.MAX_EVIDENCE_BYTES})


def _prospective_envelope_bytes(records, ref, operation, params):
    """The exact frozen-request envelope the owner preflights before reserving."""
    with records.journal._connect() as db:
        _, body = acp_turns._new_body(records, db, ref, operation, params)
    prospective = dict(body, state="possibly-written", revision=body["revision"] + 1)
    prospective["request"] = acp_turns._request(
        {
            "jsonrpc": "2.0",
            "id": "r" * (acp_turns.MAX_REQUEST_ID_BYTES - 2),
            "method": "session/prompt",
            "params": params,
        }
    )
    return len(safe_json(prospective, max_bytes=2 * acp_turns.MAX_EVIDENCE_BYTES).encode("utf-8"))


def _prompt_params_of_envelope_bytes(records, ref, operation, target):
    """Prompt params whose prospective preflight envelope is exactly `target` bytes.

    A retained character is counted three times: the prompt input, the frozen
    request and its retained frame text. A backslash costs eight envelope bytes
    for two prompt bytes, so sizing with backslashes keeps the prompt itself far
    inside its own cap. Both measured sizes below are re-measured, never assumed.
    """
    remaining = target - _prospective_envelope_bytes(records, ref, operation, _prompt_params(""))
    for escaped in range(remaining // 8, -1, -1):
        if (remaining - 8 * escaped) % 3 == 0:
            break
    else:
        pytest.fail(f"no prompt text reaches exactly {target} envelope bytes")
    params = _prompt_params("\\" * escaped + "x" * ((remaining - 8 * escaped) // 3))
    assert _prospective_envelope_bytes(records, ref, operation, params) == target
    assert _prompt_input_bytes(params) < acp_turns.MAX_PROMPT_BYTES
    return params


def test_large_prompt_fits_durable_evidence_and_cold_authorized_read(recorded, monkeypatch):
    _record_peer_prompts(monkeypatch)
    ref, lease = start(recorded)
    params = {
        "prompt": [{"type": "text", "text": "x" * 314_274}],
        "sessionId": "controlled-native-session",
    }
    # A prompt above the retired 256KiB cap, at the full-material magnitude
    # (parent-computed lower bound), must pass preflight and be retained whole.
    prompt_bytes = _prompt_input_bytes(params)
    assert 314_274 <= prompt_bytes < acp_turns.MAX_PROMPT_BYTES
    recorded.records.validate_acp_prompt_capacity(ref, params)

    result = recorded.instance.prompt(
        ref, lease, operation_ref="large-prompt-1", timeout=5, params=params
    )

    assert result["state"] == "completed"
    assert result["summary"]["successfulRpcResponse"] is True
    assert result["summary"]["modelQualityVerified"] is False
    raw = result["request"]["raw"]
    frame = result["request"]["frameUtf8"].encode("utf-8")
    decoded_frame = json.loads(frame)
    assert raw["method"] == "session/prompt"
    assert decoded_frame["params"] == params
    assert decoded_frame["id"] == raw["id"]
    assert result["request"]["frameDigest"] == "sha256:" + hashlib.sha256(frame).hexdigest()
    assert frame.endswith(b"\n")
    assert _prompt_log(recorded).read_text() == "prompt\n"

    cold = UnitRecords(
        OperationJournal(recorded.records.journal.path),
        scope_authority=helpers.Scope(),
        native_evidence=SimpleNamespace(
            verify_binding=lambda *args, **kwargs: pytest.fail(
                "authorized cold ACP receipt read must not re-prove a live binding"
            )
        ),
        verifier=recorded.authority,
        epoch_port=SimpleNamespace(current_epoch=lambda node: 0),
    )
    receipt = query(cold, recorded, ref, "large-prompt-1", result["inputDigest"])
    assert receipt == result


def test_oversize_prompt_preflight_refuses_without_reservation(recorded, monkeypatch):
    _record_peer_prompts(monkeypatch)
    ref, lease = start(recorded)
    params = {
        "prompt": [{"type": "text", "text": "x" * 600_000}],
        "sessionId": "controlled-native-session",
    }
    # Above the 576KiB complete-prompt cap: refused by name at preflight,
    # before any reserve or native prompt.
    assert _prompt_input_bytes(params) > acp_turns.MAX_PROMPT_BYTES

    with pytest.raises(AcpEvidenceCapacityRefused) as raised:
        recorded.records.validate_acp_prompt_capacity(ref, params)

    assert raised.value.code == "ACP_EVIDENCE_CAPACITY_EXCEEDED"
    assert not _prompt_log(recorded).exists()
    with recorded.records.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM harness_acp_turn_attempts").fetchone()[0] == 0


def test_measured_request_receipt_lower_bound_fits_the_frozen_request_budget(recorded, monkeypatch):
    _record_peer_prompts(monkeypatch)
    ref, _ = start(recorded)
    # The formal Codex builder measured a 1056935-byte request receipt for a
    # complete-material prompt: above the retired 1MiB budget, inside 1.75MiB.
    params = _prompt_params_of_envelope_bytes(recorded.records, ref, "o" * 256, 1_056_935)

    recorded.records.validate_acp_prompt_capacity(ref, params)

    assert not _prompt_log(recorded).exists()
    with recorded.records.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM harness_acp_turn_attempts").fetchone()[0] == 0


def test_exact_request_budget_passes_and_the_next_byte_refuses_before_reserve(recorded, monkeypatch):
    _record_peer_prompts(monkeypatch)
    ref, lease = start(recorded)
    assert acp_turns.MAX_REQUEST_EVIDENCE_BYTES == 1_835_008  # 1.75MiB frozen budget
    assert acp_turns.MAX_EVIDENCE_BYTES - acp_turns.MAX_REQUEST_EVIDENCE_BYTES == 6_553_600
    budget = acp_turns.MAX_REQUEST_EVIDENCE_BYTES
    recorded.records.validate_acp_prompt_capacity(
        ref, _prompt_params_of_envelope_bytes(recorded.records, ref, "o" * 256, budget)
    )

    operation = "request-budget-plus-one"
    over = _prompt_params_of_envelope_bytes(recorded.records, ref, operation, budget + 1)
    with pytest.raises(AcpEvidenceCapacityRefused) as raised:
        recorded.instance.prompt(ref, lease, operation_ref=operation, timeout=5, **over)

    assert raised.value.code == "ACP_EVIDENCE_CAPACITY_EXCEEDED"
    assert not _prompt_log(recorded).exists()
    with recorded.records.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM harness_acp_turn_attempts").fetchone()[0] == 0


def test_evidence_envelope_capacity_refuses_before_reserve_and_native_prompt(recorded, monkeypatch):
    _record_peer_prompts(monkeypatch)
    ref, lease = start(recorded)
    operation = "envelope-capacity-1"
    # The prompt itself stays inside its 576KiB cap; the prompt input, the
    # frozen request and its retained frame text together exceed the 1.75MiB
    # request budget by a quarter MiB.
    #
    # The complete-evidence envelope is not reachable on this prompt path:
    # the frozen-request preflight refuses at 1.75MiB first, so the real
    # reachable boundary is the request budget, asserted over below. The
    # complete-evidence envelope budget itself is explicitly 8MiB.
    assert acp_turns.MAX_EVIDENCE_BYTES == 8_388_608
    params = _prompt_params_of_envelope_bytes(
        recorded.records, ref, operation, acp_turns.MAX_REQUEST_EVIDENCE_BYTES + 262_144
    )
    assert _prompt_input_bytes(params) < acp_turns.MAX_PROMPT_BYTES

    with pytest.raises(AcpEvidenceCapacityRefused) as raised:
        recorded.instance.prompt(
            ref, lease, operation_ref=operation, timeout=5, **params
        )

    assert raised.value.code == "ACP_EVIDENCE_CAPACITY_EXCEEDED"
    assert not _prompt_log(recorded).exists()
    with recorded.records.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM harness_acp_turn_attempts").fetchone()[0] == 0


def test_complete_evidence_above_two_mib_persists_and_cold_reads_under_original_owner(recorded, monkeypatch):
    # A real Local/SDK peer emits controlled text; no provider/model is used.
    # Keeping it both in events and summary makes the actual durable receipt
    # exceed the retired 2MiB cap and exercises the new whole-receipt budget.
    peer = helpers.PEER.replace("callbacks=[]", """print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':p['sessionId'],'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'x'*1060000}}}}),flush=True)
        callbacks=[]""")
    monkeypatch.setattr(helpers, 'PEER', peer)
    ref, lease = start(recorded)
    receipt = recorded.instance.prompt(ref, lease, operation_ref='whole-evidence-above-two-mib',
        timeout=5, prompt=[])
    assert receipt['state'] == 'completed'
    assert len(receipt['summary']['text']) == 1060000
    raw = safe_json(receipt, max_bytes=acp_turns.MAX_EVIDENCE_BYTES).encode()
    assert 2 * 1024 * 1024 < len(raw) <= 2621440
    cold = UnitRecords(OperationJournal(recorded.records.journal.path),
        scope_authority=helpers.Scope(), native_evidence=object(),
        verifier=recorded.authority, epoch_port=SimpleNamespace(current_epoch=lambda node: 0))
    assert query(cold, recorded, ref, 'whole-evidence-above-two-mib', receipt['inputDigest']) == receipt

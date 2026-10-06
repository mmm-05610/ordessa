"""C: configuration fact confirmation over the original ledger.

Real temporary SQLite configuration attempts + real core apply/consumption
claims and a REAL fenced SDK transport (controlled native capture) for the
pre-send dispatch binding. Proven here: the ACK alone never becomes applied;
only a fresh native readback observation against the SAME native session
confirms; ``expectedConfigurationRevision`` is preserved in the original
attempt identity; unobservable or changed facts stay unknown and keep the
scope fence. No installed SDK or Claude binary exists (P absent): the
controlled native is a test capture, never presented as product evidence.
"""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

import claude_production_fixture as fx
from claude_production_fixture import safe_json

from ordessa_harness_claude_code.configuration_face import (
    ClaudeConfigurationFace, ClaudeConfigurationRefused, _digest_facts,
)
from ordessa_harness_claude_code.sdk import FencedSdkTransport, SdkRuntimeUnavailable
from pacthold.agents.public import ApplicationPolicy, ConfigurationChangeRequest, ConfigurationRevisionConflict


def with_face(tmp_path, **owner_flags):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face = ClaudeConfigurationFace(records=parts["records"], verifier=parts["records"].verifier,
                                   projection=parts["projection"],
                                   session_owner=ControlledSessionOwner(parts, **owner_flags))
    return parts, face, fx.cleanup_operation(parts, "stop")  # cleanup op unused here


def change_request(expected_revision, **declaration_overrides):
    declaration = dict(fx.MODEL_DECLARATION, **declaration_overrides)
    return ConfigurationChangeRequest("apply-request-1", expected_revision, (declaration,),
                                      ApplicationPolicy())


def attempt_state(parts):
    from claude_production_fixture import termination_row  # reuse the journal row helper shape
    with parts["journal"]._connect() as db:
        row = db.execute("SELECT state, source_revision, native_request_json, confirmation_json "
                         "FROM harness_unit_configuration_attempts").fetchall()
    return row


class NativeCapture:
    def __init__(self):
        self.writes = []

    async def connect(self):
        pass

    async def write(self, data):
        self.writes.append(data)

    async def read_messages(self):
        return
        yield  # pragma: no cover - empty stream

    async def close(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        pass


class Gate:
    @asynccontextmanager
    async def dispatch_guard(self, payload):
        yield


class ControlledSessionOwner:
    """The unit's native session owner; dispatches through the fenced transport."""

    def __init__(self, parts, *, seed="seed-model", session="native-observed-id",
                 readback_after_write="changed-model", flip_recheck=None, native_fails=False,
                 phase_out_readback=False, session_after_write=None):
        self.parts_parts = parts
        self.unit_ref = parts["unit"].public_ref
        self.model = seed
        self.session = session
        self.readback_after_write = readback_after_write
        self.native_fails = native_fails
        self.flip_recheck = flip_recheck
        self.phase_out_readback = phase_out_readback
        self.session_after_write = session_after_write
        self.native = NativeCapture()
        self.gate = Gate()
        self.applied_writes = 0
        self.recheck_calls = 0
        self._face = None

    def bind_face(self, face):
        from ordessa_harness_claude_code.sdk import FencedSdkTransport
        self._face = face
        self._transport = FencedSdkTransport(self.native, self.gate,
                                             dispatch_listener=face.dispatch_listener(self.unit_ref))

    def session_apply_model(self, unit, action, payload, context):
        frame = {"type": "control_request",
                 "request_id": "req_model_%d" % (self.applied_writes + 1),
                 "request": {"subtype": "set_model",
                             "model": None if action == "reset" else payload.get("model")}}
        asyncio.run(self._transport.write(json.dumps(frame) + "\n"))
        if self.native_fails:
            raise OSError("controlled native write failure")
        self.applied_writes += 1
        self.model = None if action == "reset" else payload.get("model")
        return {"outcome": "unknown", "confirmation": "ackOnly"}

    def observe_model(self, unit):
        self.recheck_calls += 1
        if self.flip_recheck is not None and self.recheck_calls >= 2:
            return {"model": self.flip_recheck}
        if self.phase_out_readback and self.applied_writes:
            return None
        return {"model": self.model}

    def observe_session(self, unit):
        if self.session is None:
            return None
        if self.applied_writes and self.session_after_write is not None:
            return self.session_after_write
        return self.session


def expected_revision(parts):
    unit = parts["unit"]
    return _digest_facts({"model": "seed-model", "nativeSessionId": "native-observed-id"})


def build(parts, **owner_flags):
    face = ClaudeConfigurationFace(records=parts["records"], verifier=parts["records"].verifier,
                                   projection=parts["projection"],
                                   session_owner=ControlledSessionOwner(parts, **owner_flags))
    owner = face.session_owner if isinstance(face.session_owner, ControlledSessionOwner) \
        else getattr(face, "_session_owner", face.session_owner)
    return face, owner


def test_ack_hot_writes_never_become_applied_without_native_readback(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts, readback_after_write="changed-model", phase_out_readback=True)
    context = parts["issued"]("configuration")
    result = face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert parts["issuer"].verified_consumption(context) is True
    assert all(item.outcome == "unknown" for item in result.item_results)
    assert result.confirmed_snapshot is None
    rows = attempt_state(parts)
    assert rows[-1]["state"] == "unknown" and rows[-1]["confirmation_json"] is None
    assert owner.native.writes and json.loads(owner.native.writes[-1])["request"]["subtype"] == "set_model"


def test_native_readback_same_session_confirms_on_original_attempt(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    result = face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert result.item_results[0].outcome == "applied"
    assert result.confirmed_snapshot.configuration["model"] == "changed-model"
    proof = result.item_results[0].confirmation
    assert proof["requestDigest"] == "change-input"
    assert proof["evidenceRef"]["evidenceRef"].startswith("claude-config/")
    rows = attempt_state(parts)
    assert rows[-1]["state"] == "confirmed" and rows[-1]["confirmation_json"] is not None
    # expectedConfigurationRevision is preserved in the original attempt identity.
    import json as _json
    identity = _json.loads(fx.safe_json({}))
    with parts["journal"]._connect() as db:
        identity_json = db.execute("SELECT identity_json FROM harness_unit_configuration_attempts").fetchone()["identity_json"]
    identity = _json.loads(identity_json)
    assert identity["expectedRevision"] == expected_revision(parts)
    assert identity["requestDigest"] == "change-input"


def test_session_identity_change_never_confirms(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts, session_after_write="replacement-session")
    context = parts["issued"]("configuration")
    result = face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert all(item.outcome == "unknown" for item in result.item_results)
    rows = attempt_state(parts)
    assert rows[-1]["state"] == "unknown"


def test_unobservable_fact_refuses_before_consuming_anything(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts, seed=None, session=None)
    context = parts["issued"]("configuration")
    with pytest.raises(ClaudeConfigurationRefused, match="fact unavailable"):
        face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert parts["issuer"].verified_consumption(context) is False
    assert attempt_state(parts) == []
    assert owner.native.writes == []


def test_stale_expected_revision_conflicts_before_consuming(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    stale = parts["request"]
    with pytest.raises((ConfigurationRevisionConflict, ClaudeConfigurationRefused)):
        face.apply(parts["unit"].public_ref, change_request("sha256:" + "0" * 64), context)
    assert parts["issuer"].verified_consumption(context) is False
    assert attempt_state(parts) == []


def test_fact_changed_before_dispatch_records_unknown_fence(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts, flip_recheck="drifted-model")
    context = parts["issued"]("configuration")
    result = face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert all(item.outcome == "unknown" for item in result.item_results)
    rows = attempt_state(parts)
    assert rows[-1]["state"] == "unknown" and rows[-1]["native_request_json"] is None


def test_required_foreign_kind_refuses_without_consuming(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    with pytest.raises(ClaudeConfigurationRefused, match="required native configuration unsupported"):
        face.apply(parts["unit"].public_ref,
                   change_request(expected_revision(parts),
                                  configurationKind="foreign.kind",
                                  schemaVersion="9"), context)
    assert parts["issuer"].verified_consumption(context) is False
    assert attempt_state(parts) == []
    assert owner.native.writes == []


def test_reset_write_stays_unknown_until_readback_supports_clearing(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    declaration = {"declarationId": "decl-reset", "configurationKind": "claude.model",
                   "schemaVersion": "1", "action": "reset", "requirement": "required",
                   "resourceRefs": []}
    request = ConfigurationChangeRequest("apply-reset-1", expected_revision(parts), (declaration,),
                                         ApplicationPolicy())
    result = face.apply(parts["unit"].public_ref, request, context)
    assert owner.model is None  # the native reset effect did happen on the session owner
    frame = _json_frame(owner.native.writes)
    assert frame["request"]["model"] is None
    assert all(item.outcome == "unknown" for item in result.item_results)  # adapter cannot confirm clearing


def _json_frame(writes):
    return json.loads(writes[-1])


def test_drifted_fact_conflicts_without_second_write(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    writes = list(owner.native.writes)
    with pytest.raises((ConfigurationRevisionConflict, ClaudeConfigurationRefused)):
        face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert owner.native.writes == writes  # no second native dispatch
    assert len(attempt_state(parts)) == 1


def test_consumed_context_is_never_redispatched(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts, native_fails=True)
    context = parts["issued"]("configuration")
    result = face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert all(item.outcome == "unknown" for item in result.item_results)
    writes = list(owner.native.writes)
    with pytest.raises(Exception):
        face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    assert owner.native.writes == writes  # the original attempt was never redispatched


def test_query_reports_original_attempt_and_unknown_facet(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    context = parts["issued"]("configuration")
    face.apply(parts["unit"].public_ref, change_request(expected_revision(parts)), context)
    read_context = parts["issuer"].issue_query(parts["request"], "flow-digest", "configuration")
    result = face.query(parts["unit"].public_ref, "flow-operation", read_context)
    assert result.item_results[0].declaration_id == "decl-model"
    assert result.item_results[0].outcome == "applied"
    assert result.item_results[0].confirmation["evidenceRef"]["evidenceRef"].startswith("claude-config/")
    assert parts["issuer"].verified_observation(read_context) is True


def test_query_without_original_attempt_is_typed_refusal(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)
    face, owner = build(parts)
    read_context = parts["issuer"].issue_query(parts["request"], "flow-digest", "configuration")
    with pytest.raises(Exception, match="original configuration attempt unavailable"):
        face.query(parts["unit"].public_ref, "flow-operation", read_context)


def test_face_demands_full_native_owner_surface(tmp_path):
    parts = fx.family_core_parts(tmp_path, with_session=True)

    class Half:
        def session_apply_model(self, *a, **k):
            return None

    with pytest.raises(ClaudeConfigurationRefused, match="ledger methods required"):
        ClaudeConfigurationFace(records=object(), verifier=object(),
                                projection=parts["projection"], session_owner=Half())
    with pytest.raises(ClaudeConfigurationRefused, match="session configuration owner required"):
        ClaudeConfigurationFace(records=parts["records"], verifier=parts["records"].verifier,
                                projection=parts["projection"], session_owner=Half())
    with pytest.raises(ClaudeConfigurationRefused, match="owner projection"):
        ClaudeConfigurationFace(records=parts["records"], verifier=parts["records"].verifier,
                                projection=object(), session_owner=ControlledSessionOwner(parts))

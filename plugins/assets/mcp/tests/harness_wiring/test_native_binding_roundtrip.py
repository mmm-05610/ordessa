"""Boundary round-trip tests (T013 需求3): native_binding is the ONE
Q4-domain <-> harness-api conversion point, and the API's own
closed-object/validate_json machinery is what enforces it — no hand-rolled
mirror guards.

双向: domain NativeIntentSet -> facet payload -> domain set; domain
NativeObservation -> observed DTO -> domain observation. 拒收: undeclared
fields, secret-shaped keys/paths, managed-lane entries — all refused by the
REAL ``ValueSchema``/``SetField``/``IntentSet`` types.
"""
import dataclasses

import pytest
from ordessa_harness_api import (
    ContractError, FieldPath, IntentSet, IntentSource, SetField, TargetHandle,
)
from wiring_helpers import CANARY, claude_planned

from backend import native_binding as nb
from backend.native_intents import (
    InstanceConfigTarget, NativeObservation, ObservedServer, SlotValue,
)


def _lit(value):
    from backend.definition import Literal
    return Literal(value)


def test_domain_to_payload_to_domain_roundtrip():
    planned = claude_planned(env=(("FOO", _lit("bar")),),
                             destination=InstanceConfigTarget(
                                 target_path="/runtime/home/.claude/.claude.json",
                                 config_key="mcpServers", config_format="json"))
    payload = nb.facet_payload_of(planned)
    # the facet payload never carries the target path (TargetHandle is
    # "never a filesystem path" — the identity belongs to the harness)
    assert "targetPath" not in payload
    flat = repr(payload)
    assert "/runtime/home" not in flat
    back = nb.intent_set_from_payload(payload)
    assert [e.native_name for e in back.entries] == ["demo"]
    assert back.entries[0].env[0].name == "FOO"
    assert back.entries[0].env[0].kind == "literal"
    assert back.entries[0].env[0].value == "bar"
    assert back.session_ref == planned.session_ref
    assert back.runtime_generation == planned.runtime_generation
    assert back.snapshot_digest == planned.snapshot_digest
    assert back.plan_digest == planned.plan_digest
    # payload -> payload is stable (closed schema already enforced)
    again = nb.FACET_PAYLOAD_SCHEMA.validate(payload)
    assert again == payload


def test_observation_roundtrip():
    observation = NativeObservation(
        observer="fake-harness-c3", session_ref="session-a",
        runtime_generation=3,
        servers=(ObservedServer(server_name="demo", transport="stdio",
                                load_state="runtime-loaded",
                                catalog_digest="sha256:cat",
                                tool_names=("read",)),))
    dto = nb.observation_payload_of(observation, evidence_ref="obs:1")
    back = nb.observation_from_payload(dto)
    assert back == observation
    assert dto["evidenceRef"] == "obs:1"


def test_undeclared_field_injection_refused_by_closed_object():
    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    smuggled = dict(payload, targetPath="/home/user/.claude.json")
    with pytest.raises(ContractError):
        nb.FACET_PAYLOAD_SCHEMA.validate(smuggled)
    # and inside an entry: the closed entry schema refuses unknown props
    entry = dict(payload["entries"][0], resolved_env=CANARY)
    with pytest.raises(ContractError):
        nb.FACET_PAYLOAD_SCHEMA.validate(dict(payload, entries=[entry]))


def test_plaintext_secret_key_refused_by_validate_json():
    from ordessa_harness_api import validate_json

    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    entry = dict(payload["entries"][0])
    # a slot smuggled as an undeclared key dies on the closed schema...
    with pytest.raises(ContractError):
        nb.FACET_PAYLOAD_SCHEMA.validate(
            dict(payload, entries=[dict(entry, token=CANARY)]))
    # ...and a secret-named JSON key dies on validate_json itself —
    # both are the API's own machinery, not a Q4 mirror.
    with pytest.raises(ContractError, match="BindSecret"):
        validate_json({"headers": {"token": CANARY}})


def test_setfield_rejects_secret_named_path_requiring_bindsecret():
    # the API itself forbids secret-bearing field paths in SetField —
    # the binding's slot routing (BindSecret or typed refusal) is the only
    # way a secret-named slot can leave a compile.
    source = IntentSource(nb.FACET_ID, nb.FACET_ITEM_ID, nb.FACET_SCHEMA_VERSION)
    handle = TargetHandle("assets.mcp.claude-code.instance-config", 1)
    with pytest.raises(ContractError, match="BindSecret"):
        SetField(source, handle, FieldPath(("mcpServers", "TOKEN")), "x")


def test_managed_lane_entry_cannot_be_shaped_into_the_payload():
    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    entry = dict(payload["entries"][0], lane="managed")
    with pytest.raises(ContractError):
        nb.FACET_PAYLOAD_SCHEMA.validate(dict(payload, entries=[entry]))


def test_intentset_rejects_foreign_intent_objects():
    with pytest.raises(ContractError):
        IntentSet(("not-an-intent",))


def test_assessment_mapping_never_upgrades_unproven_supported():
    from backend.native_intents import AssessResult, VERDICT_SUPPORTED

    # a bare "supported" verdict without runtime evidence or an evidence
    # ref is DOWNGRADED by the binding door (no self-declared support)
    fake = AssessResult("claude-code", VERDICT_SUPPORTED, "instance-config",
                        ("because-i-said-so",))
    assessment = nb.assessment_from_verdict(fake)
    assert assessment.status == "unknown"
    proven = AssessResult("claude-code", VERDICT_SUPPORTED, "instance-config",
                          ("runtime-evidence-proven",))
    assert nb.assessment_from_verdict(proven, evidence_ref="ev:probe").status \
        == "supported"
    assert nb.assessment_from_verdict(proven).status == "unknown"


def test_refusal_mapping_covers_every_error_code():
    from ordessa_harness_api import ErrorCode, Refused

    for code in ErrorCode:
        error = nb.refused_to_mcp_error(Refused(code, ("d",), True))
        assert isinstance(error.code, str) and error.code
        if code is ErrorCode.STALE_PLAN:
            assert error.code == "MCP_CAS_CONFLICT"
        if code is ErrorCode.ADAPTER_MISSING:
            assert error.code == nb._APPLICATION_PORT_ABSENT

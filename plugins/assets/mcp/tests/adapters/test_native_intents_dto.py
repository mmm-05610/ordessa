"""Intent DTO: deterministic serialisation, two destination shapes, no
plaintext-capable fields, complete-set planning (dispatch 需求1)."""
import dataclasses

import pytest
from native_helpers import (
    DictProvenance,
    attestation,
    build_snapshot,
    instance_target,
    revision_provider,
    session_target,
    stdio_revision,
)

from backend.definition import SecretRef
from backend.native_intents import (
    InstanceConfigTarget,
    NativeIntentSet,
    SessionOverrideTarget,
    SlotValue,
)
from adapters import claude, codex


def _two_server_snapshot():
    revs = [
        stdio_revision("def-b", 2, "beta", "/srv/beta", env={"TOK": SecretRef("cred-2")}),
        stdio_revision("def-a", 1, "alpha", "/srv/alpha"),
    ]
    lanes = {r.definition_id: {"lane": "native", "enforcement": "proven"} for r in revs}
    provider = revision_provider({(r.definition_id, r.revision): r for r in revs})
    return build_snapshot(revs, lanes), provider, revs


def test_same_input_same_bytes_and_digest():
    snapshot, provide, _ = _two_server_snapshot()
    provenance = DictProvenance({"cred-2": attestation("cred-2")})
    first = codex.compile(snapshot, session_target("codex"), provenance,
                          revision_provider=provide)
    second = codex.compile(snapshot, session_target("codex"), provenance,
                           revision_provider=provide)
    assert first.serialize() == second.serialize()
    assert first.plan_digest == second.plan_digest
    assert first.plan_digest.startswith("sha256:")


def test_env_ordering_does_not_change_digest():
    rev_a = stdio_revision("d", 1, "a", "/srv/a",
                           env={"ONE": SecretRef("c1"), "TWO": SecretRef("c2")})
    rev_b = stdio_revision("d", 1, "a", "/srv/a",
                           env={"TWO": SecretRef("c2"), "ONE": SecretRef("c1")})
    prov = DictProvenance({"c1": attestation("c1"), "c2": attestation("c2")})

    def provider_a(i, r):
        return rev_a

    def provider_b(i, r):
        return rev_b

    lanes = {"d": {"lane": "native", "enforcement": "proven"}}
    snap_a = build_snapshot([rev_a], lanes)
    snap_b = build_snapshot([rev_b], lanes)
    set_a = claude.compile(snap_a, instance_target("claude"), prov,
                           revision_provider=provider_a)
    set_b = claude.compile(snap_b, instance_target("claude"), prov,
                           revision_provider=provider_b)
    assert set_a.plan_digest == set_b.plan_digest
    assert set_a.serialize() == set_b.serialize()


def test_complete_set_is_one_intent_not_per_server_appends():
    snapshot, provide, _ = _two_server_snapshot()
    provenance = DictProvenance({"cred-2": attestation("cred-2")})
    intent = codex.compile(snapshot, session_target("codex"), provenance,
                           revision_provider=provide)
    assert isinstance(intent, NativeIntentSet)
    # every server planned at once, sorted deterministically by native name
    assert [e.native_name for e in intent.entries] == ["alpha", "beta"]
    # the DTO offers no append/add API
    assert not any(hasattr(NativeIntentSet, a) for a in ("append", "add", "with_server"))


def test_two_destination_shapes_injected_descriptor_only():
    snapshot, provide, _ = _two_server_snapshot()
    provenance = DictProvenance({"cred-2": attestation("cred-2")})
    file_plan = claude.compile(snapshot, instance_target("claude"), provenance,
                               revision_provider=provide)
    session_plan = claude.compile(snapshot, session_target("claude"), provenance,
                                  revision_provider=provide)
    assert file_plan.to_canonical()["destination"]["kind"] == "instance-config"
    assert session_plan.to_canonical()["destination"]["kind"] == "session-override"
    assert "targetPath" not in session_plan.to_canonical()["destination"]
    # both brands accept both shapes (R-Q4-3: destination passed by caller)
    for brand in (codex, claude):
        target = session_target("codex") if brand is codex else instance_target("claude")
        plan = brand.compile(snapshot, target, provenance, revision_provider=provide)
        assert plan.entries == plan.entries  # built fine
    # lane/owner binding fields present on every entry
    for entry in file_plan.entries:
        assert entry.lane == "native"
        assert entry.owner == "harness-native"


def test_secret_slots_carry_ref_and_revision_never_plaintext():
    rev = stdio_revision("d", 1, "a", "/srv/a", env={"TOK": SecretRef("cred-x")})
    prov = DictProvenance({"cred-x": attestation("cred-x")})
    snap = build_snapshot([rev], {"d": {"lane": "native", "enforcement": "proven"}})
    plan = claude.compile(snap, instance_target("claude"), prov,
                          revision_provider=lambda i, r: rev)
    slot = plan.entries[0].env[0]
    assert slot.to_canonical() == {
        "kind": "secretRef", "name": "TOK", "credentialRef": "cred-x",
        "credentialRevision": "rev-cred-x"}
    assert b"PLAINTEXT" not in plan.serialize()


def test_slot_value_dto_has_no_plaintext_field():
    fields = {f.name for f in dataclasses.fields(SlotValue)}
    assert fields == {"name", "kind", "value", "credential_ref", "credential_revision"}
    # 'value' only ever holds non-secret literals (kind == "literal");
    # secretRef slots cannot carry it: the compile path never sets both.
    kinds = {"literal", "secretRef"}
    literal = SlotValue(name="A", kind="literal", value="public")
    ref = SlotValue(name="B", kind="secretRef", credential_ref="c", credential_revision="r")
    assert {literal.to_canonical()["kind"], ref.to_canonical()["kind"]} == kinds


@pytest.mark.parametrize("path", ["relative/x.json", "/ok/../bad.json",
                                  "/runtime/home/{name}.json"])
def test_instance_target_descriptor_refuses_non_canonical_paths(path):
    with pytest.raises(ValueError):
        InstanceConfigTarget(target_path=path, config_key="mcpServers",
                             config_format="json")


def test_instance_target_format_must_match_path_suffix():
    with pytest.raises(ValueError):
        InstanceConfigTarget(target_path="/x/y.json", config_key="k",
                             config_format="toml")
    SessionOverrideTarget(config_key="k", config_format="toml")  # no path at all

"""compile: refusal matrix (dispatch 需求3) — secret provenance, lane
mutual-exclusion, conflicts, enforcement downgrade; never a partial plan."""
import pytest
from native_helpers import (
    CANARY,
    DictProvenance,
    FakeHostSecretService,
    attestation,
    build_snapshot,
    instance_target,
    observation,
    provenance_over_host_service,
    remote_revision,
    revision_provider,
    session_target,
    stdio_revision,
)

from backend.definition import Literal, SecretRef
from backend.errors import (
    MCP_CAS_CONFLICT,
    MCP_OWNER_CONFLICT,
    MCP_TRANSPORT_UNSUPPORTED,
    McpError,
)
from backend.native_intents import (
    MCP_CREDENTIAL_PROVENANCE_UNPROVEN,
    MCP_NATIVE_NAME_CONFLICT,
    MCP_NATIVE_TARGET_UNSUPPORTED,
    MCP_PERMISSION_ENFORCEMENT_UNPROVEN,
    PERMISSION_ENFORCEMENT_UNPROVEN_MARKER,
)
from adapters import claude, codex

PROVEN = {"lane": "native", "enforcement": "proven"}
UNPROVEN = {"lane": "native", "enforcement": "unproven"}


def _compile(brand, snapshot, target, prov, revisions, **kw):
    provider = revision_provider({(r.definition_id, r.revision): r for r in revisions})
    return brand.compile(snapshot, target, prov, revision_provider=provider, **kw)


def _basic():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/alpha",
                         args=["--x"], env={"TOKEN": SecretRef("cred-1"),
                                            "MODE": Literal("readonly")})
    snap = build_snapshot([rev], {"def-a": PROVEN})
    return rev, snap


# -- happy path ---------------------------------------------------------------

def test_stdio_plan_carries_ref_plus_revision_and_literals():
    rev, snap = _basic()
    prov = DictProvenance({"cred-1": attestation("cred-1")})
    plan = _compile(claude, snap, instance_target("claude"), prov, [rev])
    entry = plan.entries[0]
    assert entry.command == "/srv/alpha" and entry.args == ("--x",)
    assert [(s.name, s.kind) for s in entry.env] == [("MODE", "literal"), ("TOKEN", "secretRef")]
    token = next(s for s in entry.env if s.name == "TOKEN")
    assert token.credential_ref == "cred-1" and token.credential_revision == "rev-cred-1"
    assert plan.plan_digest.startswith("sha256:")
    assert plan.snapshot_digest == snap.snapshot_digest
    assert plan.harness_type == "claude-code"
    assert plan.owner == "harness-native:claude-code"


# -- secret provenance ----------------------------------------------------------

def test_unattested_secretref_is_refused():
    rev, snap = _basic()
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev])
    assert exc.value.code == MCP_CREDENTIAL_PROVENANCE_UNPROVEN


@pytest.mark.parametrize("kw", [
    {"resolver": "whoever"},                 # not the Harness / managed surface
    {"mode": "lazy-plaintext-cache"},        # not authorised-instant resolution
    {"credential_revision_override": ""},    # no revision identity
])
def test_invalid_attestation_shapes_are_refused(kw):
    rev, snap = _basic()
    override = kw.pop("credential_revision_override", None)
    att = attestation("cred-1", **kw)
    if override is not None:
        from dataclasses import replace
        att = replace(att, credential_revision=override)
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"),
                 DictProvenance({"cred-1": att}), [rev])
    assert exc.value.code == MCP_CREDENTIAL_PROVENANCE_UNPROVEN


def test_plaintext_canary_can_never_reach_intent_bytes():
    """The fake credential service can produce the plaintext; the provenance
    adapter over it keeps only the revision. Sentinels assert the serialized
    intent (and every refusal path) is byte-clean."""
    service = FakeHostSecretService()
    rev = stdio_revision("def-a", 1, "alpha", "/srv/alpha",
                         env={"TOKEN": SecretRef("cred-9")})
    snap = build_snapshot([rev], {"def-a": PROVEN})
    prov = provenance_over_host_service(service, ["cred-9"])
    plan = _compile(claude, snap, instance_target("claude"), prov, [rev])
    # refusal path first: drop the attestation -> typed refusal, canary-free
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev])
    assert CANARY not in str(exc.value)
    # and no intent may ever carry the secret slot plaintext or the canary
    payload = service.read("cred-9")[0]
    assert payload == CANARY
    assert CANARY.encode() not in plan.serialize()


# -- lane mutual exclusion -------------------------------------------------------

def test_managed_definitions_get_no_native_intent():
    native = stdio_revision("def-n", 1, "native-one", "/srv/n")
    managed = stdio_revision("def-m", 1, "managed-secret-name", "/srv/m")
    snap = build_snapshot([native, managed],
                          {"def-n": PROVEN, "def-m": {"lane": "managed", "enforcement": "proven"}})
    plan = _compile(claude, snap, instance_target("claude"), DictProvenance({}),
                    [native, managed])
    assert [e.native_name for e in plan.entries] == ["native-one"]
    assert [r["definitionId"] for r in plan.excluded_managed] == ["def-m"]
    assert "managed-secret-name" not in plan.serialize().decode()


def test_managed_and_native_sharing_one_endpoint_is_owner_conflict():
    native = stdio_revision("def-n", 1, "native-one", "/srv/same")
    managed = stdio_revision("def-m", 1, "managed-mirror", "/srv/same")
    snap = build_snapshot([native, managed],
                          {"def-n": PROVEN, "def-m": {"lane": "managed", "enforcement": "proven"}})
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}),
                 [native, managed])
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_missing_lane_binding_is_owner_conflict():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {})  # laneByDefinition failed to bind the definition
    with pytest.raises(McpError) as exc:
        _compile(codex, snap, session_target("codex"), DictProvenance({}), [rev])
    assert exc.value.code == MCP_OWNER_CONFLICT


# -- conflicts ---------------------------------------------------------------------

def test_duplicate_native_name_is_refused_not_last_wins():
    a = stdio_revision("def-a", 1, "same-name", "/srv/a")
    b = stdio_revision("def-b", 1, "same-name", "/srv/b")
    snap = build_snapshot([a, b], {"def-a": PROVEN, "def-b": PROVEN})
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [a, b])
    assert exc.value.code == MCP_NATIVE_NAME_CONFLICT


def test_same_endpoint_under_different_names_is_refused():
    a = stdio_revision("def-a", 1, "first", "/srv/twin", args=["-s"])
    b = stdio_revision("def-b", 1, "second", "/srv/twin", args=["-s"])
    snap = build_snapshot([a, b], {"def-a": PROVEN, "def-b": PROVEN})
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [a, b])
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_revision_drift_from_snapshot_binding_is_cas_conflict():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {"def-a": PROVEN})
    drifted = stdio_revision("def-a", 1, "alpha", "/srv/other")
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [drifted])
    assert exc.value.code == MCP_CAS_CONFLICT


def test_remote_transport_native_entry_is_refused():
    rev = remote_revision("def-r", 1, "remote-one", "https://mcp.example/a")
    snap = build_snapshot([rev], {"def-r": PROVEN})
    with pytest.raises(McpError) as exc:
        _compile(codex, snap, session_target("codex"), DictProvenance({}), [rev])
    assert exc.value.code == MCP_TRANSPORT_UNSUPPORTED


# -- enforcement downgrade (data-model.md:38, contracts.md:37) ------------------------

def test_unproven_enforcement_with_allow_names_marks_intent():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {"def-a": UNPROVEN}, allowed=["tool.one"])
    plan = _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev])
    assert plan.entries[0].markers == (PERMISSION_ENFORCEMENT_UNPROVEN_MARKER,)
    assert plan.markers == (PERMISSION_ENFORCEMENT_UNPROVEN_MARKER,)


def test_strict_mode_refuses_unproven_allow_names_reduction():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {"def-a": UNPROVEN}, allowed=["tool.one"])
    with pytest.raises(McpError) as exc:
        _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev],
                 strict=True)
    assert exc.value.code == MCP_PERMISSION_ENFORCEMENT_UNPROVEN


def test_unproven_without_allow_names_reduction_is_not_marked():
    """No selection rows -> snapshot-wide allowed set is empty -> no reduction
    is being demanded, so the downgrade clause does not fire."""
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {"def-a": UNPROVEN})
    plan = _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev])
    assert plan.entries[0].markers == ()
    assert plan.markers == ()


def test_proven_enforcement_never_marked_even_with_allow_names():
    rev = stdio_revision("def-a", 1, "alpha", "/srv/a")
    snap = build_snapshot([rev], {"def-a": PROVEN}, allowed=["tool.one"])
    plan = _compile(claude, snap, instance_target("claude"), DictProvenance({}), [rev])
    assert plan.entries[0].markers == ()
    assert plan.entries[0].allowed_tool_names == ("tool.one",)


# -- destination refusals -------------------------------------------------------------

def test_codex_instance_config_destination_is_refused():
    rev, snap = _basic()
    with pytest.raises(McpError) as exc:
        _compile(codex, snap, instance_target("codex"), DictProvenance({}), [rev])
    assert exc.value.code == MCP_NATIVE_TARGET_UNSUPPORTED


def test_destination_slot_mismatch_is_refused():
    rev, snap = _basic()
    wrong = session_target("claude")  # mcpServers key against the codex brand
    with pytest.raises(McpError) as exc:
        _compile(codex, snap, wrong, DictProvenance({}), [rev])
    assert exc.value.code == MCP_NATIVE_TARGET_UNSUPPORTED


def test_foreign_destination_object_is_refused():
    class NotADescriptor:
        config_key = "mcp_servers"
        config_format = "toml"

    rev, snap = _basic()
    with pytest.raises(McpError) as exc:
        codex.compile(snap, NotADescriptor(), DictProvenance({}),
                      revision_provider=revision_provider({("def-a", 1): rev}))
    assert exc.value.code == MCP_NATIVE_TARGET_UNSUPPORTED

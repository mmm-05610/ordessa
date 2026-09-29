"""assess three-valued verdicts per brand (dispatch 需求2).

L1 honesty line (t04-t05-research §3/§7, R-Q4-3): Codex and Claude Code both
sit at ``unknown`` on their structurally possible routes — no runtime
load/permission evidence exists, so no cell may report supported. Structural
infeasibility is typed unsupported with a reason.
"""
import pytest
from native_helpers import (
    FakeHarnessDecl,
    build_snapshot,
    claude_spec,
    codex_spec,
    pi_like_spec,
    remote_revision,
    revision_provider,
    stdio_revision,
)

from adapters import claude, codex

ALL_COMBOS = [
    (codex, codex_spec()),
    (claude, claude_spec()),
]


def test_assess_accepts_full_harness_declaration_wrapper():
    """HarnessDefinition-shaped input is unwrapped to .profile (real host
    type carries identity/profile; the thin C2 adapter maps it through)."""
    decl = FakeHarnessDecl(profile=codex_spec())
    assert codex.assess(decl) == codex.assess(codex_spec())


@pytest.mark.parametrize("brand,spec", ALL_COMBOS)
@pytest.mark.parametrize("destination_kind", [None, "instance-config", "session-override"])
def test_supported_is_unreachable_for_both_brands_at_l1(brand, spec, destination_kind):
    result = brand.assess(spec, destination_kind=destination_kind)
    if result.verdict == "supported":
        pytest.fail("L1 must never report supported: no runtime evidence exists")


def test_codex_session_override_is_unknown():
    result = codex.assess(codex_spec())
    assert result.verdict == "unknown"
    assert result.destination_kind == "session-override"
    assert result.reasons == ("codex-session-override-runtime-unproven",)


def test_codex_instance_config_is_typed_unsupported():
    """Projection route is structurally dead (read-only slot conflict, R-Q4-3)."""
    result = codex.assess(codex_spec(), destination_kind="instance-config")
    assert result.verdict == "unsupported"
    assert "codex-instance-config-slot-conflict" in result.reasons
    assert "instance-config-target-is-read-only-projection" in result.reasons


def test_claude_both_routes_unknown():
    file_route = claude.assess(claude_spec(), destination_kind="instance-config")
    session_route = claude.assess(claude_spec(), destination_kind="session-override")
    assert file_route.verdict == session_route.verdict == "unknown"
    assert file_route.reasons == ("claude-native-load-and-permission-unproven",)
    assert session_route.reasons == ("claude-native-load-and-permission-unproven",)


def test_no_mcp_target_declared_is_unsupported():
    """Pi-shaped registry entry: mcp slot named but no config slot -> the
    structural unsupported cell (schema.py:76-89 pairs target+key)."""
    spec = pi_like_spec()
    for brand in (codex, claude):
        result = brand.assess(spec)
        assert result.verdict == "unsupported"
        assert "no-mcp-config-slot" in result.reasons


def test_missing_mcp_slot_is_unsupported():
    spec = codex_spec(slots=("provider", "instruction"))
    result = codex.assess(spec, destination_kind="session-override")
    assert result.verdict == "unsupported"
    assert "missing-mcp-slot" in result.reasons


def test_slot_key_mismatch_is_unsupported():
    result = codex.assess(codex_spec(mcp_key="mcpServers",
                                     mcp_target="/runtime/home/.codex/settings.json"),
                          destination_kind="session-override")
    assert result.verdict == "unsupported"
    assert "slot-key-mismatch" in result.reasons


def test_remote_only_definitions_are_unsupported_for_rendering():
    rev = remote_revision("def-r", 1, "remote-one", "https://mcp.example/a")
    snap = build_snapshot([rev], {"def-r": {"lane": "native", "enforcement": "proven"}})
    provider = revision_provider({("def-r", 1): rev})
    for brand, spec in ALL_COMBOS:
        result = brand.assess(spec, snap, destination_kind="session-override",
                              revision_provider=provider)
        assert result.verdict == "unsupported"
        assert "remote-rendering-unsupported" in result.reasons


def test_managed_remote_definitions_do_not_make_the_brand_unsupported():
    rev = remote_revision("def-r", 1, "remote-one", "https://mcp.example/a")
    snap = build_snapshot([rev], {"def-r": {"lane": "managed", "enforcement": "proven"}})
    result = codex.assess(codex_spec(), snap, destination_kind="session-override",
                          revision_provider=revision_provider({("def-r", 1): rev}))
    assert result.verdict == "unknown"  # native lane unaffected; managed not rendered


def test_assess_rejects_broken_declaration_shape():
    result = codex.assess(object())
    assert result.verdict == "unsupported"
    assert result.reasons == ("declaration-shape-invalid",)

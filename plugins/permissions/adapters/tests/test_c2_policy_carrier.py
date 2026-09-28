"""A real C1 compiler projected through the public C2 carrier, without IO."""
from __future__ import annotations

from _permissions_adapters_helpers import make_ceiling, make_intent, unverified_ceiling
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, Installation, IntentSet,
    TargetDescriptor, TargetHandle, VerificationUnknown,
)
from ordessa_permissions_adapters import (
    ClaudeAdapter, CodexAdapter, PolicyCompileSnapshot,
    PolicyConfigurationAdapter,
)


def context(harness: str, version: tuple[int, int, int], target_id: str,
            allowed: tuple[tuple[str, ...], ...], entry: str) -> AdapterContext:
    target = TargetHandle(target_id, 1)
    return AdapterContext(
        (TargetDescriptor(target, "file", "json", "instance", allowed),),
        Installation(harness, version, (1, 0, 0), "controlled:installation"),
        entry, "instance", "controlled:capability")


def test_default_public_contribution_refuses_without_trusted_ceiling() -> None:
    adapter = PolicyConfigurationAdapter(ClaudeAdapter())
    ctx = context("claude-code", (0, 81, 2), ".claude/settings.json",
                  (("permissions", "ask"), ("permissions", "deny")),
                  "permissions.ask")
    desired = {"permissions.ask": ["Bash"]}
    assert adapter.assess(ctx, desired).status == "unknown"
    assert isinstance(adapter.compile(ctx, {}, desired), AdapterRefusal)
    assert isinstance(adapter.verify(ctx, desired), VerificationUnknown)


def test_controlled_claude_c1_compile_projects_only_owned_c2_fields() -> None:
    brand = ClaudeAdapter()
    snapshot = PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.81.2",
        intent=make_intent("claude-code", [
            {"key": "external_directory", "action": "allow"},
            {"key": "bash", "action": "deny"}]),
        ceiling=make_ceiling())
    compiled = brand.compilePolicy(snapshot)
    desired = compiled.as_record()
    adapter = PolicyConfigurationAdapter(brand, snapshot_resolver=lambda _ctx, _desired: snapshot)
    ctx = context("claude-code", (0, 81, 2), ".claude/settings.json",
                  (("permissions", "ask"), ("permissions", "deny")),
                  "permissions.ask")
    assert adapter.assess(ctx, desired) == Assessment("supported", "controlled:capability")
    result = adapter.compile(ctx, {}, desired)
    assert isinstance(result, IntentSet)
    assert {".".join(item.field_path.segments): item.typed_value for item in result.intents} == desired
    assert all(item.target.handle_id == ".claude/settings.json" for item in result.intents)
    assert all(item.source.item_id == adapter.descriptor.adapter_id for item in result.intents)
    assert isinstance(adapter.compile(ctx, {}, {"permissions.ask": ["Bash"]}), AdapterRefusal)


def test_controlled_codex_refuses_sandbox_field_outside_permissions_claim() -> None:
    brand = CodexAdapter()
    snapshot = PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0",
        intent=make_intent("codex", [{"key": "edit", "action": "deny"}]),
        ceiling=make_ceiling())
    desired = brand.compilePolicy(snapshot).as_record()
    adapter = PolicyConfigurationAdapter(brand, snapshot_resolver=lambda _ctx, _desired: snapshot)
    ctx = context("codex", (2, 0, 0), ".codex/config.toml",
                  (("sandbox_mode",), ("approval_policy",)), "approval_policy")
    result = adapter.compile(ctx, {}, desired)
    assert isinstance(result, AdapterRefusal)
    assert "lacks Permissions target authority" in result.reason


def test_untrusted_ceiling_and_missing_target_never_make_c2_intents() -> None:
    brand = ClaudeAdapter()
    intent = make_intent("claude-code", [
        {"key": "external_directory", "action": "allow"},
        {"key": "bash", "action": "deny"}])
    good = PolicyCompileSnapshot.of(harness_id="claude-code", native_version="0.81.2",
                                    intent=intent, ceiling=make_ceiling())
    bad = PolicyCompileSnapshot.of(harness_id="claude-code", native_version="0.81.2",
                                   intent=intent, ceiling=unverified_ceiling())
    desired = brand.compilePolicy(good).as_record()
    context_without_claim_target = context("claude-code", (0, 81, 2), "different-file",
                                           (("permissions", "ask"), ("permissions", "deny")),
                                           "permissions.ask")
    for snapshot in (good, bad):
        adapter = PolicyConfigurationAdapter(brand, snapshot_resolver=lambda _c, _d: snapshot)
        result = adapter.compile(context_without_claim_target, {}, desired)
        assert isinstance(result, AdapterRefusal)
    real_context = context("claude-code", (0, 81, 2), ".claude/settings.json",
                           (("permissions", "ask"), ("permissions", "deny")),
                           "permissions.ask")
    assert isinstance(PolicyConfigurationAdapter(
        brand, snapshot_resolver=lambda _c, _d: bad).compile(real_context, {}, desired),
        AdapterRefusal)


def test_trusted_snapshot_with_failed_c1_compiler_stays_unknown() -> None:
    brand = ClaudeAdapter()
    snapshot = PolicyCompileSnapshot.of(harness_id="claude-code", native_version="0.81.2",
                                    ceiling=make_ceiling())
    adapter = PolicyConfigurationAdapter(brand, snapshot_resolver=lambda _c, _d: snapshot)
    ctx = context("claude-code", (0, 81, 2), ".claude/settings.json",
                  (("permissions", "ask"), ("permissions", "deny")), "permissions.ask")
    def compiler_offline(_snapshot):
        raise RuntimeError("compiler unavailable")

    brand.compilePolicy = compiler_offline
    assert adapter.assess(ctx, {}) == Assessment(
        "unknown", reason="trusted policy authority or compiler unavailable")
    assert isinstance(adapter.compile(ctx, {}, {}), AdapterRefusal)

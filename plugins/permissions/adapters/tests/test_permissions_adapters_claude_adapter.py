"""T03 red/green: ClaudeAdapter.

Measured surface (posture_config.py): the only writable claude settings paths
are `permissions.ask` and `permissions.deny` (`_CLAUDE_WRITABLE_PATHS`, line
70); `permissions.allow` and `permissions.defaultMode` are deliberately
unwritable loosening knobs (comment at lines 65-69); the native tool-name map
is `_CLAUDE_SETTINGS_TOOLS` (lines 56-63) with no name for
`external_directory`. A claude intent that needs an unwritable knob is a typed
refusal, never a silent downgrade (FR-03) and never "written anyway".
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import PolicyRefusal
from ordessa_permissions_api.rules import TOOL_KEYS

from _permissions_adapters_helpers import ceiling_entry, make_ceiling, make_intent
from ordessa_permissions_adapters import (
    AdapterCode,
    ClaudeAdapter,
    CompiledIntentSet,
    CompileRefusal,
    PolicyCompileSnapshot,
    SupportEvidence,
    SupportOutcome,
)

HARNESS = "claude-code"


@pytest.fixture(scope="module")
def adapter() -> ClaudeAdapter:
    return ClaudeAdapter()


def snap(adapter, *, version="0.81.2", intent=None, ceiling=None):
    return adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id=HARNESS, native_version=version, intent=intent, ceiling=ceiling))


def test_supported_for_the_pinned_identity_version(adapter, pinned_versions) -> None:
    report = adapter.supports(SupportEvidence.of(
        harness_id=HARNESS, native_version=pinned_versions[HARNESS]))
    assert report.outcome is SupportOutcome.SUPPORTED
    assert report.evidence, "a supported answer must name its evidence"


def test_foreign_harness_is_unsupported(adapter) -> None:
    assert adapter.supports(SupportEvidence.of(
        harness_id="codex", native_version="2.0")).outcome is SupportOutcome.UNSUPPORTED


def test_version_outside_the_pinned_range_is_unknown_not_supported(adapter) -> None:
    report = adapter.supports(SupportEvidence.of(harness_id=HARNESS, native_version="9.9.9"))
    assert report.outcome is SupportOutcome.UNKNOWN


def test_ask_and_deny_map_to_native_names(adapter) -> None:
    intent = make_intent(HARNESS, [
        {"key": "external_directory", "action": "allow"},  # no knob; only allow skips
        {"key": "bash", "action": "deny"},
        {"key": "edit", "action": "ask"},
    ])
    result = snap(adapter, intent=intent)
    assert isinstance(result, CompiledIntentSet), getattr(result, "human_readable", result)
    fields = result.as_record()
    assert fields["permissions.deny"] == ["Bash"]
    assert {"Edit", "Write", "NotebookEdit"} <= set(fields["permissions.ask"])
    # unmapped keys default to ask, matching the measured posture default
    assert set(fields["permissions.ask"]) >= {"Read", "Glob", "Grep", "Task",
                                              "WebFetch", "WebSearch", "Skill"}


def test_allow_is_never_written(adapter) -> None:
    intent = make_intent(HARNESS, [{"key": "external_directory", "action": "allow"},
                                   {"key": "bash", "action": "allow"}])
    result = snap(adapter, intent=intent)
    assert isinstance(result, CompiledIntentSet)
    values = {v for vs in result.as_record().values() for v in vs}
    assert "Bash" not in values, "an allow intent must not pre-approve via any list"


def test_compiled_output_never_contains_a_loosening_field(adapter) -> None:
    # Sweep many inputs; every SUCCESSFUL claude output must be free of the
    # unwritable knobs - absence of the field, not a flag saying "not applied".
    all_one_action = lambda action: make_intent(  # noqa: E731
        HARNESS, [{"key": k, "action": action} for k in TOOL_KEYS if k != "external_directory"]
        + [{"key": "external_directory", "action": "allow"}])
    cases = [None, all_one_action("allow"), all_one_action("ask"), all_one_action("deny")]
    checked = 0
    for intent in cases:
        result = snap(adapter, intent=intent, ceiling=make_ceiling())
        if isinstance(result, CompiledIntentSet):
            checked += 1
            record = result.as_record()
            assert "permissions.allow" not in record
            assert "permissions.defaultMode" not in record
            flat = str(record)
            for banned in ("bypassPermissions", "acceptEdits", "defaultMode",
                           "danger-full-access"):
                assert banned not in flat
    assert checked >= 1, "the sweep must include at least one successful compile"


def test_unwritable_mode_request_refuses_typed(adapter) -> None:
    for mode in ("bypassPermissions", "auto", "plan", "acceptEdits", "default"):
        intent = make_intent(HARNESS, [], mode=mode)
        result = snap(adapter, intent=intent)
        assert isinstance(result, CompileRefusal)
        assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE
        assert mode in (result.target or "")


def test_external_directory_enforcement_is_unexpressible(adapter) -> None:
    for action in ("ask", "deny"):
        result = snap(adapter, intent=make_intent(
            HARNESS, [{"key": "external_directory", "action": action}]))
        assert isinstance(result, CompileRefusal)
        assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE


def test_ceiling_deny_beats_intent_allow_with_refusal(adapter) -> None:
    # 横向反例 (a): a user allow trying to widen an admin deny refuses, and no
    # successful compile of the admin deny alone ever carries an allow field.
    ceiling = make_ceiling(deny=["bash"])
    widened = snap(adapter, intent=make_intent(
        HARNESS, [{"key": "external_directory", "action": "allow"},
                  {"key": "bash", "action": "allow"}]), ceiling=ceiling)
    assert isinstance(widened, CompileRefusal)
    assert widened.code is AdapterCode.POLICY_CEILING_VIOLATION

    aligned = snap(adapter, intent=make_intent(
        HARNESS, [{"key": "external_directory", "action": "allow"},
                  {"key": "bash", "action": "deny"}]), ceiling=ceiling)
    assert isinstance(aligned, CompiledIntentSet)
    record = aligned.as_record()
    assert "Bash" in record["permissions.deny"]
    assert "permissions.allow" not in record


def test_target_scoped_ceiling_entry_is_unexpressible(adapter) -> None:
    ceiling = make_ceiling(deny=[ceiling_entry("bash", "git push:*")])
    result = snap(adapter, ceiling=ceiling)
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE


def test_unverified_ceiling_refuses(adapter) -> None:
    from _permissions_adapters_helpers import unverified_ceiling
    result = snap(adapter, ceiling=unverified_ceiling())
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_SCOPE_UNVERIFIED


def test_patterned_intent_rule_refuses(adapter) -> None:
    intent = make_intent(HARNESS, [{"key": "bash", "action": "deny",
                                    "pattern": "git push:*"}])
    result = snap(adapter, intent=intent)
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE


def test_foreign_intent_harness_refuses(adapter) -> None:
    result = snap(adapter, intent=make_intent("codex"))
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_SCOPE_UNVERIFIED


def test_no_silent_downgrade_every_failure_is_a_typed_refusal(adapter) -> None:
    # Every refused input returns a CompileRefusal object (code/source/remedy);
    # no input makes compilePolicy raise a bare exception or return a
    # watered-down IntentSet.
    bad_intents = [
        make_intent(HARNESS, [{"key": "external_directory", "action": "deny"}]),
        make_intent(HARNESS, [], mode="auto"),
        make_intent(HARNESS),  # default ask on external_directory -> refused
    ]
    for intent in bad_intents:
        try:
            result = snap(adapter, intent=intent)
        except PolicyRefusal as error:  # api-level construction refusals are fine
            assert error.code
            continue
        assert isinstance(result, CompileRefusal)
        assert result.source and result.remedy

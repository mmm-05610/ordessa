"""T03 red/green: CodexAdapter.

Measured surface (posture_config.py): the writable codex knobs are
`sandbox_mode` in (`read-only`, `workspace-write`) and `approval_policy` in
(`untrusted`, `on-request`) (`_WRITABLE_SANDBOX`/`_WRITABLE_APPROVAL`, line
79-80; strictness tables lines 77-78). `danger-full-access`, `never` and
`on-failure` are **not writable** - `on-failure` because it is
indistinguishable from `on-request` on both measured oracles (comment lines
74-76), the others because they are loosening values. Codex gates commands,
not per-tool actions, so a per-tool deny of bash/webfetch/skill/task refuses
(lines 213-218) instead of approximating.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api.rules import TOOL_KEYS

from _permissions_adapters_helpers import make_ceiling, make_intent
from ordessa_permissions_adapters import (
    AdapterCode,
    CodexAdapter,
    CompiledIntentSet,
    CompileRefusal,
    PolicyCompileSnapshot,
    SupportEvidence,
    SupportOutcome,
)

HARNESS = "codex"
WRITABLE_SANDBOX = ("read-only", "workspace-write")
WRITABLE_APPROVAL = ("untrusted", "on-request")


@pytest.fixture(scope="module")
def adapter() -> CodexAdapter:
    return CodexAdapter()


def snap(adapter, *, version="2.0", intent=None, ceiling=None):
    return adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id=HARNESS, native_version=version, intent=intent, ceiling=ceiling))


def test_supported_for_the_pinned_identity_version(adapter, pinned_versions) -> None:
    report = adapter.supports(SupportEvidence.of(
        harness_id=HARNESS, native_version=pinned_versions[HARNESS]))
    assert report.outcome is SupportOutcome.SUPPORTED
    assert report.evidence


def test_write_denial_compiles_to_read_only(adapter) -> None:
    for key in ("edit", "external_directory"):
        result = snap(adapter, intent=make_intent(
            HARNESS, [{"key": k, "action": "allow"} for k in TOOL_KEYS if k not in ("read", key)]
            + [{"key": "read", "action": "ask"}, {"key": key, "action": "deny"}]))
        assert isinstance(result, CompiledIntentSet), getattr(result, "human_readable", result)
        assert result.as_record()["sandbox_mode"] == "read-only"


def test_bash_ask_compiles_to_untrusted_otherwise_on_request(adapter) -> None:
    # Measured rule: asking on bash is `untrusted`; asking on other gated keys
    # is `on-request` (posture_config.py:222-227).
    result = snap(adapter)  # all keys default ask, incl. bash
    assert isinstance(result, CompiledIntentSet)
    assert result.as_record()["approval_policy"] == "untrusted"

    result = snap(adapter, intent=make_intent(
        HARNESS, [{"key": "bash", "action": "allow"}]))
    assert isinstance(result, CompiledIntentSet)
    assert result.as_record()["approval_policy"] == "on-request"


def test_per_tool_denies_outside_writes_are_unexpressible(adapter) -> None:
    for key in ("bash", "webfetch", "skill", "task"):
        result = snap(adapter, intent=make_intent(
            HARNESS, [{"key": key, "action": "deny"}]))
        assert isinstance(result, CompileRefusal)
        assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE
        assert key in (result.target or "")


def test_loosening_modes_refuse(adapter) -> None:
    # `never` (no approvals) and `on-failure` (unobservable difference from
    # on-request) are declared codex names but not writable values.
    for mode in ("never", "on-failure"):
        result = snap(adapter, intent=make_intent(HARNESS, [], mode=mode))
        assert isinstance(result, CompileRefusal)
        assert result.code in {AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                               AdapterCode.POLICY_CEILING_VIOLATION}
    # `untrusted` and `on-request` are writable; asking for them succeeds.
    for mode in ("untrusted", "on-request"):
        result = snap(adapter, intent=make_intent(HARNESS, [], mode=mode))
        assert not (isinstance(result, CompileRefusal)
                    and result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE)


def test_managed_danger_full_access_under_ceiling_refuses(adapter) -> None:
    # 横向反例 (d): the intent asks for the posture that only
    # `danger-full-access` + `never` could give (full access, no approvals)
    # while the managed ceiling bounds exposure - compile refuses and never
    # attempts a bypass value.
    ceiling = make_ceiling(deny=["edit"], approval=["bash"], exposure="exec")
    intent = make_intent(HARNESS, [{"key": "edit", "action": "allow"},
                                   {"key": "bash", "action": "allow"}])
    result = snap(adapter, intent=intent, ceiling=ceiling)
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_CEILING_VIOLATION

    # A ceiling *below* exec exposure with an intent allowing bash also refuses.
    strict = make_ceiling(exposure="read")
    result = snap(adapter, intent=make_intent(HARNESS, [{"key": "bash", "action": "allow"}]),
                  ceiling=strict)
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_CEILING_VIOLATION


def test_successes_only_ever_carry_writable_values(adapter) -> None:
    intents = [None]
    for action in ("allow", "ask", "deny"):
        intents.append(make_intent(HARNESS, [{"key": k, "action": action}
                                              for k in TOOL_KEYS if k not in ("edit", "external_directory")]
                                   + [{"key": "edit", "action": "deny"},
                                      {"key": "external_directory", "action": "deny"}]))
    seen = 0
    for intent in intents:
        result = snap(adapter, intent=intent, ceiling=make_ceiling())
        if isinstance(result, CompiledIntentSet):
            seen += 1
            record = result.as_record()
            if "sandbox_mode" in record:
                assert record["sandbox_mode"] in WRITABLE_SANDBOX
            if "approval_policy" in record:
                assert record["approval_policy"] in WRITABLE_APPROVAL
    assert seen >= 1
    # The loosening values are outside the adapter's writable vocabulary at
    # all levels (measured: posture_config.py:79-80).
    assert "danger-full-access" not in adapter.writable_sandbox_values()
    assert "never" not in adapter.writable_approval_values()
    assert "on-failure" not in adapter.writable_approval_values()


def test_never_emits_a_missing_generation_identity(adapter) -> None:
    # version outside range refuses rather than compiling blind
    result = snap(adapter, version="999.0")
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_SCOPE_UNVERIFIED

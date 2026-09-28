"""T05 — Codex native-sandbox adapter rules, all measured in-tree.

Evidence (file:line):
- writable sandbox values = ``_WRITABLE_SANDBOX`` (read-only / workspace-write),
  ``posture_config.py:79``; ``danger-full-access`` is in the native vocabulary
  (proven by the committed Codex schema ``SandboxMode`` enum, see test below)
  but is never writable — under a ceiling that forbids loosening it refuses, it
  does not attempt a bypass (harness-adapters.md Codex row).
- strictness table ``posture_config.py:77``; the profile ``Sandbox`` field the
  bridge carries: ``pkg/codexacp/runtime.go:26-27,116-117``.
"""
from __future__ import annotations

from dataclasses import replace

from _sandbox_adapters_helpers import (
    CODEX_TARGET,
    authorized_facts,
    codex_config,
    codex_intent,
    enforce_ceiling,
    permissive_ceiling,
    pin,
    platform_facts,
    target_handle,
)

from ordessa_harness_api import Assessment, Match, Mismatch, VerificationUnknown
from ordessa_sandbox_api import NetworkMode, SandboxApplyScope, SandboxErrorCode, \
    ToolCategory
from ordessa_sandbox_adapters import (
    CodexSandboxAdapter,
    CompileRefusal,
    CompiledIntent,
    sandbox_code_of,
)


def test_committed_codex_schema_backs_the_mode_vocabulary():
    # the generated, version-matched schema — not the docs — is the source of
    # accepted sandbox_mode values (task rule).
    from _sandbox_adapters_helpers import codex_schema_sandbox_modes
    modes = codex_schema_sandbox_modes()
    assert set(modes) == {"read-only", "workspace-write", "danger-full-access"}


def test_workspace_write_compiles_and_owns_sandbox_mode():
    adapter = CodexSandboxAdapter()
    result = adapter.compile(codex_intent(), target_handle(CODEX_TARGET), (permissive_ceiling(),))
    assert isinstance(result, CompiledIntent)
    assert result.outcome == "intent-set"
    paths = {f.field_path for f in result.intents}
    assert "sandbox_mode" in paths
    # the adapter only ever owns its declared native fields
    assert paths <= set(adapter.native_field_claims())
    mode = next(f for f in result.intents if f.field_path == "sandbox_mode")
    assert mode.value == "workspace-write"


def test_danger_full_access_refused_under_permissive_ceiling_no_bypass():
    adapter = CodexSandboxAdapter()
    intent = codex_intent(config=codex_config(sandbox_mode="danger-full-access"))
    result = adapter.compile(intent, target_handle(CODEX_TARGET), (permissive_ceiling(),))
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_NATIVE_UNSUPPORTED"
    # no bypass: nothing was emitted to be applied
    assert result.emitted_intents == ()


def test_admin_enforced_sandbox_cannot_be_disabled_by_profile():
    adapter = CodexSandboxAdapter()
    intent = codex_intent(config=codex_config(sandbox_mode="danger-full-access"))
    result = adapter.compile(intent, target_handle(CODEX_TARGET),
                             (enforce_ceiling(minimum_strictness=3),))
    assert isinstance(result, CompileRefusal)
    # distinct code: an enforced sandbox cannot be switched off
    assert result.code.value == "SANDBOX_CONFIG_CONFLICT"


def test_inexpressible_coverage_refused_no_approximation():
    from ordessa_sandbox_api import SandboxCeiling
    adapter = CodexSandboxAdapter()
    ceiling = SandboxCeiling(brand="codex", enforce=True,
                             required_coverage=frozenset({ToolCategory.MCP}),
                             source="signed-admin")
    result = adapter.compile(codex_intent(), target_handle(CODEX_TARGET), (ceiling,))
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_NATIVE_UNSUPPORTED"


def test_ceiling_forbidding_network_exposure_refused():
    adapter = CodexSandboxAdapter()
    intent = codex_intent(network=NetworkMode.ALLOWED,
                          config=codex_config(network_access=True))
    result = adapter.compile(intent, target_handle(CODEX_TARGET),
                             (replace(permissive_ceiling(), network_allowed_max=False),))
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_CONFIG_CONFLICT"
    # positive counterpart: network disabled compiles
    ok = adapter.compile(codex_intent(), target_handle(CODEX_TARGET), (permissive_ceiling(),))
    assert isinstance(ok, CompiledIntent)


def test_assess_in_range_supported_out_of_range_unknown(pinned):
    adapter = CodexSandboxAdapter()
    good = adapter.assess(pin("codex", pinned["codex"]), platform_facts(),
                          authorized_facts())
    assert isinstance(good, Assessment)
    assert good.status == "supported"
    assert good.evidence_ref  # a green answer names its evidence
    bad = adapter.assess(pin("codex", "9.9"), platform_facts(), authorized_facts())
    assert bad.status == "unknown"
    assert sandbox_code_of(bad.reason) is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_verify_answers_with_the_platform_verification_types():
    from _sandbox_adapters_helpers import effect_observation
    adapter = CodexSandboxAdapter()
    assert isinstance(adapter.verify(effect_observation("verified")), Match)
    unknown = adapter.verify(effect_observation("unknown"))
    assert isinstance(unknown, VerificationUnknown)
    # a proven negative is still not a Match and keeps its own stable code
    unsupported = adapter.verify(effect_observation("unsupported"))
    assert isinstance(unsupported, VerificationUnknown)
    assert sandbox_code_of(unsupported.reason) is \
        SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    assert sandbox_code_of(unsupported.reason) is not \
        sandbox_code_of(unknown.reason)
    assert not isinstance(unknown, Mismatch)


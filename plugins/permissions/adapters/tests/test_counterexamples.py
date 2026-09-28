"""T03 red/green: the横向反例 this level can actually prove.

From harness-adapters.md §"至少六个横向反例" - the six cross-brand negative
cases, restricted honestly to what per-brand config-time adapters can observe
before any tool side effect happens (the runtime halves of these cases belong
to G1/G2 and T07):

(a) a user `allow` trying to widen an admin `deny` refuses, and the compiled
    brand output never even carries the loosening field;
(b) Pi without extension evidence is `unsupported` and emits no compiled
    intent;
(c) a Claude request that needs a non-writable knob refuses typed;
(d) a Codex managed posture that only `danger-full-access` could serve, under
    a ceiling that forbids it, refuses - no bypass attempt;
(e) a stale/mismatched observation is never `Confirmed`;
(f) overlapping adapter ranges refuse at composition time.

All refusals here are observable **before** any effect: they are return
values of a pure compile, not side effects.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import RuleAction

from _permissions_adapters_helpers import make_ceiling, make_intent
from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, ValueSchema, VersionRange)
from ordessa_permissions_adapters import (
    AdapterCode,
    ClaudeAdapter,
    CodexAdapter,
    CompiledIntentSet,
    CompileRefusal,
    PiAdapter,
    PolicyCompileSnapshot,
    PolicyConfigurationAdapter,
    SupportEvidence,
    SupportOutcome,
    VerifyOutcome,
    PolicyBinding,
    PolicyObservation,
    configuration_descriptor,
)
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, HarnessContributionError, HarnessContributionRegistry,
    POINT_API_VERSION)
from server_plugin_api import Contribution, ContributionBatch, stage_contributions


def test_a_user_allow_cannot_widen_an_admin_deny_in_compiled_output() -> None:
    ceiling = make_ceiling(deny=["bash"])
    adapter = ClaudeAdapter()
    widened = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.81.2",
        intent=make_intent("claude-code", [
            {"key": "external_directory", "action": "allow"},
            {"key": "bash", "action": "allow"}]),
        ceiling=ceiling))
    assert isinstance(widened, CompileRefusal)
    assert widened.code is AdapterCode.POLICY_CEILING_VIOLATION
    # and when it does compile, the loosening field is absent entirely -
    # asserted by absence, not by a flag.
    ok = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.81.2",
        intent=make_intent("claude-code", [
            {"key": "external_directory", "action": "allow"},
            {"key": "bash", "action": "deny"}]),
        ceiling=ceiling))
    assert isinstance(ok, CompiledIntentSet)
    record = ok.as_record()
    assert "permissions.allow" not in record
    assert all("allow" not in key for key in record)
    # same rule on codex: an intent allow under an admin deny refuses too
    codex = CodexAdapter().compilePolicy(PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0",
        intent=make_intent("codex", [{"key": "edit", "action": "allow"}]),
        ceiling=make_ceiling(deny=["edit"])))
    assert isinstance(codex, CompileRefusal)
    assert codex.code is AdapterCode.POLICY_CEILING_VIOLATION


def test_b_pi_without_extension_evidence_refuses_and_emits_nothing() -> None:
    adapter = PiAdapter()
    assert adapter.supports(SupportEvidence.of(harness_id="pi",
                                               native_version="2.0")).outcome \
        is SupportOutcome.UNSUPPORTED
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="pi", native_version="2.0", ceiling=make_ceiling(deny=["bash"])))
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_ADAPTER_MISSING
    assert not isinstance(result, CompiledIntentSet)


def test_c_claude_non_writable_knob_refuses() -> None:
    adapter = ClaudeAdapter()
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.81.2",
        intent=make_intent("claude-code", [], mode="bypassPermissions")))
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE
    # the refusal names what was asked and why - nothing was written anyway
    assert "bypassPermissions" in (result.target or "")
    assert result.remedy


def test_d_codex_managed_danger_full_access_under_ceiling_refuses() -> None:
    # the only posture that satisfies "everything allowed, never ask" needs
    # danger-full-access + never, both outside the writable vocabulary
    adapter = CodexAdapter()
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0",
        intent=make_intent("codex", [{"key": "bash", "action": "allow"}]),
        ceiling=make_ceiling(exposure="write")))
    assert isinstance(result, CompileRefusal)
    assert result.code is AdapterCode.POLICY_CEILING_VIOLATION
    assert "danger-full-access" not in str(vars(result))


def test_e_stale_observation_is_never_confirmed() -> None:
    adapter = CodexAdapter()
    observation = PolicyObservation.of(
        harness_id="codex",
        compile_binding=PolicyBinding(native_version="2.0", runtime_generation="gen-a"),
        observed_binding=PolicyBinding(native_version="2.0", runtime_generation="gen-b"),
        expected_fields={"approval_policy": "untrusted"},
        observed_values={"approval_policy": "untrusted"},
        receipt_confirmed=True, receipt_source="config-readback")
    assert adapter.verifyPolicy(observation).outcome is VerifyOutcome.MISMATCH


def test_f_overlapping_ranges_refuse_at_composition_time() -> None:
    # refusal authority: the platform's point-conflict registry, not a
    # private second admission path; nothing is admitted and nothing of the
    # first claim is replaced (no last-wins).
    registry = HarnessContributionRegistry()
    first = configuration_descriptor(CodexAdapter())
    overlapping = ConfigurationAdapterDescriptor(
        "x2", "v1", "permissions.policy-adapters", "v1", "codex",
        VersionRange(first.native_versions.minimum, (3, 5, 0)),
        # mirror the live declared adapter pin (contribution.py
        # _ADAPTER_VERSION, backed by pyproject.toml:7): the counterexample
        # must actually overlap, whatever exact pin the facet declares.
        first.adapter_versions, first.entries,
        ValueSchema("object"), first.claims)
    batch = ContributionBatch(
        (Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                      PolicyConfigurationAdapter(CodexAdapter(), first)),
         Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                      PolicyConfigurationAdapter(CodexAdapter(), overlapping))),
        open_points=frozenset({CONFIGURATION_POINT}))
    with pytest.raises(HarnessContributionError) as error:
        stage_contributions(registry.configuration_handler, "owner.a", batch)
    assert "verlap" in str(error.value)
    assert registry.configuration_descriptors() == ()


def test_all_refusals_observable_before_any_effect() -> None:
    # compile results are pure values; RuleAction remains the shared language
    assert {a.value for a in RuleAction} == {"allow", "ask", "deny"}
    refusal = ClaudeAdapter().compilePolicy(PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.0.0"))
    assert isinstance(refusal, CompileRefusal)  # unevidenced pin: refuse, don't guess

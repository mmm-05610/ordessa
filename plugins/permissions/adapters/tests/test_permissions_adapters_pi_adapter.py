"""T03 red/green: PiAdapter.

Measured facts: Pi's permission gate is an **example extension**
(`tool_call`/permission-gate), not a built-in hosted rule
(docs/design/safety-controls/harness-adapters.md §matrix row "Pi";
research-and-reuse.md §官方机制与风险). In this tree `harnesses.toml` does NOT
declare a `permissions` capability for pi (pi `capabilities` line 388), and no
extension load is evidenced anywhere. Therefore: with no evidence of the
loaded extension, `supports` answers `unsupported` and every
enforcement-requiring compile is a typed refusal - explicitly never the
fallback "bare Pi is fine". Even a vacuous (all-allow) policy refuses without
extension evidence: absence of evidence is not permission.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api.rules import TOOL_KEYS

from _permissions_adapters_helpers import full_allow_intent, make_ceiling, make_intent
from ordessa_permissions_adapters import (
    AdapterCode,
    CompiledIntentSet,
    CompileRefusal,
    PiAdapter,
    PiToolCallGateEvidence,
    PolicyCompileSnapshot,
    SupportEvidence,
    SupportOutcome,
)

HARNESS = "pi"


@pytest.fixture(scope="module")
def adapter() -> PiAdapter:
    return PiAdapter()


def gate(keys=TOOL_KEYS, *, version="2.0", loaded=True, extension_id="ext:test-permission-gate",
         generation="gen-pi-1") -> PiToolCallGateEvidence:
    return PiToolCallGateEvidence.of(extension_id=extension_id, loaded=loaded,
                                     interceptable_tool_keys=keys,
                                     observed_native_version=version, generation=generation)


def snap(adapter, *, version="2.0", intent=None, ceiling=None, gate_evidence=None):
    evidence = None
    if gate_evidence is not None:
        evidence = SupportEvidence.of(harness_id=HARNESS, native_version=version,
                                      pi_tool_call_gate=gate_evidence)
    return adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id=HARNESS, native_version=version, intent=intent, ceiling=ceiling,
        evidence=evidence))


def test_no_extension_evidence_is_unsupported(adapter) -> None:
    # 横向反例 (b), part 1.
    report = adapter.supports(SupportEvidence.of(harness_id=HARNESS, native_version="2.0"))
    assert report.outcome is SupportOutcome.UNSUPPORTED


def test_failed_or_absent_gate_refuses_every_compile(adapter) -> None:
    # 横向反例 (b), part 2: no compiled intent is emitted without evidence -
    # even for a policy that names nothing, and even when the extension is
    # present but failed to load.
    for gate_evidence in (None, gate(loaded=False)):
        for intent in (None, make_intent(HARNESS), full_allow_intent(HARNESS)):
            result = snap(adapter, intent=intent, ceiling=make_ceiling(),
                          gate_evidence=gate_evidence)
            assert isinstance(result, CompileRefusal), (gate_evidence, intent)
            assert result.code is AdapterCode.POLICY_ADAPTER_MISSING


def test_extension_must_stay_out_of_the_capability_claim(adapter) -> None:
    # `attach`/permissions evidence in-tree is only the Go bridge channel
    # (pkg/piacp/embedded.go RespondPermission); a bridge binary alone is not
    # extension evidence, so a bare version match never flips to supported.
    assert adapter.supports(None).outcome is not SupportOutcome.SUPPORTED
    assert adapter.supports(SupportEvidence.of(
        harness_id=HARNESS, native_version="2.0")).outcome is SupportOutcome.UNSUPPORTED


def test_gate_covering_all_keys_compiles_with_evidence(adapter) -> None:
    intent = make_intent(HARNESS, [{"key": "bash", "action": "deny"}])
    result = snap(adapter, intent=intent, ceiling=make_ceiling(), gate_evidence=gate())
    assert isinstance(result, CompiledIntentSet), getattr(result, "human_readable", result)
    record = result.as_record()
    assert record["toolCallGate.deny"] == ["bash"]
    assert "read" in record["toolCallGate.ask"]
    # The compiled set names the extension it assumed, so a verify or audit
    # can tell this is extension-backed, not built-in.
    assert result.notes and any("ext:test-permission-gate" in note for note in result.notes)


def test_uncovered_tool_refuses(adapter) -> None:
    result = snap(adapter, intent=make_intent(HARNESS, [{"key": "bash", "action": "deny"}]),
                  ceiling=make_ceiling(), gate_evidence=gate(keys=("edit",)))
    assert isinstance(result, CompileRefusal)
    assert result.code in {AdapterCode.POLICY_SCOPE_UNVERIFIED,
                           AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE}


def test_generation_mismatch_between_gate_and_snapshot_refuses(adapter) -> None:
    # The gate observation must belong to the same native generation the
    # policy is compiled for; a foreign generation is never a basis.
    evidence = SupportEvidence.of(harness_id=HARNESS, native_version="2.0",
                                  pi_tool_call_gate=gate())
    snapshot = PolicyCompileSnapshot.of(harness_id=HARNESS, native_version="2.0",
                                        ceiling=make_ceiling(), evidence=evidence)
    ok = adapter.compilePolicy(snapshot)
    assert isinstance(ok, CompiledIntentSet)
    stale = PolicyCompileSnapshot.of(harness_id=HARNESS, native_version="2.1",
                                     ceiling=make_ceiling(), evidence=evidence)
    result = adapter.compilePolicy(stale)
    assert isinstance(result, CompileRefusal)


def test_gate_evidence_shape_is_validated(adapter) -> None:
    with pytest.raises(Exception):
        PiToolCallGateEvidence.of(extension_id="", loaded=True,
                                  interceptable_tool_keys=TOOL_KEYS,
                                  observed_native_version="2.0", generation="g")
    with pytest.raises(Exception):
        PiToolCallGateEvidence.of(extension_id="ext:x", loaded=True,
                                  interceptable_tool_keys=("not-a-tool-key",),
                                  observed_native_version="2.0", generation="g")


def test_pi_declares_no_native_modes_so_mode_requests_refuse(adapter) -> None:
    # BRAND_NATIVE_MODES["pi"] is empty (brand.py line 28): a pi intent cannot
    # even be constructed with a brand mode; the refusal is structural.
    from ordessa_permissions_api import PolicyRefusal
    with pytest.raises(PolicyRefusal):
        make_intent(HARNESS, [], mode="auto")

"""PiAdapter - Pi permission policy adapter (T03).

Pi has no built-in hosted permission rule: the official `tool_call` gate is
an **example extension** (permission-gate), and the sandbox situation is the
same story (docs/design/safety-controls/harness-adapters.md row "Pi";
research-and-reuse.md §官方机制与风险). In this tree the evidence is thin on
purpose:

- `plugins/harness/.../harnesses.toml:388` - the pi family does **not** declare
  the `permissions` capability;
- `plugins/harness/adapters/acp-adapter/pkg/piacp/embedded.go:39-66,199` - the
  Go bridge has the ACP `session/request_permission` request/response shape
  (S-level channel evidence), but there is no server-side handler and no proof
  any extension is loaded (baseline-t00.md: only codex declares the capability
  at harnesses.toml:13).

Therefore: without a named, loaded tool_call-gate extension observation,
`supports` answers `unsupported` and every `compilePolicy` is a typed
`POLICY_ADAPTER_MISSING` refusal - explicitly never the fallback "bare Pi is
fine", not even for an all-allow policy (a vacuous compile would certify the
absence of enforcement). With extension evidence, only the tool keys the
observation names as interceptable may be enforced; everything else refuses.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_permissions_api import RuleAction

from .base import BaseBrandAdapter
from .codes import AdapterCode
from .dto import PiToolCallGateEvidence, PolicyCompileSnapshot, SupportEvidence
from .ranges import NativeVersionRange
from .results import (
    CompileRefusal,
    CompileResult,
    CompiledIntentSet,
    SupportReport,
)

__all__ = ["PiAdapter"]


class PiAdapter(BaseBrandAdapter):
    adapter_id = "permissions.policy-adapter.pi"
    harness_id = "pi"
    version_range = NativeVersionRange(minimum="2.0", maximum="3.0")

    def expressible_actions(self) -> Mapping[str, Any]:
        # nothing is expressible *built-in*; expressibility exists only per
        # extension observation, which the compile consults live.
        return {"read": frozenset(), "edit": frozenset(), "bash": frozenset(),
                "task": frozenset(), "webfetch": frozenset(), "skill": frozenset(),
                "external_directory": frozenset()}

    def _supports_extra(self, evidence: SupportEvidence) -> SupportReport:
        gate = evidence.pi_tool_call_gate
        if gate is None:
            return SupportReport.unsupported(
                code=AdapterCode.POLICY_ADAPTER_MISSING,
                reason="no tool_call gate extension observation exists; the Pi "
                       "gate is an example extension, not built-in, and bare Pi "
                       "is never a permission authority")
        if not gate.loaded:
            return SupportReport.unsupported(
                code=AdapterCode.POLICY_ADAPTER_MISSING,
                reason=f"extension {gate.extension_id} was observed but not "
                       "loaded; enforcement-requiring policies refuse")
        if gate.observed_native_version != evidence.native_version:
            return SupportReport.unknown(
                code=AdapterCode.POLICY_SCOPE_UNVERIFIED,
                reason="the gate observation belongs to a different native pin")
        return SupportReport.supported(
            evidence="harnesses.toml:377-388 pin note + caller-provided loaded "
                     "tool_call gate extension observation")

    def _assemble(self, actions: Mapping[str, RuleAction],
                  snapshot: PolicyCompileSnapshot, mode: Any) -> CompileResult:
        gate = None if snapshot.evidence is None else snapshot.evidence.pi_tool_call_gate
        if gate is None or not gate.loaded or \
                gate.observed_native_version != snapshot.native_version:
            # 反例 (b): no compiled intent at all without extension evidence -
            # including a vacuous all-allow policy, which would otherwise
            # certify "bare Pi is fine".
            return CompileRefusal(
                AdapterCode.POLICY_ADAPTER_MISSING,
                source=f"{self.adapter_id}.compilePolicy",
                target="no loaded Pi tool_call gate extension is evidenced for "
                       "this pin; refusing instead of falling back to bare Pi")
        enforced = {key: action for key, action in actions.items()
                    if action is not RuleAction.ALLOW}
        uncovered = sorted(key for key in enforced if key not in gate.interceptable_tool_keys)
        if uncovered:
            return CompileRefusal(
                AdapterCode.POLICY_SCOPE_UNVERIFIED,
                source=f"{self.adapter_id}.compilePolicy",
                target="the observed gate does not name these tools as "
                       f"interceptable: {','.join(uncovered)}")
        fields: dict[str, Any] = {"toolCallGate.extensionId": gate.extension_id}
        ask = sorted(key for key, action in enforced.items() if action is RuleAction.ASK)
        deny = sorted(key for key, action in enforced.items() if action is RuleAction.DENY)
        if ask:
            fields["toolCallGate.ask"] = tuple(ask)
        if deny:
            fields["toolCallGate.deny"] = tuple(deny)
        notes = (f"extension-backed only: {gate.extension_id} "
                 f"observed at {gate.observed_native_version}",
                 "the gate is a Pi example extension, not built-in enforcement")
        return CompiledIntentSet(harness_id=self.harness_id, fields=fields,
                                 notes=notes)

    def verifiable_fields(self) -> frozenset[str]:
        # No in-tree oracle proves a Pi gate honoured a compiled rule (no L2
        # evidence for the extension's receipt shape), so verification can
        # never report Confirmed - it distinguishes Mismatch from Unknown only.
        return frozenset()

"""ClaudeSandboxAdapter — claude-code native-sandbox configuration adapter (T05).

Claude's documented native sandbox scopes the **Bash / PowerShell / Monitor**
subprocess kinds only — it never covers Read/Edit/MCP tools (harness-adapters.md
Claude row; API ``ClaudeSandboxConfig.COVERABLE == {BASH}``). So:

* compiling a ``requiredCoverage`` that includes read/edit/MCP/network returns
  ``SANDBOX_COVERAGE_UNPROVEN`` and the adapter must NOT claim coverage=all. The
  compiled output carries only the three toggles — broader coverage is
  *absent*, not asserted off by a flag (the 横向反例 "Bash 却宣称 MCP 隔离");
* platform: Linux/WSL2 bubblewrap + macOS Seatbelt supported, native Windows
  unsupported (``SANDBOX_PLATFORM_UNSUPPORTED``), an unmeasured OS is `unknown`
  (``SANDBOX_EFFECT_UNKNOWN``) — the two are never merged (contracts.md §C4).

Field names are namespaced away from the Permissions claude projection
(``permissions.ask``/``permissions.deny``) so the two owners pre-allocate
disjoint native paths (§C2 conflict gate).
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_harness_api.contracts import Assessment
from ordessa_harness_api.intents import TargetHandle
from ordessa_sandbox_api import (
    ClaudeSandboxConfig,
    NativeSandboxIntent,
    PlatformResult,
    SandboxErrorCode,
    ToolCategory,
    assess_platform,
)

from .base import BaseSandboxAdapter
from .dto import AdapterPin, AuthorizedFacts
from .ranges import NativeVersionRange
from .results import CompileRefusal, CompileResult, assessment_supported, \
    assessment_unknown, assessment_unsupported
from .seam import CompiledFieldIntent, KIND_SET_FIELD

__all__ = ["ClaudeSandboxAdapter"]

#: the three sandbox toggles this adapter may ever write
_TOGGLES = (("enable_bash_sandbox", "bashSandbox"),
            ("enable_power_shell_sandbox", "powerShellSandbox"),
            ("enable_monitor_sandbox", "monitorSandbox"))


class ClaudeSandboxAdapter(BaseSandboxAdapter):
    adapter_id = "sandbox.native-config.claude-code"
    harness_id = "claude-code"
    brand = "claude-code"
    version_range = NativeVersionRange(minimum="0.81.2", maximum="0.82.0")
    coverable = frozenset({ToolCategory.BASH})
    capability_evidence = (
        "harness-adapters.md Claude row (documented Bash/PowerShell/Monitor "
        "scope; Linux/WSL2 bwrap, macOS Seatbelt); API ClaudeSandboxConfig "
        "COVERABLE == {BASH}")

    def native_field_claims(self) -> tuple[str, ...]:
        return tuple(path for _attr, path in _TOGGLES)

    def config_from_payload(self, payload: Mapping[str, Any]) -> ClaudeSandboxConfig:
        """The closed point payload -> the domain claude toggles.

        The payload schema is the platform's own closed object, so a
        coverage=all style key never reaches here.
        """
        return ClaudeSandboxConfig(**{
            attr: bool(payload.get(path, False)) for attr, path in _TOGGLES})

    def _assess_brand(self, pin: AdapterPin, platform_facts,
                      authorized_facts: AuthorizedFacts) -> Assessment:
        assessment = assess_platform(platform_facts.os_name, platform_facts.os_version,
                                     brand=self.brand)
        if assessment.result is PlatformResult.SUPPORTED:
            return assessment_supported(
                evidence=f"{self.capability_evidence}; mechanism={assessment.mechanism!r}",
                reason=f"documented native mechanism on {assessment.os_name}")
        if assessment.result is PlatformResult.UNSUPPORTED:
            return assessment_unsupported(
                SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED, assessment.reason)
        return assessment_unknown(
            SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, assessment.reason)

    def _check_coverage(self, intent: NativeSandboxIntent) -> CompileRefusal | None:
        beyond = intent.required_coverage - self.coverable
        if beyond:
            # may not claim coverage=all; the unprovable categories refuse
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
                source=f"{self.adapter_id}.compile",
                target="claude's Bash/PowerShell/Monitor sandbox cannot prove "
                       f"coverage of {sorted(str(c) for c in beyond)}; those "
                       "tools stay under Permissions control")
        return None

    def _compile_brand(self, intent: NativeSandboxIntent, target: TargetHandle,
                       authorized: AuthorizedFacts | None) -> CompileResult:
        config = intent.config
        fields = [CompiledFieldIntent(
            field_path_segments=(path,), value=True, kind=KIND_SET_FIELD,
            intent=intent, target=target)
            for attr, path in _TOGGLES if getattr(config, attr)]
        if not fields:
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                source=f"{self.adapter_id}.compile",
                target="no Bash/PowerShell/Monitor toggle is enabled; there is "
                       "nothing to compile and no broader claim is emitted")
        # note the deliberate ABSENCE of any read/edit/MCP/network coverage field
        return self._result(intent, fields,
                            ["Bash/PowerShell/Monitor toggles only; no coverage "
                             "assertion beyond the covered subprocess kinds"])


"""PiSandboxAdapter — Pi native-sandbox configuration adapter (T05).

Pi has no built-in native sandbox at all: the official path is an optional
``sandbox/`` extension that replaces Bash and depends on an external runtime
(harness-adapters.md Pi row; API ``PiSandboxConfig`` refuses without a named
extension). Therefore:

* with no evidence of a *loaded* sandbox extension, ``assess`` answers
  ``unsupported`` and ``compile`` returns ``SANDBOX_NATIVE_UNSUPPORTED`` with
  **zero** compiled intents — there is no fallback that configures bare Pi as
  isolated (the 横向反例 "Pi 扩展缺席却 UI 显示安全"; a vacuous compile would
  certify the absence of enforcement);
* a loaded extension observed at a *different* pin is ``unknown``, not a pass;
* only an observed, loaded, matching extension compiles — as a real Harness C3
  ``InvokeAction`` (§C2 names the action form for exactly this case: Pi's
  sandbox is not a config field, it is an external extension being invoked),
  with the extension observation it expects to be honoured. The published
  descriptor still files ZERO native-field claims.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_harness_api.contracts import Assessment
from ordessa_harness_api.intents import TargetHandle
from ordessa_sandbox_api import NativeSandboxIntent, SandboxErrorCode, ToolCategory

from .base import BaseSandboxAdapter
from .dto import AdapterPin, AuthorizedFacts, PiSandboxExtensionEvidence
from .ranges import NativeVersionRange
from .results import CompileRefusal, CompileResult, assessment_supported, \
    assessment_unknown, assessment_unsupported
from .seam import CompiledFieldIntent, KIND_INVOKE_ACTION

__all__ = ["PiSandboxAdapter"]


class PiSandboxAdapter(BaseSandboxAdapter):
    adapter_id = "sandbox.native-config.pi"
    harness_id = "pi"
    brand = "pi"
    version_range = NativeVersionRange(minimum="2.0", maximum="3.0")
    coverable = frozenset({ToolCategory.BASH})
    capability_evidence = (
        "harness-adapters.md Pi row (sandbox is an optional extension that "
        "replaces Bash; no built-in native sandbox)")

    def native_field_claims(self) -> tuple[str, ...]:
        return ("sandboxExtension",)

    def config_from_payload(self, payload: Mapping[str, Any]):
        """Pi's payload carries NO config: the point schema admits nothing and
        the sandbox is an external extension, so the template config stands."""
        return None

    def _assess_brand(self, pin: AdapterPin, platform_facts,
                      authorized_facts: AuthorizedFacts) -> Assessment:
        ext = authorized_facts.pi_sandbox_extension
        if ext is None:
            return assessment_unsupported(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                "no sandbox-extension observation exists; the Pi sandbox "
                "is an optional extension, not built-in, and bare Pi is "
                "never isolated")
        if not ext.loaded:
            return assessment_unsupported(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"extension {ext.extension_id} was observed but not loaded; "
                "nothing is configured as a fallback")
        if ext.observed_native_version != pin.native_version:
            return assessment_unknown(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                "the extension observation belongs to a different native pin")
        return assessment_supported(
            evidence=f"loaded Pi sandbox extension {ext.extension_id!r} "
                     f"observed at pin {ext.observed_native_version} "
                     "(extension-backed only)",
            reason="extension-backed only; no built-in Pi sandbox is claimed")

    def _compile_brand(self, intent: NativeSandboxIntent, target: TargetHandle,
                       authorized: AuthorizedFacts | None) -> CompileResult:
        source = f"{self.adapter_id}.compile"
        ext = None if authorized is None else authorized.pi_sandbox_extension
        if ext is None or not ext.loaded:
            # no compiled intent at all — never fall back to bare Pi
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED, source=source,
                target="no loaded Pi sandbox extension is evidenced for this "
                       "pin; refusing instead of falling back to bare Pi")
        if ext.observed_native_version != (intent.native_version_pin
                                           or intent.harness_id):
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, source=source,
                target=f"extension observed at {ext.observed_native_version!r}, "
                       "not the intent's pin; nothing is compiled on stale evidence")
        return self._result(
            intent,
            [CompiledFieldIntent(
                field_path_segments=("sandboxExtension",),
                value=ext.extension_id, kind=KIND_INVOKE_ACTION, intent=intent,
                target=target,
                # what the C3 action declares it must be observed against —
                # the platform refuses an InvokeAction without one
                expected_observation=f"pi-sandbox-extension-loaded:"
                                     f"{ext.extension_id}"
                                     f"@{ext.observed_native_version}",
            )],
            ["extension-backed only: the Bash replacement is an external "
             "InvokeAction, not a config field; the C4 controlled materializer "
             "refuses actions without a separate executor, so this action "
             "reaches no write in this tree"])


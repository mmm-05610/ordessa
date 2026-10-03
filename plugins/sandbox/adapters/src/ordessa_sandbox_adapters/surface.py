"""The platform-shaped surface: this facet as a real ``ConfigurationAdapter``.

``harness-api`` publishes the consumer contract the point's C4 service calls —
``ConfigurationAdapter`` (``descriptor`` + ``assess(context, request)`` +
``compile(context, before, desired) -> IntentSet | AdapterRefusal`` +
``verify(context, observed) -> Verification``). The brand adapters in
``codex.py``/``claude_code.py``/``pi.py`` keep the *business* shape §C2 gives
them (a pin, platform facts, authorized facts, a ceiling set and a
``NativeSandboxIntent``), which the host cannot call. This module is the single
edge between the two: it subclasses the platform Protocol (so conformance is
Python-enforced, not asserted by a hand-written list) and

* reads its target from the ``AdapterContext`` — the server-issued
  ``TargetHandle``; it never derives a handle or a generation from a string,
* lets the platform's own closed ``ValueSchema`` refuse a payload (§C2 forbids
  arbitrary shell/path writes; the refusal is the platform's
  ``ContractError``, see ``tests/test_c3_platform_guards.py``),
* converts a business ``CompileRefusal`` into the platform's ``AdapterRefusal``
  carrying a *platform* ``ErrorCode`` while keeping the §C4 stable code in the
  reason prefix (``results.sandbox_code_of`` reads it back),
* returns real ``IntentSet`` objects bound in ``seam.py``.

``verify`` compares the readback against what *this* surface last compiled. The
published record states that the operation-bound native receipt and instance
generation are absent and that no Q5 production verifier is installed
(``harness-api.json`` limitations), so this verifier is a controlled-fixture
comparator — it can only ever answer ``Match``/``Mismatch``/
``VerificationUnknown`` and never a confirmation of its own.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional, Sequence, Tuple

from ordessa_harness_api.contracts import (
    AdapterContext,
    AdapterRefusal,
    Assessment,
    ConfigurationAdapter,
    Match,
    Mismatch,
    TargetHandle,
    Verification,
    VerificationUnknown,
)
from ordessa_harness_api.errors import ErrorCode
from ordessa_harness_api.intents import IntentSet
from ordessa_sandbox_api import NativeSandboxIntent, PlatformFacts, SandboxErrorCode

from .base import BaseSandboxAdapter
from .dto import AdapterPin, AuthorizedFacts
from .points import build_configuration_descriptor
from .results import CompileRefusal, CompiledIntent, sandbox_reason, \
    verification_match
from .seam import KIND_INVOKE_ACTION

__all__ = ["PLATFORM_REFUSAL_CODE", "SandboxConfigurationSurface"]

#: Each business refusal code, expressed in the PLATFORM's own ErrorCode
#: vocabulary (no invented codes). Derivation of every row:
#:   - the three documented-limit codes land in CAPABILITY_UNSUPPORTED, the
#:     platform's own "this capability is not offered" code;
#:   - a field-claim / administrator-ceiling collision is the platform's
#:     TARGET_CONFLICT;
#:   - an effect this tree cannot prove (unmeasured pin, stale extension
#:     observation, undeclared cross-session impact) is ISOLATION_UNPROVEN —
#:     the platform code for "isolation is not demonstrated", which is exactly
#:     §C4's `SANDBOX_EFFECT_UNKNOWN` and stays distinct from the documented
#:     limit above;
#:   - a malformed intent is INVALID_FRAGMENT, a busy provider is BUSY.
PLATFORM_REFUSAL_CODE: Mapping[SandboxErrorCode, ErrorCode] = {
    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED: ErrorCode.CAPABILITY_UNSUPPORTED,
    SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN: ErrorCode.CAPABILITY_UNSUPPORTED,
    SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED: ErrorCode.CAPABILITY_UNSUPPORTED,
    SandboxErrorCode.SANDBOX_CONFIG_CONFLICT: ErrorCode.TARGET_CONFLICT,
    SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN: ErrorCode.ISOLATION_UNPROVEN,
    SandboxErrorCode.SANDBOX_INTENT_INVALID: ErrorCode.INVALID_FRAGMENT,
    SandboxErrorCode.PROVIDER_BUSY: ErrorCode.BUSY,
}


def _dotted(version: Optional[Tuple[int, int, int]]) -> str:
    return "" if version is None else ".".join(str(part) for part in version)


class SandboxConfigurationSurface(ConfigurationAdapter):
    """One brand adapter, callable through the published C2/C4 contract."""

    def __init__(self, adapter: BaseSandboxAdapter, *,
                 intent: NativeSandboxIntent,
                 platform_facts: PlatformFacts | None = None,
                 authorized: AuthorizedFacts | None = None,
                 ceilings: Sequence[Any] = (),
                 pins: Mapping[str, str] | None = None) -> None:
        if intent.brand != adapter.brand or intent.harness_id != adapter.harness_id:
            raise ValueError("the surface's intent template belongs to another brand")
        self.adapter = adapter
        self.intent = intent
        self.platform_facts = platform_facts
        self.authorized = AuthorizedFacts() if authorized is None else authorized
        self.ceilings = tuple(ceilings)
        self.descriptor = build_configuration_descriptor(adapter, pins=pins)
        # the fields this surface last compiled: the only expectation a
        # controlled-fixture comparator may check a readback against
        self._compiled: tuple[tuple[tuple[str, ...], Any], ...] = ()

    # ------------------------------------------------------------------ assess
    def assess(self, context: AdapterContext, request: Any) -> Assessment:
        if self.platform_facts is None:
            return Assessment(
                "unknown",
                reason=sandbox_reason(SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                                      "no platform facts were injected, so the "
                                      "native mechanism cannot be assessed"))
        installation = context.installation
        native_version = _dotted(installation.native_version)
        if not native_version:
            return Assessment(
                "unknown",
                reason=sandbox_reason(SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                                      "the native version is unverified; no "
                                      "menu is invented for an unmeasured pin"))
        return self.adapter.assess(AdapterPin(harness_id=installation.harness_id,
                                              native_version=native_version),
                                   self.platform_facts, self.authorized)

    # ----------------------------------------------------------------- compile
    def _target_handle(self, context: AdapterContext) -> TargetHandle | None:
        claimed = {claim.target_id for claim in self.descriptor.claims}
        for target in context.targets:
            if target.handle.handle_id in claimed:
                return target.handle
        if claimed:
            return None
        # Pi files no native-field claim: its action carries no file target
        for target in context.targets:
            return target.handle
        return None

    def compile(self, context: AdapterContext, before: Any,
                desired: Any) -> IntentSet | AdapterRefusal:
        # 1. the platform's closed payload schema is the first gate: a shell- or
        #    path-shaped key raises ContractError here, in the platform's words
        payload = self.descriptor.payload_schema.validate(desired)
        handle = self._target_handle(context)
        if handle is None:
            return AdapterRefusal(
                ErrorCode.TARGET_CONFLICT,
                sandbox_reason(SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
                               f"the context issues no target for the claims of "
                               f"{self.descriptor.adapter_id}"))
        config = self.adapter.config_from_payload(payload)
        intent = self.intent if config is None else dataclasses.replace(
            self.intent, config=config)
        result = self.adapter.compile(intent, handle, self.ceilings,
                                      authorized=self.authorized)
        if isinstance(result, CompileRefusal):
            return AdapterRefusal(PLATFORM_REFUSAL_CODE[result.code], result.reason)
        assert isinstance(result, CompiledIntent)
        intents = result.to_harness_c3()
        self._compiled = tuple(
            (field.field_path_segments, field.value) for field in result.intents
            if field.kind != KIND_INVOKE_ACTION)
        return intents

    # ------------------------------------------------------------------ verify
    def verify(self, context: AdapterContext, observed: Any) -> Verification:
        if not self._compiled:
            return VerificationUnknown(sandbox_reason(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                "this surface compiled no field for the current request, so the "
                "readback has nothing to be compared against"))
        if not isinstance(observed, Mapping):
            return VerificationUnknown(sandbox_reason(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                "the native readback is not a structured document, so the "
                "compiled fields cannot be observed"))
        for segments, expected in self._compiled:
            cursor: Any = observed
            for part in segments:
                if not isinstance(cursor, Mapping) or part not in cursor:
                    return Mismatch(sandbox_reason(
                        SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
                        f"native readback carries no {'.'.join(segments)}"))
                cursor = cursor[part]
            if not _same(cursor, expected):
                return Mismatch(sandbox_reason(
                    SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
                    f"native readback {'.'.join(segments)} differs from the "
                    "compiled value"))
        return verification_match(
            f"sandbox.native-configuration.readback:{self.descriptor.adapter_id}")


def _same(observed: Any, expected: Any) -> bool:
    """JSON-shaped equality, tolerant of list/tuple spellings only."""
    if isinstance(expected, (list, tuple)) and isinstance(observed, (list, tuple)):
        return len(observed) == len(expected) and all(
            _same(a, b) for a, b in zip(observed, expected))
    if isinstance(expected, Mapping) and isinstance(observed, Mapping):
        return set(expected) == set(observed) and all(
            _same(observed[key], expected[key]) for key in expected)
    if isinstance(expected, bool) or isinstance(observed, bool):
        return type(observed) is type(expected) and observed == expected
    return observed == expected

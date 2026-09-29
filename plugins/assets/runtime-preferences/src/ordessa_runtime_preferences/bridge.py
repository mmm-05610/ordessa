"""Thin adapters→harness-api bridge: the eight brand adapters register into
the real C2 point (``harness.configuration-adapters``) as typed
``ConfigurationAdapter``s.

Direction discipline (model-provider form, not its imports): this module may
import the public ``ordessa_harness_api`` contract; the reverse import never
exists. The pure brand modules and the catalog stay untouched — their
three-state verdicts and citations are conformance-pinned — so this layer
only *translates*:

- the payload ``{"<group>": {params}}`` (closed schema, one to four groups)
  becomes one :class:`PreferenceRequest` per present group; compile refuses
  when any present group is not ``available`` — never a partial application;
- the local ``CompileIntent``s become ``SetField``s against the harness
  target the context carries (handle ids mirror the catalog targets);
- the brand reconfiguration declaration is not part of the harness C2
  ``compile`` surface; it stays available through :func:`reconfiguration_for`
  for the controlled runtime, never lost, never claimed as hot-reload.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from ordessa_harness_api import (
    AdapterRefusal, Assessment, ConfigurationAdapterDescriptor, ErrorCode,
    FieldClaim, FieldPath, IntentSet as HarnessIntentSet, IntentSource,
    Match, Mismatch, SetField, TargetHandle as HarnessTargetHandle,
    ValueSchema, VerificationUnknown, VersionRange,
)

from . import common, engine, keys
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .dsh import DshAdapter
from .hermes import HermesAdapter
from .kilo import KiloAdapter
from .opencode import OpencodeAdapter
from .pi import PiAdapter
from .qwen import QwenAdapter
from .types import PreferenceRequest, Refusal as LocalRefusal

BRANDS = keys.BRANDS

#: This package's adapter version, as the descriptor's ``adapter_versions``
#: single point (installed dist is 1.0.0a1).
ADAPTER_VERSION = (1, 0, 0)

#: The handle ids mirror the catalog targets (the host issues handles with
#: this vocabulary). dsh has no pinnable target at document level.
HANDLE_IDS = {brand: keys.BRAND_TARGETS[brand][0] for brand in BRANDS}

_IMPL = {
    "pi": PiAdapter, "codex": CodexAdapter, "claude-code": ClaudeAdapter,
    "hermes": HermesAdapter, "opencode": OpencodeAdapter, "dsh": DshAdapter,
    "qwen": QwenAdapter, "kilo": KiloAdapter,
}

_REFUSAL_CODES = {
    "capability-unsupported": ErrorCode.CAPABILITY_UNSUPPORTED,
    "target-conflict": ErrorCode.TARGET_CONFLICT,
    "invalid-request": ErrorCode.INVALID_FRAGMENT,
    "admin-only-key": ErrorCode.CAPABILITY_UNSUPPORTED,
}


def _nullable(**fields: ValueSchema) -> tuple[tuple[str, ValueSchema], ...]:
    return tuple((name, ValueSchema(kind, nullable=True))
                 for name, kind in fields.items())


def _group_schemas() -> tuple[tuple[str, ValueSchema], ...]:
    types = {
        "enabled": "boolean", "mode": "string", "thresholdPercent": "integer",
        "thresholdTokens": "integer", "reserveTokens": "integer",
        "keepRecentTokens": "integer", "summaryModelRef": "string",
        "budgetTokens": "integer", "extractionModelRef": "string",
        "shellPath": "string", "commandPrefix": "string", "backend": "string",
        "persistent": "boolean", "timeoutMs": "integer", "maxRetries": "integer",
        "baseDelayMs": "integer", "maxDelayMs": "integer",
        "streamIdleTimeoutMs": "integer", "transport": "string",
        "proxyRef": "string",
    }
    schemas = []
    for group in keys.GROUPS:
        fields = []
        for name in keys.CANONICAL_PARAMS[group]:
            if name == "envRefs":
                fields.append((name, ValueSchema("object", nullable=True,
                                                 additional_properties=True)))
            else:
                fields.append((name, ValueSchema(types[name], nullable=True)))
        schemas.append((group, ValueSchema("object", nullable=True,
                                           properties=tuple(fields))))
    return tuple(schemas)


def payload_schema() -> ValueSchema:
    """The ``runtime-preferences.item.v1`` payload: one to four group objects
    with canonical parameter values. References stay reference strings; the
    closed schemas leave no room for undeclared keys."""
    return ValueSchema("object", properties=_group_schemas())


def _claims(brand: str) -> tuple[FieldClaim, ...]:
    """Parent/exact field claims mirroring only the *compiled* native keys.
    Admin-only and recorded-but-uncompiled keys are structurally unclaimable
    (RA-4); dsh, with no pinnable target, claims nothing."""
    target = HANDLE_IDS[brand]
    if target is None:
        return ()
    claim_paths = {
        "pi": (("compaction",), ("retry",), ("shellPath",), ("shellCommandPrefix",)),
        "codex": (("model_auto_compact_token_limit",), ("memories",),
                  ("features", "shell_tool"), ("background_terminal_max_timeout",)),
        "claude-code": (("autoCompactEnabled",), ("autoMemoryEnabled",), ("defaultShell",)),
        "hermes": (),
        "opencode": (("compaction",), ("shell",)),
        "dsh": (),
        "qwen": (("context", "autoCompactThreshold"),
                 ("memory", "enableManagedAutoMemory"),
                 ("tools", "shell", "defaultTimeoutMs")),
        "kilo": (("compaction",), ("shell",)),
    }
    return tuple(FieldClaim("file", target, path) for path in claim_paths[brand])


def descriptor_for(brand: str) -> ConfigurationAdapterDescriptor:
    """The real C2 ``ConfigurationAdapterDescriptor`` for one brand.

    ``native_versions`` is the document-level *assessment window*, not a
    support claim: no per-brand version thresholds are pinned at this
    evidence level (sources-and-gaps R1, registered in the report). The
    bounded window says only "this evidence round assessed 0.1.0–2.0.0";
    outside it the adapter honestly does not match, and the bounded maximum
    lets a future evidence round register a provably disjoint successor.
    """
    if brand not in BRANDS:
        raise ValueError(f"unknown brand {brand!r}")
    return ConfigurationAdapterDescriptor(
        f"assets.runtime-preferences.{brand}", "v1", common.FACET_ID,
        common.FACET_SCHEMA_VERSION, brand,
        VersionRange((0, 1, 0), (2, 0, 0)), VersionRange(ADAPTER_VERSION),
        (common.ENTRY,), payload_schema(), _claims(brand),
    )


def _local_context(context: Any) -> Any:
    native = context.installation.native_version
    version = ".".join(str(part) for part in native) if native else None
    targets = {target.kind: target for target in context.targets}
    file_target = targets.get("file")
    identity = file_target.handle.handle_id if file_target is not None else ""
    return (version, identity)


def _preference_requests(payload: Mapping[str, Any]) -> tuple[PreferenceRequest, ...]:
    """One request per present group; schema-validated groups only arrive
    here, so an empty payload simply yields no requests (the honest probe)."""
    requests = []
    for group in keys.GROUPS:
        value = payload.get(group)
        if isinstance(value, Mapping):
            requests.append(PreferenceRequest(group, dict(value)))
    return tuple(requests)


def _expected_paths(compiled) -> dict[str, Any]:
    return {".".join(intent.field_path): intent.typed_value
            for intent in compiled.intents}


def reconfiguration_for(brand: str, payload: Mapping[str, Any]) -> str:
    """'unverified' | 'restart-resume' | 'reload' | 'session-local' | 'refused'
    for one payload — the pinned catalog discipline; the harness C2 compile
    surface does not carry it, so the controlled runtime reads it here.
    ``unverified`` dominates any mixed payload."""
    local_ctx = _LocalContextProbe(brand)
    verdicts = []
    for request in _preference_requests(payload):
        result = _IMPL[brand]().compile(local_ctx, {}, request)
        if isinstance(result, LocalRefusal):
            return "refused"
        verdicts.append(result.reconfiguration)
    if not verdicts:
        return "refused"
    if "unverified" in verdicts:
        return "unverified"
    return sorted(verdicts)[0]


class _LocalContextProbe:
    """A minimal context for reconfiguration probes (document-level window)."""

    def __init__(self, brand: str) -> None:
        self.target_handle = engine.target_handle(brand)
        self.harness_version = "0.0.0"
        self.capabilities: dict[str, Any] = {}
        self.generation = None

    @property
    def scope(self) -> str:
        return "instance"


class BridgeConfigurationAdapter:
    """One brand as a real C2 ``ConfigurationAdapter`` (assess/compile/verify)."""

    def __init__(self, brand: str) -> None:
        if brand not in BRANDS:
            raise ValueError(f"unknown brand {brand!r}")
        self.brand = brand
        self.descriptor = descriptor_for(brand)
        self._impl = _IMPL[brand]()

    # -- C2 surface -----------------------------------------------------------

    def assess(self, context: Any, request: Mapping[str, Any]) -> Assessment:
        requests = _preference_requests(request) if isinstance(request, Mapping) else ()
        if not requests:
            # C4 inspect probes with an empty request; a probe carries no
            # preference facts, so the honest verdict is unknown, never
            # supported.
            return Assessment("unknown", reason="probe request carries no preference facts")
        version, _identity = _local_context(context)
        verdicts = [self._impl.assess(_ctx(context, version), req) for req in requests]
        if any(v.verdict == "unsupported" for v in verdicts):
            worst = next(v for v in verdicts if v.verdict == "unsupported")
        elif any(v.verdict == "unknown" for v in verdicts):
            worst = next(v for v in verdicts if v.verdict == "unknown")
        else:
            worst = verdicts[0]
        evidence = (f"assets.runtime-preferences:{self.brand}:doc"
                    if worst.verdict == "supported" else None)
        return Assessment(worst.verdict, reason=worst.reason, evidence_ref=evidence)

    def compile(self, context: Any, before: Mapping[str, Any], desired: Mapping[str, Any]
                ) -> HarnessIntentSet | AdapterRefusal:
        requests = _preference_requests(desired)
        if not requests:
            return AdapterRefusal(ErrorCode.INVALID_FRAGMENT,
                                  "payload carries no preference group")
        version, identity = _local_context(context)
        local_ctx = _ctx(context, version, identity)
        intents = []
        item_ids = set()
        for request in requests:
            compiled = self._impl.compile(local_ctx, before, request)
            if isinstance(compiled, LocalRefusal):
                return _to_refusal(compiled)
            intents.extend(compiled.intents)
            item_ids.add(request.group)
        source_item = item_ids.pop() if len(item_ids) == 1 else "preferences"
        harness_intents = _harness_intents(context, intents, source_item)
        # The harness C2 IntentSet carries intents only; the brand
        # reconfiguration declaration and the per-key apply modes stay on the
        # local surface (read them via reconfiguration_for / the catalog).
        return HarnessIntentSet(tuple(harness_intents))

    def verify(self, context: Any, observed: Mapping[str, Any]) -> Match | Mismatch | VerificationUnknown:
        version, _identity = _local_context(context)
        verdict = self._impl.verify(_ctx(context, version), observed)
        if verdict.verdict == "match":
            digest = common.digest_label(dict(observed.get("expected") or {}))
            return Match(f"runtime-preferences:readback:{digest}")
        if verdict.verdict == "mismatch":
            return Mismatch(verdict.reason or "native readback differs from the compiled intent")
        return VerificationUnknown(verdict.reason or "no read-back sample")


class _Ctx:
    """The local AdapterContext projected from the harness context."""

    def __init__(self, context: Any, version: str | None, identity: str) -> None:
        from .types import AdapterContext, TargetHandle

        self._inner = AdapterContext(
            target_handle=TargetHandle(context.installation.harness_id, "instance", identity),
            harness_version=version,
            capabilities=dict(context.capabilities) if hasattr(context, "capabilities") else {},
            generation=getattr(context, "generation", None),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _ctx(context: Any, version: str | None, identity: str | None = None) -> Any:
    if identity is None:
        file_targets = [t for t in context.targets if t.kind == "file"]
        identity = file_targets[0].handle.handle_id if file_targets else ""
    return _Ctx(context, version, identity)


def _to_refusal(refusal: LocalRefusal) -> AdapterRefusal:
    code = _REFUSAL_CODES.get(refusal.code, ErrorCode.CAPABILITY_UNSUPPORTED)
    return AdapterRefusal(code, refusal.message)


def _harness_intents(context: Any, local_intents: tuple[Any, ...],
                     source_item: str) -> list[SetField]:
    source = IntentSource(common.FACET_ID, source_item, common.FACET_SCHEMA_VERSION)
    file_targets = [t for t in context.targets if t.kind == "file"]
    if not file_targets:
        raise ValueError("adapter context lacks authorized file target")
    handle = file_targets[0].handle
    intents = []
    for intent in local_intents:
        intents.append(SetField(source, handle, FieldPath(intent.field_path),
                                intent.typed_value))
    return intents

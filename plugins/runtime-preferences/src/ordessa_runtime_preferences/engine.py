"""The shared assess/compile/verify engine behind the eight brand adapters.

One engine, eight thin brand modules: the brand-specific facts live entirely
in :mod:`ordessa_runtime_preferences.keys` (three-state verdicts, native
paths, apply modes, admin exclusions, citations). The engine turns a cell
verdict into typed behavior:

- ``available``  → compile the documented keys, refuse unmapped params;
- ``unsupported``→ typed refusal carrying the cell's evidence-backed reason;
- ``unknown``    → typed refusal saying exactly that (honest, not silent);
- admin-only keys never compile and never enter C2 claims (RA-4).

Pure module: no HOME, no network, no spawn, no file writes, no secret
content; model/backend values travel only as reference strings.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common, keys
from .types import (
    AdapterContext, Assessment, CompileIntent, IntentSet, PreferenceRequest,
    Refusal, TargetHandle, Verdict,
)

_PARAM_TYPES: dict[str, tuple[type, ...]] = {
    "enabled": (bool,),
    "mode": (str,),
    "thresholdPercent": (int,),
    "thresholdTokens": (int,),
    "reserveTokens": (int,),
    "keepRecentTokens": (int,),
    "summaryModelRef": (str,),
    "budgetTokens": (int,),
    "extractionModelRef": (str,),
    "shellPath": (str,),
    "commandPrefix": (str,),
    "backend": (str,),
    "persistent": (bool,),
    "timeoutMs": (int,),
    "maxRetries": (int,),
    "baseDelayMs": (int,),
    "maxDelayMs": (int,),
    "streamIdleTimeoutMs": (int,),
    "transport": (str,),
    "proxyRef": (str,),
}

_REFERENCE_PARAMS = ("summaryModelRef", "extractionModelRef", "proxyRef")


def _positive_int(group: str, name: str, value: int) -> str | None:
    if isinstance(value, bool) or value < 0:
        return f"{group}.{name} must be a non-negative integer"
    return None


def validate_params(group: str, params: Mapping[str, Any]) -> Refusal | None:
    """The closed canonical vocabulary, enforced (facet schema v1)."""
    vocabulary = keys.CANONICAL_PARAMS[group]
    for name, value in params.items():
        if name not in vocabulary:
            return Refusal("invalid-request",
                           f"{group}.{name} is outside the canonical v1 vocabulary",
                           {"vocabulary": vocabulary})
        if name in ("envRefs",):
            if not isinstance(value, Mapping) or not all(
                    isinstance(k, str) and isinstance(v, str) and v.startswith("ref://")
                    for k, v in value.items()):
                return Refusal("invalid-request",
                               f"{group}.envRefs must map names to ref:// references")
            continue
        expected = _PARAM_TYPES.get(name)
        if expected is None:
            return Refusal("invalid-request", f"{group}.{name} is not a typed v1 parameter")
        if not isinstance(value, expected) or isinstance(value, bool) and bool not in expected:
            return Refusal("invalid-request",
                           f"{group}.{name} must be {'/'.join(t.__name__ for t in expected)}")
        if name in _REFERENCE_PARAMS and not str(value).strip():
            return Refusal("invalid-request", f"{group}.{name} must be a non-empty reference")
        if isinstance(value, int) and not isinstance(value, bool):
            problem = _positive_int(group, name, value)
            if problem:
                return Refusal("invalid-request", problem)
        if name == "thresholdPercent" and not 1 <= value <= 99:
            return Refusal("invalid-request", "compaction.thresholdPercent must be 1-99")
    return None


def assess(brand: str, context: AdapterContext, request: PreferenceRequest) -> Assessment:
    gate = common.version_gate(context.harness_version)
    if gate != "supported":
        return Assessment(gate, f"native adapter version {context.harness_version!r} "
                                f"is {gate} (document-level window; no pinned thresholds yet)",
                          harness_id=brand, native_version=context.harness_version)
    cell = keys.cell(brand, request.group)
    if cell.status == keys.STATUS_AVAILABLE:
        return Assessment("supported", None, harness_id=brand,
                          native_version=context.harness_version)
    if cell.status == keys.STATUS_UNSUPPORTED:
        return Assessment("unsupported", cell.conclusion, harness_id=brand,
                          native_version=context.harness_version)
    return Assessment("unknown", cell.conclusion, harness_id=brand,
                      native_version=context.harness_version)


def _project_scope_refusal(context: AdapterContext) -> Refusal | None:
    if context.target_handle.scope != "instance":
        return Refusal("target-conflict",
                       f"{context.target_handle.harness_id} run-level preferences are instance-scoped; "
                       "project tiers are trust/admin-gated and never preset",
                       {"scope": context.target_handle.scope})
    return None


def compile(brand: str, context: AdapterContext,
            request: PreferenceRequest) -> IntentSet | Refusal:
    group = request.group
    if group not in keys.GROUPS:
        return Refusal("invalid-request", f"unknown preference group {group!r}")
    invalid = validate_params(group, request.params)
    if invalid is not None:
        return invalid
    if not request.params:
        return Refusal("invalid-request", "an empty preference carries no parameter")
    scope_refusal = _project_scope_refusal(context)
    if scope_refusal is not None:
        return scope_refusal
    assessment = assess(brand, context, request)
    if assessment.verdict != "supported":
        return Refusal("capability-unsupported", assessment.reason or "not supported")
    cell = keys.cell(brand, group)
    if cell.target is None:
        return Refusal("capability-unsupported",
                       f"{brand} {group}: the native write target is not pinnable at document "
                       "evidence level (Cordis per-package assembly); refusing instead of guessing",
                       {"evidence": key.evidence for key in cell.keys})
    mapping = keys.compiled_keys(brand, group)
    unmapped = sorted(set(request.params) - set(mapping))
    if unmapped:
        recorded = {key.canonical: key.note for key in cell.keys
                    if key.canonical in unmapped and key.note}
        return Refusal("capability-unsupported",
                       f"{brand} {group}: parameter(s) {unmapped} have no faithful native mapping "
                       "at this evidence level; the documented keys are recorded but not compiled",
                       {"unmapped": unmapped, "recorded_notes": recorded,
                        "admin_only": [key.path for key in keys.admin_only_keys(brand, group)]})
    intents = []
    for name, value in request.params.items():
        intents.append(CompileIntent(
            context.target_handle, mapping[name], _native_value(brand, group, name, value),
            source_item=group))
    return IntentSet(
        facet_id=common.FACET_ID, contributor_version=common.CONTRIBUTOR_VERSION,
        intents=tuple(intents), reconfiguration=common.item_reconfiguration(brand, group),
        apply_modes=tuple((mapping[name], _apply_mode(brand, group, name))
                          for name in request.params),
    )


def _apply_mode(brand: str, group: str, canonical: str) -> str:
    for key in keys.cell(brand, group).keys:
        if key.canonical == canonical and not key.admin_only:
            return key.apply_mode
    return keys.APPLY_UNKNOWN


def _native_value(brand: str, group: str, canonical: str, value: Any) -> Any:
    """The native-typed value for one compiled key (conversions documented in
    the catalog; conversions without citations never happen)."""
    if brand == "qwen" and canonical == "thresholdPercent":
        # qwen settings doc @ 302e7d88: context.autoCompactThreshold is the
        # fraction of the context window (default 0.85); the facet stores 1-99.
        return round(value / 100, 4)
    return value


def verify(brand: str, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
    """Read-back discipline: only an observed native readback decides
    ``match``; a projected digest alone is ``unknown``; when the harness
    reports a native session identity, a changed one is ``mismatch`` (a
    session/new must never impersonate resume)."""
    readback = observed.get("readback")
    if not isinstance(readback, Mapping):
        return Verdict("unknown", "no read-back sample; a projected file digest "
                                  "is not evidence of effect")
    expected = observed.get("expected")
    if not isinstance(expected, Mapping) or not expected:
        return Verdict("unknown", "no compiled expectation to compare against")
    # Readback keys are the string forms ("compaction.enabled") of the
    # compiled structured paths; the bridge builds both sides.
    differing = {path: {"expected": expected[path], "observed": readback.get(path)}
                 for path in expected if readback.get(path) != expected[path]}
    if differing:
        return Verdict("mismatch", "native read-back differs from the compiled expectation",
                       evidence={"differing": differing})
    session_now = observed.get("native_session_id")
    session_before = context.capabilities.get("native_session_id")
    if (session_now is not None and session_before is not None
            and session_now != session_before):
        return Verdict("mismatch", "native session identity changed; "
                                   "a session/new must never impersonate resume")
    return Verdict("match", None,
                   evidence={"applied_layer": "native-readback",
                             "digest": common.digest_label(dict(expected))})


def target_handle(brand: str) -> TargetHandle | None:
    """The instance target this package claims for one brand (None = not
    pinnable; the descriptor then carries no file claims)."""
    target, _codec = keys.BRAND_TARGETS[brand]
    if target is None:
        return None
    return TargetHandle(brand, "instance", target)

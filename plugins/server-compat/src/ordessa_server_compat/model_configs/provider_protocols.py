"""Canonical provider-protocol vocabulary and provider/model fact validation.

Work Order 092 (R-0013 layer 1) converges every protocol string the Server may
see - the wire's ``provenance.wireApi``, a record's ``protocols``, a model's
``protocols`` and a Harness descriptor's ``wireProtocols`` - onto one canonical
four-value vocabulary. Real-world dialects (cc-switch / mcode / pi / hermes)
are normalized at this single boundary; an unknown string is a typed refusal,
never a closest-match guess. Model facts (``protocols`` / ``capabilities``) and
endpoint URLs are validated here so the service can persist them verbatim and
read them back with absence preserved (an absent fact stays absent - we never
invent a default, because an invented fact is a lie the front end cannot tell
apart from a verified one).

This module is provider/harness neutral and free of I/O: it only transforms and
validates in-memory values. Persisting and deriving are the service's job.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution.protocols import CANONICAL_PROTOCOLS

#: The canonical display order comes from the single shared vocabulary in the
#: neutral execution layer; this module never redefines it.
_CANONICAL_ORDER = {name: index for index, name in enumerate(CANONICAL_PROTOCOLS)}
_CANONICAL_SET = frozenset(CANONICAL_PROTOCOLS)

#: Observed dialects, keyed by their lower-cased spelling, each mapping to the
#: canonical value it stands for. The canonical values map to themselves so a
#: caller may pass an already-normalized string through unchanged.
_DIALECT_TO_CANONICAL: dict[str, str] = {
    "openai-chat": "openai-chat",
    "chat": "openai-chat",
    "chat_completions": "openai-chat",
    "openai-completions": "openai-chat",
    "openai-responses": "openai-responses",
    "responses": "openai-responses",
    "anthropic-messages": "anthropic-messages",
    "anthropic": "anthropic-messages",
    "anthropic_messages": "anthropic-messages",
    "messages": "anthropic-messages",
    "claude": "anthropic-messages",
    "gemini-generate": "gemini-generate",
    "gemini": "gemini-generate",
    "generatecontent": "gemini-generate",
}


def normalize_protocol(value: Any) -> str:
    """Return the canonical value for one dialect string.

    Raises a typed ``PROTOCOL_UNKNOWN`` naming the offending value for anything
    that is not a known dialect - there is deliberately no fuzzy match.
    """
    if not isinstance(value, str) or not value.strip():
        _protocol_unknown(value)
    canonical = _DIALECT_TO_CANONICAL.get(value.strip().lower())
    if canonical is None:
        _protocol_unknown(value)
    return canonical


def _protocol_unknown(value: Any) -> None:
    raise ServerError(
        "PROTOCOL_UNKNOWN",
        f"Unknown protocol: {value!r} is not one of {list(CANONICAL_PROTOCOLS)} "
        "or a recognized dialect", status=422,
    )


def normalize_protocols(values: Any) -> list[str]:
    """Normalize a list of dialect strings to a de-duplicated, canonically
    ordered list. Raises ``PROTOCOL_UNKNOWN`` for any unknown member.
    """
    if not isinstance(values, list):
        raise ServerError(
            "PROTOCOL_UNKNOWN", "protocols must be a list of strings", status=422,
        )
    seen = {normalize_protocol(value) for value in values}
    return sorted(seen, key=lambda name: _CANONICAL_ORDER[name])


def normalize_wire_api(value: Any) -> Any:
    """Normalize a single provenance ``wireApi`` value, preserving absence.

    ``None`` stays ``None`` (unknown is not a guess); a known dialect becomes its
    canonical value; an unknown string is a typed refusal.
    """
    if value is None:
        return None
    return normalize_protocol(value)


def validate_endpoints(endpoints: Any, declared_protocols: Iterable[str]) -> dict[str, str]:
    """Validate the per-protocol ``endpoints`` map.

    Keys must be a subset of the record's declared ``protocols`` (canonical),
    and each URL follows the probe's discipline (https, loopback exception,
    non-loopback private refused) - so an endpoint can never smuggle in a
    target the probe would refuse. Returns a stable, canonically-keyed map.
    """
    if endpoints is None:
        return {}
    if not isinstance(endpoints, Mapping):
        raise ServerError(
            "PROFILE_CONFIGURATION_INVALID", "endpoints must be an object", status=422,
        )
    from ordessa_server_compat.model_configs.probe import ProbeError, _validate_endpoint

    allowed = set(declared_protocols)
    normalized: dict[str, str] = {}
    for key, url in endpoints.items():
        protocol = normalize_protocol(key)
        if protocol not in allowed:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                f"endpoint key {key!r} is not among the declared protocols", status=422,
            )
        if not isinstance(url, str) or not url:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", "endpoint URLs must be non-empty strings", status=422,
            )
        try:
            base, _host = _validate_endpoint(url)
        except ProbeError as error:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", f"endpoint {key!r}: {error}", status=422,
            ) from None
        normalized[protocol] = base
    return {name: normalized[name] for name in sorted(normalized, key=lambda n: _CANONICAL_ORDER[n])}


# The documented capability keys (092 R3). Anything else is refused rather than
# silently dropped, so a client typo cannot look like "not supported".
_CAPABILITY_BOOL_KEYS = ("toolCall", "reasoning")


def validate_capabilities(capabilities: Any) -> dict[str, Any] | None:
    """Strict-validate a model's ``capabilities`` object.

    Absent (``None``) stays absent and returns ``None`` so the caller can omit
    the key entirely (an unverified model must not gain a fabricated fact).
    Wrong types or undocumented keys raise ``PROVIDER_MODEL_INVALID``.
    """
    if capabilities is None:
        return None
    if not isinstance(capabilities, Mapping):
        raise _invalid_model("capabilities must be an object")
    out: dict[str, Any] = {}
    for key in _CAPABILITY_BOOL_KEYS:
        if key in capabilities:
            value = capabilities[key]
            if not isinstance(value, bool):
                raise _invalid_model(f"capabilities.{key} must be a boolean")
            out[key] = value
    if "reasoningOptions" in capabilities:
        out["reasoningOptions"] = _validate_reasoning_options(capabilities["reasoningOptions"])
    if "modalities" in capabilities:
        out["modalities"] = _validate_modalities(capabilities["modalities"])
    if "limits" in capabilities:
        out["limits"] = _validate_limits(capabilities["limits"])
    if "cost" in capabilities:
        out["cost"] = _validate_cost(capabilities["cost"])
    documented = set(_CAPABILITY_BOOL_KEYS) | {
        "reasoningOptions", "modalities", "limits", "cost",
    }
    stray = set(capabilities) - documented
    if stray:
        raise _invalid_model(f"unknown capability keys: {sorted(stray)}")
    return out


def _validate_reasoning_options(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _invalid_model("capabilities.reasoningOptions must be a list")
    options: list[dict[str, Any]] = []
    for option in value:
        if not isinstance(option, Mapping) or not isinstance(option.get("type"), str):
            raise _invalid_model("reasoning options need a string 'type'")
        extra = set(option) - {"type", "values"}
        if extra:
            raise _invalid_model(f"unknown reasoning option keys: {sorted(extra)}")
        entry: dict[str, Any] = {"type": option["type"]}
        if "values" in option:
            values = option["values"]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise _invalid_model("reasoning option 'values' must be a list of strings")
            entry["values"] = list(values)
        options.append(entry)
    return options


def _validate_modalities(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        raise _invalid_model("capabilities.modalities must be an object")
    stray = set(value) - {"input", "output"}
    if stray:
        raise _invalid_model(f"unknown modality keys: {sorted(stray)}")
    out: dict[str, list[str]] = {}
    for key in ("input", "output"):
        if key in value:
            items = value[key]
            if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
                raise _invalid_model(f"modalities.{key} must be a list of strings")
            out[key] = list(items)
    return out


def _validate_limits(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise _invalid_model("capabilities.limits must be an object")
    stray = set(value) - {"context", "output"}
    if stray:
        raise _invalid_model(f"unknown limit keys: {sorted(stray)}")
    out: dict[str, int] = {}
    for key in ("context", "output"):
        if key in value:
            number = value[key]
            if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                raise _invalid_model(f"limits.{key} must be a non-negative integer")
            out[key] = number
    return out


def _validate_cost(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise _invalid_model("capabilities.cost must be an object")
    stray = set(value) - {"input", "output", "cacheRead"}
    if stray:
        raise _invalid_model(f"unknown cost keys: {sorted(stray)}")
    out: dict[str, float] = {}
    for key in ("input", "output", "cacheRead"):
        if key in value:
            number = value[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
                raise _invalid_model(f"cost.{key} must be a non-negative number")
            out[key] = number
    return out


def _invalid_model(message: str) -> ServerError:
    return ServerError("PROVIDER_MODEL_INVALID", message, status=422)


def normalize_model_facts(model: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of one model entry with its protocol dialects normalized
    and capabilities strict-validated, preserving absence.

    A model without ``protocols`` gains no protocols key; one without
    ``capabilities`` gains no capabilities key. This is what lets the record read
    back an unverified fact as *absent* rather than fabricated.
    """
    out = dict(model)
    if "protocols" in model and model["protocols"] is not None:
        out["protocols"] = normalize_protocols(model["protocols"])
    capabilities = validate_capabilities(model.get("capabilities"))
    if capabilities is not None:
        out["capabilities"] = capabilities
    else:
        out.pop("capabilities", None)
    return out

"""Thin adapters→harness-api bridge: the brand adapters register into the real
C2 point (``harness.configuration-adapters``) as typed
``ConfigurationAdapter``s (PB-2 of 014).

Direction discipline (dispatch PB-2): this module may import the public
``ordessa_harness_api`` contract; the reverse import never exists. The pure
brand modules (``pi``/``codex``/``claude``) stay untouched — their dialect
facts and semantics are conformance-pinned — so this layer only *translates*
types:

- local ``types.py`` surfaces (authored in 011-z3 against the then-absent C2)
  map onto the real ``ConfigurationAdapterDescriptor`` / ``Assessment`` /
  ``IntentSet`` / ``Match`` vocabulary;
- codex's local ``MountContent`` provider section becomes a ``SetField`` of the
  parsed golden TOML table, so the value that reaches materialization is
  byte-faithful to ``common.render_codex_provider_section`` (the S-08② golden
  pin);
- the brand reconfiguration declaration (session-local vs restart-resume) is
  not part of the harness C2 ``compile`` surface; it stays available through
  :func:`reconfiguration_for` for the controlled E2 runtime, never lost.

Pure module: no HOME, no network, no spawn, no file writes, no secret content.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ordessa_harness_api import (
    AdapterRefusal, Assessment, ConfigurationAdapterDescriptor, ErrorCode,
    FieldClaim, FieldPath, IntentSet as HarnessIntentSet, IntentSource, Match,
    Mismatch, SetField, BindSecret as HarnessBindSecret, TargetHandle as HarnessTargetHandle,
    ValueSchema, VerificationUnknown, VersionRange,
)

from . import common
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .pi import PiAdapter
from .types import AdapterContext as LocalAdapterContext
from .types import BindSecret as LocalBindSecret
from .types import ChoiceRequest, CompileIntent, IntentSet as LocalIntentSet
from .types import MountContent as LocalMountContent
from .types import Refusal as LocalRefusal
from .types import TargetHandle as LocalTargetHandle

BRANDS = ("pi", "codex", "claude-code")

#: The facet every brand adapter contributes under (frozen in the 011-z3
#: manifests; conformance-pinned).
FACET_ID = "assets.model-provider"
FACET_SCHEMA_VERSION = "1"
CONTRIBUTOR_VERSION = "1"
#: The C2 entry (channel) the adapters serve; the harness service matches
#: ``context.entry`` against this.
ENTRY = "acp"

#: Stable server-issued handle ids the descriptors claim and the host's target
#: authority issues (same vocabulary as the harness controlled fixtures).
HANDLE_IDS = {
    "pi": "pi.models.json",
    "codex": "codex.config.toml",
    "claude-code": "claude.settings.json",
}

#: Frozen adapter ids (011-z3 manifests; conformance-pinned). The claude brand
#: is ``claude-code`` as a harness id but ``claude`` in the adapter id.
ADAPTER_IDS = {"pi": "assets.model-provider.pi", "codex": "assets.model-provider.codex",
               "claude-code": "assets.model-provider.claude"}

#: This package's adapter version, as the descriptor's ``adapter_versions``
#: single point (installed dist is 1.0.0a1).
ADAPTER_VERSION = (1, 0, 0)

#: The brand secret slots, declared as environment-target claims (the C4
#: vocabulary carries secrets only as ``BindSecret`` against an environment
#: slot; the slot is a reference holder, never a value).
SECRET_SLOTS = {"pi": "api_key", "codex": "CODEX_API_KEY", "claude-code": "ANTHROPIC_AUTH_TOKEN"}

_IMPL = {"pi": PiAdapter, "codex": CodexAdapter, "claude-code": ClaudeAdapter}


def _inclusive_ceiling(exclusive_high: tuple[int, ...]) -> tuple[int, int, int]:
    """``<0.6`` becomes the inclusive ceiling of everything below: the last
    version of the previous minor series. Semver tuples compare element-wise,
    so a sentinel 999999 covers an open patch/minor range."""
    major, minor = exclusive_high[0], exclusive_high[1]
    if minor > 0:
        return (major, minor - 1, 999999)
    return (major - 1, 999999, 999999)


def native_version_range(brand: str) -> VersionRange:
    low, high = common.SUPPORTED_VERSION_RANGES[brand]
    minimum = common.parse_version(low)  # type: ignore[assignment]
    assert minimum is not None
    return VersionRange((minimum + (0, 0))[:3], _inclusive_ceiling(common.parse_version(high)))


def choice_payload_schema() -> ValueSchema:
    """The ``model-provider.choice.v1`` payload: one Provider/Model selection.

    ``credentialRef`` is a secret *reference*; content never travels here.
    """
    return ValueSchema(
        "object",
        properties=(
            ("provider", ValueSchema("string")),
            ("model", ValueSchema("string")),
            ("endpoint", ValueSchema("string", nullable=True)),
            ("protocol", ValueSchema("string")),
            ("credentialRef", ValueSchema("string", nullable=True)),
            ("brandFields", ValueSchema("object", nullable=True)),
        ),
        required=("provider", "model", "protocol"),
    )


def _claims(brand: str) -> tuple[FieldClaim, ...]:
    handle = HANDLE_IDS[brand]
    claims = [FieldClaim("file", handle, ("session", "model"))]
    if brand == "pi":
        claims.append(FieldClaim("file", handle, ("providers",)))
    elif brand == "codex":
        claims.extend((
            FieldClaim("file", handle, ("model",)),
            FieldClaim("file", handle, ("model_provider",)),
            FieldClaim("file", handle, ("model_providers",)),
        ))
    else:
        claims.append(FieldClaim("file", handle, ("env",)))
    claims.append(FieldClaim("environment", handle, (SECRET_SLOTS[brand],)))
    return tuple(claims)


def descriptor_for(brand: str) -> ConfigurationAdapterDescriptor:
    """The real C2 ``ConfigurationAdapterDescriptor`` for one brand."""
    if brand not in BRANDS:
        raise ValueError(f"unknown brand {brand!r}")
    return ConfigurationAdapterDescriptor(
        ADAPTER_IDS[brand], "v1", FACET_ID, FACET_SCHEMA_VERSION,
        brand, native_version_range(brand), VersionRange(ADAPTER_VERSION),
        (ENTRY,), choice_payload_schema(), _claims(brand),
    )


def _local_request(payload: Mapping[str, Any]) -> ChoiceRequest:
    brand_fields = payload.get("brandFields") or {}
    return ChoiceRequest(
        provider_config_id=str(payload.get("providerConfigId") or payload["provider"]),
        model_id=payload["model"],
        endpoint=payload.get("endpoint"),
        protocol=payload["protocol"],
        credential_ref=payload.get("credentialRef"),
        provider_name=payload["provider"],
        brand_fields=dict(brand_fields),
    )


def _local_context(context: Any, expected_session_id: str | None = None) -> LocalAdapterContext:
    """Project the harness context onto the local shape (version gate facts)."""
    native = context.installation.native_version
    version = ".".join(str(part) for part in native) if native else None
    return LocalAdapterContext(
        target_handle=LocalTargetHandle(
            harness_id=context.installation.harness_id, scope="instance",
            identity=context.targets[0].handle.handle_id),
        harness_version=version,
        capabilities={"native_session_id": expected_session_id},
    )


_REFUSAL_CODES = {
    "capability-unsupported": ErrorCode.CAPABILITY_UNSUPPORTED,
    "target-conflict": ErrorCode.TARGET_CONFLICT,
}


def _to_refusal(refusal: LocalRefusal) -> AdapterRefusal:
    code = _REFUSAL_CODES.get(refusal.code, ErrorCode.CAPABILITY_UNSUPPORTED)
    return AdapterRefusal(code, refusal.message)


def _compiled_intents(context: Any, compiled: LocalIntentSet,
                      mounted_facts: Mapping[int, tuple[str, str]]) -> HarnessIntentSet:
    source = IntentSource(FACET_ID, "choice", FACET_SCHEMA_VERSION)
    intents = []
    for intent in compiled.intents:
        if isinstance(intent, LocalBindSecret):
            # Secrets bind against the environment target the host issued;
            # a file handle is never a secret slot.
            target = _harness_target_of_kind(context, "environment")
            intents.append(HarnessBindSecret(source, target, intent.slot, intent.secret_ref))
            continue
        target = _harness_target_of_kind(context, "file", intent.target_handle.identity)
        if isinstance(intent, CompileIntent):
            intents.append(SetField(source, target, FieldPath(intent.field_path), intent.typed_value))
        elif isinstance(intent, LocalMountContent):
            # codex's provider section: the golden TOML text parsed back into
            # the typed table (S-08② golden consistency by construction).
            endpoint, protocol = mounted_facts[id(intent)]
            table = _codex_provider_table(intent, endpoint, protocol)
            intents.append(SetField(source, target, FieldPath(("model_providers", table["name"])), table))
        else:  # pragma: no cover - the local vocabulary is closed
            raise ValueError(f"unsupported local intent {type(intent).__name__}")
    return HarnessIntentSet(tuple(intents))


def _harness_target_of_kind(context: Any, kind: str,
                            identity: str | None = None) -> HarnessTargetHandle:
    for target in context.targets:
        if target.kind != kind:
            continue
        if identity is None or target.handle.handle_id == identity:
            return target.handle
    wanted = identity or kind
    raise ValueError(f"adapter context lacks authorized {kind} target {wanted!r}")


def _codex_provider_table(mount: LocalMountContent, endpoint: str, protocol: str) -> dict[str, Any]:
    import tomllib

    provider = mount.content_ref.split(":", 1)[1]
    text = common.render_codex_provider_section(
        provider=provider, base_url=endpoint, protocol=protocol)
    parsed = tomllib.loads(text)
    return dict(parsed["model_providers"][provider])


def reconfiguration_for(brand: str, payload: Mapping[str, Any]) -> str:
    """'session-local' | 'restart-resume' | 'refused' for one choice.

    The brand reconfiguration declaration is a pinned semantic (conformance);
    the harness C2 compile surface does not carry it, so the controlled E2
    runtime reads it here to drive restart-resume honestly.
    """
    local_ctx = LocalAdapterContext(
        target_handle=LocalTargetHandle(harness_id=brand, scope="instance",
                                        identity=HANDLE_IDS[brand]),
        harness_version=common.SUPPORTED_VERSION_RANGES[brand][0],
    )
    result = _IMPL[brand]().compile(local_ctx, {}, _local_request(payload))
    if isinstance(result, LocalRefusal):
        return "refused"
    return result.reconfiguration


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
        verdict = self._impl.assess(_local_context(context), _local_request(request))
        return Assessment(verdict.verdict, reason=verdict.reason,
                          evidence_ref=f"assets.model-provider:{self.brand}:pin"
                          if verdict.verdict == "supported" else None)

    def compile(self, context: Any, before: Mapping[str, Any], desired: Mapping[str, Any]
                ) -> HarnessIntentSet | AdapterRefusal:
        payload = dict(desired)
        compiled = self._impl.compile(
            _local_context(context), before, _local_request(payload))
        if isinstance(compiled, LocalRefusal):
            return _to_refusal(compiled)
        # Keep the endpoint/protocol facts the local MountContent dropped, for
        # the codex golden table.
        mounted_facts: dict[int, tuple[str, str]] = {}
        for intent in compiled.intents:
            if isinstance(intent, LocalMountContent):
                mounted_facts[id(intent)] = (str(payload.get("endpoint") or ""), str(payload["protocol"]))
        return _compiled_intents(context, compiled, mounted_facts)

    def verify(self, context: Any, observed: Mapping[str, Any]) -> Match | Mismatch | VerificationUnknown:
        expected_session = observed.get("expected_native_session_id")
        local_ctx = _local_context(context, expected_session_id=expected_session
                                   if isinstance(expected_session, str) else None)
        verdict = self._impl.verify(local_ctx, observed)
        if verdict.verdict == "match":
            digest = hashlib.sha256(
                json.dumps(observed, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
            return Match(f"model-provider:readback:{digest}")
        if verdict.verdict == "mismatch":
            return Mismatch(verdict.reason or "native readback differs from the compiled intent")
        return VerificationUnknown(verdict.reason or "no read-back sample")

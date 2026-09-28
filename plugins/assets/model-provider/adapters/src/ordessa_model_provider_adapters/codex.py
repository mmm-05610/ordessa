"""Codex configuration adapter (``assets.model-provider.codex``), facet
``assets.model-provider`` — pure assess/compile/verify, E1.

Brand facts (provenance: official Codex config reference; t00-freeze §5):
``model_provider`` / ``model_providers.*`` live ONLY in the instance-private
``config.toml`` generation — a project ``.codex/config.toml`` must never
override these keys, so a project-scope target is a typed refusal. Writing the
config file alone is not evidence the session picked it up; a model-only
change may go session-local through the app-server thread control, a
provider change is restart-resume on the SAME thread.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common
from .types import (
    AdapterContext, Assessment, BindSecret, ChoiceRequest, CompileIntent,
    IntentSet, MountContent, Refusal, TargetHandle, Verdict,
)

ADAPTER_ID = "assets.model-provider.codex"
CONTRIBUTOR_VERSION = "1"


def registration_manifest() -> dict[str, Any]:
    return {
        "adapter_id": ADAPTER_ID,
        "facet_id": "assets.model-provider",
        "facet_schema_version": 1,
        "api_version": "v1",
        "harness_id": "codex",
        "supported_native_versions": common.RANGE_STRINGS["codex"],
        "native_target": common.NATIVE_TARGET["codex"],
        "entries": ("assess", "compile", "verify"),
        "payload_schema": "model-provider.choice.v1",
        "claims": {
            "config.toml (instance scope only)": (
                "model_provider", "model_providers.*", "model"),
        },
    }


class CodexAdapter:
    adapter_id = ADAPTER_ID
    registration_manifest = staticmethod(registration_manifest)

    def assess(self, context: AdapterContext, request: ChoiceRequest) -> Assessment:
        gate = common.version_in_range("codex", context.harness_version)
        if gate != "supported":
            reason = (f"native adapter version {context.harness_version!r} "
                      f"is {gate} for {common.RANGE_STRINGS['codex']}")
            return Assessment(gate, reason, harness_id="codex",
                              native_version=context.harness_version)
        try:
            common.translate_protocol("codex", request.protocol)
        except common.ProtocolUnsupported as error:
            return Assessment("unsupported", str(error), harness_id="codex",
                              native_version=context.harness_version)
        return Assessment("supported", None, harness_id="codex",
                          native_version=context.harness_version)

    def compile(
        self, context: AdapterContext, before: Mapping[str, Any],
        desired: ChoiceRequest,
    ) -> IntentSet | Refusal:
        if context.target_handle.scope != "instance":
            # A project .codex/config.toml cannot override provider keys; this
            # is a scope conflict, not a silent no-op (official config rules).
            return Refusal(
                "target-conflict",
                "codex provider keys cannot be written to a project "
                ".codex/config.toml; only the instance-private generation",
                details={"scope": context.target_handle.scope},
            )
        assessment = self.assess(context, desired)
        if assessment.verdict != "supported":
            return Refusal("capability-unsupported", assessment.reason or "not supported")
        brand = dict(desired.brand_fields)
        before_provider = brand.get("before_provider")
        provider_changed = before_provider is not None and before_provider != desired.provider_name
        session_field = CompileIntent(
            context.target_handle, ("model",), desired.model_id)
        if not provider_changed:
            return IntentSet(
                facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
                intents=(session_field,),
                reconfiguration="session-local",
            )
        # A different provider needs the instance-private provider table plus
        # the top-level selector, then a controlled restart that resumes the
        # SAME thread/session identity.
        intents: list[Any] = [
            MountContent(
                context.target_handle,
                "model_providers." + desired.provider_name,
                "codex-provider-section:" + desired.provider_name,
                common.digest_label(desired),
                mode="replace-owned",
            ),
            CompileIntent(context.target_handle, ("model_provider",), desired.provider_name),
            session_field,
        ]
        if desired.credential_ref:
            intents.append(BindSecret(
                context.target_handle, "CODEX_API_KEY", desired.credential_ref))
        return IntentSet(
            facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
            intents=tuple(intents),
            reconfiguration="restart-resume",
            resume_expectation={"native_session_id": context.capabilities.get("native_session_id")},
        )

    def verify(self, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
        read_back = observed.get("readback")
        if not isinstance(read_back, Mapping):
            return Verdict("unknown", "no read-back sample; a written config.toml "
                                      "is a projection, not an applied fact")
        expected = observed.get("desired_model")
        provider = observed.get("desired_provider")
        if provider is not None and read_back.get("provider") != provider:
            return Verdict("mismatch", "session provider differs from the compiled intent",
                           evidence={"readback": dict(read_back)})
        if read_back.get("model") != expected:
            return Verdict("mismatch", "session model differs from the compiled intent",
                           evidence={"readback": dict(read_back)})
        if observed.get("native_session_id") != context.capabilities.get("native_session_id"):
            return Verdict("mismatch", "native session identity changed across "
                                       "the reconfiguration")
        return Verdict("match", None, evidence={"applied_layer": "thread-readback"})

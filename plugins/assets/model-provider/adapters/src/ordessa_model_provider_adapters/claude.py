"""Claude Code configuration adapter (``assets.model-provider.claude``), facet
``assets.model-provider`` — pure assess/compile/verify, E1.

Brand facts (provenance: official model-config docs; the in-repo controlled
evidence ``plugins/harness/packaging/claude/provider-*.mjs``): the model
selection and ``ANTHROPIC_BASE_URL`` are two different things. The model goes
session-local through the session config control; an endpoint/provider change
requires a new private generation and a controlled restart that resumes the
SAME native session id — a ``session/new`` transcript replay is never resume
evidence, and verify refuses a changed session identity.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common
from .types import (
    AdapterContext, Assessment, BindSecret, ChoiceRequest, CompileIntent,
    IntentSet, Refusal, Verdict,
)

ADAPTER_ID = "assets.model-provider.claude"
CONTRIBUTOR_VERSION = "1"


def registration_manifest() -> dict[str, Any]:
    return {
        "adapter_id": ADAPTER_ID,
        "facet_id": "assets.model-provider",
        "facet_schema_version": 1,
        "api_version": "v1",
        "harness_id": "claude-code",
        "supported_native_versions": common.RANGE_STRINGS["claude-code"],
        "native_target": common.NATIVE_TARGET["claude-code"],
        "entries": ("assess", "compile", "verify"),
        "payload_schema": "model-provider.choice.v1",
        "claims": {
            "settings.json env (instance scope only)": ("ANTHROPIC_BASE_URL",),
            "session config": ("model",),
        },
    }


class ClaudeAdapter:
    adapter_id = ADAPTER_ID
    registration_manifest = staticmethod(registration_manifest)

    def assess(self, context: AdapterContext, request: ChoiceRequest) -> Assessment:
        gate = common.version_in_range("claude-code", context.harness_version)
        if gate != "supported":
            reason = (f"native adapter version {context.harness_version!r} "
                      f"is {gate} for {common.RANGE_STRINGS['claude-code']}")
            return Assessment(gate, reason, harness_id="claude-code",
                              native_version=context.harness_version)
        try:
            common.translate_protocol("claude-code", request.protocol)
        except common.ProtocolUnsupported as error:
            return Assessment("unsupported", str(error), harness_id="claude-code",
                              native_version=context.harness_version)
        return Assessment("supported", None, harness_id="claude-code",
                          native_version=context.harness_version)

    def compile(
        self, context: AdapterContext, before: Mapping[str, Any],
        desired: ChoiceRequest,
    ) -> IntentSet | Refusal:
        if context.target_handle.scope != "instance":
            return Refusal(
                "target-conflict",
                "claude provider env keys are instance-scoped; a project-scope "
                "write would leak routing into unrelated sessions",
                details={"scope": context.target_handle.scope},
            )
        assessment = self.assess(context, desired)
        if assessment.verdict != "supported":
            return Refusal("capability-unsupported", assessment.reason or "not supported")
        params = desired.params
        if params is not None and params.has_any():
            # 016 MPX: the claude-code first-hand pin in this tree is the env
            # routing key + session model only; none of the four request-param
            # families has a pinned native field here. Refusing is the honest
            # projection - a settings-key guess would silently no-op.
            return Refusal(
                "capability-unsupported",
                "claude-code has no first-hand request-param key in this tree "
                "(the settings.json pin carries ANTHROPIC_BASE_URL; effort / "
                "budget / timeout / retry have no in-repo field)",
                details={"families": [name for name, value in (
                    ("reasoningEffort", params.reasoning_effort),
                    ("maxTokens", params.max_tokens),
                    ("timeoutMs", params.timeout_ms),
                    ("retry", params.retry)) if value is not None]})
        brand = dict(desired.brand_fields)
        if not brand.get("endpoint_changed"):
            # model-only: the per-native-session Query-level model config, one
            # session-local intent - the endpoint is NOT touched (the two are
            # different settings and stay independent).
            return IntentSet(
                facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
                intents=(CompileIntent(
                    context.target_handle, ("session", "model"), desired.model_id,
                ),),
                reconfiguration="session-local",
            )
        # endpoint/provider change: a new private generation with the env
        # routing key, then a controlled restart resuming the SAME native
        # session id. A credential change rides the same path.
        intents: list[Any] = [
            CompileIntent(
                context.target_handle, ("env", "ANTHROPIC_BASE_URL"), desired.endpoint,
            ),
        ]
        if desired.credential_ref:
            intents.append(BindSecret(
                context.target_handle, "ANTHROPIC_AUTH_TOKEN", desired.credential_ref))
        return IntentSet(
            facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
            intents=tuple(intents),
            reconfiguration="restart-resume",
            resume_expectation={"native_session_id": context.capabilities.get("native_session_id")},
        )

    def verify(self, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
        read_back = observed.get("readback")
        if not isinstance(read_back, Mapping):
            return Verdict("unknown", "no read-back sample; settings.json bytes "
                                      "are a projection, not an applied fact")
        expected = observed.get("desired_model")
        if read_back.get("model") != expected:
            return Verdict("mismatch", "session model differs from the desired choice",
                           evidence={"readback": dict(read_back)})
        session_now = observed.get("native_session_id")
        expected_session = context.capabilities.get("native_session_id")
        if session_now != expected_session:
            return Verdict("mismatch", "native session identity changed; a "
                                       "session/new must never impersonate resume")
        return Verdict("match", None, evidence={"applied_layer": "session-readback"})

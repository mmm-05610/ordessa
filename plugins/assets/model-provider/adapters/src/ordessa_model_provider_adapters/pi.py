"""Pi configuration adapter (``assets.model-provider.pi``), facet
``assets.model-provider`` — pure assess/compile/verify, E1.

Brand facts (provenance: ``docs/design/model-provider/research-and-reuse.md``,
official Pi docs @ ``2b0a123d``): ``models.json`` declares providers; a
session's ``set_model`` RPC switches the model *parameter*. An RPC command
success is not evidence a later model request succeeds - the read-back layer
decides. Provider add/remove or a credential change is never session-local.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common
from .types import (
    AdapterContext, Assessment, BindSecret, ChoiceRequest, CompileIntent,
    IntentSet, Refusal, TargetHandle, Verdict,
)

ADAPTER_ID = "assets.model-provider.pi"
CONTRIBUTOR_VERSION = "1"


def registration_manifest() -> dict[str, Any]:
    return {
        "adapter_id": ADAPTER_ID,
        "facet_id": "assets.model-provider",
        "facet_schema_version": 1,
        "api_version": "v1",
        "harness_id": "pi",
        "supported_native_versions": common.RANGE_STRINGS["pi"],
        "native_target": common.NATIVE_TARGET["pi"],
        "entries": ("assess", "compile", "verify"),
        "payload_schema": "model-provider.choice.v1",
        "claims": {
            "models.json": ("providers.<id>", "session model via set_model RPC"),
            "settings.json (instance scope)": ("retry",),
        },
    }


class PiAdapter:
    adapter_id = ADAPTER_ID
    registration_manifest = staticmethod(registration_manifest)

    def assess(self, context: AdapterContext, request: ChoiceRequest) -> Assessment:
        gate = common.version_in_range("pi", context.harness_version)
        if gate != "supported":
            reason = (f"native adapter version {context.harness_version!r} "
                      f"is {gate} for {common.RANGE_STRINGS['pi']}")
            return Assessment(gate, reason, harness_id="pi",
                              native_version=context.harness_version)
        try:
            common.translate_protocol("pi", request.protocol)
        except common.ProtocolUnsupported as error:
            return Assessment("unsupported", str(error), harness_id="pi",
                              native_version=context.harness_version)
        return Assessment("supported", None, harness_id="pi",
                          native_version=context.harness_version)

    def compile(
        self, context: AdapterContext, before: Mapping[str, Any],
        desired: ChoiceRequest,
    ) -> IntentSet | Refusal:
        assessment = self.assess(context, desired)
        if assessment.verdict != "supported":
            return Refusal("capability-unsupported", assessment.reason or "not supported")
        brand = dict(desired.brand_fields)
        provider_ready = bool(brand.get("provider_in_instance"))
        credential_changed = bool(brand.get("credential_changed"))
        params = desired.params
        param_intents: list[Any] = []
        params_escalate = False
        if params is not None and params.has_any():
            param_intents, refusal, params_escalate = _compile_params(
                context, before, desired, params)
            if refusal is not None:
                return refusal
        if provider_ready and not credential_changed and not params_escalate:
            # session-local: the provider config already lives in the private
            # instance's models.json; the model travels via the set_model RPC.
            return IntentSet(
                facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
                intents=(CompileIntent(
                    context.target_handle, ("session", "model"), desired.model_id,
                ),),
                reconfiguration="session-local",
            )
        # provider add/remove or an auth change needs a new private generation
        # and a controlled restart that resumes the SAME native session. The
        # provider enters as ONE golden object (provenance:
        # ordessa_harness.native_materialization.render_pi_provider) — the C4
        # merge authority owns a declared array subtree as a unit, so the
        # whole provider object is a single typed field write.
        _, dialect = common.translate_protocol("pi", desired.protocol)
        provider_object = {
            "baseUrl": desired.endpoint,
            "api": dialect,
        }
        intents: list[Any] = []
        golden_written = any(
            isinstance(intent, CompileIntent)
            and intent.field_path == ("providers", desired.provider_name)
            for intent in param_intents)
        if not golden_written:
            # a param family that already rewrote the provider subtree (the
            # budget golden object) owns the write; a second base object here
            # would clobber the models array it just preserved
            intents.append(CompileIntent(
                context.target_handle,
                ("providers", desired.provider_name), provider_object,
            ))
        intents.extend(param_intents)
        if desired.credential_ref:
            intents.append(BindSecret(
                context.target_handle, "api_key", desired.credential_ref))
        return IntentSet(
            facet_id="assets.model-provider", contributor_version=CONTRIBUTOR_VERSION,
            intents=tuple(intents),
            reconfiguration="restart-resume",
            resume_expectation={"native_session_id": context.capabilities.get("native_session_id")},
        )

    def verify(self, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
        read_back = observed.get("readback")
        if not isinstance(read_back, Mapping):
            return Verdict("unknown", "no read-back sample; a projected file digest "
                                      "and an RPC ack are not evidence of effect")
        expected = observed.get("desired_model")
        if read_back.get("model") != expected:
            return Verdict("mismatch", "session read-back differs from the desired model",
                           evidence={"readback": dict(read_back)})
        session_now = observed.get("native_session_id")
        expected_session = context.capabilities.get("native_session_id")
        if session_now != expected_session:
            return Verdict("mismatch", "native session identity changed; "
                                       "a session/new must never impersonate resume")
        return Verdict("match", None, evidence={"applied_layer": "session-readback"})

def _compile_params(context: AdapterContext, before: Mapping[str, Any],
                    desired: ChoiceRequest,
                    params: Any) -> tuple[list[Any], Refusal | None, bool]:
    """The 016 MPX param families for pi, projected from first-hand pins.

    ``maxTokens`` (budget) rides the golden provider object, rewritten from
    the CURRENT native sample (``before``) so the models array survives; the
    retry family writes the pinned block of the native ``settings.json``
    target (``deploy/pi/settings.json`` shape). Reasoning effort and timeout
    have no authorized in-facet pin and refuse with that exact reason.
    """
    intents: list[Any] = []
    escalated = False
    if params.reasoning_effort is not None:
        return [], Refusal(
            "capability-unsupported",
            "pi reasoning effort has no first-hand pin inside this facet's "
            "targets: PiConfig.thinking / --thinking are launch-descriptor "
            "facts, and the models.json samplingParams.thinking pin covers "
            "only the {'type': 'disabled'} spelling - no level enum to "
            "project without guessing"), False
    if params.max_tokens is not None:
        sample = before.get("providers", {}) if isinstance(before, Mapping) else {}
        provider_sample = sample.get(desired.provider_name) \
            if isinstance(sample, Mapping) else None
        models = provider_sample.get("models") \
            if isinstance(provider_sample, Mapping) else None
        if not isinstance(models, list) or not models:
            return [], Refusal(
                "capability-unsupported",
                "pi budget (maxTokens) needs the current native provider "
                "sample in `before`; rewriting the provider subtree without "
                "it would clobber the models array"), False
        rewritten: list[Any] = []
        hit = False
        for entry in models:
            if isinstance(entry, Mapping) and entry.get("id") == desired.model_id:
                entry = {**dict(entry), common.PI_MAX_TOKENS_KEY: params.max_tokens}
                hit = True
            rewritten.append(entry)
        if not hit:
            return [], Refusal(
                "capability-unsupported",
                f"model {desired.model_id!r} is not in the current native "
                "sample; a budget write may only retune a declared entry"), False
        # The golden object keeps the sample's untouched fields (cost, input,
        # sibling models) but the CHOICE's own routing facts win: an endpoint
        # or protocol change in the same compile is never silently dropped.
        _, dialect = common.translate_protocol("pi", desired.protocol)
        provider_object = {
            **dict(provider_sample),
            "baseUrl": desired.endpoint
            if desired.endpoint is not None else provider_sample.get("baseUrl"),
            "api": dialect,
            "models": rewritten,
        }
        intents.append(CompileIntent(
            context.target_handle,
            ("providers", desired.provider_name), provider_object))
        escalated = True
    if params.timeout_ms is not None:
        return [], Refusal(
            "capability-unsupported",
            "the only first-hand pi timeout fact (timeoutMs) lives on the "
            "harness deployment descriptor, outside this facet's authorized "
            "targets"), False
    if params.retry is not None:
        retry = params.retry
        value = {
            "enabled": retry["enabled"], "maxRetries": retry["maxRetries"],
            "provider": {"maxRetries": retry["provider"]["maxRetries"],
                         "maxRetryDelayMs": retry["provider"]["maxRetryDelayMs"]},
        }
        intents.append(CompileIntent(
            TargetHandle(harness_id=context.target_handle.harness_id,
                         scope="instance",
                         identity=common.PI_SETTINGS_HANDLE_ID),
            ("retry",), value))
        escalated = True
    return intents, None, escalated

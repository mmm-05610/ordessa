"""Pi configuration adapter (``assets.model-provider.pi``), facet
``assets.model-provider`` — pure assess/compile/verify, E1.

Brand facts (provenance: ``docs/implementation/design/model-provider/research-and-reuse.md``,
official Pi docs @ ``2b0a123d``): ``models.json`` declares providers; a
session's ``set_model`` RPC switches the model *parameter*. An RPC command
success is not evidence a later model request succeeds - the read-back layer
decides. Provider add/remove or a credential change is never session-local.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import acp_model_facts as common
from ordessa_execution_agents.harness.configuration.validation.version_ranges import version_in_range
from ordessa_execution_agents.harness.definitions.model_compilation import (
    AdapterContext, Assessment, BindSecret, ChoiceRequest, CompileIntent,
    IntentSet, Refusal, RequestParams, TargetHandle, Verdict,
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
        gate = version_in_range(context.harness_version, common.VERSION_RANGE)
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
        if (context.target_handle.harness_id != "pi" or context.target_handle.scope != "instance"
                or not common.identity_text(context.target_handle.identity)):
            return Refusal("target-conflict", "Pi compiler requires its own explicit instance target")
        assessment = self.assess(context, desired)
        if assessment.verdict != "supported":
            return Refusal("capability-unsupported", assessment.reason or "not supported")
        if not isinstance(desired.brand_fields, Mapping):
            return Refusal("capability-unsupported", "brand facts must be an object")
        brand = dict(desired.brand_fields)
        if any(name in brand and type(brand[name]) is not bool
               for name in ("provider_in_instance", "credential_changed", "endpoint_changed")):
            return Refusal("capability-unsupported", "provider and credential change facts must be booleans")
        if not common.identity_text(desired.model_id) or not common.identity_text(desired.provider_name):
            return Refusal("capability-unsupported", "model and provider identities must be explicit text")
        if desired.endpoint is not None and not common.identity_text(desired.endpoint):
            return Refusal("capability-unsupported", "endpoint must be explicit text")
        if desired.credential_ref is not None and not common.identity_text(desired.credential_ref):
            return Refusal("capability-unsupported", "secret reference must be explicit text")
        provider_ready = brand.get("provider_in_instance", False)
        credential_changed = brand.get("credential_changed", False)
        endpoint_changed = brand.get("endpoint_changed", False)
        if credential_changed and desired.credential_ref is None:
            return Refusal("capability-unsupported", "credential change requires a secret reference")
        params = desired.params
        param_intents: list[Any] = []
        params_escalate = False
        if params is not None:
            if not isinstance(params, RequestParams):
                return Refusal("capability-unsupported", "request params must use the public DTO")
            try:
                params = RequestParams.from_record({"reasoningEffort": params.reasoning_effort,
                    "maxTokens": params.max_tokens, "timeoutMs": params.timeout_ms, "retry": params.retry})
            except ValueError as error:
                return Refusal("capability-unsupported", str(error))
        if params is not None and params.has_any():
            param_intents, refusal, params_escalate = _compile_params(
                context, before, desired, params)
            if refusal is not None:
                return refusal
        if "provider_in_instance" not in brand:
            return Refusal("capability-unsupported", "provider presence observation unavailable")
        if endpoint_changed and not common.identity_text(desired.endpoint):
            return Refusal("capability-unsupported", "endpoint change requires explicit endpoint")
        if provider_ready and not credential_changed and not endpoint_changed and not params_escalate:
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
        # ordessa_server_product.native_materialization.render_pi_provider) — the C4
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
        if endpoint_changed and provider_ready and not golden_written:
            providers = before.get("providers") if isinstance(before, Mapping) else None
            observed = providers.get(desired.provider_name) if isinstance(providers, Mapping) else None
            if not isinstance(observed, Mapping):
                return Refusal("capability-unsupported", "endpoint change requires current native provider sample")
            if not common.safe_provider_sample(observed):
                return Refusal("capability-unsupported", "native provider credential material requires the credential owner")
            intents.append(CompileIntent(context.target_handle, ("providers", desired.provider_name),
                {**dict(observed), "baseUrl": desired.endpoint, "api": dialect}))
        if not provider_ready and not golden_written:
            if not common.identity_text(desired.endpoint):
                return Refusal("capability-unsupported", "provider addition requires explicit endpoint")
            # a param family that already rewrote the provider subtree (the
            # budget golden object) owns the write; a second base object here
            # would clobber the models array it just preserved
            intents.append(CompileIntent(
                context.target_handle,
                ("providers", desired.provider_name), provider_object,
            ))
        intents.extend(param_intents)
        intents.append(CompileIntent(context.target_handle, ("session", "model"), desired.model_id))
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
        if (context.target_handle.harness_id != "pi" or context.target_handle.scope != "instance"
                or not common.identity_text(context.target_handle.identity)):
            return Verdict("unknown", "Pi instance target identity evidence unavailable")
        read_back = observed.get("readback")
        if not isinstance(read_back, Mapping):
            return Verdict("unknown", "no read-back sample; a projected file digest "
                                      "and an RPC ack are not evidence of effect")
        expected = observed.get("desired_model")
        if not common.identity_text(expected) or not common.identity_text(read_back.get("model")):
            return Verdict("unknown", "model identity evidence unavailable")
        if read_back.get("model") != expected:
            return Verdict("mismatch", "session read-back differs from the desired model",
                           evidence={"readback": dict(read_back)})
        session_now = observed.get("native_session_id")
        expected_session = context.capabilities.get("native_session_id")
        if not common.identity_text(session_now) or not common.identity_text(expected_session):
            return Verdict("unknown", "native session identity evidence unavailable")
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
    target (``deployment/settings.json`` shape). Reasoning effort and timeout
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
        if sum(isinstance(entry, Mapping) and entry.get("id") == desired.model_id for entry in models) > 1:
            return [], Refusal("capability-unsupported", "duplicate model identity in current native sample"), False
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
        if not common.safe_provider_sample(provider_sample):
            return [], Refusal("capability-unsupported", "native provider credential material requires the credential owner"), False
        endpoint = desired.endpoint if desired.endpoint is not None else provider_sample.get("baseUrl")
        if not common.identity_text(endpoint):
            return [], Refusal("capability-unsupported", "budget requires observed or desired endpoint"), False
        # The golden object keeps the sample's untouched fields (cost, input,
        # sibling models) but the CHOICE's own routing facts win: an endpoint
        # or protocol change in the same compile is never silently dropped.
        _, dialect = common.translate_protocol("pi", desired.protocol)
        provider_object = {
            **dict(provider_sample),
            "baseUrl": endpoint,
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

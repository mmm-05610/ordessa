"""Pure Pi 0.5 native model-option compiler over independently read facts.

Pinned ACP config.js encodes option values as provider + '/' + model id and
decodes at the FIRST slash. Model ids may contain further slashes. We require
the resulting value in the native options, never synthesize availability.
This narrow path switches an already available native model only. Endpoint,
credentials and other provider changes require their own observed/apply path.
"""
from collections.abc import Mapping

from ordessa_harness_api import AdapterRefusal, ApplicationTarget, ErrorCode, IntentSource, InvokeAction


def compile_live_model(snapshot, target: ApplicationTarget, desired, source: IntentSource):
    """No I/O or effects; runtime owns the snapshot and executor revalidates it."""
    def refuse(message):
        return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, message)

    if (not isinstance(target, ApplicationTarget) or snapshot.target != target
        or snapshot.busy is not False or not snapshot.native_generation):
        return refuse("Current idle native owner observation required")
    if (not isinstance(source, IntentSource) or source.facet_id != "assets.model-provider"
        or source.contribution_version != "1"):
        return refuse("Model facet source required")
    if not isinstance(desired, Mapping) or not {"provider", "model"} <= set(desired):
        return refuse("Native model selection cannot apply provider settings or request parameters")
    full_choice = set(desired) != {"provider", "model"}
    if full_choice and (
        not {"provider", "model", "protocol", "endpoint"} <= set(desired)
        or set(desired) - {"provider", "model", "protocol", "endpoint", "credentialRef", "brandFields", "requestParams"}
        or desired.get("credentialRef") is not None
        or desired.get("brandFields") not in (None, {})
        or desired.get("requestParams") not in (None, {})
    ):
        return refuse("Native selection cannot apply credentials, hints or request parameters")
    provider, model = desired["provider"], desired["model"]
    if any(type(value) is not str or not value or value != value.strip()
           or len(value) > 4096 or any(ord(char) < 32 for char in value)
           for value in (provider, model)) or "/" in provider:
        return refuse("Invalid native provider/model identity")
    options = snapshot.config_options
    if not isinstance(options, list) or any(not isinstance(option, dict) for option in options):
        return refuse("Malformed native options")
    entries = [option for option in options if option.get("id") == "model"]
    if len(entries) != 1 or entries[0].get("type") != "select":
        return refuse("One native model selector required")
    values = entries[0].get("options")
    if not isinstance(values, list) or any(not isinstance(option, dict) for option in values):
        return refuse("Malformed native model catalog")
    native_value = provider + "/" + model
    matches = [option for option in values if option.get("value") == native_value]
    if len(matches) != 1:
        return refuse("Native model is absent or ambiguous")
    if full_choice:
        metadata = matches[0].get("_meta")
        facts = metadata.get("ordessaModel") if isinstance(metadata, dict) else None
        # This mapping is the pinned Pi dialect, not a claim supplied by the
        # resource plugin. Endpoint equality is deliberately exact.
        if (not isinstance(facts, dict) or set(facts) != {"provider", "model", "api", "baseUrl"}
            or facts["provider"] != provider or facts["model"] != model
            or desired["protocol"] != "openai-chat" or facts["api"] != "openai-completions"
            or desired["endpoint"] != facts["baseUrl"]):
            return refuse("Requested routing differs from independently observed native model")
    return InvokeAction(source, "acp.session.set-config-option", "1",
                        {"configId": "model", "value": native_value},
                        "pi-native-model:" + native_value)

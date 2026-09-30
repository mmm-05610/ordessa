"""Current real catalogue resolution, with no native effects or secret reads."""
from dataclasses import FrozenInstanceError

import pytest

from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver
from ordessa_model_provider.testing import RecordingSecretStore, harness_descriptor, seed_credential_row, wire_body
from ordessa_model_provider_adapters.bridge import choice_payload_schema
from ordessa_server.errors import ServerError


FACTS = {"provider_in_instance": False, "credential_changed": False}


def saved(catalog, **overrides):
    body = wire_body(configuration=[], protocols=["openai-chat"],
                     endpoints={"openai-chat": "http://127.0.0.1:8765/v1"})
    body.update(overrides)
    record = catalog.create("create", body)
    return {"harnessId": "pi", "providerConfigId": record["id"], "modelId": "m1"}


def resolve(catalog, choice, **kwargs):
    return ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema()).resolve(
        choice, harness_id=choice["harnessId"], brand_fields=FACTS, **kwargs)


def refused(code, call):
    with pytest.raises(ServerError) as caught:
        call()
    assert caught.value.code == code


def test_real_catalogue_projects_valid_c2_payload_and_separate_fence(catalog):
    choice = saved(catalog)
    result = resolve(catalog, choice)
    assert result.payload == {"provider": "acme", "model": "m1", "protocol": "openai-chat",
                              "endpoint": "http://127.0.0.1:8765/v1", "credentialRef": None,
                              "brandFields": FACTS}
    assert choice_payload_schema().validate(result.payload) == result.payload
    assert result.revisions["configVersion"] == 1
    assert result.revisions["providerConfigId"] == choice["providerConfigId"]
    assert "configVersion" not in result.payload


def test_reference_only_never_reads_secret_store(catalog, stack, harnesses):
    seed_credential_row(stack["database"])
    harnesses._descriptors["pi"] = harness_descriptor(credential_kind="api_key")
    catalog.secret_store = RecordingSecretStore()
    choice = saved(catalog, credentialId="cred-1")
    result = resolve(catalog, choice)
    assert result.payload["credentialRef"] == "ref://cred-1"
    assert catalog.secret_store.reads == 0
    assert "loc://" not in repr(result)
    assert "sekret" not in repr(result)


@pytest.mark.parametrize("facts", [{}, {"provider_in_instance": False},
                                  {"provider_in_instance": False, "credential_changed": 0}])
def test_runtime_facts_cannot_be_guessed(catalog, facts):
    choice = saved(catalog)
    resolver = ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema())
    refused("RUNTIME_FACTS_UNVERIFIED", lambda: resolver.resolve(choice, harness_id="pi", brand_fields=facts))


def test_secrets_in_runtime_facts_refuse(catalog):
    choice = saved(catalog)
    resolver = ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema())
    refused("PROFILE_CONFIGURATION_INVALID", lambda: resolver.resolve(
        choice, harness_id="pi", brand_fields={**FACTS, "apiKey": "secret"}))


def test_snapshots_are_detached_and_frozen(catalog):
    choice = saved(catalog)
    facts = {**FACTS, "nested": {"values": [1]}}
    result = ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema()).resolve(
        choice, harness_id="pi", brand_fields=facts)
    facts["nested"]["values"].append(2)
    payload = result.payload
    payload["brandFields"]["nested"]["values"].append(3)
    result.revisions["harnessProtocols"].clear()
    assert result.payload["brandFields"]["nested"]["values"] == [1]
    assert result.revisions["harnessProtocols"] == ["openai-chat"]
    with pytest.raises(FrozenInstanceError):
        result._payload_json = "{}"


@pytest.mark.parametrize("key,value", [("apiKey", "secret"), ("modelId", ""), ("modelId", 1)])
def test_invalid_saved_atomic_choice(catalog, key, value):
    choice = saved(catalog)
    choice[key] = value
    refused("PROFILE_FACET_VALUE_INVALID", lambda: resolve(catalog, choice))


def test_current_archive_model_and_binding_are_revalidated(catalog):
    choice = saved(catalog)
    refused("MODEL_NOT_FOUND", lambda: resolve(catalog, {**choice, "modelId": "removed"}))
    refused("SELECTION_UNSUPPORTED", lambda: resolve(catalog, {**choice, "harnessId": "codex"}))
    original = catalog.records.get
    catalog.records.get = lambda record_id: {**original(record_id), "archived_at": "now"}
    refused("PROVIDER_ARCHIVED", lambda: resolve(catalog, choice))


def test_missing_provider_and_unregistered_harness(catalog):
    choice = saved(catalog)
    refused("PROVIDER_NOT_FOUND", lambda: resolve(catalog, {**choice, "providerConfigId": "missing"}))
    refused("HARNESS_UNAVAILABLE", lambda: resolve(catalog, {**choice, "harnessId": "absent"}))


def test_ambiguous_protocol_requires_explicit_selection(catalog):
    choice = saved(catalog, harness="codex", protocols=["openai-chat", "openai-responses"])
    choice["harnessId"] = "codex"
    refused("PROTOCOL_AMBIGUOUS", lambda: resolve(catalog, choice))
    assert resolve(catalog, choice, protocol="responses").payload["protocol"] == "openai-responses"
    refused("PROTOCOL_UNSUPPORTED", lambda: resolve(catalog, choice, protocol="anthropic"))


def test_undeclared_protocols_are_unknown_and_not_defaulted(catalog):
    choice = saved(catalog, protocols=None, endpoints=None)
    refused("PROTOCOL_UNSUPPORTED", lambda: resolve(catalog, choice))


def test_model_protocol_and_capability_facts_are_strict(catalog):
    choice = saved(catalog, models=[{"modelId": "m1", "availability": "available",
                                    "protocols": ["openai-chat"], "capabilities": {"toolCall": True}}])
    assert resolve(catalog, choice, required_capabilities={"toolCall": True}).payload["model"] == "m1"
    refused("SELECTION_UNSUPPORTED", lambda: resolve(catalog, choice, required_capabilities={"reasoning": True}))
    original = catalog.project
    catalog.project = lambda row: {**original(row), "models": [{"modelId": "m1", "availability": "available",
                                                              "capabilities": {"typo": True}}]}
    refused("PROVIDER_MODEL_INVALID", lambda: resolve(catalog, choice))


def test_unavailable_model_refuses(catalog):
    choice = saved(catalog, models=[{"modelId": "m1", "availability": "unavailable", "unavailableReason": "gone"}])
    refused("SELECTION_UNSUPPORTED", lambda: resolve(catalog, choice))


def test_missing_credential_kind_or_reference_refuses(catalog, stack, harnesses):
    seed_credential_row(stack["database"])
    choice = saved(catalog, harness=None, credentialId="cred-1")
    refused("CREDENTIAL_UNRESOLVED", lambda: resolve(catalog, choice))
    harnesses._descriptors["pi"] = harness_descriptor(credential_kind="api_key")
    catalog.credentials._rows.clear()
    refused("CREDENTIAL_UNRESOLVED", lambda: resolve(catalog, choice))


def test_mutating_catalogue_during_resolution_refuses(catalog):
    choice = saved(catalog)
    original = catalog.project
    def changing_projection(row):
        result = original(row)
        catalog.update(row["id"], row["version"], "change", {"displayName": "changed"})
        return result
    catalog.project = changing_projection
    # update itself uses project: mutate once, then restore for its own reads.
    def once(row):
        catalog.project = original
        return changing_projection(row)
    catalog.project = once
    refused("CONFIG_REVISION_CONFLICT", lambda: resolve(catalog, choice))


def test_invalid_endpoint_is_revalidated(catalog):
    choice = saved(catalog)
    original = catalog.project
    catalog.project = lambda row: {**original(row), "endpoints": {"openai-chat": "http://10.0.0.1"}}
    refused("PROFILE_CONFIGURATION_INVALID", lambda: resolve(catalog, choice))


def test_current_catalogue_updates_replace_payload_and_fence(catalog):
    choice = saved(catalog)
    before = resolve(catalog, choice)
    catalog.update(choice["providerConfigId"], 1, "change", {
        "endpoints": {"openai-chat": "http://127.0.0.1:8766/v1"},
        "models": [{"modelId": "m1", "availability": "available", "capabilities": {"reasoning": True}}],
    })
    after = resolve(catalog, choice, required_capabilities={"reasoning": True})
    assert before.payload["endpoint"] == "http://127.0.0.1:8765/v1"
    assert after.payload["endpoint"] == "http://127.0.0.1:8766/v1"
    assert after.revisions["configVersion"] == 2
    assert before.revisions["configObjectDigest"] != after.revisions["configObjectDigest"]
    assert before.revisions["modelsObjectDigest"] != after.revisions["modelsObjectDigest"]


def test_model_protocol_exclusion_refuses(catalog):
    choice = saved(catalog, models=[{"modelId": "m1", "availability": "available",
                                    "protocols": ["openai-responses"]}])
    refused("PROTOCOL_UNSUPPORTED", lambda: resolve(catalog, choice))


def test_harness_protocol_changes_during_resolution_refuse(catalog, harnesses):
    choice = saved(catalog)
    original = catalog.project
    # Change after the first protocol read.
    original_protocols = harnesses.wire_protocols
    calls = 0
    def changing_protocols(harness):
        nonlocal calls
        calls += 1
        return original_protocols(harness) if calls == 1 else {"openai-responses": ""}
    harnesses.wire_protocols = changing_protocols
    # project also derives compatibility (two reads), so suppress that derived
    # read in this controlled race; the actual row/models still come from it.
    projected = original(catalog.records.get(choice["providerConfigId"]))
    calls = 0
    catalog.project = lambda row: projected
    refused("CONFIG_REVISION_CONFLICT", lambda: resolve(catalog, choice))

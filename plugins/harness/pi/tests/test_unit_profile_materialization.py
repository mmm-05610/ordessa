"""Fixed Pi Profile native files through a bound remote-shaped FileArea."""
from copy import deepcopy
from dataclasses import replace
import json
import posixpath
from types import SimpleNamespace

import pytest
from ordessa_execution_agents.preparation import PreparedAgent, PreparedHarness, ConfigurationResources, SessionBootstrap
from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.profiles import ProfileRevisionRef, content_digest, encode_revision_ref, canonical_content
from ordessa_execution_api.environment.operations import safe_json
from ordessa_harness_pi.configuration.unit_materialization import PiUnitProfileMaterializer, PiProfileMaterializationRefused

DEFINITION = {"environmentNamespace": "env", "definitionId": "pi", "revision": "1"}
FACTS = {"action": "prepare", "query": False, "operationRef": "operation"}


class Files:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.bad_readback = False
        self.fail_write = False

    def root(self):
        return "/remote-unit"

    def path(self, relative):
        return posixpath.join(self.root(), relative)

    def ensure(self, relative):
        self.calls.append(("ensure", relative))
        return self.path(relative)

    def write_text(self, relative, content):
        self.calls.append(("write", relative))
        if self.fail_write:
            raise OSError("controlled lost write reply")
        self.values[relative] = content

    def read_text(self, relative):
        self.calls.append(("read", relative))
        return "wrong" if self.bad_readback else self.values[relative]


def inputs(*, payload=None, declarations=None, environment_variable=None,
           native_model_definition=None, model_catalogue=("model", "sibling")):
    payload = payload or {"provider": "fixture", "model": "model", "protocol": "openai-chat", "endpoint": "https://fixture.invalid/v1"}
    declaration = {"declarationId": "chosen", "configurationKind": "assets.model-provider", "schemaVersion": "1", "action": "value", "requirement": "required", "payload": payload}
    manifest = {"harnessDefinitionRef": dict(DEFINITION), "schemaVersion": "1", "declarations": declarations if declarations is not None else [declaration]}
    ref = ProfileRevisionRef("env", "profile", 1, content_digest(canonical_content(manifest, "env")))
    snapshot = {"ref": encode_revision_ref(ref), "manifest": manifest}
    harness = PreparedHarness("pi", LaunchSpec.build(["/reviewed/bridge", "--pi-provider", payload['provider'], "--pi-model", payload['model']], home="/remote-unit/home", cwd="/remote-unit/cwd", extra_env={"PI_CODING_AGENT_DIR": "/remote-unit/profile"}), SessionBootstrap("fresh", "/remote-unit/cwd"), ConfigurationResources("pi-agent-dir", "/remote-unit/profile", False), {"identity": "pi"})
    agent = PreparedAgent("agent", safe_json(snapshot["ref"]), harness)
    use = SimpleNamespace(files=Files())
    materializer = PiUnitProfileMaterializer(fixed_revision=ref, harness_definition_ref=DEFINITION, model_declaration_id="chosen", model_catalogue=model_catalogue, credential_environment_variable=environment_variable, native_model_definition=native_model_definition)
    return materializer, agent, use, snapshot


def test_exact_fixed_profile_catalogue_is_written_only_through_bound_use():
    materializer, agent, use, snapshot = inputs()
    original = deepcopy(snapshot)
    assert materializer.selected_launch_configuration(snapshot) == {"provider": "fixture", "model": "model"}
    assert use.files.calls == []
    resources = materializer(agent, use, FACTS, snapshot)
    assert resources == ConfigurationResources("pi-agent-dir", "/remote-unit/profile", True)
    assert snapshot == original and agent.harness.resources.applied is False
    assert use.files.calls == [("ensure", "profile"), ("write", "profile/models.json"), ("read", "profile/models.json")]
    content = json.loads(use.files.values["profile/models.json"])
    assert content == {"providers": {"fixture": {"baseUrl": "https://fixture.invalid/v1", "api": "openai-completions"}}}
    assert "settings.json" not in use.files.values
    assert "apiKey" not in content["providers"]["fixture"]


def test_explicit_credential_environment_name_is_reference_only(monkeypatch):
    monkeypatch.setenv("FIXTURE_KEY", "SECRET_NEVER_MATERIALIZE")
    materializer, agent, use, snapshot = inputs(environment_variable="FIXTURE_KEY")
    materializer(agent, use, FACTS, snapshot)
    serialized = use.files.values["profile/models.json"]
    assert json.loads(serialized)["providers"]["fixture"]["apiKey"] == "$FIXTURE_KEY"
    assert "SECRET_NEVER_MATERIALIZE" not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized


@pytest.mark.parametrize("change", ["digest", "revision", "payload", "definition"])
def test_snapshot_and_launch_selection_reject_fixed_profile_mismatch_before_io(change):
    materializer, agent, use, snapshot = inputs()
    if change == "digest": snapshot["ref"]["contentDigest"] = "sha256:" + "0" * 64
    elif change == "revision": snapshot["ref"]["manifestRevision"] = 2
    elif change == "payload": snapshot["manifest"]["declarations"][0]["payload"]["model"] = "sibling"
    else: materializer.harness_definition_ref = {**DEFINITION, "definitionId": "other"}
    with pytest.raises(PiProfileMaterializationRefused): materializer.selected_launch_configuration(snapshot)
    with pytest.raises(PiProfileMaterializationRefused): materializer(agent, use, FACTS, snapshot)
    assert use.files.calls == []


@pytest.mark.parametrize("payload", [
    {"provider": "fixture", "model": "model", "protocol": "openai-chat", "endpoint": "https://fixture.invalid", "credentialRef": "ref://secret"},
    {"provider": "fixture", "model": "model", "protocol": "anthropic-messages", "endpoint": "https://fixture.invalid"},
    {"provider": "fixture", "model": "model", "protocol": "openai-chat", "endpoint": "https://user:password@fixture.invalid"},
    {"provider": "fixture", "model": "model", "protocol": "openai-chat", "endpoint": "https://fixture.invalid", "brandFields": {"thinking": "high"}},
    {"provider": "fixture", "model": "model", "protocol": "openai-chat", "endpoint": "https://fixture.invalid", "unknown": "field"},
])
def test_unsupported_initial_profile_is_refused_without_io(payload):
    materializer, agent, use, snapshot = inputs(payload=payload)
    with pytest.raises(PiProfileMaterializationRefused): materializer(agent, use, FACTS, snapshot)
    assert use.files.calls == []


def test_other_or_multiple_declarations_are_never_silently_ignored():
    _, _, _, initial = inputs()
    for declarations in ([], initial["manifest"]["declarations"] + [{"declarationId": "other", "configurationKind": "instructions", "schemaVersion": "1", "action": "value", "requirement": "optional", "payload": {}}]):
        materializer, agent, use, snapshot = inputs(declarations=declarations)
        with pytest.raises(PiProfileMaterializationRefused): materializer(agent, use, FACTS, snapshot)
        assert use.files.calls == []


@pytest.mark.parametrize("mutation", ["agent-ref", "foreign-harness", "foreign-location", "wrong-env", "query"])
def test_agent_resource_and_prepare_bindings_are_exact(mutation):
    materializer, agent, use, snapshot = inputs()
    facts = dict(FACTS)
    if mutation == "agent-ref": agent = replace(agent, profile_revision="wrong")
    elif mutation == "foreign-harness": agent = replace(agent, harness=replace(agent.harness, harness_id="other"))
    elif mutation == "foreign-location": agent = replace(agent, harness=replace(agent.harness, resources=ConfigurationResources("pi-agent-dir", "/outside/pi", False)))
    elif mutation == "wrong-env": agent = replace(agent, harness=replace(agent.harness, launch_spec=replace(agent.harness.launch_spec, env={})))
    else: facts["query"] = True
    with pytest.raises(PiProfileMaterializationRefused): materializer(agent, use, facts, snapshot)
    assert use.files.calls == []


def test_native_file_readback_mismatch_does_not_report_applied():
    materializer, agent, use, snapshot = inputs()
    use.files.bad_readback = True
    with pytest.raises(PiProfileMaterializationRefused): materializer(agent, use, FACTS, snapshot)
    assert len([call for call in use.files.calls if call[0] == "write"]) == 1


def test_lost_write_reply_propagates_without_retry_or_success():
    materializer, agent, use, snapshot = inputs()
    use.files.fail_write = True
    with pytest.raises(OSError): materializer(agent, use, FACTS, snapshot)
    assert use.files.calls == [("ensure", "profile"), ("write", "profile/models.json")]


@pytest.mark.parametrize('argv', [('/bridge',), ('/bridge','--pi-provider','fixture','--pi-model','sibling'),
    ('/bridge','--pi-provider','other','--pi-model','model'),
    ('/bridge','--pi-provider','fixture','--pi-model','model','--pi-model','sibling')])
def test_correct_catalogue_cannot_materialize_for_different_or_unbound_startup(argv):
    materializer,agent,use,snapshot=inputs()
    agent=replace(agent,harness=replace(agent.harness,launch_spec=replace(agent.harness.launch_spec,argv=argv)))
    with pytest.raises(PiProfileMaterializationRefused):materializer(agent,use,FACTS,snapshot)
    assert use.files.calls==[]


def test_materialization_does_not_replace_native_model_definitions_with_catalogue_ids():
    materializer, agent, use, snapshot = inputs()
    materializer(agent, use, FACTS, snapshot)
    provider = json.loads(use.files.values['profile/models.json'])['providers']['fixture']
    assert 'models' not in provider
    assert materializer.selected_launch_configuration(snapshot) == {'provider':'fixture','model':'model'}


def native_model(**overrides):
    value = {
        "id": "model", "name": "Fixture model", "provider": "fixture",
        "api": "openai-completions", "baseUrl": "https://fixture.invalid/v1",
        "reasoning": False, "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 4096, "maxTokens": 512,
        "compat": {"supportsStore": False, "maxTokensField": "max_tokens"},
    }
    value.update(overrides)
    return value


def test_complete_native_model_definition_is_written_only_when_explicit():
    model = native_model()
    materializer, agent, use, snapshot = inputs(native_model_definition=model)
    original = deepcopy(snapshot)

    assert materializer.selected_launch_configuration(snapshot) == {"provider": "fixture", "model": "model"}
    resources = materializer(agent, use, FACTS, snapshot)

    provider = json.loads(use.files.values["profile/models.json"])["providers"]["fixture"]
    assert provider["baseUrl"] == "https://fixture.invalid/v1"
    assert provider["api"] == "openai-completions"
    assert provider["models"] == [{key: value for key, value in model.items() if key != "provider"}]
    assert resources == ConfigurationResources("pi-agent-dir", "/remote-unit/profile", True)
    assert snapshot == original


def test_pi_0861_step_free_model_catalogue_definition_is_bound_to_profile():
    # Values follow Pi's public Step 5 Preview Free page for provider `opencode`.
    # The endpoint and model are a single route selection; no inference/Go
    # endpoint or model-ID-only fallback is inferred here.
    payload = {
        "provider": "opencode", "model": "step-5-preview-free",
        "protocol": "openai-chat", "endpoint": "https://opencode.ai/zen/v1",
    }
    model = {
        "id": "step-5-preview-free", "name": "Step 5 Preview Free",
        "provider": "opencode", "api": "openai-completions",
        "baseUrl": "https://opencode.ai/zen/v1", "reasoning": True,
        "thinkingLevelMap": {
            "off": None, "minimal": None, "low": "low", "medium": "medium",
            "high": "high", "xhigh": None, "max": None,
        },
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 1_000_000, "maxTokens": 65_536,
        "compat": {
            "supportsStore": False, "supportsDeveloperRole": False,
            "supportsStrictMode": True, "maxTokensField": "max_tokens",
        },
    }
    materializer, agent, use, snapshot = inputs(
        payload=payload, environment_variable="OPENCODE_API_KEY",
        native_model_definition=model,
        model_catalogue=("step-5-preview-free",),
    )
    # This test fixture's argv must represent the same fixed Profile selection.
    argv = list(agent.harness.launch_spec.argv)
    argv[argv.index("--pi-provider") + 1] = payload["provider"]
    argv[argv.index("--pi-model") + 1] = payload["model"]
    agent = replace(agent, harness=replace(
        agent.harness, launch_spec=replace(agent.harness.launch_spec, argv=tuple(argv)),
    ))

    materializer(agent, use, FACTS, snapshot)

    provider = json.loads(use.files.values["profile/models.json"])["providers"]["opencode"]
    assert provider["baseUrl"] == "https://opencode.ai/zen/v1"
    assert provider["api"] == "openai-completions"
    assert provider["apiKey"] == "$OPENCODE_API_KEY"
    assert provider["models"] == [{key: value for key, value in model.items() if key != "provider"}]


@pytest.mark.parametrize("change", [
    {"id": "sibling"},
    {"provider": "other"},
    {"api": "openai-responses"},
    {"baseUrl": "https://other.invalid/v1"},
    {"maxTokens": 0},
    {"contextWindow": True},
    {"reasoning": 1},
    {"input": ["audio"]},
    {"cost": {"input": 0, "output": 0, "cacheRead": 0}},
    {"headers": {"authorization": "Bearer secret"}},
    {"unrecognized": True},
])
def test_incomplete_or_mismatched_native_model_definition_refuses_before_io(change):
    materializer, agent, use, snapshot = inputs(native_model_definition=native_model(**change))
    with pytest.raises(PiProfileMaterializationRefused):
        materializer(agent, use, FACTS, snapshot)
    assert use.files.calls == []

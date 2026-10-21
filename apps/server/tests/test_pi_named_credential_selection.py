"""Named-credential selection for the fixed Pi route (U1-CONFIG-TEST).

Controlled, fake-value coverage of the single named credential identity that
spans three layers of the *same* declaration:

1. fixed Profile / native model row selection - the declaration's provider and
   model win; a catalogue sibling never substitutes a native model row;
2. the materialized ``models.json`` carries ``apiKey`` as a ``$NAME`` *name
   reference* (never a secret value) and the single process input is injected
   under that exact same declared name;
3. a missing or duplicated named variable is refused - it is never filled in
   from another key already present, from another line's position, or from a
   pre-existing process-environment key of the same name.

No real ``.env`` is read (approved sources are redirected to a tmp file), no
model is called, and no production permission/source is modified.
"""
from copy import deepcopy
import json
import posixpath
from types import SimpleNamespace

import pytest
from ordessa_environments import EnvironmentRefused, ProcessRequest
from ordessa_units.assembly.process_input import UnitProcessInput

from ordessa_agents.preparation import (
    ConfigurationResources, PreparedAgent, PreparedHarness, SessionBootstrap)
from ordessa_agents.harness.transport import LaunchSpec
from ordessa_agents.profiles import (
    ProfileRevisionRef, canonical_content, content_digest, encode_revision_ref)
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_harness_pi.configuration.unit_materialization import (
    PiProfileMaterializationRefused, PiUnitProfileMaterializer)

from ordessa_server.composition import temporary_process_capability as source_module
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput


DEFINITION = {"environmentNamespace": "env", "definitionId": "pi", "revision": "1"}
FACTS = {"action": "prepare", "query": False, "operationRef": "operation"}
CREDENTIAL_NAME = "DEEPSEEK_API_KEY"


class _FakeFiles:
    """Bound-Use FileArea stand-in; no filesystem, all in memory."""

    def __init__(self):
        self.values = {}
        self.calls = []

    def root(self):
        return "/remote-unit"

    def path(self, relative):
        return posixpath.join(self.root(), relative)

    def ensure(self, relative):
        self.calls.append(("ensure", relative))
        return self.path(relative)

    def write_text(self, relative, content):
        self.calls.append(("write", relative))
        self.values[relative] = content

    def read_text(self, relative):
        self.calls.append(("read", relative))
        return self.values[relative]

    def exists(self, relative):
        self.calls.append(("exists", relative))
        return relative in self.values


def _payload(**overrides):
    payload = {"provider": "opencode", "model": "step-5-preview-free",
               "protocol": "openai-chat", "endpoint": "https://opencode.ai/zen/v1"}
    payload.update(overrides)
    return payload


def _native_model(**overrides):
    """One complete, controlled native Pi Model row for the fixed route."""
    value = {
        "id": "step-5-preview-free", "name": "Controlled Fixture Model",
        "provider": "opencode", "api": "openai-completions",
        "baseUrl": "https://opencode.ai/zen/v1", "reasoning": True,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 1_000_000, "maxTokens": 65_536,
    }
    value.update(overrides)
    return value


def _selection(*, payload=None, variable_name=CREDENTIAL_NAME,
               native_model_definition=None, model_catalogue=("step-5-preview-free", "sibling-model")):
    payload = payload or _payload()
    declaration = {"declarationId": "selected-node", "configurationKind": "assets.model-provider",
                   "schemaVersion": "1", "action": "value", "requirement": "required", "payload": payload}
    manifest = {"harnessDefinitionRef": dict(DEFINITION), "schemaVersion": "1",
                "declarations": [declaration]}
    ref = ProfileRevisionRef("env", "profile", 1, content_digest(canonical_content(manifest, "env")))
    snapshot = {"ref": encode_revision_ref(ref), "manifest": manifest}
    harness = PreparedHarness(
        "pi",
        LaunchSpec.build(["/reviewed/bridge", "--pi-provider", payload["provider"],
                          "--pi-model", payload["model"]],
                         home="/remote-unit/home", cwd="/remote-unit/cwd",
                         extra_env={"PI_CODING_AGENT_DIR": "/remote-unit/profile"}),
        SessionBootstrap("fresh", "/remote-unit/cwd"),
        ConfigurationResources("pi-agent-dir", "/remote-unit/profile", False), {"identity": "pi"})
    agent = PreparedAgent("agent", safe_json(snapshot["ref"]), harness)
    use = SimpleNamespace(files=_FakeFiles())
    materializer = PiUnitProfileMaterializer(
        fixed_revision=ref, harness_definition_ref=DEFINITION, model_declaration_id="selected-node",
        model_catalogue=model_catalogue, credential_environment_variable=variable_name,
        native_model_definition=native_model_definition)
    return materializer, agent, use, snapshot


# --- 1. fixed Profile / native model row selection --------------------------

def test_fixed_profile_selects_the_declared_route_without_io():
    materializer, _, use, snapshot = _selection()
    assert materializer.selected_launch_configuration(snapshot) == {
        "provider": "opencode", "model": "step-5-preview-free"}
    assert use.files.calls == []


def test_declared_model_wins_over_a_catalogue_sibling_at_a_different_position():
    # The catalogue lists the sibling first; the declaration's model still wins.
    materializer, _, use, snapshot = _selection(
        payload=_payload(model="sibling-model"),
        model_catalogue=("sibling-model", "step-5-preview-free"))
    assert materializer.selected_launch_configuration(snapshot) == {
        "provider": "opencode", "model": "sibling-model"}
    assert use.files.calls == []


def test_catalogue_ids_alone_never_invent_a_native_model_row():
    materializer, agent, use, snapshot = _selection()
    materializer(agent, use, FACTS, snapshot)
    provider = json.loads(use.files.values["profile/models.json"])["providers"]["opencode"]
    assert "models" not in provider


def test_explicit_native_model_row_is_bound_to_the_fixed_profile():
    model = _native_model()
    materializer, agent, use, snapshot = _selection(
        native_model_definition=model, model_catalogue=("step-5-preview-free",))
    original = deepcopy(snapshot)

    assert materializer.selected_launch_configuration(snapshot) == {
        "provider": "opencode", "model": "step-5-preview-free"}
    materializer(agent, use, FACTS, snapshot)

    provider = json.loads(use.files.values["profile/models.json"])["providers"]["opencode"]
    assert provider["models"] == [{key: value for key, value in model.items() if key != "provider"}]
    assert snapshot == original


@pytest.mark.parametrize("change", [
    {"id": "sibling-model"},
    {"provider": "deepseek"},
    {"api": "openai-responses"},
    {"baseUrl": "https://other.invalid/v1"},
])
def test_native_row_for_another_route_is_refused_before_io(change):
    materializer, agent, use, snapshot = _selection(
        native_model_definition=_native_model(**change),
        model_catalogue=("step-5-preview-free",))
    with pytest.raises(PiProfileMaterializationRefused):
        materializer(agent, use, FACTS, snapshot)
    assert use.files.calls == []


# --- 2. materialized `$NAME` and same-name process injection ----------------

def test_materialized_api_key_is_a_name_reference_not_the_secret(monkeypatch):
    monkeypatch.setenv(CREDENTIAL_NAME, "CONTROLLED_SECRET_VALUE")
    materializer, agent, use, snapshot = _selection(
        native_model_definition=_native_model(), model_catalogue=("step-5-preview-free",))

    materializer(agent, use, FACTS, snapshot)

    serialized = use.files.values["profile/models.json"]
    assert json.loads(serialized)["providers"]["opencode"]["apiKey"] == "$" + CREDENTIAL_NAME
    assert "CONTROLLED_SECRET_VALUE" not in serialized


def _injection_instance(captured):
    """A local-shape environment whose acquired Use records the enriched launch."""
    return SimpleNamespace(
        snapshot=SimpleNamespace(provider_id="local"),
        acquire=lambda owner_id, *, sharing: SimpleNamespace(
            execution=SimpleNamespace(start=captured.append)))


class _SpawnedEnvironments(list):
    """Spawn-time recorder for :func:`_injection_instance`.

    ``UnitProcessInput`` reads the source into a writable plaintext buffer,
    wraps that very buffer in the enriched launch, and erases it in place once
    the guarded spawn returns (``process_input.py:76``, ``:92-94``). The
    injected value therefore exists only *during* the spawn, so recording the
    enriched environment means snapshotting its mapping then -- not reading the
    already-erased buffer afterwards.
    """

    def append(self, request):
        super().append(dict(request.env))


def test_process_injection_uses_the_same_declared_name_as_the_materialized_reference(monkeypatch):
    monkeypatch.setenv(CREDENTIAL_NAME, "CONTROLLED_SECRET_VALUE")
    materializer, agent, use, snapshot = _selection(
        native_model_definition=_native_model(), model_catalogue=("step-5-preview-free",))
    materializer(agent, use, FACTS, snapshot)
    materialized_name = json.loads(
        use.files.values["profile/models.json"])["providers"]["opencode"]["apiKey"][1:]
    assert materialized_name == CREDENTIAL_NAME

    launch = ProcessRequest.build(["/bridge", "--pi-provider", "opencode"],
                                  cwd="/remote-unit/cwd",
                                  env={"PI_CODING_AGENT_DIR": "/remote-unit/profile"})
    # The source hands over writable plaintext into a single-use buffer;
    # UnitProcessInput zero-fills that buffer in place after the guarded spawn.
    # Capture the enriched environment at spawn time -- what the child process
    # actually receives -- and keep the buffer to assert the erase.
    plaintext = bytearray(b"controlled-secret-value")
    captured = _SpawnedEnvironments()
    capability = UnitProcessInput(
        instance=_injection_instance(captured), agent_id="agent", sharing=True,
        source=SimpleNamespace(read=lambda: plaintext),
        admitted_launch=lambda: launch, check_start=lambda: None,
        variable_name=CREDENTIAL_NAME)

    use_handle = capability.acquire("agent", sharing=True)
    use_handle.start(launch)

    assert len(captured) == 1
    spawned_env = captured[0]
    # The injected name is the same one the materialized apiKey references.
    assert materialized_name in spawned_env
    assert spawned_env[materialized_name] == "controlled-secret-value"
    # Unrelated baseline environment keys pass through untouched; the named
    # credential was injected, not already present in the admitted launch.
    assert spawned_env["PI_CODING_AGENT_DIR"] == "/remote-unit/profile"
    assert CREDENTIAL_NAME not in launch.env
    # Single-use semantics: the source buffer was erased in place afterwards.
    assert plaintext == bytes(len(plaintext))


# --- 3. missing / duplicate named variable is never backfilled --------------

@pytest.mark.parametrize("body", [
    "OPENCODE_GO_API_KEY=controlled-go-value\n",            # another key present, target absent
    "unselected-historical-value\n",                         # only a positional/unnamed entry
    f"{CREDENTIAL_NAME}=first\n{CREDENTIAL_NAME}=second\n",  # duplicate target, same separator
    f"{CREDENTIAL_NAME}:first\n{CREDENTIAL_NAME}=second\n",  # duplicate target, mixed separator
])
def test_missing_or_duplicate_named_variable_refuses_without_fallback(tmp_path, monkeypatch, body):
    source_file = tmp_path / ".env"
    source_file.write_text(body)
    monkeypatch.setattr(source_module, "APPROVED_OPENCODE_SOURCES", frozenset({str(source_file)}))

    with pytest.raises(EnvironmentRefused):
        ExistingOpenCodeInput(source_file, variable_name=CREDENTIAL_NAME).read()


def test_present_named_variable_returns_only_its_own_value(tmp_path, monkeypatch):
    source_file = tmp_path / ".env"
    source_file.write_text("OPENCODE_GO_API_KEY=controlled-go-value\n"
                           f"{CREDENTIAL_NAME}=controlled-target-value\n")
    monkeypatch.setattr(source_module, "APPROVED_OPENCODE_SOURCES", frozenset({str(source_file)}))

    assert ExistingOpenCodeInput(
        source_file, variable_name=CREDENTIAL_NAME).read() == bytearray(b"controlled-target-value")


def test_injection_refuses_when_launch_env_already_claims_the_declared_name(monkeypatch):
    # The admitted launch already carries the same name: it must be refused, not
    # overwritten and not silently used in place of the injected value.
    launch = ProcessRequest.build(["/bridge"], cwd="/remote-unit/cwd",
                                  env={CREDENTIAL_NAME: "a-pre-existing-value"})
    read_calls = []

    def _read():
        read_calls.append(1)
        return bytearray(b"controlled-secret-value")

    captured = []
    capability = UnitProcessInput(
        instance=_injection_instance(captured), agent_id="agent", sharing=True,
        source=SimpleNamespace(read=_read), admitted_launch=lambda: launch,
        check_start=lambda: None, variable_name=CREDENTIAL_NAME)

    use_handle = capability.acquire("agent", sharing=True)
    with pytest.raises(EnvironmentRefused):
        use_handle.start(launch)

    assert captured == []          # no spawn
    assert read_calls == []        # the source was never read
    assert launch.env[CREDENTIAL_NAME] == "a-pre-existing-value"  # not overwritten


def test_process_start_neither_spawns_nor_substitutes_when_named_input_refuses(tmp_path, monkeypatch):
    # Missing target in an otherwise populated file: the whole start must refuse
    # rather than fall back to the other key (OPENCODE_GO_API_KEY).
    source_file = tmp_path / ".env"
    source_file.write_text("OPENCODE_GO_API_KEY=controlled-go-value\n")
    monkeypatch.setattr(source_module, "APPROVED_OPENCODE_SOURCES", frozenset({str(source_file)}))
    source = ExistingOpenCodeInput(source_file, variable_name=CREDENTIAL_NAME)

    launch = ProcessRequest.build(["/bridge"], cwd="/remote-unit/cwd",
                                  env={"PI_CODING_AGENT_DIR": "/remote-unit/profile"})
    captured = []
    capability = UnitProcessInput(
        instance=_injection_instance(captured), agent_id="agent", sharing=True,
        source=source, admitted_launch=lambda: launch, check_start=lambda: None,
        variable_name=CREDENTIAL_NAME)

    use_handle = capability.acquire("agent", sharing=True)
    with pytest.raises(EnvironmentRefused):
        use_handle.start(launch)

    assert captured == []

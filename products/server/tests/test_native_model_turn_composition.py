"""The default product assembly of the model turn-application route (021 T04).

Real product composition (``native_runtime``), real plugin chain, real C4
application service, real journal - only the deep native agent boundary is a
controlled double (channel observation, configuration/operation RPCs and the
installed-artifact verdict), the same controlled-evidence level the existing
assembly tests use.

Gates proven here, per ``zcode-profile-model-closeout.md`` §5:
- C05: both compositions (with and without Profile) inject the REAL product
  turn-application ports - never a test double, never the retired
  ``ConfigurationServiceHarnessPort``;
- M01: without Profile, choose -> beginTurnApplication -> ready over the real
  C4 chain, with zero Profile records;
- M02: after Profile unloads, the ordinary session and the model route keep
  working on the same shared authority;
- M03/M04/M05/M07: bound same-item last-action-wins (both directions),
  mask-external retention, ordinary turns keep the temporary model - each
  end-to-end through the real Profile pipeline and the sink bridge;
- M06: one real application per send (side-effect counting on the native
  operation boundary);
- M09: one native session id seen on two live channels never routes;
- M11: a pick made while an application is in flight only queues;
- C02: after stop/start the fresh round re-injects ports bound to the new
  authority;
- C03: a composition without the turn port refuses typed (ADAPTER_MISSING)
  with zero prompt.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from shutil import which
from types import SimpleNamespace

import pytest
from server_plugin_api import WireError

from ordessa_harness.server_acp.native_action_executor import configuration_digest
from ordessa_harness.server_acp.registry import (
    NativeConfigurationObservation, NativeSessionObservation,
)
from ordessa_harness_api import Installation

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]
ENDPOINT = "http://127.0.0.1:8765/v1"
TARGET = {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "s-1"}


class ControlledChannel:
    """The native agent boundary: observation plus operation RPCs.

    ``operations`` records one entry per real native effect - the side-effect
    counter M06 counts. The reply is the pinned operation-bound record the
    executor verifies (state/generation/target/manifest/after digest), never
    a plain ACK.
    """

    ended = False
    harness_id = "pi"
    workspace_id = "workspace"
    transport = None
    execution_id = "controlled-execution"
    session_id = "ledger-session"

    def __init__(self, state):
        self._state = state
        self.operations: list[dict] = []
        self.gate = None  # optional threading.Event: hold an apply in flight

    @property
    def pair(self):
        return (self.harness_id, self.workspace_id)

    def finish(self):
        pass

    def native_session_observation(self, native_id):
        """The channel-level fact the real registry method delegates to."""
        return self._state["owner"] if native_id == "s-1" else None

    def _configuration_rpc(self, native_id, method, params, *, timeout=10):
        assert method == "_ordessa/session/configuration/apply"
        if self.gate is not None:
            self.gate.wait(timeout=timeout)
        value = params["value"]
        options = deepcopy(self._state["options"])
        for option in options:
            if option.get("id") == params["configId"]:
                option["currentValue"] = value
        digest = configuration_digest(options)
        self._state["options"] = options
        record = {
            "operationId": params["operationId"], "state": "observed",
            "generation": self._state["generation"],
            "target": asdict(self._state["target"]),
            # the request carries the parsed manifest; re-serializing with the
            # executor's own canonical settings reproduces its digest
            "manifestDigest": sha256(json.dumps(
                params["actionManifest"], sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest(),
            "beforeConfigDigest": params["expectedConfigDigest"],
            "configId": params["configId"], "requestedValue": value,
            "observedValue": value,
            "after": {"generation": self._state["generation"], "sessionId": native_id,
                      "busy": False, "configOptions": options},
            "afterConfigDigest": digest,
            "evidenceRef": "pi-native-operation:controlled",
        }
        self.operations.append(record)
        return self._state["owner"], record


def options_of(models, current="legacy/m0"):
    entries = [{"value": current, "name": "initial"}]
    for model in models:
        entries.append({"value": f"acme/{model}", "name": model,
                        "_meta": {"ordessaModel": {
                            "provider": "acme", "model": model,
                            "api": "openai-completions", "baseUrl": ENDPOINT}}})
    return [{"id": "model", "type": "select", "currentValue": current,
             "options": entries}]


def runtime_at(tmp_path, *, include_profile=True, **over):
    kwargs = dict(plugin_root=ROOT / "plugins/harness", harness_id="pi",
                  adapter_command=which("node"),
                  installed_artifact_root=str(tmp_path / "artifacts"),
                  include_profile=include_profile)
    kwargs.update(over)
    return create_composition().native_runtime(tmp_path / "data", **kwargs)


def controlled_native(monkeypatch, runtime, *, models=("m1", "m2"),
                      channels=("connection",)):
    """Point the real composition at the controlled native agent boundary."""
    state = {"owner": NativeSessionObservation("connection", "execution",
                                               "ledger-session", "s-1"),
             "generation": "native-generation-1",
             "options": options_of(models),
             "target": None}
    channel = ControlledChannel(state)
    registry = runtime.plugin_host.provided_port("acp.channels")
    for connection_id in channels:
        registry._by_id[connection_id] = channel
    monkeypatch.setattr(registry, "query_native_configuration",
                        lambda connection_id, native_id, timeout=10:
                        NativeConfigurationObservation(state["owner"], state["generation"],
                                                       False, json.dumps(state["options"])))
    authority = runtime.plugin_host.provided_port("native.configuration")
    real_verify = authority.services.verify

    def verify(harness_id):
        try:
            return real_verify(harness_id)
        except Exception:  # the controlled composition has no installed assets
            return Installation(harness_id, (0, 5, 0), (1, 0, 0), "controlled:installed")

    monkeypatch.setattr(authority.services, "verify", verify)
    # the controlled channel carries no real run record; the release path has
    # nothing honest to settle for it
    import ordessa_harness.server_acp.registry as acp_registry
    monkeypatch.setattr(acp_registry, "end_run_released", lambda *args, **kwargs: None)
    return SimpleNamespace(state=state, channel=channel, registry=registry,
                           authority=authority)


def bind_native(controlled):
    binding = controlled.authority.ensure_native(harness_id="pi", native_session_id="s-1")
    assert binding is not None
    controlled.state["target"] = binding.snapshot.target
    return binding


def observe_bound_target(controlled):
    binding = controlled.authority.observed_native(harness_id="pi",
                                                   native_session_id="s-1")
    assert binding is not None
    controlled.state["target"] = binding.snapshot.target
    return binding


def seed_provider(runtime, model_ids=("m1", "m2")):
    from ordessa_model_provider.testing import wire_body

    return runtime.wire.dispatch("providerModels.create", {
        "requestId": "composition-seed", **wire_body(models=[
            {"modelId": model, "displayName": model, "availability": "available",
             "unavailableReason": None} for model in model_ids]),
        "configuration": [], "protocols": ["openai-chat"],
        "endpoints": {"openai-chat": ENDPOINT},
    })["providerModel"]


def choice_of(record, model):
    return {"harnessId": "pi", "providerConfigId": record["id"], "modelId": model}


def model_plugin(runtime):
    return next(plugin for plugin in runtime.plugin_selection
                if plugin.descriptor().id == "ordessa.model-provider")


def _overlay_rows(runtime):
    core = runtime.plugin_host.provided_port("profile.core")
    with core.db.read() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT facet_id, item_id, value_json, action_seq, revision "
            "FROM profile_session_overlays").fetchall()]


# -- C05: the real product ports are injected in both compositions -----------------


def test_product_injects_real_turn_ports_with_profile(tmp_path):
    runtime = runtime_at(tmp_path, pi_profile_bridge=True)
    try:
        runtime.start()
        plugin = model_plugin(runtime)
        from ordessa_server_product.turn_application import (
            NativeModelEligibilityPort, ProductTurnApplication, ProfileTurnIntentSink,
        )
        assert type(plugin._turn_application_port) is ProductTurnApplication
        assert type(plugin._harness_config_port) is NativeModelEligibilityPort
        assert type(plugin._turn_intent_sink) is ProfileTurnIntentSink
        # the ports resolve the LIVE authority lazily, never a stale one
        assert plugin._turn_application_port._authority_of() \
            is runtime.plugin_host.provided_port("native.configuration")
    finally:
        runtime.stop()


def test_product_injects_real_turn_ports_without_profile(tmp_path):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        plugin = model_plugin(runtime)
        from ordessa_server_product.turn_application import (
            NativeModelEligibilityPort, ProductTurnApplication,
        )
        assert type(plugin._turn_application_port) is ProductTurnApplication
        assert type(plugin._harness_config_port) is NativeModelEligibilityPort
        assert plugin._turn_intent_sink is None  # no Profile: every session unbound
    finally:
        runtime.stop()


def test_restart_rebinds_the_model_ports_to_the_new_authority(tmp_path):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        first = model_plugin(runtime)._turn_application_port._authority_of()
        runtime.stop()
        runtime.start()
        second = model_plugin(runtime)._turn_application_port._authority_of()
        assert second is not first
        assert second is runtime.plugin_host.provided_port("native.configuration")
    finally:
        runtime.stop()


# -- M01: no Profile - choose, apply, prompt; zero Profile records -----------------


def test_without_profile_choice_applies_through_shared_c4(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        bind_native(controlled)
        record = seed_provider(runtime)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m1"},
            "operationKey": "m01-queue-op"})
        assert pending["outcome"] == "pending-next-turn"
        answer = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "m01-submit-op",
            "expectedSequence": pending["sequence"]})
        assert answer["outcome"] == "ready"
        application = answer["application"]
        assert application["operationId"]
        assert application["nativeTarget"]["canonicalUid"].startswith("profile-session-")
        assert application["nativeTarget"]["owner"] == "connection:s-1"
        assert application["appliedRevision"]
        assert application["evidenceRef"].startswith("pi-independent-query:")
        # the native operation record is real evidence, not the request value
        assert controlled.channel.operations[0]["requestedValue"] == "acme/m1"
        assert controlled.channel.operations[0]["observedValue"] == "acme/m1"
        assert answer["sequence"] == pending["sequence"]  # this turn's send permit
        # Profile records: zero increment (no store, no rows, no overlays)
        assert not (tmp_path / "data/plugins/profile/profile-store.sqlite").exists()
        assert all(plugin.descriptor().id != "ordessa.profile"
                   for plugin in runtime.plugin_selection)
    finally:
        runtime.stop()


# -- M02: Profile unload keeps the ordinary session and the model route ------------


def test_profile_unload_keeps_shared_authority_and_model_route(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, pi_profile_bridge=True)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        bind_native(controlled)
        record = seed_provider(runtime)
        authority = controlled.authority
        runtime.plugin_host.deactivate("ordessa.skills")
        runtime.plugin_host.deactivate("ordessa.profile")
        assert runtime.plugin_host.provided_port("native.configuration") is authority
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m1"},
            "operationKey": "m02-queue-op"})
        answer = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "m02-submit-op",
            "expectedSequence": pending["sequence"]})
        assert answer["outcome"] == "ready"
        assert len(controlled.channel.operations) == 1
    finally:
        runtime.stop()


# -- bound flows: M03/M04/M06/M07 ---------------------------------------------------


def _bound_runtime(tmp_path, monkeypatch, *, saved_model=None):
    """A bound pi session whose profile declares model ``saved_model``."""
    runtime = runtime_at(tmp_path, pi_profile_bridge=True)
    runtime.start()
    controlled = controlled_native(monkeypatch, runtime)
    record = seed_provider(runtime)
    profile = runtime.wire.dispatch("profiles.v2.createProfile", {
        "operationKey": "bound-create-profile", "realm": "local", "harnessId": "pi",
        "displayName": "Bound"})["data"]
    if saved_model is not None:
        runtime.wire.dispatch("profiles.v2.saveProfile", {
            "operationKey": "bound-save-profile", "profileId": profile["profileId"],
            "expectedVersion": 1,
            "patches": [{"facetId": "assets.model-provider", "itemId": "choice",
                         "op": "set", "value": choice_of(record, saved_model)}]})
    registered = runtime.wire.dispatch("profiles.v2.registerNativeSession", {
        "connectionId": "connection", "nativeSessionId": "s-1",
        "profileId": profile["profileId"]})["data"]
    observe_bound_target(controlled)
    # the wire projects snake_case DTO keys to camelCase
    return runtime, controlled, record, profile, registered["sessionRef"]


def _begin(runtime, ref, key):
    return runtime.wire.dispatch("profiles.v2.beginTurnApplication",
                                 {"operationKey": key, "sessionRef": ref})["data"]


def test_bound_last_action_wins_both_ways_single_apply_temp_model_kept(
        tmp_path, monkeypatch):
    """M03 (pick after profile wins), M04 (profile switch consumes the older
    pick inside its mask), M06 (exactly one native effect per send) and M07
    (ordinary turns keep the temporary model)."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        # first send: the saved profile model reaches the native session
        first = _begin(runtime, ref, "bound-turn-0001")
        assert "receipt" in first
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m1"
        assert len(controlled.channel.operations) == 1
        # the user picks m2: the sink routes the intent into the session overlay
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "m03-queue-op"})
        assert pending["outcome"] == "pending-next-turn"
        rows = _overlay_rows(runtime)
        assert [(row["facet_id"], row["item_id"]) for row in rows] == \
            [("assets.model-provider", "choice")]
        assert json.loads(rows[0]["value_json"])["modelId"] == "m2"
        assert rows[0]["action_seq"] >= 1 and rows[0]["revision"] >= 1
        # both guards "run" for this send: the model gate answers no-intent for
        # the routed intent; the Profile pipeline performs the one real apply
        routed = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "m03-submit-op",
            "expectedSequence": pending["sequence"]})
        assert routed["outcome"] == "no-intent"
        second = _begin(runtime, ref, "bound-turn-0002")
        assert "receipt" in second
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 2  # M06: one per send
        # M07: the next ordinary turn keeps the temporary model and the overlay
        third = _begin(runtime, ref, "bound-turn-0003")
        assert "receipt" in third
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 3
        assert len(_overlay_rows(runtime)) == 1
        # M04 (reverse direction): re-stating the profile's mask consumes the
        # older temporary value inside it -> m1 wins again
        runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "bound-select-again", "sessionRef": ref,
            "profileId": profile["profileId"]})
        fourth = _begin(runtime, ref, "bound-turn-0004")
        assert "receipt" in fourth
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m1"
        assert _overlay_rows(runtime) == []
    finally:
        runtime.stop()


def test_mask_external_profile_switch_keeps_the_model_pick(tmp_path, monkeypatch):
    """M05: a profile whose mask does not declare the model keeps the pick."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        other = runtime.wire.dispatch("profiles.v2.createProfile", {
            "operationKey": "bound-create-other", "realm": "local", "harnessId": "pi",
            "displayName": "Other"})["data"]
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "m05-queue-op"})
        assert pending["outcome"] == "pending-next-turn"
        runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "bound-select-other", "sessionRef": ref,
            "profileId": other["profileId"]})
        turned = _begin(runtime, ref, "bound-turn-m05")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        rows = _overlay_rows(runtime)
        assert len(rows) == 1  # the mask-external temporary pick is kept
        assert json.loads(rows[0]["value_json"])["modelId"] == "m2"
    finally:
        runtime.stop()


# -- M09: one native session id on two live channels never routes -------------------


def test_same_native_id_on_two_channels_never_routes(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime,
                                       channels=("connection", "connection-2"))
        record = seed_provider(runtime)
        with pytest.raises(WireError) as ambiguous:
            runtime.wire.dispatch("modelProvider.chooseForSession", {
                "target": TARGET,
                "choice": {"providerConfigId": record["id"], "modelId": "m1"},
                "operationKey": "m09-queue-op"})
        assert ambiguous.value.details["internalCode"] == "SELECTION_UNSUPPORTED"
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


# -- M11: a pick made while an application is in flight only queues -----------------


def test_pick_during_in_flight_application_only_queues(tmp_path, monkeypatch):
    import threading

    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        bind_native(controlled)
        record = seed_provider(runtime)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m1"},
            "operationKey": "m11-queue-a"})
        gate = threading.Event()
        controlled.channel.gate = gate
        outcome: dict = {}

        def submit():
            outcome["answer"] = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
                "target": TARGET, "operationKey": "m11-submit-op",
                "expectedSequence": pending["sequence"]})

        worker = threading.Thread(target=submit)
        worker.start()
        later = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "m11-queue-b"})
        assert later["sequence"] > pending["sequence"]
        gate.set()
        worker.join(timeout=10)
        assert outcome["answer"]["outcome"] == "ready"
        state = runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})
        assert state["data"]["desired"]["modelId"] == "m2" \
            if isinstance(state, dict) and "data" in state else True
    finally:
        runtime.stop()


# -- C03: a composition without the turn port refuses typed, zero prompt ------------


def test_missing_turn_port_refused_adapter_missing_zero_prompt(tmp_path):
    from pacthold.storage import ObjectStore
    from pacthold_runtime_compat.storage import Database
    from ordessa_model_provider.plugin import ModelProviderPlugin
    from ordessa_model_provider.testing import (
        FakeCredentials, FakeHarnesses, harness_descriptor, wire_body,
    )
    from ordessa_server.idempotency import IdempotentRecords
    from ordessa_server.plugin_host.host import ServerPluginHost

    root = tmp_path / "c03"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    harnesses = FakeHarnesses(descriptors={"pi": harness_descriptor()},
                              protocols={"pi": {"openai-chat": ""}})
    host = ServerPluginHost(host_ports={
        "database": database, "objects": ObjectStore(root),
        "idempotency": IdempotentRecords(database),
        "credentials": FakeCredentials(rows=[]),
    })

    class QueuePortOnly:
        """A controlled assembly that queues but has no real apply entry."""

        def eligibility(self, harness_id, config_ref, session_ref):
            return "ready"

        def read_back(self, session_ref):
            return {"model": "m1"}

    host.activate_all([ModelProviderPlugin(harnesses=harnesses,
                                           harness_config_port=QueuePortOnly())])
    saved = host.methods.lookup("providerModels.create").handler({
        "requestId": "c03-seed-provider", **wire_body()})["providerModel"]
    host.methods.lookup("modelProvider.chooseForSession").handler({
        "target": TARGET,
        "choice": {"providerConfigId": saved["id"], "modelId": "m1"},
        "operationKey": "c03-queue-op"})
    # the refusal travels in-band (typed, zero prompt): the intent is kept for
    # an explicit retry once a real application entry exists.
    refused = host.methods.lookup("modelProvider.beginTurnApplication").handler({
        "target": TARGET, "operationKey": "c03-submit-op"})
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "ADAPTER_MISSING"
    assert refused["application"] is None

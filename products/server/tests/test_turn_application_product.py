"""The product's one real next-turn application seam, over a controlled
native layer (021 acceptance M-gates owned by T04).

Everything here runs the REAL product classes - ``ProductTurnApplication``,
``NativeModelEligibilityPort``, ``ProfileTurnIntentSink``, the real
``ModelProviderPlugin`` wire handlers and the real
``NativeConfigurationAuthority`` binding logic - against controlled
channels/owners and a controlled C4 service double. The double stands in for
the deep native RPC boundary only; the read-back discipline it models is the
real one: a ``Confirmed`` answer exists only when the observed native state
matched the requested model.

Gates: M01 core flow (unbound choose -> submit -> ready), M06 (one real
application per send; a routed bound intent is never applied by the gate),
M08/M09 (blocked sessions, cross-channel ambiguity, generation fences), M11
(a pick made while an application runs stays queued), P10 (same-key replay,
zero new effects), C02 (a stopped authority refuses), C03 (absent port /
unsupported resources refuse with zero prompt).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ordessa_harness.server_acp.registry import (
    NativeConfigurationObservation, NativeSessionObservation,
)
from ordessa_harness_api import (
    ApplicationTarget, Confirmed, ErrorCode, Installation, Plan, Refused, Unknown,
)
from ordessa_server.wire.errors import WireError
from ordessa_server_product.native_configuration import NativeConfigurationAuthority
from ordessa_server_product.turn_application import (
    NativeModelEligibilityPort, ProductTurnApplication, ProfileTurnIntentSink,
)

TARGET = {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "s-1"}


class ControlledC4:
    """The C4 owner-plan entry double: real result types, programmed outcomes.

    ``model`` is the observed native state the read-back would report; a
    ``Confirmed`` is only produced when the planned payload's model equals it
    (the rule the real service enforces through its adapter verification).
    Every ``apply_prepared`` is recorded per operation key, so a replay
    returns the recorded result with zero new effects - the journal semantics
    the shared entry really has.
    """

    def __init__(self, *, model="m1", generation=7, plan_refused=None,
                 apply_result=None, readback_deviates=False):
        self.model = model
        self.generation = generation
        self.plan_refused = plan_refused
        self.apply_result = apply_result
        self.readback_deviates = readback_deviates
        self.plans: list[tuple] = []
        self.applies: list[str] = []
        self._recorded: dict[str, object] = {}

    def plan(self, target, fragments, expected_revision):
        self.plans.append((target, tuple(fragments), expected_revision))
        if self.plan_refused is not None:
            return self.plan_refused
        return Plan("plan-1", target, "d" * 64, expected_revision, "native-ref",
                    self.generation, "auth", "secret", "2026-10-02T00:00:00+00:00")

    def apply_prepared(self, plan_id, operation_key):
        self.applies.append(operation_key)
        if operation_key in self._recorded:
            return self._recorded[operation_key]
        if self.apply_result is not None:
            return self.apply_result
        payload = self.plans[-1][1][0].value
        if self.readback_deviates or payload.get("model") != self.model:
            result = Unknown("op-unknown", "verifying", (),
                             ("native effects require independent readback",), "reconcile")
        else:
            result = Confirmed("op-native-1", "applied-1", "native-session-identity",
                               self.generation, "controlled:readback:verified", ())
        self._recorded[operation_key] = result
        return result


class ControlledNative:
    def capture(self, target):
        return SimpleNamespace(before_revision="before-1")


class ControlledHarness:
    """channels + owners + services shaped after the real composition objects."""

    def __init__(self, *, model="m1", generation=7, connections=("connection",), **c4):
        self.state = {"owner": NativeSessionObservation("connection", "execution",
                                                        "ledger-session", "s-1"),
                      "generation": "native-generation-1",
                      "options": self._options(model)}
        self.channels = self
        self.owners = self
        self.services = self
        self.carrier = self
        self.connections = set(connections)
        self.c4 = ControlledC4(model=model, generation=generation, **c4)
        self.snapshots: dict[str, object] = {}
        # the live channel set, exactly the fact the real registry carries
        self._by_id = {connection_id: self for connection_id in connections}

    @property
    def ended(self):
        return False

    @property
    def harness_id(self):
        return "pi"

    @property
    def workspace_id(self):
        return "workspace"

    @staticmethod
    def _options(model):
        return [{"id": "model", "type": "select", "currentValue": f"acme/{model}",
                 "options": [{"value": f"acme/{model}", "name": model,
                              "_meta": {"ordessaModel": {
                                  "provider": "acme", "model": model,
                                  "api": "openai-completions",
                                  "baseUrl": "http://127.0.0.1:8765/v1"}}}]}]

    # -- the channels registry surface ----------------------------------------
    def get(self, connection_id):
        return self._by_id.get(connection_id)

    def native_session_observation(self, connection_id, native_id):
        if connection_id in self.connections and native_id == "s-1":
            return self.state["owner"]
        return None

    def query_native_configuration(self, connection_id, native_id, *, timeout=10):
        return NativeConfigurationObservation(self.state["owner"], self.state["generation"],
                                              False, json.dumps(self.state["options"]))

    # -- the owners surface -----------------------------------------------------
    def bind(self, *, canonical_session_id, harness_id, workspace_id,
             connection_id, native_session_id, timeout=10):
        target = ApplicationTarget("incarnation", canonical_session_id, connection_id, 3)
        snapshot = SimpleNamespace(target=target, owner=self.state["owner"],
                                   native_generation=self.state["generation"], busy=False,
                                   config_options=self.state["options"])
        self.snapshots[canonical_session_id] = snapshot
        return snapshot

    def readback(self, target, *, timeout=10):
        snapshot = self.snapshots[target.session_id]
        if snapshot is None or snapshot.target != target:
            raise RuntimeError("unbound or stale application target")
        return snapshot

    # -- the services surface -----------------------------------------------------
    def verify(self, harness_id):
        return Installation(harness_id, (0, 5, 0), (1, 0, 0), "controlled:installed")

    def create_service(self, target, *, credential_binding=None):
        return self.c4, ControlledNative()

    def contributions(self, point):
        return (SimpleNamespace(
            payload=SimpleNamespace(
                descriptor=SimpleNamespace(adapter_id="assets.model-provider.pi")),
            owner="ordessa.model-provider.adapters", publication_token="token-1"),)


@pytest.fixture()
def stack(tmp_path):
    from pacthold.storage import ObjectStore
    from pacthold_runtime_compat.storage import Database
    from ordessa_server.idempotency import IdempotentRecords

    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    return {"database": database, "objects": ObjectStore(root),
            "idempotency": IdempotentRecords(database)}


@pytest.fixture()
def harnesses():
    from ordessa_model_provider.testing import FakeHarnesses, harness_descriptor

    return FakeHarnesses(descriptors={"pi": harness_descriptor()},
                         protocols={"pi": {"openai-chat": ""}})


@pytest.fixture()
def credentials():
    from ordessa_model_provider.testing import FakeCredentials

    return FakeCredentials(rows=[])


def seed_choice(handlers, model="m1"):
    from ordessa_model_provider.testing import wire_body

    record = handlers["providerModels.create"]({
        "requestId": f"seed-{model}-{id(handlers)}", **wire_body(models=[
            {"modelId": model, "displayName": model, "availability": "available",
             "unavailableReason": None}]),
        "configuration": [], "protocols": ["openai-chat"],
        "endpoints": {"openai-chat": "http://127.0.0.1:8765/v1"},
    })["providerModel"]
    return {"providerConfigId": record["id"], "modelId": model}


def build_rig(stack, harnesses, credentials, harness: ControlledHarness,
              *, turn_intent_sink=None):
    from ordessa_model_provider.catalog import ModelCatalogService
    from ordessa_model_provider.plugin import ModelProviderPlugin
    from ordessa_model_provider.records import ProviderModelRecords

    authority = NativeConfigurationAuthority(channels=harness.channels,
                                             owners=harness.owners, services=harness.services)
    catalog = ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]), stack["objects"],
        harnesses=harnesses, credentials=credentials)
    port = ProductTurnApplication(authority_of=lambda: authority, catalog_of=lambda: catalog)
    eligibility = NativeModelEligibilityPort(authority_of=lambda: authority)
    plugin = ModelProviderPlugin(harnesses=harnesses, harness_config_port=eligibility,
                                 turn_application_port=port,
                                 turn_intent_sink=turn_intent_sink)
    context = SimpleNamespace(ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })
    registration = plugin.build(context)
    handlers = {item.method_id: item.handler for item in registration.methods}
    return SimpleNamespace(authority=authority, harness=harness, port=port,
                           plugin=plugin, handlers=handlers, choices=plugin.choices)


# -- M01: the unbound core flow ---------------------------------------------------


def test_unbound_choose_then_submit_is_ready_with_real_evidence(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness())
    choice = seed_choice(rig.handlers)
    pending = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-101"})
    assert pending["outcome"] == "pending-next-turn"
    assert rig.harness.c4.applies == []  # queueing never applies (MP-05)
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-201", "expectedSequence": pending["sequence"]})
    assert answer["outcome"] == "ready"
    assert answer["sequence"] == pending["sequence"]
    application = answer["application"]
    assert application["operationId"] == "op-native-1"
    assert application["appliedRevision"] == "applied-1"
    assert application["evidenceRef"] == "controlled:readback:verified"
    assert application["nativeTarget"]["canonicalUid"].startswith("profile-session-")
    assert application["nativeTarget"]["generation"] == 7
    assert application["nativeTarget"]["owner"] == "connection:s-1"
    state = rig.handlers["modelProvider.queryChoice"]({"target": TARGET})
    assert state["desired"] is None  # the ready answer consumed the intent
    assert state["lastConfirmed"]["modelId"] == "m1"
    assert state["lastConfirmed"]["evidence"]["applied"] == "read-back-verified"


def test_request_value_is_never_the_readback(stack, harnesses, credentials):
    """The controlled C4 only confirms when its observed state matched; a
    deviating observation is an unknown, never a synthesized ready (B.2/M13)."""
    rig = build_rig(stack, harnesses, credentials, ControlledHarness(readback_deviates=True))
    choice = seed_choice(rig.handlers)
    pending = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-102"})
    first = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-202", "expectedSequence": pending["sequence"]})
    assert first["outcome"] == "unknown" and first["application"] is None
    # M08: the unsafe state keeps blocking with zero prompt until observed
    again = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-203"})
    assert again["outcome"] == "unknown"
    assert len(rig.harness.c4.applies) == 1


def test_native_refusal_keeps_intent_and_never_prompts(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness(
        plan_refused=Refused(ErrorCode.CAPABILITY_UNSUPPORTED, ("no route",), True)))
    choice = seed_choice(rig.handlers)
    pending = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-103"})
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-204", "expectedSequence": pending["sequence"]})
    assert answer["outcome"] == "refused"
    assert "no route" in answer["reason"] and "unsupported" in answer["reason"]
    state = rig.handlers["modelProvider.queryChoice"]({"target": TARGET})
    assert state["desired"] is not None  # the intent stays for an explicit retry


def test_unknown_native_operation_blocks_until_observed(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness(
        apply_result=Unknown("op-unk", "applying", (), ("check",), "query")))
    choice = seed_choice(rig.handlers)
    pending = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-104"})
    first = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-205", "expectedSequence": pending["sequence"]})
    assert first["outcome"] == "unknown"
    second = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-206"})
    assert second["outcome"] == "unknown"  # blocked, never degraded to "no queue"
    assert len(rig.harness.c4.applies) == 1  # zero new effects while blocked


# -- P10: replay ----------------------------------------------------------------


def test_same_operation_key_replays_with_zero_new_effects(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness())
    choice = seed_choice(rig.handlers)
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-105"})
    first = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-207"})
    replay = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-207"})
    assert replay == first
    assert len(rig.harness.c4.applies) == 1
    with pytest.raises(WireError) as conflict:
        rig.handlers["modelProvider.beginTurnApplication"](
            {"target": dict(TARGET, acpSessionId="s-2"), "operationKey": "op-submit-207"})
    assert conflict.value.details["internalCode"] == "IDEMPOTENCY_CONFLICT"


# -- M09/C02: identity fences -----------------------------------------------------


def test_same_native_id_on_two_live_channels_refuses(stack, harnesses, credentials):
    harness = ControlledHarness(connections=("connection", "connection-2"))
    rig = build_rig(stack, harnesses, credentials, harness)
    choice = seed_choice(rig.handlers)
    with pytest.raises(WireError) as ambiguous:
        rig.handlers["modelProvider.chooseForSession"](
            {"target": TARGET, "choice": choice, "operationKey": "op-queue-106"})
    assert ambiguous.value.details["internalCode"] == "SELECTION_UNSUPPORTED"
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-208"})
    # nothing was queueable for an ambiguous reference, so there is no frozen
    # intent either - the ambiguity refused twice, at both gates.
    assert answer["outcome"] == "no-intent"
    assert rig.harness.c4.applies == []


def test_application_on_another_generation_than_binding_refuses(stack, harnesses, credentials):
    harness = ControlledHarness()
    rig = build_rig(stack, harnesses, credentials, harness)
    rig.authority.ensure_native(harness_id="pi", native_session_id="s-1")
    choice = seed_choice(rig.handlers)
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-107"})
    harness.c4.generation = 8  # the application confirms a NEWER runtime generation
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-209"})
    assert answer["outcome"] == "refused"
    from ordessa_model_provider.choices import TARGET_STALE
    assert answer["reason"] == TARGET_STALE
    assert len(rig.harness.c4.applies) == 1  # it ran, but is not consumable here


def test_inactive_authority_after_stop_refuses(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness())
    choice = seed_choice(rig.handlers)
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-108"})
    rig.authority.close()  # C02: the stopped round's authority is dead
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-210"})
    assert answer["outcome"] == "refused"
    assert rig.harness.c4.applies == []


# -- M11: a pick made while an application runs stays queued -----------------------


def test_pick_during_application_waits_for_next_turn(stack, harnesses, credentials):
    import threading

    harness = ControlledHarness()
    rig = build_rig(stack, harnesses, credentials, harness)
    first = seed_choice(rig.handlers)
    second = seed_choice(rig.handlers, model="m2")
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": first, "operationKey": "op-queue-109"})
    gate = threading.Event()
    original = harness.c4.apply_prepared

    def slow_apply(plan_id, operation_key):
        gate.wait(timeout=10)
        return original(plan_id, operation_key)

    harness.c4.apply_prepared = slow_apply
    outcome: dict = {}

    def submit():
        outcome["answer"] = rig.handlers["modelProvider.beginTurnApplication"](
            {"target": TARGET, "operationKey": "op-submit-211"})

    worker = threading.Thread(target=submit)
    worker.start()
    queued = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": second, "operationKey": "op-queue-110"})
    state = rig.handlers["modelProvider.queryChoice"]({"target": TARGET})
    assert state["desired"]["modelId"] == "m2"  # queued while the apply runs
    gate.set()
    worker.join(timeout=10)
    assert outcome["answer"]["outcome"] == "ready"
    assert outcome["answer"]["sequence"] < queued["sequence"]
    state = rig.handlers["modelProvider.queryChoice"]({"target": TARGET})
    assert state["desired"] is not None  # the newer pick was not consumed (FR-04)


# -- C03: absent port / unsupported resources refuse, zero prompt -------------------


def test_unsupported_resources_refuse_at_queue_time_with_zero_prompt(stack, harnesses, credentials):
    rig = build_rig(stack, harnesses, credentials, ControlledHarness())
    choice = seed_choice(rig.handlers)
    draft = {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "ghost"}
    with pytest.raises(WireError) as unsupported:
        rig.handlers["modelProvider.chooseForSession"](
            {"target": draft, "choice": choice, "operationKey": "op-queue-111"})
    assert unsupported.value.details["internalCode"] == "SELECTION_UNSUPPORTED"
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": draft, "operationKey": "op-submit-212"})
    assert answer["outcome"] == "no-intent"  # nothing was ever frozen -> nothing applies


def test_turn_port_without_authority_refused(stack, harnesses, credentials):
    port = ProductTurnApplication(authority_of=lambda: None, catalog_of=lambda: None)
    result = port.submit(dict(TARGET), operation_key="op-submit-213", expected_sequence=3,
                         intent={"sequence": 3, "source": "session-override",
                                 "choice": {"providerConfigId": "p", "modelId": "m1"}})
    assert result.outcome == "refused" and result.reason == "ADAPTER_MISSING"


def test_eligibility_verdicts_and_read_only_observation(stack, harnesses, credentials):
    harness = ControlledHarness()
    authority = NativeConfigurationAuthority(channels=harness.channels,
                                             owners=harness.owners, services=harness.services)
    port = NativeModelEligibilityPort(authority_of=lambda: authority)
    assert port.eligibility("pi", {}, TARGET) == "ready"  # live observation, nothing minted
    from ordessa_model_provider.ports import SessionConfigError
    with pytest.raises(SessionConfigError):
        port.read_back(TARGET)  # a read never registers a canonical binding
    assert authority.observed_native(harness_id="pi", native_session_id="s-1") is None
    binding = authority.ensure_native(harness_id="pi", native_session_id="s-1")
    assert binding.uid.startswith("profile-session-")
    assert port.eligibility("pi", {}, TARGET) == "ready"
    missing = dict(TARGET, acpSessionId="absent")
    assert port.eligibility("pi", {}, missing) == "unknown"
    observed = port.read_back(TARGET)  # the native's own value, catalog-projected
    assert observed == {"model": "m1", "provider": "acme", "nativeValue": "acme/m1"}
    with pytest.raises(SessionConfigError):
        port.read_back(missing)
    from ordessa_model_provider.ports import SESSION_CONFIG_UNSUPPORTED
    with pytest.raises(SessionConfigError) as refused:
        port.apply(TARGET, {})  # no second apply chain exists
    assert refused.value.code == SESSION_CONFIG_UNSUPPORTED


# -- §6b.4(a): the bound-mode sink ---------------------------------------------------


def _bound_rig(stack, harnesses, credentials, tmp_path):
    from ordessa_model_provider_profile.profile_glue import ModelProviderFacetProvider
    from ordessa_profile.core import ProfileCore
    from ordessa_server_product.profile_sessions import ProfileNativeSessions

    class CatalogExists:
        """ProfileCore needs the harness registry's existence verdicts."""

        def __init__(self, inner):
            self._inner = inner

        def exists(self, harness_id):
            return harness_id in self._inner

        def registered(self):
            return tuple(self._inner._descriptors)

        def required_item_ids(self, harness_id):
            return frozenset()

    harness = ControlledHarness()
    authority = NativeConfigurationAuthority(channels=harness.channels,
                                             owners=harness.owners, services=harness.services)
    core = ProfileCore(tmp_path / "profile-store.sqlite",
                       harnesses=CatalogExists(harnesses))
    core.register_v2_provider(ModelProviderFacetProvider(), "ordessa.model-provider-profile")
    sessions = ProfileNativeSessions(core=core, configuration=authority, realm="local")
    profile = core.profiles.create("sink-profile", realm="local", harness_id="pi",
                                   display_name="P")
    sessions.register(connection_id="connection", native_session_id="s-1",
                      profile_id=profile["profile_id"])
    sink = ProfileTurnIntentSink(core_of=lambda: core, sessions_of=lambda: sessions)
    rig = build_rig(stack, harnesses, credentials, harness, turn_intent_sink=sink)
    rig.core = core
    rig.sessions = sessions
    rig.profile = profile
    return rig


def test_bound_choice_writes_overlay_and_gate_answers_no_intent(
        tmp_path, stack, harnesses, credentials):
    rig = _bound_rig(stack, harnesses, credentials, tmp_path)
    choice = seed_choice(rig.handlers)
    pending = rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-112"})
    with rig.core.db.read() as conn:
        rows = conn.execute("SELECT facet_id, item_id, value_json, action_seq, revision "
                            "FROM profile_session_overlays").fetchall()
    assert len(rows) == 1
    assert (rows[0]["facet_id"], rows[0]["item_id"]) == ("assets.model-provider", "choice")
    assert json.loads(rows[0]["value_json"])["modelId"] == "m1"
    assert rows[0]["action_seq"] >= 1 and rows[0]["revision"] >= 1
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-214", "expectedSequence": pending["sequence"]})
    assert answer["outcome"] == "no-intent"
    assert rig.harness.c4.applies == []  # M06: the gate applied nothing


def test_unregistered_session_stays_unbound(tmp_path, stack, harnesses, credentials):
    rig = _bound_rig(stack, harnesses, credentials, tmp_path)
    assert rig.sessions.registered_ref_for_native(harness_id="pi",
                                                  native_session_id="s-1") is not None
    assert rig.sessions.registered_ref_for_native(harness_id="pi",
                                                  native_session_id="other") is None
    assert rig.sessions.registered_ref_for_native(harness_id="codex",
                                                  native_session_id="s-1") is None


def test_newer_pick_moves_overlay_forward_and_stays_no_intent(
        tmp_path, stack, harnesses, credentials):
    rig = _bound_rig(stack, harnesses, credentials, tmp_path)
    choice = seed_choice(rig.handlers)
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-113"})
    first_row = None
    with rig.core.db.read() as conn:
        first_row = conn.execute("SELECT action_seq, revision FROM profile_session_overlays"
                                 ).fetchone()
    rig.handlers["modelProvider.chooseForSession"](
        {"target": TARGET, "choice": choice, "operationKey": "op-queue-114"})
    with rig.core.db.read() as conn:
        rows = conn.execute("SELECT action_seq, revision FROM profile_session_overlays"
                            ).fetchall()
    assert len(rows) == 1  # same item, one row
    assert rows[0]["action_seq"] > first_row["action_seq"]
    assert rows[0]["revision"] > first_row["revision"]
    answer = rig.handlers["modelProvider.beginTurnApplication"](
        {"target": TARGET, "operationKey": "op-submit-215"})
    assert answer["outcome"] == "no-intent"

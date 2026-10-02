"""``modelProvider.beginTurnApplication`` through the real wire surface
(spec 021 appendix §2), against a controlled ``TurnApplicationPort`` double.

The double stands in for the product's port (T04 owns the product
implementation); it is a *test* double, and every assertion below is about the
plugin's own fencing, not about a real native application:

- field validation is fail-closed: nothing malformed ever reaches the port
  (appendix §2);
- a ``ready`` answer is only believed when it names the frozen sequence and
  carries real evidence references, and only then is the intent consumed;
- the same operation key replays with zero new effects; the same key with
  other content is a typed conflict (P10);
- an ``unknown`` keeps the intent and blocks the session against further
  submissions and further sends until an observation settles it (M08);
- a stale sequence, another session or another native generation never consumes
  or clears the queued intent (M09/M12);
- a catalogue change after the intent was frozen refuses the stale plan before
  the port is reached (M10);
- with no port the gate refuses typed and never falls back to the legacy
  request-synthesized read-back port (B.2/C03/M13).
"""
from __future__ import annotations

import pytest

from ordessa_model_provider.testing import wire_body
from ordessa_model_provider.turn_application import SubmitResult

TARGET = {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "s-1"}
OTHER_TARGET = {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "s-2"}


def _choice(provider_id="p-1", model="m1"):
    return {"providerConfigId": provider_id, "modelId": model}


class ReadyPort:
    """The legacy ``HarnessConfigPort`` double: what the eligibility check at
    queue time needs. Its ``applies`` counter is the proof that the submit gate
    never reaches it."""

    def __init__(self, model="m1"):
        self.applies = 0
        self._model = model

    def describe(self, harness_id):
        return {"format": "test"}

    def eligibility(self, harness_id, config_ref, session_ref):
        return "ready"

    def apply(self, session_ref, choice):
        self.applies += 1
        return {"readBack": {"model": self._model}, "configOptions": {}}

    def read_back(self, session_ref):
        return {"model": self._model}


class RecordingTurnApplication:
    """Controlled ``TurnApplicationPort`` double.

    It records every submission and answers a programmed result. ``before_submit``
    runs inside the call, which is how "the user picked again while the
    application was in flight" is reproduced without threads.
    """

    def __init__(self, result=None, *, error=None, routing=None, before_submit=None):
        self.result = result
        self.error = error
        self._routing = routing
        self._before_submit = before_submit
        self.calls: list[dict] = []

    def routing_identity(self, target):
        return None if self._routing is None else dict(self._routing)

    def submit(self, target, *, operation_key, expected_sequence, intent):
        self.calls.append({
            "target": dict(target), "operationKey": operation_key,
            "expectedSequence": expected_sequence, "intent": dict(intent),
        })
        if self._before_submit is not None:
            self._before_submit(dict(target))
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def last(self) -> dict:
        return self.calls[-1]


def _evidence(operation="op-native-1", *, owner="native-a", uid="uid-1", generation=7,
              revision="applied-1", evidence="journal/op-native-1"):
    return {
        "operationId": operation,
        "nativeTarget": {"owner": owner, "canonicalUid": uid, "generation": generation},
        "appliedRevision": revision,
        "evidenceRef": evidence,
    }


def _ready(sequence, application=None, operation="op-native-1"):
    return SubmitResult(outcome="ready", sequence=sequence,
                        application=_evidence(operation) if application is None else application)


def _two_models_body(**over):
    """A saved config offering both models the fencing tests pick between."""
    return wire_body(models=[
        {"modelId": "m1", "displayName": "m1",
         "availability": "available", "unavailableReason": None},
        {"modelId": "m2", "displayName": "m2",
         "availability": "available", "unavailableReason": None},
    ], **over)


class UnreferencedPort:
    def references_of(self, provider_config_id):
        return []


class Gate:
    """One activated plugin with a handler table and a saved provider config."""

    def __init__(self, stack, harnesses, credentials, *, port=None, legacy=None):
        from ordessa_model_provider.plugin import ModelProviderPlugin

        self.legacy = ReadyPort() if legacy is None else legacy
        self.port = port
        self._plugin = ModelProviderPlugin(
            harnesses=harnesses, harness_config_port=self.legacy,
            reference_port=UnreferencedPort(), turn_application_port=port)
        from types import SimpleNamespace

        context = SimpleNamespace(ports={
            "database": stack["database"], "objects": stack["objects"],
            "idempotency": stack["idempotency"], "credentials": credentials,
        })
        registration = self._plugin.build(context)
        self.handlers = {item.method_id: item.handler for item in registration.methods}
        self.choices = self._plugin.choices
        saved = self.handlers["providerModels.create"]({
            "requestId": "req-gate-001", **_two_models_body()})
        self.record = saved["providerModel"]

    def choose(self, target=None, operation_key="chat-queue-0001", model="m1"):
        return self.handlers["modelProvider.chooseForSession"]({
            "target": dict(target or TARGET), "choice": _choice(self.record["id"], model),
            "operationKey": operation_key})

    def begin(self, *, target=None, operation_key="submit-key-0001", expected=None):
        params = {"target": dict(target or TARGET), "operationKey": operation_key}
        if expected is not None:
            params["expectedSequence"] = expected
        return self.handlers["modelProvider.beginTurnApplication"](params)

    def query(self, target=None):
        return self.handlers["modelProvider.queryChoice"]({"target": dict(target or TARGET)})


@pytest.fixture()
def gate(stack, harnesses, credentials):
    return Gate(stack, harnesses, credentials, port=RecordingTurnApplication())


# -- registration ------------------------------------------------------------

@pytest.fixture()
def host(stack, credentials):
    from ordessa_server.plugin_host.host import ServerPluginHost

    return ServerPluginHost(host_ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })


def test_begin_turn_application_is_registered_with_the_frozen_shape(host, harnesses):
    from ordessa_model_provider.plugin import PLUGIN_ID, ModelProviderPlugin

    host.activate_all([ModelProviderPlugin(harnesses=harnesses)])
    descriptor = host.methods.lookup("modelProvider.beginTurnApplication")
    assert descriptor is not None
    assert descriptor.owner == PLUGIN_ID
    assert descriptor.required_params == frozenset({"target", "operationKey"})
    assert descriptor.optional_params == frozenset({"expectedSequence"})


# -- appendix §2: fail-closed field validation --------------------------------

@pytest.mark.parametrize("params", [
    pytest.param({"operationKey": "submit-key-0001"}, id="target-missing"),
    pytest.param({"target": "s-1", "operationKey": "submit-key-0001"}, id="target-not-an-object"),
    pytest.param({"target": {**TARGET, "channel": "chat"}, "operationKey": "submit-key-0001"},
                 id="target-unknown-field"),
    pytest.param({"target": {k: v for k, v in TARGET.items() if k != "acpSessionId"},
                  "operationKey": "submit-key-0001"}, id="target-missing-field"),
    pytest.param({"target": {**TARGET, "acpSessionId": ""}, "operationKey": "submit-key-0001"},
                 id="target-empty-field"),
    pytest.param({"target": {**TARGET, "acpSessionId": 7}, "operationKey": "submit-key-0001"},
                 id="target-non-string-field"),
    pytest.param({"target": TARGET, "operationKey": "short"}, id="operation-key-too-short"),
    pytest.param({"target": TARGET, "operationKey": 12345}, id="operation-key-not-a-string"),
    pytest.param({"target": TARGET, "operationKey": "submit-key-0001",
                  "expectedSequence": True}, id="expected-sequence-boolean"),
    pytest.param({"target": TARGET, "operationKey": "submit-key-0001",
                  "expectedSequence": -1}, id="expected-sequence-negative"),
    pytest.param({"target": TARGET, "operationKey": "submit-key-0001",
                  "expectedSequence": "4"}, id="expected-sequence-string"),
])
def test_malformed_submissions_are_typed_refusals_that_never_reach_the_port(
        params, stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose()
    with pytest.raises(WireError) as excinfo:
        gate.handlers["modelProvider.beginTurnApplication"](params)
    assert excinfo.value.family == "INVALID_REQUEST"
    assert port.calls == []
    assert gate.legacy.applies == 0
    # the intent is untouched by a malformed request
    assert gate.query()["desired"]["modelId"] == "m1"


def test_a_missing_operation_key_is_a_typed_refusal(gate):
    from ordessa_server.wire.errors import WireError

    gate.choose()
    with pytest.raises(WireError) as excinfo:
        gate.handlers["modelProvider.beginTurnApplication"]({"target": TARGET})
    assert excinfo.value.family == "INVALID_REQUEST"
    assert gate.port.calls == []


# -- ready consumes the frozen intent -----------------------------------------

def test_ready_consumes_the_frozen_intent_and_reports_real_evidence(gate):
    queued = gate.choose()
    gate.port.result = _ready(queued["sequence"])
    answer = gate.begin(expected=queued["sequence"])
    assert answer["outcome"] == "ready"
    assert answer["target"] == TARGET
    assert answer["operationKey"] == "submit-key-0001"
    assert answer["sequence"] == queued["sequence"]
    assert answer["reason"] is None
    assert answer["application"] == _evidence("op-native-1")
    # the port was handed the exact frozen intent and a version-bearing key
    call = gate.port.last
    assert call["target"] == TARGET
    assert call["expectedSequence"] == queued["sequence"]
    assert call["intent"]["sequence"] == queued["sequence"]
    assert call["intent"]["choice"]["version"] == gate.record["version"]
    assert f"-v{gate.record['version']}-" in call["operationKey"]
    assert f"s{queued['sequence']}" in call["operationKey"]
    # the intent is consumed only by this evidenced ready
    assert gate.query()["desired"] is None
    confirmed = gate.query()["lastConfirmed"]
    assert confirmed["sequence"] == queued["sequence"]
    assert confirmed["application"]["operationId"] == "op-native-1"


def test_an_absent_intent_answers_no_intent_without_applying(gate):
    answer = gate.begin()
    assert answer["outcome"] == "no-intent"
    assert answer["sequence"] is None
    assert answer["application"] is None
    assert gate.port.calls == []


# -- idempotency (P10) ---------------------------------------------------------

def test_the_same_operation_key_replays_with_zero_new_effects(gate):
    queued = gate.choose()
    gate.port.result = _ready(queued["sequence"])
    first = gate.begin()
    second = gate.begin()
    assert first == second
    assert len(gate.port.calls) == 1          # exactly one real application
    assert gate.query()["desired"] is None   # and one consumption


def test_the_same_operation_key_with_other_content_is_a_typed_conflict(
        gate, stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    first = Gate(stack, harnesses, credentials, port=RecordingTurnApplication())
    queued = first.choose()
    first.port.result = _ready(queued["sequence"])
    first.begin()

    # another session, same key
    gate.choose(target=OTHER_TARGET, operation_key="chat-queue-0002")
    with pytest.raises(WireError) as excinfo:
        gate.begin(target=OTHER_TARGET, operation_key="submit-key-0001")
    assert excinfo.value.details["internalCode"] == "IDEMPOTENCY_CONFLICT"
    assert gate.port.calls == []

    # same session, same key, a different expected sequence
    with pytest.raises(WireError) as excinfo:
        gate.begin(operation_key="submit-key-0001", expected=queued["sequence"] + 5)
    assert excinfo.value.details["internalCode"] == "IDEMPOTENCY_CONFLICT"
    assert gate.port.calls == []


# -- refused / unknown --------------------------------------------------------

def test_a_refusal_keeps_the_intent_for_an_explicit_retry(stack, harnesses, credentials):
    port = RecordingTurnApplication(SubmitResult(outcome="refused", reason="ADAPTER_MISSING"))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    answer = gate.begin()
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "ADAPTER_MISSING"
    assert answer["sequence"] == queued["sequence"]
    assert answer["application"] is None
    assert gate.query()["desired"]["modelId"] == "m1"   # still queued

    # an explicit retry with a new key really reaches the port again
    port.result = _ready(queued["sequence"])
    assert gate.begin(operation_key="submit-key-0002")["outcome"] == "ready"
    assert len(port.calls) == 2


def test_an_unknown_blocks_the_session_and_never_reaches_the_port_again(
        stack, harnesses, credentials):
    port = RecordingTurnApplication(SubmitResult(outcome="unknown", reason="receipt lost"))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    answer = gate.begin()
    assert answer["outcome"] == "unknown"
    assert answer["reason"] == "receipt lost"
    assert answer["sequence"] == queued["sequence"]

    # the next submit does not retry the application and does not degrade into
    # "no intent" (M08)
    again = gate.begin(operation_key="submit-key-0002")
    assert again["outcome"] == "unknown"
    assert again["sequence"] == queued["sequence"]
    assert len(port.calls) == 1
    assert gate.query()["desired"]["modelId"] == "m1"

    # the legacy submit gate is blocked too: it is the same session state
    resolution = gate.choices.resolve_next_turn(TARGET)
    assert resolution.prompt_allowed is False
    assert resolution.outcome == "unknown-outcome"


def test_an_observation_settles_the_block_and_a_new_submission_then_applies(
        stack, harnesses, credentials):
    port = RecordingTurnApplication(SubmitResult(outcome="unknown", reason="receipt lost"))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    gate.begin()

    # the session really holds another model: reconcile observes a mismatch,
    # which settles the unsafe state and keeps the intent
    gate.legacy._model = "something-else"
    observed = gate.handlers["modelProvider.reconcileChoice"](
        {"target": TARGET, "operationId": queued["sequence"]})
    assert observed["outcome"] == "refused"
    assert len(port.calls) == 1            # reconcile observes, never re-applies
    assert gate.query()["desired"]["modelId"] == "m1"

    port.result = _ready(queued["sequence"])
    assert gate.begin(operation_key="submit-key-0003")["outcome"] == "ready"
    assert len(port.calls) == 2


def test_a_confirmed_observation_clears_the_block(stack, harnesses, credentials):
    port = RecordingTurnApplication(SubmitResult(outcome="unknown", reason="receipt lost"))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    gate.begin()
    # the legacy read-back double reports the intended model: a confirmed
    # observation consumes the intent and settles the session
    observed = gate.handlers["modelProvider.reconcileChoice"](
        {"target": TARGET, "operationId": queued["sequence"]})
    assert observed["outcome"] == "confirmed"
    assert gate.query()["desired"] is None
    port.result = _ready(queued["sequence"])
    # nothing is left to submit for this session
    assert gate.begin(operation_key="submit-key-0004")["outcome"] == "no-intent"


# -- fencing (M09/M12) ---------------------------------------------------------

def test_a_stale_expected_sequence_is_refused_without_applying(stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose(model="m1")
    latest = gate.choose(model="m2", operation_key="chat-queue-0002")
    answer = gate.begin(expected=latest["sequence"] - 1)
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "TARGET_STALE"
    assert answer["sequence"] == latest["sequence"]
    assert port.calls == []
    assert gate.query()["desired"]["modelId"] == "m2"    # the newer pick survives


def test_a_submission_never_consumes_another_session_s_intent(
        stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose(target=TARGET)
    gate.choose(target=OTHER_TARGET, operation_key="chat-queue-0002")
    gate.port.result = _ready(gate.query(target=OTHER_TARGET)["revision"])
    answer = gate.begin(target=OTHER_TARGET, operation_key="submit-key-0002")
    assert answer["outcome"] == "ready"
    assert port.last["target"] == OTHER_TARGET
    assert gate.query(target=TARGET)["desired"]["modelId"] == "m1"


def test_a_pick_made_during_the_application_survives_the_ready(stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    first = gate.choose(model="m1")

    def pick_again(target):
        if target == TARGET and not port.calls[0]["intent"]["choice"]["modelId"] == "m2":
            gate.choose(model="m2", operation_key="chat-queue-0002")

    port._before_submit = pick_again
    port.result = _ready(first["sequence"])
    answer = gate.begin()
    # the application really happened and is reported with its evidence ...
    assert answer["outcome"] == "ready"
    assert answer["sequence"] == first["sequence"]
    # ... but it never consumed the pick made while it ran (FR-04, M12)
    assert gate.query()["desired"]["modelId"] == "m2"


def test_an_answer_naming_another_sequence_is_discarded(stack, harnesses, credentials):
    port = RecordingTurnApplication(_ready(sequence=9999))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    answer = gate.begin()
    assert answer["outcome"] == "unknown"
    assert answer["sequence"] == queued["sequence"]
    assert gate.query()["desired"]["modelId"] == "m1"


def test_a_ready_without_real_evidence_is_not_ready(stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()

    for index, broken in enumerate(
            ({}, {"operationId": "op-1"}, _evidence() | {"evidenceRef": ""},
             _evidence() | {"nativeTarget": {"owner": "a"}},
             _evidence() | {"nativeTarget": {"owner": "a", "canonicalUid": "u",
                                             "generation": -1}})):
        port.result = SubmitResult(outcome="ready", sequence=None, application=broken)
        gate = Gate(stack, harnesses, credentials, port=port)
        queued = gate.choose(operation_key=f"chat-queue-evidence-{index}")
        answer = gate.begin(operation_key=f"submit-evidence-{index}")
        assert answer["outcome"] == "unknown", broken
        assert answer["sequence"] == queued["sequence"]
        assert answer["application"] is None
        assert gate.query()["desired"]["modelId"] == "m1"


def test_an_unreadable_port_answer_blocks_rather_than_passes(stack, harnesses, credentials):
    from ordessa_model_provider.ports import (
        SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED, SessionConfigError,
    )

    port = RecordingTurnApplication(error=SessionConfigError(
        SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose(operation_key="chat-queue-unknown-1")
    assert gate.begin(operation_key="submit-unknown-1")["outcome"] == "unknown"
    assert gate.begin(operation_key="submit-unknown-2")["outcome"] == "unknown"
    assert len(port.calls) == 1

    port = RecordingTurnApplication(error=SessionConfigError(
        SESSION_CONFIG_REJECTED, "authorization refused"))
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose(operation_key="chat-queue-rejected-1")
    answer = gate.begin(operation_key="submit-rejected-1")
    assert answer["outcome"] == "refused"
    assert answer["reason"] == SESSION_CONFIG_REJECTED
    assert gate.query()["desired"]["modelId"] == "m1"


def test_a_result_routed_to_another_generation_is_refused(stack, harnesses, credentials):
    port = RecordingTurnApplication(
        _ready(sequence=1, application=_evidence(generation=8)),
        routing={"owner": "native-a", "canonicalUid": "uid-1", "generation": 7})
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()
    answer = gate.begin()
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "TARGET_STALE"
    assert gate.query()["desired"]["modelId"] == "m1"

    # the exact observed identity is accepted, and it is part of the key
    port.result = _ready(sequence=1)
    answer = gate.begin(operation_key="submit-key-0002")
    assert answer["outcome"] == "ready"
    assert answer["sequence"] == queued["sequence"]


# -- M10: a stale plan is refused before the port ---------------------------

def test_a_catalogue_change_after_queueing_refuses_the_stale_plan(
        stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    queued = gate.choose()

    # the config was edited (a new version, e.g. a rotated credential or a new
    # endpoint) after the intent was frozen
    gate.handlers["modelProvider.saveProviderConfig"]({
        "operationKey": "op-cfg-update-001", "expectedVersion": gate.record["version"],
        "patch": {"providerConfigId": gate.record["id"], **_two_models_body(displayName="v2")},
    })
    answer = gate.begin()
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "CONFIG_REVISION_CONFLICT"
    assert port.calls == []
    assert gate.query()["desired"]["modelId"] == "m1"   # kept for a fresh pick


def test_an_archived_config_refuses_the_stale_plan(stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose()
    gate.handlers["providerModels.archive"]({
        "requestId": "req-archive-001", "providerModelId": gate.record["id"],
        "expectedVersion": gate.record["version"]})
    answer = gate.begin()
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "PROVIDER_ARCHIVED"
    assert port.calls == []


def test_the_submitted_key_is_version_bearing(stack, harnesses, credentials):
    port = RecordingTurnApplication()
    gate = Gate(stack, harnesses, credentials, port=port)
    gate.choose()
    port.result = SubmitResult(outcome="ready", sequence=None,
                               application=_evidence())
    gate.begin()
    key = port.last["operationKey"]
    assert key.startswith(f"mp-turn-s1-v{gate.record['version']}-")
    assert not key.endswith("-")  # never an unversioned legacy key
    assert key != f"mp-{key}"


# -- absence of the real application entry ------------------------------------

def test_without_the_port_the_gate_refuses_typed_and_never_falls_back(
        stack, harnesses, credentials):
    # the legacy pseudo read-back port IS injected here - and must stay unused
    legacy = ReadyPort()
    gate = Gate(stack, harnesses, credentials, port=None, legacy=legacy)
    queued = gate.choose()
    answer = gate.begin()
    assert answer["outcome"] == "refused"
    assert answer["reason"] == "ADAPTER_MISSING"
    assert answer["sequence"] == queued["sequence"]
    assert answer["application"] is None
    assert legacy.applies == 0                     # no fallback application
    assert gate.query()["desired"]["modelId"] == "m1"


def test_a_composition_without_any_port_cannot_queue_a_selection(stack, harnesses, credentials):
    """C03, the plugin half: with neither the eligibility port nor the
    application port, the independent path refuses typed at the queue step -
    there is no fallback that could let a prompt through."""
    from ordessa_server.wire.errors import WireError

    from ordessa_model_provider.plugin import ModelProviderPlugin

    plugin = ModelProviderPlugin(harnesses=harnesses)
    from types import SimpleNamespace

    context = SimpleNamespace(ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })
    handlers = {item.method_id: item.handler for item in plugin.build(context).methods}
    record = handlers["providerModels.create"]({
        "requestId": "req-gate-noport-001", **_two_models_body()})["providerModel"]
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.chooseForSession"]({
            "target": TARGET, "choice": _choice(record["id"]),
            "operationKey": "chat-queue-0001"})
    assert excinfo.value.details["internalCode"] == "SELECTION_UNSUPPORTED"

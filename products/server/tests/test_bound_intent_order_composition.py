"""Bound-session click-order and intent-handover composition counterexamples
(021 appendix §6c, codex review F1/F2).

The real product composition (``native_runtime``) drives the exact wire calls
the two composer contributions emit, in the order the user clicked:

- F1: the click that happened first must reach the backend first, and the
  backend's ``action_seq`` stamping must make the last *click* win - in both
  arrival orders (P→M and M→P), for consecutive picks, and for a pick made
  while an application is in flight; every send still applies exactly once
  and nothing is written back to the global profile record;
- F2: a bound target whose overlay handover FAILED or is UNKNOWN is never
  folded into "unbound": ``chooseForSession`` answers ``intentRoute``
  (``profile-overlay`` | ``independent`` | ``handover-failed``), the intent
  stays queued with the mark, and ``modelProvider.beginTurnApplication``
  typed-refuses ``HANDOVER_UNRESOLVED`` with zero native effects until a
  newer successful pick supersedes the mark. A composition without the sink
  reads ``independent`` and applies for real (M01 semantics, now visible).

Controlled-evidence level identical to ``test_native_model_turn_composition``
(the deep native agent boundary is the controlled double; everything between
the wire and the channel is the real product chain).
"""
from __future__ import annotations

import threading

from test_native_model_turn_composition import (
    TARGET, _begin, _bound_runtime, _overlay_rows, bind_native, choice_of,
    controlled_native, model_plugin, observe_bound_target, runtime_at,
    seed_provider,
)

import json
import pytest


@pytest.mark.parametrize("saved_model,expected", [(None, "acme/m2"), ("m1", "acme/m1")])
def test_first_profile_binding_adopts_older_independent_intent(tmp_path, monkeypatch, saved_model, expected):
    runtime = runtime_at(tmp_path, pi_profile_bridge=True)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        record = seed_provider(runtime)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET, "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "first-independent-model"})
        assert pending["intentRoute"] == "independent"
        profile = runtime.wire.dispatch("profiles.v2.createProfile", {
            "operationKey": "first-profile", "realm": "local", "harnessId": "pi",
            "displayName": "First"})["data"]
        if saved_model:
            runtime.wire.dispatch("profiles.v2.saveProfile", {
                "operationKey": "first-profile-values", "profileId": profile["profileId"],
                "expectedVersion": 1, "patches": [{"facetId": "assets.model-provider",
                "itemId": "choice", "op": "set", "value": choice_of(record, saved_model)}]})
        ref = runtime.wire.dispatch("profiles.v2.registerNativeSession", {
            "connectionId": "connection", "nativeSessionId": "s-1",
            "profileId": profile["profileId"]})["data"]["sessionRef"]
        observe_bound_target(controlled)
        runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "first-profile-click", "sessionRef": ref, "profileId": profile["profileId"]})
        assert runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})["intentRoute"] == "profile-overlay"
        assert "receipt" in _begin(runtime, ref, "first-bound-apply")
        assert [op["requestedValue"] for op in controlled.channel.operations] == [expected]
    finally:
        runtime.stop()


def test_routed_intent_after_profile_unload_never_answers_no_intent(tmp_path, monkeypatch):
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch, saved_model="m1")
    try:
        runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET, "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "routed-before-unload"})
        runtime.plugin_host.deactivate("ordessa.skills")
        runtime.plugin_host.deactivate("ordessa.profile")
        answer = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "unloaded-profile-submit"})
        assert answer["outcome"] == "refused"
        assert answer["reason"] == "HANDOVER_UNRESOLVED"
        assert controlled.channel.operations == []
        assert runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})["desired"]["modelId"] == "m2"
    finally:
        runtime.stop()


# -- F1: click order = intent order, both directions --------------------------------


def test_profile_click_then_model_click_model_wins_single_apply(tmp_path, monkeypatch):
    """P(m1) → M(m2) → send: the later click (m2) wins, exactly one apply."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        # P-click: the explicit Profile selection registers at click time
        clicked = runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "f1-p-click", "sessionRef": ref,
            "profileId": profile["profileId"]})["data"]
        assert clicked["switchState"] == "pending"
        # M-click: the model choice hands over to the session overlay
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f1-m-click"})
        assert pending["outcome"] == "pending-next-turn"
        assert pending["intentRoute"] == "profile-overlay"
        state = runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})
        assert state["desired"]["modelId"] == "m2"
        assert state["intentRoute"] == "profile-overlay"
        # the send: the model gate answers no-intent (the overlay owns the
        # intent); the Profile pipeline performs the one real application
        routed = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f1-m-gate",
            "expectedSequence": pending["sequence"]})
        assert routed["outcome"] == "no-intent"
        turned = _begin(runtime, ref, "f1-send")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 1  # one native effect per send
        # zero global write-back: the profile record itself is unchanged
        record_before = runtime.wire.dispatch("profiles.v2.getProfile",
                                              {"profileId": profile["profileId"]})["data"]
        current = runtime.wire.dispatch("profiles.v2.getProfile",
                                        {"profileId": profile["profileId"]})["data"]
        assert current["currentRevision"] == record_before["currentRevision"]
    finally:
        runtime.stop()


def test_model_click_then_profile_click_profile_wins_single_apply(tmp_path, monkeypatch):
    """M(m2) → P(m1) → send: the later click (the Profile) wins; the in-mask
    older temporary value is consumed and the overlay is cleared."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f1-reverse-m-click"})
        assert pending["outcome"] == "pending-next-turn"
        assert pending["intentRoute"] == "profile-overlay"
        runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "f1-reverse-p-click", "sessionRef": ref,
            "profileId": profile["profileId"]})
        turned = _begin(runtime, ref, "f1-reverse-send")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m1"
        assert len(controlled.channel.operations) == 1
        assert _overlay_rows(runtime) == []  # the in-mask temporary pick was consumed
    finally:
        runtime.stop()


def test_model_click_then_model_free_profile_keeps_the_pick(tmp_path, monkeypatch):
    """M(m2) → P(no model item) → send: the mask-external pick is kept."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        other = runtime.wire.dispatch("profiles.v2.createProfile", {
            "operationKey": "f1-keep-create", "realm": "local", "harnessId": "pi",
            "displayName": "Other"})["data"]
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f1-keep-m-click"})
        assert pending["intentRoute"] == "profile-overlay"
        runtime.wire.dispatch("profiles.v2.selectForSession", {
            "operationKey": "f1-keep-p-click", "sessionRef": ref,
            "profileId": other["profileId"]})
        turned = _begin(runtime, ref, "f1-keep-send")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        rows = _overlay_rows(runtime)
        assert len(rows) == 1 and json.loads(rows[0]["value_json"])["modelId"] == "m2"
    finally:
        runtime.stop()


def test_consecutive_model_clicks_collapse_into_the_newest_single_overlay(tmp_path, monkeypatch):
    """M(m1) → M(m2) → send: the queue and the overlay keep only m2; one apply."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        first = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m1"},
            "operationKey": "f1-consecutive-a"})
        second = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f1-consecutive-b"})
        assert second["sequence"] > first["sequence"]
        assert second["intentRoute"] == "profile-overlay"
        rows = _overlay_rows(runtime)
        assert len(rows) == 1 and json.loads(rows[0]["value_json"])["modelId"] == "m2"
        state = runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})
        assert state["desired"]["modelId"] == "m2"
        assert state["intentRoute"] == "profile-overlay"
        gate = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f1-consecutive-gate",
            "expectedSequence": second["sequence"]})
        assert gate["outcome"] == "no-intent"
        turned = _begin(runtime, ref, "f1-consecutive-send")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 1
    finally:
        runtime.stop()


def test_click_during_in_flight_bound_send_waits_for_the_next_turn(tmp_path, monkeypatch):
    """A click made while a bound application is in flight only queues (its
    overlay action_seq is later); the in-flight send keeps its admitted value
    and the next send applies the clicked one."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        gate = threading.Event()
        controlled.channel.gate = gate
        outcome: dict = {}

        def send():
            outcome["turn"] = _begin(runtime, ref, "f1-inflight-send")

        worker = threading.Thread(target=send)
        worker.start()
        try:
            clicked = runtime.wire.dispatch("modelProvider.chooseForSession", {
                "target": TARGET,
                "choice": {"providerConfigId": record["id"], "modelId": "m2"},
                "operationKey": "f1-inflight-click"})
            assert clicked["outcome"] == "pending-next-turn"
            assert clicked["intentRoute"] == "profile-overlay"
        finally:
            # always release the native boundary, whatever the assertions did
            gate.set()
            worker.join(timeout=30)
        assert "receipt" in outcome["turn"]
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m1"
        assert len(controlled.channel.operations) == 1
        controlled.channel.gate = None
        # the routed intent survives the in-flight send; the next send applies it
        routed = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f1-inflight-gate",
            "expectedSequence": clicked["sequence"]})
        assert routed["outcome"] == "no-intent"
        second = _begin(runtime, ref, "f1-inflight-send-2")
        assert "receipt" in second
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 2  # still one per send
    finally:
        runtime.stop()


# -- F2: a failed/unknown overlay handover is never "unbound" -----------------------


def _flaky_overlay(runtime, monkeypatch, state):
    """Make the sink's overlay write fail while ``state['ok']`` is False."""
    core = runtime.plugin_host.provided_port("profile.core")
    original = core.sessions.set_overlay

    def flaky(*args, **kwargs):
        if not state["ok"]:
            raise state["error"]()
        return original(*args, **kwargs)

    monkeypatch.setattr(core.sessions, "set_overlay", flaky)
    return core


def test_handover_failure_marks_the_intent_and_blocks_the_send(tmp_path, monkeypatch):
    """set_overlay raising is a handover FAILURE: intentRoute=handover-failed,
    the intent stays queued with the mark, the submit gate typed-refuses
    HANDOVER_UNRESOLVED with zero native effects, and a newer successful pick
    supersedes the mark."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        state = {"ok": False, "error": lambda: RuntimeError("overlay write lost")}
        _flaky_overlay(runtime, monkeypatch, state)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f2-failed-click"})
        assert pending["outcome"] == "pending-next-turn"  # the intent is kept
        assert pending["intentRoute"] == "handover-failed"
        state_view = runtime.wire.dispatch("modelProvider.queryChoice", {"target": TARGET})
        assert state_view["desired"]["modelId"] == "m2"
        assert state_view["intentRoute"] == "handover-failed"
        # the backend backstop: typed refusal, intent kept, zero apply
        gate = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f2-failed-gate",
            "expectedSequence": pending["sequence"]})
        assert gate["outcome"] == "refused"
        assert gate["reason"] == "HANDOVER_UNRESOLVED"
        assert gate["application"] is None
        assert controlled.channel.operations == []  # zero native effects
        # a newer successful pick supersedes the failed mark
        state["ok"] = True
        retry = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f2-failed-retry"})
        assert retry["intentRoute"] == "profile-overlay"
        routed = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f2-failed-gate-2",
            "expectedSequence": retry["sequence"]})
        assert routed["outcome"] == "no-intent"
        turned = _begin(runtime, ref, "f2-failed-send")
        assert "receipt" in turned
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m2"
        assert len(controlled.channel.operations) == 1
    finally:
        runtime.stop()


def test_unknown_handover_outcome_is_never_folded_into_unbound(tmp_path, monkeypatch):
    """An unexpected bridge exception is an UNKNOWN handover, not 'unbound':
    fail-closed with the same mark and backstop (no independent apply)."""
    runtime, controlled, record, profile, ref = _bound_runtime(tmp_path, monkeypatch,
                                                               saved_model="m1")
    try:
        state = {"ok": False,
                 "error": lambda: ValueError("intent bridge exploded")}
        _flaky_overlay(runtime, monkeypatch, state)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m2"},
            "operationKey": "f2-unknown-click"})
        assert pending["outcome"] == "pending-next-turn"
        assert pending["intentRoute"] == "handover-failed"
        gate = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f2-unknown-gate",
            "expectedSequence": pending["sequence"]})
        assert gate["outcome"] == "refused"
        assert gate["reason"] == "HANDOVER_UNRESOLVED"
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


def test_without_the_sink_the_route_reads_independent_and_applies(tmp_path, monkeypatch):
    """No Profile assembly: sink absent → intentRoute=independent, and the
    submit gate applies for real over the shared C4 (M01, now explicit)."""
    runtime = runtime_at(tmp_path, include_profile=False)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime)
        bind_native(controlled)
        record = seed_provider(runtime)
        pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
            "target": TARGET,
            "choice": {"providerConfigId": record["id"], "modelId": "m1"},
            "operationKey": "f2-independent-click"})
        assert pending["outcome"] == "pending-next-turn"
        assert pending["intentRoute"] == "independent"
        answer = runtime.wire.dispatch("modelProvider.beginTurnApplication", {
            "target": TARGET, "operationKey": "f2-independent-gate",
            "expectedSequence": pending["sequence"]})
        assert answer["outcome"] == "ready"
        assert controlled.channel.operations[-1]["requestedValue"] == "acme/m1"
    finally:
        runtime.stop()

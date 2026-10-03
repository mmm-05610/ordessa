"""T010-10 gates: the A1 five-owner wire face round-trips through the plugin
registration — the InteractionOwner entries included (agent.interaction.*)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ordessa_agent.plugin import AgentDomainPlugin
from ordessa_agent.owners import AgentOwnerRegistry


def handlers_of(registration):
    return {method.method_id: method.handler for method in registration.methods}


@pytest.fixture()
def handlers():
    return handlers_of(AgentDomainPlugin(AgentOwnerRegistry()).build(SimpleNamespace()))


def test_interaction_record_then_list_round_trip(handlers):
    recorded = handlers["agent.interaction.record"](
        {"target": "t1", "interactionId": "i1", "fields": {"kind": "approval", "state": "pending"}})
    assert recorded == {"record": {"kind": "approval", "state": "pending"}}
    listed = handlers["agent.interaction.list"]({"target": "t1"})
    assert listed == {"items": [{"kind": "approval", "state": "pending"}]}


def test_interaction_record_refuses_malformed_frames(handlers):
    with pytest.raises(Exception):
        handlers["agent.interaction.record"]({"target": "t1", "fields": {}})
    with pytest.raises(Exception):
        handlers["agent.interaction.record"]({"target": "t1", "interactionId": "i1", "fields": "not-a-map"})


def test_five_owner_faces_share_one_registry_across_methods(handlers):
    handlers["agent.config.submitOperation"]({"target": "t2", "patch": {"model": "m"}})
    handlers["agent.submitInput"]({"target": "t2", "draftRevision": 3, "capture": {"outcome": "accepted"}})
    handlers["agent.interaction.record"]({"target": "t2", "interactionId": "i", "fields": {"ok": True}})
    snapshot = handlers["agent.config.read"]({"target": "t2"})
    assert snapshot["resolved"] == {"model": "m"}
    assert snapshot["revision"] == 1
    assert handlers["agent.session.list"]({"target": "t2"}) == {"items": []}
    assert handlers["agent.run.query"]({"target": "t2", "runId": "r"}) == {
        "outcome": "unknown", "queryHint": "run:r", "resend": False}

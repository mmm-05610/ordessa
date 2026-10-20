"""The generation callback is bounded by the retained original Unit owner."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ordessa_units.api import UnitApiRefused


ROOT = Path(__file__).resolve().parents[3]
UNIT_TESTS = ROOT / "packages/execution/units/tests"
if str(UNIT_TESTS) not in sys.path:
    sys.path.insert(0, str(UNIT_TESTS))
from test_local_owner import ACP_PEER_REVERSE_WRITE, live_owner


_OPERATOR_PATH = ROOT / "tooling/checks/server_product/probe-work-package-generation.py"
_OPERATOR_SPEC = importlib.util.spec_from_file_location(
    "generation_file_callback_operator", _OPERATOR_PATH)
_OPERATOR = importlib.util.module_from_spec(_OPERATOR_SPEC)
_OPERATOR_SPEC.loader.exec_module(_OPERATOR)


class _DeferredCallbackApproval:
    """Assembly-time placeholder; the real owner is bound after Unit creation."""

    def __init__(self):
        self.delegate = None

    def authorize(self, **request):
        if self.delegate is None:
            raise AssertionError("the original Unit callback owner was not bound")
        return self.delegate.authorize(**request)


_DEFERRED_APPROVAL = _DeferredCallbackApproval()


def _peer_for(path):
    return ACP_PEER_REVERSE_WRITE.replace("callback-proof.txt", path)


def _bind_generation_approval(world, unit):
    runtime = SimpleNamespace(unit_execution_owner=world.owner, units=world.public_manager)
    approval = _OPERATOR.generation_file_approval(
        runtime=runtime,
        permission=world.owner.permission,
        environment_instance=world.environment,
    )
    _DEFERRED_APPROVAL.delegate = approval
    return approval


def _unit_cwd(world, unit):
    reservation = world.owner.records.owner_read_unit(unit.identity["unitId"])
    return Path(reservation.facts["privateRootFacts"]["cwd"])


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "preparation_peer": _peer_for("spec.md"),
    "callback_approval": _DEFERRED_APPROVAL,
}], indirect=True)
def test_original_sdk_callback_writes_only_selected_generation_document(live_owner):
    world = live_owner
    assert _DEFERRED_APPROVAL.delegate is None
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    interaction = None
    try:
        approval = _bind_generation_approval(world, unit)
        interaction = unit.interaction(authorization)
        response = interaction.prompt(
            {"prompt": [{"type": "text", "text": "exercise the original ACP callback"}]},
            timeout=5,
        )

        assert response["callbackReply"] == {
            "jsonrpc": "2.0", "id": "reverse-write", "result": {}}
        assert (_unit_cwd(world, unit) / "spec.md").read_text(encoding="utf-8") == "written-once"
        assert not (_unit_cwd(world, unit) / "other.md").exists()

        session_id = unit.snapshot()["sessionId"]
        unit_ref = dict(unit.identity)
        base = {
            "unit_ref": unit_ref,
            "session_id": session_id,
            "environment_identity": world.environment.identity,
            "request_id": "direct-guard-check",
            "method": "session/request_permission",
        }
        command_request = {
            "sessionId": session_id,
            "approval": "command",
            "files": ["spec.md"],
            "toolCall": {"kind": "execute", "locations": [{"path": "spec.md"}]},
            "options": [{"kind": "allow_once", "optionId": "once"}],
        }
        assert approval.authorize(**base, params=command_request) is None

        always_only_request = {
            "sessionId": session_id,
            "approval": "file",
            "files": ["spec.md"],
            "toolCall": {"kind": "edit", "locations": [{"path": "spec.md"}]},
            "options": [{"kind": "allow_always", "optionId": "always"}],
        }
        assert approval.authorize(**base, params=always_only_request) is None

        with pytest.raises(UnitApiRefused):
            approval.authorize(**{**base, "method": "fs/write_text_file",
                                  "environment_identity": "foreign-environment"},
                               params={"sessionId": session_id, "path": "spec.md"})
        with pytest.raises(UnitApiRefused):
            approval.authorize(**{**base, "method": "fs/write_text_file",
                                  "session_id": "foreign-session"},
                               params={"sessionId": session_id, "path": "spec.md"})
    finally:
        if interaction is not None:
            interaction.disconnect()
        unit.close(authorization)
        _DEFERRED_APPROVAL.delegate = None


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "preparation_peer": _peer_for("other.md"),
    "callback_approval": _DEFERRED_APPROVAL,
}], indirect=True)
def test_original_sdk_callback_refuses_unlisted_generation_document(live_owner):
    world = live_owner
    assert _DEFERRED_APPROVAL.delegate is None
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    interaction = None
    try:
        _bind_generation_approval(world, unit)
        interaction = unit.interaction(authorization)
        response = interaction.prompt(
            {"prompt": [{"type": "text", "text": "attempt an unlisted file callback"}]},
            timeout=5,
        )

        assert response["callbackReply"]["error"] == {
            "code": -32000, "message": "Original callback approval refused", "data": None}
        assert not (_unit_cwd(world, unit) / "other.md").exists()
    finally:
        if interaction is not None:
            interaction.disconnect()
        unit.close(authorization)
        _DEFERRED_APPROVAL.delegate = None


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "preparation_peer": _peer_for("spec.md"),
}], indirect=True)
def test_missing_original_callback_owner_returns_unavailable_without_file_effect(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    interaction = None
    try:
        interaction = unit.interaction(authorization)
        response = interaction.prompt(
            {"prompt": [{"type": "text", "text": "request a file callback without an owner"}]},
            timeout=5,
        )

        assert response["callbackReply"]["error"] == {
            "code": -32000, "message": "Original callback approval owner unavailable",
            "data": None}
        assert not (_unit_cwd(world, unit) / "spec.md").exists()
    finally:
        if interaction is not None:
            interaction.disconnect()
        unit.close(authorization)

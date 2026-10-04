"""Actual product/wire/Agent/Environment/journal with a controlled native edge.

Only the Harness/native conditional-submit/query/history capability and its
SQLite effects are controlled. Product composition, Server wire registry,
Agent owners, Environment dispatch claim, and domain journal remain real.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from server_plugin_api import WireError

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "scripts" / "packaging"
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))

from controlled_native_fixture import (  # noqa: E402
    ControlledNativeFixture,
    controlled_product_composition,
    controlled_submission_policy,
    test_protected_fingerprint as _test_fingerprint_fixture,
)

DRAFT_LOCATION = {
    "kind": "draft",
    "connectionId": "controlled-connection",
    "draftId": "controlled-draft-1",
}
PRINCIPAL = "local"
ATTACHMENT_ID = "attachment-controlled-1"
ATTACHMENT_BYTES = b"immutable controlled native attachment\x00bytes"


def _runtime(data_root: Path, native, fingerprint, policy, *, include_profile: bool):
    composition = controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=fingerprint,
        submission_policy=policy,
    )
    return composition.default_runtime(data_root, include_profile=include_profile)


def _resolve_target(runtime) -> str:
    resolved = runtime.wire.dispatch("agent.session.resolve", {"location": DRAFT_LOCATION})
    target = resolved["target"]
    assert isinstance(target, str) and target
    return target


def _write_config_operation(runtime, target: str, patch: dict[str, object]) -> str:
    result = runtime.wire.dispatch("agent.config.submitOperation", {
        "target": target,
        "patch": patch,
        "sourceRef": "controlled-closeout-profile-intent",
    })
    assert result["state"] == "pending"
    return result["operationId"]


def _capture(*, submission_id: str, revision: int, text: str, operation_id: str, mode: str):
    return {
        "submissionId": submission_id,
        "draft": {
            "draftId": DRAFT_LOCATION["draftId"],
            "draftRevision": revision,
            "text": text,
            "attachmentIds": [ATTACHMENT_ID],
        },
        "configOperationIds": [operation_id],
        "schema": "agent-input/v1",
        "mode": mode,
    }


def _submit(runtime, target: str, capture: dict[str, object]):
    return runtime.wire.dispatch("agent.submitInput", {
        "target": target,
        "draftRevision": capture["draft"]["draftRevision"],
        "capture": capture,
    })


def _query(runtime, target: str, submission_id: str):
    return runtime.wire.dispatch("agent.submission.query", {
        "target": target,
        "submissionId": submission_id,
    })


@pytest.mark.parametrize("include_profile", [True, False])
def test_controlled_native_two_rounds_and_restart_history_use_real_product_wire(
    tmp_path, include_profile,
):
    effects_db = tmp_path / "native-effects.sqlite"
    native = ControlledNativeFixture(
        effects_db,
        mode="createWithConfig",
        attachment_bytes={ATTACHMENT_ID: ATTACHMENT_BYTES},
    )
    fingerprint = _test_fingerprint_fixture()
    policy = controlled_submission_policy()
    data_root = tmp_path / "server-data"

    runtime = _runtime(data_root, native, fingerprint, policy, include_profile=include_profile)
    try:
        runtime.start()
        enabled = {plugin.descriptor().id for plugin in runtime.plugin_selection}
        assert ('ordessa.profile' in enabled) is include_profile
        target = _resolve_target(runtime)
        native.bind_backend_target(target)

        # A first-send draft is backend-minted and maps to the same logical
        # target through both configurations and the later restart.
        first_operation = _write_config_operation(
            runtime, target, {"model": "M1", "general.prompt": "Preserve this prompt"},
        )
        assert runtime.wire.dispatch('agent.config.read', {'target':target})['revision'] == 1
        native.set_mode("createWithConfig")  # explicit fresh-session condition
        first_capture = _capture(
            submission_id="controlled-submission-1", revision=1,
            text="first prompt", operation_id=first_operation, mode="createWithConfig",
        )
        first = _submit(runtime, target, first_capture)
        assert first["outcome"] == "accepted"
        assert first["stage"] == "completed"
        assert first["replayed"] is False
        assert first["configApply"] == {"outcome": "applied", "operationIds": [first_operation]}
        assert first["inputAcceptance"]["session"] == {
            "sessionId": "logical-session-controlled-1",
            "nativeSessionId": "native-session-controlled-1",
            "generation": 1,
            "ownerRef": "native-owner:controlled-1",
        }
        assert first["runResult"] == {"outcome": "running", "runId": "run-controlled-submission-1"}
        assert runtime.wire.dispatch('agent.config.read', {'target':target})['revision'] == 2

        second_operation = _write_config_operation(runtime, target, {"model": "M2"})
        assert runtime.wire.dispatch('agent.config.read', {'target':target})['revision'] == 3
        native.set_mode("existing")  # explicit continuation of that native session
        second_capture = _capture(
            submission_id="controlled-submission-2", revision=2,
            text="second prompt", operation_id=second_operation, mode="existing",
        )
        second = _submit(runtime, target, second_capture)
        assert second["outcome"] == "accepted"
        assert second["stage"] == "completed"
        assert second["configApply"] == {"outcome": "applied", "operationIds": [second_operation]}
        config = runtime.wire.dispatch("agent.config.read", {"target": target})
        assert config["resolved"] == {"model": "M2", "general.prompt": "Preserve this prompt"}
        # Intent and trusted result settlement both advance the same chain.
        assert config["revision"] == 4
        assert len(config['operations']) == 2
        assert config["operations"][0]["state"] == "applied"
        assert config["operations"][1]["state"] == "applied"

        history1 = _query(runtime, target, "controlled-submission-1")
        history2 = _query(runtime, target, "controlled-submission-2")
        assert history1["outcome"] == history2["outcome"] == "accepted"
        assert history1["resend"] is history2["resend"] is False
        assert history1["inputAcceptance"]["session"]["nativeSessionId"] == "native-session-controlled-1"
        assert history2["runResult"]["runId"] == "run-controlled-submission-2"
        sessions = runtime.wire.dispatch("agent.session.list", {"target": target})
        assert sessions["source"] == "native-query"
        assert sessions["items"] == [{
            "target": target,
            "sessionId": "logical-session-controlled-1",
            "nativeSessionId": "native-session-controlled-1",
            "generation": 1,
            "ownerRef": "native-owner:controlled-1",
            "source": "native-session-query",
        }]
        counts_before_restart = native.all_effect_counts()
        assert len(counts_before_restart) == 2
        assert set(counts_before_restart.values()) == {1}
        assert {event[2] for event in native.dispatches} == {
            "controlled-submission-1", "controlled-submission-2",
        }
    finally:
        runtime.stop()

    # A new Server runtime gets the same SQLite Environment and Agent journal,
    # and the controlled native fixture reconstructs results from its separate
    # native effects DB. No model/adapter call is involved.
    restarted = _runtime(data_root, native, fingerprint, policy, include_profile=include_profile)
    try:
        restarted.start()
        target_after_restart = _resolve_target(restarted)
        assert target_after_restart == target
        native.bind_backend_target(target_after_restart)
        for submission_id in ("controlled-submission-1", "controlled-submission-2"):
            restored = _query(restarted, target_after_restart, submission_id)
            assert restored["outcome"] == "accepted"
            assert restored["resend"] is False
            assert restored["configApply"]["outcome"] == "applied"
            assert restored["inputAcceptance"]["outcome"] == "accepted"
            assert restored["runResult"]["outcome"] == "running"
        sessions_after_restart = restarted.wire.dispatch("agent.session.list", {"target": target_after_restart})
        assert sessions_after_restart["source"] == "native-query"
        assert len(sessions_after_restart["items"]) == 1

        binding_calls_before_replay = len(native.dispatches)
        replay = _submit(restarted, target_after_restart, second_capture)
        assert replay["outcome"] == "accepted"
        assert replay["replayed"] is True
        assert replay["resend"] is False
        assert native.all_effect_counts() == counts_before_restart
        assert len(native.dispatches) == binding_calls_before_replay
    finally:
        restarted.stop()

    # Attachment bytes are resolved through the test adapter; native effects
    # are counted by the complete Environment/principal/request identity.
    with sqlite3.connect(effects_db) as connection:
        rows = connection.execute("SELECT payload FROM native_effect_events ORDER BY event_id").fetchall()
    expected_digest = hashlib.sha256(ATTACHMENT_BYTES).hexdigest()
    payloads = [json.loads(row[0]) for row in rows]
    assert len(payloads) == 2
    assert all(item["attachmentSha256"] == {ATTACHMENT_ID: expected_digest} for item in payloads)
    assert {item["mode"] for item in payloads} == {"existing", "createWithConfig"}


@pytest.mark.parametrize("missing", ["native", "native-condition", "fingerprint", "policy"])
def test_missing_native_capability_or_durability_dependency_is_typed_and_has_zero_effects(
    tmp_path, missing,
):
    mode = "createWithConfig" if missing == "native-condition" else "existing"
    native = ControlledNativeFixture(
        tmp_path / "native-effects.sqlite", mode=mode,
        attachment_bytes={ATTACHMENT_ID: ATTACHMENT_BYTES},
        create_with_config_conditional=(missing != "native-condition"),
    )
    fingerprint = _test_fingerprint_fixture()
    policy = None
    if missing == "native":
        native_port = None
    else:
        native_port = native
    if missing == "fingerprint":
        fingerprint = None
    if missing == "policy":
        # Product's default local policy deliberately refuses agent.submit.
        # This must remain a typed authorization refusal before any native call.
        policy = None

    runtime = _runtime(
        tmp_path / "server-data", native_port, fingerprint, policy, include_profile=False,
    )
    try:
        runtime.start()
        target = _resolve_target(runtime)
        native.bind_backend_target(target)
        operation_id = _write_config_operation(runtime, target, {"model": "M1"})
        capture = _capture(
            submission_id=f"missing-{missing}", revision=1, text="cannot dispatch",
            operation_id=operation_id, mode=mode,
        )
        expected_family = "FORBIDDEN" if missing == "policy" else "CAPABILITY_UNSUPPORTED"
        with pytest.raises(WireError) as failure:
            _submit(runtime, target, capture)
        assert failure.value.family == expected_family
        if missing == 'policy':
            assert failure.value.details['internalCode'] == 'AUTHORIZATION_REFUSED'
        assert native.all_effect_counts() == {}
        assert native.dispatches == []
    finally:
        runtime.stop()

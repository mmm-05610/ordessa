"""Historical submission facts stay queryable after binding decoders disappear.

The test uses the real product Environment, Agent journal, Server wire and
SQLite stores. Only the native conditional edge and its separately owned
effect database are controlled; the restarted query has no native or
fingerprint capability.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "scripts" / "packaging"
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))

from controlled_native_fixture import (  # noqa: E402
    ControlledNativeFixture,
    controlled_product_composition,
    test_protected_fingerprint as _test_fingerprint,
)
from ordessa_server_product.composition import create_composition  # noqa: E402


def test_original_submission_facts_survive_missing_draft_binding_decoder(tmp_path):
    data_root = tmp_path / "server-data"
    native = ControlledNativeFixture(tmp_path / "native-effects.sqlite", mode="existing")
    first = controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=_test_fingerprint(),
    ).default_runtime(data_root, include_profile=False)
    location = {"kind": "draft", "connectionId": "query-recovery", "draftId": "draft-history"}
    capture = {
        "submissionId": "historical-request-1",
        "draft": {
            "draftId": "draft-history",
            "draftRevision": 7,
            "text": "captured historical input",
            "attachmentIds": [],
        },
        "configOperationIds": [],
        "schema": "agent-input/v1",
        "mode": "existing",
    }

    try:
        first.start()
        target = first.wire.dispatch("agent.session.resolve", {"location": location})["target"]
        native.bind_backend_target(target)
        capture["expectedConditions"] = first.wire.dispatch("agent.submission.capture.read", {
            "target": target, "mode": "existing",
        })
        accepted = first.wire.dispatch("agent.submitInput", {
            "target": target,
            "draftRevision": capture["draft"]["draftRevision"],
            "capture": capture,
        })
        assert accepted["outcome"] == "accepted"
        assert accepted["configApply"] == {"outcome": "applied", "operationIds": []}
        assert accepted["inputAcceptance"]["outcome"] == "accepted"
        assert accepted["runResult"]["outcome"] == "running"
        dispatch_counts = native.all_effect_counts()
        assert len(dispatch_counts) == 1
        assert set(dispatch_counts.values()) == {1}
    finally:
        first.stop()

    # Reopen the actual persisted Environment and Agent journal without a
    # native submit/query port or protected fingerprint key. Then make the
    # Agent draft decoder unavailable while retaining the original journal.
    restarted = create_composition().default_runtime(data_root, include_profile=False)
    try:
        restarted.start()
        agent_plugin = next(
            plugin for plugin in restarted.plugin_selection
            if plugin.descriptor().id == "ordessa.agent"
        )
        repository = agent_plugin._repository
        assert repository is not None
        repository.knows_draft = lambda _target: False

        history = restarted.wire.dispatch("agent.submission.query", {
            "target": target,
            "submissionId": capture["submissionId"],
        })
        assert history["request"] == accepted["request"]
        assert history["outcome"] == "unknown"  # native capability is absent after restart
        assert history["configApply"] == accepted["configApply"]
        assert history["inputAcceptance"] == accepted["inputAcceptance"]
        assert history["runResult"] == accepted["runResult"]
        assert history["resend"] is False

        # A target mismatch or absent request ID must not reveal the original
        # receipt or its config/input/run facts.
        for query in (
            {"target": "another-agent-target", "submissionId": capture["submissionId"]},
            {"target": target, "submissionId": "different-request-id"},
        ):
            hidden = restarted.wire.dispatch("agent.submission.query", query)
            assert hidden["outcome"] == "unknown"
            assert hidden["submissionId"] == query["submissionId"]
            assert hidden["resend"] is False
            assert "request" not in hidden
            assert "configApply" not in hidden
            assert "inputAcceptance" not in hidden
            assert "runResult" not in hidden
    finally:
        restarted.stop()

    assert native.all_effect_counts() == dispatch_counts
    assert len(native.dispatches) == 1

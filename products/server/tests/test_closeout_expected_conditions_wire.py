"""Production wire rejects submissions without a trusted source-condition capture."""
from __future__ import annotations

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


def test_public_wire_requires_conditions_before_journal_or_native_effect(tmp_path):
    native = ControlledNativeFixture(
        tmp_path / "native-effects.sqlite", mode="existing",
    )
    runtime = controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=_test_fingerprint_fixture(),
        submission_policy=controlled_submission_policy(),
    ).default_runtime(tmp_path / "server-data", include_profile=False)
    try:
        runtime.start()
        location = {"kind": "draft", "connectionId": "controlled-connection",
                    "draftId": "controlled-draft-1"}
        target = runtime.wire.dispatch("agent.session.resolve", {"location": location})["target"]
        native.bind_backend_target(target)
        operation = runtime.wire.dispatch("agent.config.submitOperation", {
            "target": target, "patch": {"model": "M1"}, "sourceRef": "wire-guard-test",
        })["operationId"]
        capture = {
            "submissionId": "missing-expected-conditions",
            "draft": {"draftId": "controlled-draft-1", "draftRevision": 1,
                      "text": "must not dispatch", "attachmentIds": []},
            "configOperationIds": [operation], "schema": "agent-input/v1", "mode": "existing",
        }

        with pytest.raises(WireError) as failure:
            runtime.wire.dispatch("agent.submitInput", {
                "target": target, "draftRevision": 1, "capture": capture,
            })

        assert failure.value.family == "CAPABILITY_UNSUPPORTED"
        assert native.dispatches == []
        assert native.all_effect_counts() == {}
        journal_path = tmp_path / "server-data" / "plugins" / "agent" / "submissions.sqlite"
        assert not journal_path.exists()
    finally:
        runtime.stop()

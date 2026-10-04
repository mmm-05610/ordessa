"""The native effect must receive the exact attachment bytes the journal froze."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "scripts" / "packaging"
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))

from controlled_native_fixture import (  # noqa: E402
    ControlledNativeFixture,
    controlled_product_composition,
    test_protected_fingerprint as _test_fingerprint_fixture,
)


def test_native_effect_uses_attachment_bytes_frozen_before_dispatch(tmp_path: Path):
    data_root = tmp_path / "server-data"
    effects_db = tmp_path / "native-effects.sqlite"
    attachment_id = "mutable-controlled-attachment"
    captured_bytes = b"bytes returned to the trusted capture"
    changed_bytes = b"later bytes from the same mutable attachment id"
    native = ControlledNativeFixture(
        effects_db,
        mode="existing",
        attachment_bytes={attachment_id: captured_bytes},
    )
    original_read = native.read_attachment
    read_count = 0

    def change_after_capture(target: str, selected_id: str) -> bytes:
        nonlocal read_count
        content = original_read(target, selected_id)
        read_count += 1
        if read_count == 1:
            # The service has received its copy. Change the native source
            # before submit is invoked to expose any second mutable read.
            native._attachments[selected_id] = changed_bytes
        return content

    native.read_attachment = change_after_capture
    composition = controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=_test_fingerprint_fixture(),
    )
    runtime = composition.default_runtime(data_root, include_profile=False)
    try:
        runtime.start()
        target = runtime.wire.dispatch("agent.session.resolve", {"location": {
            "kind": "draft",
            "connectionId": "attachment-snapshot-connection",
            "draftId": "attachment-snapshot-draft",
        }})["target"]
        native.bind_backend_target(target)
        conditions = runtime.wire.dispatch("agent.submission.capture.read", {
            "target": target, "mode": "existing",
        })
        response = runtime.wire.dispatch("agent.submitInput", {
            "target": target,
            "draftRevision": 1,
            "capture": {
                "submissionId": "attachment-snapshot-submission",
                "draft": {
                    "draftId": "attachment-snapshot-draft",
                    "draftRevision": 1,
                    "text": "submit with captured attachment",
                    "attachmentIds": [attachment_id],
                },
                "configOperationIds": [],
                "schema": "agent-input/v1",
                "mode": "existing",
                "expectedConditions": conditions,
            },
        })
        assert response["outcome"] == "accepted"
        assert response["stage"] == "completed"
    finally:
        runtime.stop()

    with sqlite3.connect(data_root / "plugins" / "agent" / "submissions.sqlite") as connection:
        encoded_input = connection.execute(
            "SELECT encoded_input FROM agent_submission_journal WHERE request_id=?",
            ("attachment-snapshot-submission",),
        ).fetchone()[0]
    frozen_attachments = json.loads(encoded_input)["attachments"]
    journaled_bytes = base64.b64decode(frozen_attachments[attachment_id]["base64"])
    assert journaled_bytes == captured_bytes

    with sqlite3.connect(effects_db) as connection:
        payload = json.loads(connection.execute(
            "SELECT payload FROM native_effects WHERE request_id=?",
            ("attachment-snapshot-submission",),
        ).fetchone()[0])
    dispatched_digest = payload["attachmentSha256"][attachment_id]
    assert dispatched_digest == hashlib.sha256(journaled_bytes).hexdigest()

"""Work Order 142: a declared-empty workspace snapshot must not fold into "no snapshot".

`_WorkerChannels` used a truthiness test to store the before-snapshot, so `{}` (a
legitimately declared *empty* workspace) collapsed to `None` (no snapshot at all). The
change-set branch keys on `is None`, so the WSL channel reported the change set as
unknown on every first turn even when the round had clearly added files. The two
statements are different facts and must stay separate.

These gates drive the real `workspace_change_set` (the same method the envelope reads):
* declared-empty `{}` + a file present in the after-listing -> "all added", not None;
* no snapshot `None` -> still None (unchanged honest "unknown");
* a non-empty snapshot with no change -> an empty change set, not None.
"""
from __future__ import annotations

from ordessa_server_compat.execution.sidecar import _WorkerChannels


class _FakeClient:
    def __init__(self, files):
        self._files = files

    def request(self, op, arguments, *, timeout=None):
        assert op == "workspace.list"
        return {"files": list(self._files)}


def _channels(*, snapshot, after_files):
    return _WorkerChannels(
        _FakeClient(after_files), "attempt-1", 1, "view-1",
        workspace_before_snapshot=snapshot,
    )


def test_declared_empty_snapshot_with_a_new_file_is_all_added(tmp_path):
    change = _channels(
        snapshot={},
        after_files=[{"path": "notes.md", "size": 12, "digest": "sha256:aaa"}],
    ).workspace_change_set()
    assert change is not None, "an empty snapshot is a real snapshot, not 'unknown'"
    assert [entry["path"] for entry in change["added"]] == ["notes.md"]
    assert change["modified"] == [] and change["removed"] == []


def test_no_snapshot_still_reports_no_change_set(tmp_path):
    change = _channels(
        snapshot=None,
        after_files=[{"path": "notes.md", "size": 12, "digest": "sha256:aaa"}],
    ).workspace_change_set()
    assert change is None  # honest "unknown" for an undeclared snapshot is preserved


def test_non_empty_snapshot_unchanged_file_yields_empty_change_set(tmp_path):
    snapshot = {"notes.md": {"size": 12, "digest": "sha256:aaa"}}
    change = _channels(
        snapshot=snapshot,
        after_files=[{"path": "notes.md", "size": 12, "digest": "sha256:aaa"}],
    ).workspace_change_set()
    assert change is not None
    assert change["added"] == [] and change["modified"] == [] and change["removed"] == []

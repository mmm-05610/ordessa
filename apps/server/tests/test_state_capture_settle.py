"""The home audit is a bounded record, never a refused turn.

Under the native-home model nothing is uploaded, so an over-large or churning
home cannot fail a turn the way a capture could: whatever did not fit is a
reported fact (`truncated`). The one rule that stays fail-closed is the
credential scan - an injected value that reached the home names the file, and
the caller deletes exactly that file.

These tests drive the channel against an in-memory home that the Worker would
serve, so the churn and the bounds are exact.
"""
from __future__ import annotations

import base64
import hashlib

import pytest

from ordessa_server_compat.execution.sidecar import SidecarError, _WorkerChannels


WINDOW = ".pi/sessions"
FILE = f"{WINDOW}/state.db"


class FakeHome:
    """A home the Worker would serve, with a mutable file set."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.list_calls = 0
        self.get_calls = 0
        self.deleted: list[str] = []
        self.before_get = None

    def request(self, op, arguments=None, **_keywords):
        if op == "home.list":
            self.list_calls += 1
            relative = arguments.get("relative") or ""
            prefix = f"{relative}/" if relative else ""
            files = [
                {"path": path, "size": len(content)}
                for path, content in sorted(self.files.items())
                if path.startswith(prefix)
            ]
            stripped = [{"path": f["path"][len(prefix):], "size": f["size"]} for f in files]
            return {"files": stripped,
                    "truncated": {"entries": 0, "bytes": 0, "oversize": 0}, "skipped": 0}
        if op == "home.get":
            if self.before_get is not None:
                self.before_get(self)
            self.get_calls += 1
            path = arguments["path"]
            content = self.files[path]
            offset = int(arguments.get("offset", 0))
            maximum = int(arguments.get("maxLength", 32768))
            end = min(offset + maximum, len(content))
            return {
                "path": path, "offset": offset, "nextOffset": end, "totalBytes": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "data": base64.b64encode(content[offset:end]).decode(),
                "eof": end == len(content),
            }
        if op == "home.delete":
            self.deleted.append(arguments["path"])
            self.files.pop(arguments["path"], None)
            return {"deleted": arguments["path"]}
        raise AssertionError(f"unexpected op {op}")


def channels(home: FakeHome, **keywords) -> _WorkerChannels:
    return _WorkerChannels(
        home, "attempt-1", 1, "view-1",
        home_locator="pi-test/.pi", audit_window=WINDOW,
        **keywords,
    )


def test_the_audit_records_what_the_home_contains():
    home = FakeHome({FILE: b"state-bytes"})
    audit = channels(home).audit_state()
    assert audit["audited"]["files"] == 1
    assert audit["files"] == [{"path": "state.db", "size": 11,
                               "digest": "sha256:" + hashlib.sha256(b"state-bytes").hexdigest()}]


def test_a_protected_path_is_not_part_of_the_audit():
    """Read-only configuration is not state: it never enters the manifest."""
    home = FakeHome({FILE: b"state", f"{WINDOW}/config.yaml": b"config"})
    audit = channels(home, protected_state_paths=("config.yaml",)).audit_state()
    assert [item["path"] for item in audit["files"]] == ["state.db"]
    assert audit["audited"]["files"] == 1


def test_oversize_files_are_truncation_facts_not_failures():
    """Nothing is uploaded any more, so a big file is bookkeeping, not a fault."""
    home = FakeHome({FILE: b"state", f"{WINDOW}/big.bin": b"x" * (9 * 1024 * 1024)})
    audit = channels(home).audit_state()
    assert [item["path"] for item in audit["files"]] == ["state.db"]
    assert audit["truncated"]["oversize"] == 1
    assert audit["truncated"]["entries"] >= 1
    assert audit["truncated"]["bytes"] >= 9 * 1024 * 1024


def test_worker_reported_truncation_flows_into_the_manifest():
    home = FakeHome()
    home.request = lambda op, arguments=None, **kw: (
        {"files": [], "truncated": {"entries": 7, "bytes": 4096, "oversize": 1}, "skipped": 2}
        if op == "home.list" else (_ for _ in ()).throw(AssertionError("no reads expected"))
    )
    audit = channels(home).audit_state()
    assert audit["truncated"] == {"entries": 7, "bytes": 4096, "oversize": 1}
    assert audit["skipped"] == 2
    assert home.get_calls == 0, "truncated entries are counted, never read"


def test_a_credential_in_the_home_names_the_file_and_fails_closed():
    home = FakeHome({
        FILE: b"clean",
        f"{WINDOW}/leaked.json": b'{"key": "fake-token-abc"}',
        f"{WINDOW}/other.db": b"more",
    })
    with pytest.raises(SidecarError) as refused:
        channels(home, forbidden_content=b"fake-token-abc").audit_state()
    assert refused.value.code == "SIDECAR_STATE_CONTAINS_SECRET"
    # The rule's clean-up: delete exactly the one file that leaked.
    channels(home, forbidden_content=b"fake-token-abc")  # a fresh channel for symmetry
    leak_relative = str(refused.value).rsplit(": ", 1)[-1]
    home.request("home.delete", {"locator": "pi-test/.pi",
                                 "path": f"{WINDOW}/{leak_relative}"})
    assert f"{WINDOW}/leaked.json" not in home.files
    assert home.files[FILE] == b"clean", "no other file is touched"


def test_an_empty_window_audits_to_nothing_without_reads():
    home = FakeHome()
    audit = channels(home).audit_state()
    assert audit["audited"]["files"] == 0
    assert home.get_calls == 0


def test_a_channel_without_a_home_audits_to_nothing():
    channel = _WorkerChannels(FakeHome(), "attempt-1", 1, "view-1")
    audit = channel.audit_state()
    assert audit["audited"]["files"] == 0
    assert audit["files"] == []

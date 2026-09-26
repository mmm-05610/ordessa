"""Order 62: read-only Git status - fields, nulls, bounds, and no writes.

The counterexamples the order names: a non-repository (typed reason, all
nulls), a timeout, an output-limit breach, a parse failure, and the
read-only property itself (the porcelain bytes are identical before and after
the query, and the index's mtime does not move).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from ordessa_server.workspaces.git_status import (
    GitStatus,
    local_git_status,
    parse_numstat,
    parse_porcelain_v2,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture()
def repo(tmp_path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@example.test")
    _git(path, "config", "user.name", "tester")
    (path / "readme.md").write_text("line one\nline two\n", encoding="utf-8")
    _git(path, "add", "readme.md")
    _git(path, "commit", "-m", "first")
    return path


def test_the_six_fields_come_from_machine_readable_output(repo):
    (repo / "readme.md").write_text("line one\nline two changed\nline three\n", encoding="utf-8")
    (repo / "new.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "new.txt")

    status = local_git_status(str(repo))
    assert status.reason is None, status.reasons
    assert status.branch == "main"
    assert status.changed_files == 2
    assert status.additions == 3 and status.deletions == 1
    # No upstream configured: ahead/behind are *unknown*, never zero.
    assert status.ahead is None and status.behind is None
    wire = status.as_wire()
    assert set(wire) == {"branch", "changedFiles", "additions", "deletions",
                         "ahead", "behind", "reason"}


def test_a_non_repository_is_a_typed_reason_with_all_nulls(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "notes.txt").write_text("x", encoding="utf-8")
    status = local_git_status(str(plain))
    assert status.reason == "GIT_NOT_A_REPOSITORY"
    assert (status.branch, status.changed_files, status.additions,
            status.deletions, status.ahead, status.behind) == (None,) * 6

    missing = local_git_status(str(tmp_path / "nope"))
    assert missing.reason == "GIT_WORKSPACE_MISSING"
    assert (missing.branch, missing.changed_files, missing.additions,
            missing.deletions, missing.ahead, missing.behind) == (None,) * 6


def test_bounds_and_parse_failures_are_typed_never_truncated(tmp_path, monkeypatch):
    repo = tmp_path / "project"
    repo.mkdir()
    # A git *shim*: the module runs a fixed argv, so the shim stands in for a
    # slow or flooding git without touching the real one.
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ['PATH']}")
    timed_out = local_git_status(str(repo), timeout=0.3)
    assert timed_out.reason == "GIT_TIMEOUT"

    shim.write_text("#!/bin/sh\nyes '1 M. N... 100644 100644 100644 a b c.txt'\n", encoding="utf-8")
    limitted = local_git_status(str(repo), timeout=5.0, max_bytes=4096)
    assert limitted.reason == "GIT_OUTPUT_LIMIT"

    with pytest.raises(ValueError):
        parse_porcelain_v2(b"# branch.ab oops\n")
    with pytest.raises(ValueError):
        parse_numstat(b"not-a-numstat-line\n")


def test_a_binary_diff_keeps_the_line_counts_null(repo):
    (repo / "blob.bin").write_bytes(bytes(range(256)))
    _git(repo, "add", "blob.bin")
    status = local_git_status(str(repo))
    assert status.changed_files == 1
    assert status.additions is None and status.deletions is None
    assert status.reason == "GIT_BINARY_DIFF"


def test_the_query_writes_nothing(repo):
    (repo / "readme.md").write_text("changed\n", encoding="utf-8")
    porcelain = ["git", "-C", str(repo), "--no-optional-locks",
                 "status", "--porcelain=v2", "--branch"]
    before = subprocess.run(porcelain, stdout=subprocess.PIPE, check=True).stdout
    index = repo / ".git" / "index"
    index_mtime = index.stat().st_mtime_ns

    status = local_git_status(str(repo))
    assert status.reason is None

    after = subprocess.run(porcelain, stdout=subprocess.PIPE, check=True).stdout
    assert after == before, "the status query changed the repository's state"
    assert index.stat().st_mtime_ns == index_mtime, "the index was refreshed (a write)"


def test_the_workspace_git_status_wire_returns_the_six_fields(tmp_path, repo):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    # Local record aliases, the same discipline as test_profile_permissions:
    # a stopped runtime's facades read None (the ports belong to the active
    # round), but the round's records stay usable across client sessions.
    workspaces_repo = runtime.repository.workspaces
    workspace = workspaces_repo.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path=str(repo), connection_id="connection")[1]
    with runtime.database.transaction() as conn:
        conn.execute(
            "UPDATE server_workspaces SET env_kind='local', normalized_path=? WHERE id=?",
            (str(repo), workspace["workspace_id"]),
        )
    (repo / "readme.md").write_text("changed line\nand another\n", encoding="utf-8")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        result = client.post("/wire/v1/workspaces.gitStatus", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "g", "method": "workspaces.gitStatus",
            "params": {"requestId": "git-status-1", "workspaceId": workspace["workspace_id"]},
        }).json()["result"]["git"]
    assert result["branch"] == "main"
    assert result["changedFiles"] == 1
    assert result["additions"] == 2 and result["deletions"] == 2
    assert result["reason"] is None
    # No host path anywhere in the answer.
    assert str(repo) not in str(result)

    # A workspace that is not a repository answers the typed reason, all nulls.
    plain = tmp_path / "plain"
    plain.mkdir()
    second = workspaces_repo.create(
        key="w2", request_digest="w2", distribution="Ubuntu", remote_user="tester",
        remote_path=str(plain), connection_id="connection-2")[1]
    with runtime.database.transaction() as conn:
        conn.execute(
            "UPDATE server_workspaces SET env_kind='local', normalized_path=? WHERE id=?",
            (str(plain), second["workspace_id"]),
        )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        refused = client.post("/wire/v1/workspaces.gitStatus", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "g2", "method": "workspaces.gitStatus",
            "params": {"requestId": "git-status-2", "workspaceId": second["workspace_id"]},
        }).json()["result"]["git"]
    assert refused["reason"] == "GIT_NOT_A_REPOSITORY"
    assert refused["branch"] is None and refused["changedFiles"] is None

"""Order 63: the memory read face - declared, bounded, scanned, read-only.

Counterexamples: an undeclared family (no partition), a missing declared file
(absent, not empty), an oversized file, a symlink, a credential hit (refused,
no content), and a missing home (typed reason).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ordessa_server.profiles.memory import (
    MAX_MEMORY_FILE_BYTES,
    read_memory,
)


def test_declared_files_are_read_with_digests_and_missing_ones_are_absent(tmp_path):
    home = tmp_path / "home"
    (home / ".codex" / "memories").mkdir(parents=True)
    (home / ".codex" / "memories" / "MEMORY.md").write_text(
        "remember the nonce\n", encoding="utf-8")
    result = read_memory(home, declared=(
        ".codex/memories/MEMORY.md", ".codex/memories/memory_summary.md"))
    assert result["available"] is True and result["reason"] is None
    assert [item["path"] for item in result["files"]] == [".codex/memories/MEMORY.md"]
    assert result["files"][0]["content"] == "remember the nonce\n"
    assert result["files"][0]["digest"].startswith("sha256:")
    assert result["files"][0]["size"] == 19


def test_bounds_symlinks_and_secrets_refuse_typed_without_leaking(tmp_path):
    home = tmp_path / "home"
    (home / ".codex" / "memories").mkdir(parents=True)
    (home / ".codex" / "memories" / "MEMORY.md").write_text("ok\n", encoding="utf-8")
    (home / ".codex" / "memories" / "memory_summary.md").write_text(
        "x" * (MAX_MEMORY_FILE_BYTES + 1), encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-ish\n", encoding="utf-8")
    (home / ".codex" / "memories" / "linked.md").symlink_to(outside)
    (home / ".hermes").mkdir()
    (home / ".hermes" / "MEMORY.md").write_text("api key: sk-abc123\n", encoding="utf-8")

    result = read_memory(
        home,
        declared=(".codex/memories/MEMORY.md", ".codex/memories/memory_summary.md",
                  ".codex/memories/linked.md", ".hermes/MEMORY.md", "../escape.md"),
        forbidden=b"sk-abc123",
    )
    by_path = {item["path"]: item for item in result["files"]}
    assert result["reason"] == "MEMORY_FILE_OUTSIDE_BOUNDS"
    assert "content" in by_path[".codex/memories/MEMORY.md"]
    # The oversized file is refused (no entry at all), the symlink never
    # followed, and the credential-bearing file refused without its content.
    assert ".codex/memories/memory_summary.md" not in by_path
    assert ".codex/memories/linked.md" not in by_path
    assert by_path[".hermes/MEMORY.md"]["refused"] is True
    assert "content" not in by_path[".hermes/MEMORY.md"]
    assert "../escape.md" not in by_path


def test_a_missing_home_is_the_one_typed_reason_for_the_whole_answer(tmp_path):
    missing = read_memory(tmp_path / "nope", declared=(".claude/CLAUDE.md",))
    assert missing == {"available": False, "reason": "MEMORY_HOME_MISSING", "files": []}
    assert read_memory(None, declared=(".claude/CLAUDE.md",))["reason"] == "MEMORY_HOME_MISSING"


def test_the_memory_wire_face_reads_the_profile_home_or_hides_the_partition(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    profile = runtime.repository.profiles.create(
        key="p", request_digest="p", name="role", harness_type="codex",
        config_digest=runtime.objects.publish(
            b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest,
        credential_id=None)[1]
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token

        def call(method, params):
            return client.post(f"/wire/v1/{method}", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": method, "method": method, "params": params,
            }).json()

        # No home yet: the typed reason, not an empty partition pretending.
        before = call("profiles.memory", {
            "requestId": "memory-1", "profileId": profile["profile_id"]})["result"]["memory"]
        assert before["available"] is False and before["reason"] == "MEMORY_HOME_MISSING"

        # Lay out the home the way a turn would have created it, then read.
        from ordessa_server_compat.composition import (
            _profile_home_locator, _registry_native_homes,
        )

        locator = _profile_home_locator(
            profile["name"], _registry_native_homes()["codex"],
            profile_id=profile["profile_id"])
        home = tmp_path / "server" / "profiles" / locator.split("/", 1)[0]
        (home / ".codex" / "memories").mkdir(parents=True)
        (home / ".codex" / "memories" / "MEMORY.md").write_text("nonce 42\n", encoding="utf-8")
        after = call("profiles.memory", {
            "requestId": "memory-2", "profileId": profile["profile_id"]})["result"]["memory"]
        assert after["available"] is True
        assert after["files"][0]["path"] == ".codex/memories/MEMORY.md"
        assert after["files"][0]["content"] == "nonce 42\n"
        assert str(home) not in str(after), "no host path in the answer"

        # A family that declares no memory paths hides the partition.
        pi = runtime.repository.profiles.create(
            key="p2", request_digest="p2", name="pi-role", harness_type="pi",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"pi","configuration":{}}').digest,
            credential_id=None)[1]
        hidden = call("profiles.memory", {
            "requestId": "memory-3", "profileId": pi["profile_id"]})["result"]["memory"]
        assert hidden["available"] is False and hidden["files"] == []
        assert "declares no memory paths" in hidden["note"]

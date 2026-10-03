"""§1 row 1 roundtrip over the real dispatch: save -> list -> get ->
approve -> archive, with the CAS / idempotency / scope-isolation refusals
projected through the composition's family table (SC `_asset_refusal`
style, MCP codes)."""
from __future__ import annotations

from service_helpers import stdio_definition


def _revision_view(saved, **overrides):
    params = {"serverScope": "s1", "principal": "alice", "definitionId": "demo"}
    params.update(overrides)
    return saved.call("mcp.get", **params)


def test_save_list_get_approve_archive_roundtrip(saved):
    listed = saved.call("mcp.list", serverScope="s1", principal="alice")
    assert listed["definitions"] == [{
        "definitionId": "demo", "serverScope": "s1", "nativeName": "demo",
        "transport": "stdio", "archived": False, "latestRevision": 1}]

    got = _revision_view(saved)
    rev = got["latestRevision"]
    assert rev["revision"] == 1 and rev["digest"].startswith("sha256:")
    assert rev["shape"] == "v2"
    assert rev["approval"] == {"actor": "alice", "approvedAt": rev["approval"]["approvedAt"]}

    second = saved.call("mcp.saveRevision", serverScope="s1", principal="alice",
                        definitionId="demo",
                        definition=stdio_definition(MODE="two"),
                        expectedVersion=1, operationKey="op-save-2")
    assert second["revision"]["revision"] == 2
    assert second["definition"]["latestRevision"] == 2
    assert second["replayed"] is False

    archived = saved.call("mcp.archive", serverScope="s1", principal="alice",
                          definitionId="demo")
    assert archived["definition"]["archived"] is True
    # archive blocks NEW assignments but the revisions stay readable (§1)
    assert _revision_view(saved, revision=1)["latestRevision"]["revision"] == 1


def test_cas_conflict_is_conflict_version(saved):
    saved.expect_refusal(
        "mcp.saveRevision", family="CONFLICT_VERSION", internal_code="MCP_CAS_CONFLICT",
        serverScope="s1", principal="alice", definitionId="demo",
        definition=stdio_definition(), expectedVersion=0, operationKey="op-late")


def test_operation_key_replay_and_conflict(saved):
    again = saved.call("mcp.saveRevision", serverScope="s1", principal="alice",
                       definitionId="demo", definition=stdio_definition(),
                       expectedVersion=0, operationKey="op-save-1")
    assert again["replayed"] is True
    assert again["revision"]["digest"] == (
        _revision_view(saved)["latestRevision"]["digest"])
    saved.expect_refusal(
        "mcp.saveRevision", family="CONFLICT_REQUEST",
        internal_code="MCP_OPERATION_CONFLICT",
        serverScope="s1", principal="alice", definitionId="demo",
        definition=stdio_definition(MODE="different"),
        expectedVersion=1, operationKey="op-save-1")


def test_foreign_scope_never_learns_existence(saved):
    saved.expect_refusal("mcp.get", family="NOT_FOUND", internal_code="MCP_ASSET_MISSING",
                         serverScope="other", principal="mallory", definitionId="demo")
    listed = saved.call("mcp.list", serverScope="other", principal="mallory")
    assert listed["definitions"] == []


def test_definition_field_validation_refuses_before_storage(saved):
    # v2 rule: a bare string env value is a typed refusal (backend/definition.py)
    saved.expect_refusal(
        "mcp.saveRevision", family="INVALID_REQUEST",
        internal_code="MCP_DEFINITION_INVALID",
        serverScope="s1", principal="alice", definitionId="bad-one",
        definition={"name": "bad-one",
                    "transport": {"stdio": {"command": "/bin/true",
                                            "env": {"TOKEN": "plaintext"}}}},
        expectedVersion=0, operationKey="op-bad")


def test_approve_unbound_principal_actor_is_caller(saved):
    answer = saved.call("mcp.approveRevision", serverScope="s1", principal="bob",
                        definitionId="demo", revision=1)
    # approval is idempotent; the first actor (alice) stands — the record
    # attributes the FIRST approval, and this proof pins whose name is on it.
    assert answer["approval"]["actor"] == "alice"

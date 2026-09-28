"""Order 65 A/B: delegation edges, the roster, and the two tools' contract.

Counterexamples named by the order: an unauthorized name (refused, with the
authorized names inlined and nothing else leaked), a widened optional argument,
a cycle, a depth overrun, a malformed description, and the rule that a Profile
with no grants gets neither tool.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.profiles.subagents import (
    DEFAULT_TURNS_LIMIT,
    MAX_TIMEOUT_SECONDS,
    DelegationError,
    check_cycle,
    grant_edges,
    has_delegation,
    inline_available,
    resolve_roster,
    tool_definitions,
    validate_run_arguments,
)
from pacthold_runtime_compat.storage import Database


def _profiles(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    records = ProfileRecords(database, IdempotentRecords(database))
    created = {}
    for name in ("alpha", "beta", "gamma"):
        created[name] = records.create(
            key=name, request_digest=name, name=name, harness_type="codex",
            config_digest="sha256:" + "0" * 64, credential_id=None)[1]
    return database, records, created


def test_only_granted_profiles_appear_and_cycles_never_become_representable(tmp_path):
    database, records, created = _profiles(tmp_path)
    alpha, beta, gamma = (created[name]["profile_id"] for name in ("alpha", "beta", "gamma"))
    records.grant_subagent(parent_id=alpha, child_id=beta)

    edges = grant_edges(records.subagent_grants())
    profiles = [
        {"id": created["alpha"]["profile_id"], "name": "alpha", "harness_type": "codex"},
        {"id": beta, "name": "beta", "harness_type": "claude-code"},
        {"id": gamma, "name": "gamma", "harness_type": "codex"},
    ]
    roster = resolve_roster(parent_id=alpha, edges=edges, profiles=profiles)
    assert [entry["name"] for entry in roster] == ["beta"]
    assert roster[0]["harness"] == "claude-code" and roster[0]["available"] is True
    # An unavailable child is still listed (the parent is authorized to know),
    # marked with its reason.
    marked = resolve_roster(parent_id=alpha, edges=edges, profiles=profiles,
                            availability={beta: "PROFILE_ARCHIVED"})
    assert marked[0]["available"] is False and marked[0]["reason"] == "PROFILE_ARCHIVED"

    # A→B→A is refused when the grant is asked for, not at call time.
    with pytest.raises(ServerError) as cycle:
        records.grant_subagent(parent_id=beta, child_id=alpha)
    assert cycle.value.code == "SUBAGENT_CYCLE"
    # Self-grants are refused too.
    with pytest.raises(ServerError):
        records.grant_subagent(parent_id=alpha, child_id=alpha)

    # zero grants, zero tools; and the child's own edges decide its tools.
    assert has_delegation(edges, gamma) is False
    assert tool_definitions(roster=[]) == []
    child_edges = grant_edges(records.subagent_grants())
    child_roster = resolve_roster(parent_id=beta, edges=child_edges, profiles=profiles)
    assert child_roster == []
    assert tool_definitions(roster=child_roster) == []


def test_a_cycle_is_refused_by_name_and_depth_is_not_a_ceiling():
    """Ruling R-0016 revoked 65's depth limit; the cycle rule is what remains.

    The chain this checks is the shape the server now reads off the ledger, so a
    long one must pass and a repeated role must not: a role inside its own call
    is waiting on itself.
    """
    check_cycle(["alpha", "beta"])
    check_cycle(["alpha", "beta", "gamma", "delta", "epsilon"])
    with pytest.raises(DelegationError) as cycle:
        check_cycle(["alpha", "beta", "alpha"])
    assert cycle.value.code == "SUBAGENT_CYCLE"


def test_the_tools_carry_the_roster_and_refuse_unauthorized_or_widened_calls():
    roster = [
        {"profileId": "p1", "name": "beta", "harness": "claude-code",
         "description": "reviewer", "available": True, "reason": None},
        {"profileId": "p2", "name": "gamma", "harness": "codex",
         "description": "builder", "available": True, "reason": None},
    ]
    tools = tool_definitions(roster=roster)
    assert [tool["name"] for tool in tools] == ["list_subagents", "run_subagent"]
    run = tools[1]
    assert "beta" in run["description"] and "gamma" in run["description"]
    assert run["inputSchema"]["required"] == ["subagent", "description", "prompt"]
    # The parameter exists for a caller that wants list-only tools. It is not a
    # child restriction: ruling R-0016 revoked 65's "children get no run tool"
    # default, and production always builds both from the child's own grants.
    child_tools = tool_definitions(roster=roster, include_run=False)
    assert [tool["name"] for tool in child_tools] == ["list_subagents"]

    validated = validate_run_arguments(
        {"subagent": "beta", "description": "review the code", "prompt": "Do X and report Y."},
        roster=roster)
    assert validated["timeout"] == 600 and validated["max_turns"] == DEFAULT_TURNS_LIMIT

    # An unauthorized name: typed, with only the authorized names inlined.
    with pytest.raises(DelegationError) as unauthorized:
        validate_run_arguments(
            {"subagent": "delta", "description": "do the thing", "prompt": "x"},
            roster=roster)
    payload = inline_available(unauthorized.value)
    assert payload["error"] == "SUBAGENT_NOT_AUTHORIZED"
    assert payload["available"] == ["beta", "gamma"]
    assert "delta" not in str(payload)

    # Optional arguments may only narrow.
    with pytest.raises(DelegationError) as widened:
        validate_run_arguments(
            {"subagent": "beta", "description": "review the code", "prompt": "x",
             "permission": "full-access"}, roster=roster)
    assert widened.value.code == "SUBAGENT_PERMISSION_WIDENED"
    with pytest.raises(DelegationError) as model:
        validate_run_arguments(
            {"subagent": "beta", "description": "review the code", "prompt": "x",
             "model": "gpt-2"}, roster=roster, child_limits={"models": ["gpt-5"]})
    assert model.value.code == "SUBAGENT_MODEL_WIDENED"

    # Bounds: the ten-minute timeout and the per-turn fan-out.
    with pytest.raises(DelegationError) as timeout:
        validate_run_arguments(
            {"subagent": "beta", "description": "review the code", "prompt": "x",
             "timeout": MAX_TIMEOUT_SECONDS + 1}, roster=roster)
    assert timeout.value.code == "SUBAGENT_TIMEOUT_INVALID"
    with pytest.raises(DelegationError) as turns:
        validate_run_arguments(
            {"subagent": "beta", "description": "review the code", "prompt": "x",
             "max_turns": DEFAULT_TURNS_LIMIT + 1}, roster=roster)
    assert turns.value.code == "SUBAGENT_TURNS_INVALID"

    # The description's shape is the native one: a 3-5 word label.
    with pytest.raises(DelegationError) as label:
        validate_run_arguments(
            {"subagent": "beta", "description": "too", "prompt": "x"}, roster=roster)
    assert label.value.code == "SUBAGENT_ARGUMENT_INVALID"

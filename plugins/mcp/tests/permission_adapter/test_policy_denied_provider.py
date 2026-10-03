"""T06-wiring proof: the resolve-layer `policy_denied` hook served by Q5.

The provider derives "definition ids no layer may re-enable" from the real
Q5 ceiling vocabulary (hard denies + exposure caps over `TOOL_EXPOSURE`),
and the resolution test wires it into the real ``backend/resolve.py`` to
show a higher administrator prohibition beating a profile enable (FR-01 /
contracts §4: the merge layers may not re-enable what the ceiling denied).
"""
from __future__ import annotations

import ordessa_permissions_api as q5
from pa_shared import NOW, default_binding, intent_allowing, snapshot_with, table_provider

from backend.assignment import McpAssignmentStore
from backend.definition_store import McpDefinitionStore
from backend.permission_adapter import Q5PermissionAuthority, q5_policy_denied_definition_ids
from backend.permissions import (
    PERMISSION_ENFORCEMENT_UNPROVEN,
    STATUS_REFUSED,
    check_tool_callable,
)
from backend.resolve import resolve_preview

HARD_DENY_CEILING = {
    "policyId": "ceil-hard", "scope": "admin", "revision": 1,
    "source": "signed-admin", "signed": True, "maximumExposure": "full",
    "effectiveFrom": "2020-01-01T00:00:00+00:00",
    "deny": [{"key": "read", "pattern": "/etc/*"}],
}
READ_CAP_CEILING = {
    "policyId": "ceil-cap", "scope": "admin", "revision": 1,
    "source": "signed-admin", "signed": True, "maximumExposure": "read",
    "effectiveFrom": "2020-01-01T00:00:00+00:00",
}
HEX64 = "b" * 64


def _bindings():
    return (
        {"definition_id": "etc-reader", "tool_key": "read", "target": "/etc/hosts"},
        {"definition_id": "repo-reader", "tool_key": "read", "target": "/repo/a.py"},
        {"definition_id": "runner", "tool_key": "bash", "target": None},
        {"definition_id": "weird", "tool_key": "not_a_q5_key", "target": None},
    )


def test_provider_denies_ceiling_blocked_and_exposure_capped(world):
    world.store_ceiling_record(HARD_DENY_CEILING)
    world.store_ceiling_record(READ_CAP_CEILING)
    denied = q5_policy_denied_definition_ids(
        ceilings=world.policies.ceilings_current(), bindings=_bindings())
    # etc-reader: hard deny; runner: bash exceeds the read cap; weird: outside
    # the closed vocabulary - none may be re-enabled. repo-reader is NOT here:
    # read under /repo is allowed by both ceilings (the deny pattern is bounded).
    assert set(denied) == {"etc-reader", "runner", "weird"}
    # the reading is the real Q5 effective ceiling, not a re-implementation
    effective = q5.intersect_ceilings(list(world.policies.ceilings_current()))
    assert effective.blocks("read", "/etc/hosts")
    assert not effective.blocks("read", "/repo/a.py")
    assert q5.TOOL_EXPOSURE["bash"].rank > effective.maximum_exposure.rank


def test_missing_or_untrusted_ceilings_denies_everything():
    bindings = _bindings()
    good = (q5.PolicyCeiling.from_record(HARD_DENY_CEILING),)
    assert q5_policy_denied_definition_ids(ceilings=(), bindings=bindings) == \
        tuple(b["definition_id"] for b in bindings)
    untrusted = q5.PolicyCeiling.unverified("no-provider")
    assert q5_policy_denied_definition_ids(ceilings=(untrusted,), bindings=bindings) == \
        tuple(b["definition_id"] for b in bindings)
    # honest control: the same provider with a trusted ceiling does NOT deny
    # everything - only the bound-and-blocked ids (asymmetry seal; the read
    # cap is gone with this single ceiling, so `runner` is re-enableable).
    assert q5_policy_denied_definition_ids(ceilings=good, bindings=bindings) == \
        ("etc-reader", "weird")


def test_admin_authorization_can_never_purge_a_denied_id(world):
    """The provider has no authorization input at all; a valid ticket attached
    to the re-enabling intent changes nothing in the ceiling-denied set."""
    world.store_ceiling_record(HARD_DENY_CEILING)
    digest = q5.intersect_ceilings(list(world.policies.ceilings_current())).revision_digest
    ticket = q5.AdminAuthorization.of(
        issuer="root", subject="read", target="/etc/hosts", ceiling_revision=digest,
        verified=True, expires_at=(NOW.replace(year=2027)).isoformat())
    intent = intent_allowing(rules=(q5.TypedRule.of(
        key="read", action="allow", pattern="/etc/hosts", priority=5,
        authorization=ticket),))
    assert intent.rules[0].authorization is ticket
    denied = q5_policy_denied_definition_ids(
        ceilings=world.policies.ceilings_current(), bindings=_bindings())
    assert "etc-reader" in denied  # the ticket unlocks intent-internal order only


# -- the resolve layer: a ceiling deny beats a profile enable --------------------


def _publish_and_enable(tmp_path, *, def_id="etc-reader", tool="search"):
    definitions = McpDefinitionStore(tmp_path / "defs")
    assignments = McpAssignmentStore(tmp_path / "assignments", definitions)
    definitions.save_revision(
        server_scope="scope-a", definition_id=def_id,
        definition={"name": def_id, "transport": {"stdio": {
            "command": f"/bin/{def_id}", "args": [],
            "env": {"KEY": {"secretRef": "credential_1"}}}}},
        expected_version=0, operation_key=f"save-{def_id}")
    definitions.approve_revision(server_scope="scope-a", definition_id=def_id,
                                 revision=1, actor="admin-1")
    assignments.assign(
        server_scope="scope-a", principal="alice", scope_kind="profile",
        scope_id="profile-rev-9", harness=None, definition_id=def_id,
        decision="enable", approved_revision=1,
        tool_selection={"mode": "allowNames", "names": [tool],
                        "catalogDigest": "sha256:cat-1"},
        observed_catalog={"catalogDigest": "sha256:cat-1", "toolNames": [tool]},
        expected_row_version=0, operation_key=f"on-{def_id}")
    return definitions, assignments


def test_q5_ceiling_deny_blocks_the_profile_enable_in_resolution(world, tmp_path):
    world.store_ceiling_record(HARD_DENY_CEILING)
    definitions, assignments = _publish_and_enable(tmp_path)
    denied = q5_policy_denied_definition_ids(
        ceilings=world.policies.ceilings_current(),
        bindings=({"definition_id": "etc-reader", "tool_key": "read",
                   "target": "/etc/hosts"},))
    assert denied == ("etc-reader",)
    base = dict(server_scope="scope-a", principal="alice", assignments=assignments,
                definitions=definitions, profile_revision="profile-rev-9")
    enabled = resolve_preview(**base)
    assert [e["definition_id"] for e in enabled.definition_revisions] == ["etc-reader"]
    blocked = resolve_preview(**base, policy_denied=denied)
    assert blocked.definition_revisions == ()
    assert blocked.allowed_tool_names == ()
    # and the double gate then refuses the tool without consulting Q5 at all
    spy = world.make_authorizer()
    adapter = Q5PermissionAuthority(
        authorizer=spy, ceiling_provider=world.policies.ceilings_current,
        binding_provider=table_provider({"session-1": default_binding()}))
    decision = check_tool_callable(blocked, adapter, "search", "sha256:" + HEX64,
                                   NOW.timestamp(), principal="alice",
                                   session_ref="session-1", lease_id="l",
                                   definition_id="etc-reader")
    assert decision.status == STATUS_REFUSED
    assert decision.gate == "catalog-subset"
    assert spy.consultations == []


def test_untrusted_snapshot_lane_still_refuses_before_q5(world):
    """Sanity that the adapter is plugged into the SAME double gate: an
    unproven native lane refuses before the (real) authority is consulted."""
    adapter = world.make_adapter(authorizer=world.make_authorizer(),
                                 tool_key_map={"search": "read"})
    snapshot = snapshot_with(("search",), lane="native", enforcement="unproven")
    decision = check_tool_callable(snapshot, adapter, "search", "sha256:" + HEX64,
                                   NOW.timestamp(), principal="user-1",
                                   session_ref="session-1", lease_id="l",
                                   definition_id="def1")
    assert decision.status == STATUS_REFUSED
    assert decision.code == PERMISSION_ENFORCEMENT_UNPROVEN

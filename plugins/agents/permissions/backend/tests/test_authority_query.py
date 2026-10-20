"""PE1-2..PE1-5: the authority query surface over the existing stores.

The controlled matrix the dispatch names - authorization PRESENT / ABSENT /
EXPIRED / REVOKED - plus the honesty rules around it: absence is an empty
tuple or `None`, never a default allow; another session's facts never
surface; a revoked grant refuses even its first spend; rule-derived records
never answer a session query. Everything runs against the real product
storage provider in tmp dirs, zero real models (E2 discipline).
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import (
    AuthorityScope,
    AuthoritySourceKind,
    AuthorityStateKind,
    NativeReceipt,
    PolicyRefusal,
)
from support import (admin_ceiling, approval_record, make_operation, seeded_database,
                     seed_session, utc)

from ordessa_permissions_backend import (ApprovalFacts, PermissionsAuthority,
                                         PolicyRepository)


@pytest.fixture
def world(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    return database, facts, policies, PermissionsAuthority(facts, policies)


def _settled_allow(facts, *, session_id="session-1", execution_id="turn-1",
                   target="/repo/a.py", native_request_id="native-g",
                   expires_minutes=5, decision="allow", scope={"kind": "once"}):
    operation = make_operation(ceilings=[admin_ceiling()], target=target,
                               session_id=session_id, execution_id=execution_id,
                               native_request_id=native_request_id)
    record = approval_record(operation, requested_at=utc(),
                             expires_at=utc(minutes=expires_minutes))
    facts.request(session_id=session_id, execution_id=execution_id, request=record)
    approval_id = record["approvalId"]
    facts.decide(approval_id=approval_id, decision=decision, scope=scope,
                 expected_version=1, request_id=f"decide-{native_request_id}",
                 now=utc(minutes=1))
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=1)))
    return approval_id, operation


# -- the four states -----------------------------------------------------------


def test_present_authorization_answers_with_the_frozen_dto(world):
    _database, facts, _policies, authority = world
    approval_id, operation = _settled_allow(facts)
    found = authority.effective_for_operation(
        tool="bash", operation_digest=operation.operation_digest, now=utc(minutes=2))
    assert len(found) == 1
    record = found[0]
    assert record.source is AuthoritySourceKind.APPROVAL_GRANT
    assert record.scope is AuthorityScope.SESSION
    assert record.state is AuthorityStateKind.ACTIVE
    assert record.tool == "bash" and record.target == "/repo/a.py"
    assert record.fact_ref == approval_id
    assert record.effective is True
    # the store never recorded a person: declared absence, not a guess
    assert record.requested_by is None and record.approved_by is None
    assert set(record.as_record()) == {
        "authorityId", "source", "scope", "tool", "target", "operationDigest",
        "requestedBy", "approvedBy", "grantedAt", "expiresAt", "state", "revision",
        "factRef"}


def test_absent_authorization_is_an_honest_empty_answer_never_a_default_allow(world):
    _database, _facts, _policies, authority = world
    assert authority.effective_for_operation(tool="bash", now=utc()) == ()
    assert authority.effective_for_session("session-1", now=utc()) == ()
    assert authority.effective_for_user("user-1", now=utc()) == ()
    assert authority.lookup("approval_nobody", now=utc()) is None
    # a query for an undeclared tool key is an empty world, not a refusal
    assert authority.effective_for_operation(tool="read", target="/none",
                                             now=utc()) == ()


def test_expired_authorization_leaves_the_listings_and_lookup_says_expired(world):
    _database, facts, _policies, authority = world
    approval_id, _operation = _settled_allow(facts, expires_minutes=5)
    within = authority.effective_for_operation(tool="bash", now=utc(minutes=2))
    assert len(within) == 1 and within[0].state is AuthorityStateKind.ACTIVE
    after = authority.effective_for_operation(tool="bash", now=utc(minutes=10))
    assert after == ()
    looked = authority.lookup(approval_id, now=utc(minutes=10))
    assert looked is not None and looked.state is AuthorityStateKind.EXPIRED
    assert looked.effective is False


def test_revoked_authorization_is_listed_nowhere_and_cannot_be_spent(world):
    _database, facts, _policies, authority = world
    approval_id, operation = _settled_allow(facts)
    assert len(authority.effective_for_operation(tool="bash", now=utc(minutes=2))) == 1
    revoked = authority.revoke(approval_id, reason="operator requested",
                               now=utc(minutes=3))
    assert revoked is not None and revoked.state is AuthorityStateKind.REVOKED
    assert authority.effective_for_operation(tool="bash", now=utc(minutes=4)) == ()
    assert authority.effective_for_session("session-1", now=utc(minutes=4)) == ()
    looked = authority.lookup(approval_id, now=utc(minutes=4))
    assert looked is not None and looked.state is AuthorityStateKind.REVOKED
    # the settled decision itself was never rewritten...
    row = facts.get(approval_id)
    assert row["decision"] == "allow" and row["state"] == "settled"
    # ...but the spent-grant gate refuses the revoked grant
    spent = facts.consume_grant(approval_id=approval_id,
                                operation_digest=operation.operation_digest,
                                native_request_id=operation.native_request_id,
                                moment=utc(minutes=5))
    assert spent is False


def test_revoke_refuses_what_is_not_a_settled_allow_grant(world):
    database, facts, _policies, authority = world
    assert authority.revoke("approval_missing", reason="x", now=utc()) is None
    # an OPEN approval is not an authorization fact yet
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-o")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id,
                  execution_id=operation.execution_id, request=record)
    assert authority.revoke(record["approvalId"], reason="x", now=utc()) is None
    # a settled DENY is not one either
    deny_id, _operation = _settled_allow(facts, decision="deny",
                                         native_request_id="native-d")
    assert authority.revoke(deny_id, reason="x", now=utc()) is None
    # a revocation is recorded once; a re-revoke neither rewrites nor fails
    grant_id, _operation = _settled_allow(facts, native_request_id="native-r")
    first = authority.revoke(grant_id, reason="first", now=utc(minutes=2))
    again = authority.revoke(grant_id, reason="second", now=utc(minutes=3))
    assert first is not None and again is not None
    # the FIRST revocation fact stands: neither the reason nor the timestamp
    # is overwritten by the second call (history is never rewritten)
    with database.read() as conn:
        stored = dict(conn.execute("SELECT * FROM server_approvals WHERE id=?",
                                   (grant_id,)).fetchone())
    assert stored["revoked_reason"] == "first"
    assert stored["revoked_at"] == utc(minutes=2).isoformat()


def test_consumed_grant_reads_as_consumed(world):
    _database, facts, _policies, authority = world
    approval_id, operation = _settled_allow(facts)
    assert facts.consume_grant(approval_id=approval_id,
                               operation_digest=operation.operation_digest,
                               native_request_id=operation.native_request_id,
                               moment=utc(minutes=2)) is True
    looked = authority.lookup(approval_id, now=utc(minutes=3))
    assert looked is not None and looked.state is AuthorityStateKind.CONSUMED
    assert looked.effective is False


# -- sessions and persons ---------------------------------------------------------


def test_two_sessions_never_see_each_others_authorization(world):
    database, facts, _policies, authority = world
    seed_session(database, session_id="session-2", execution_id="turn-2")
    first_id, _operation = _settled_allow(facts, session_id="session-1",
                                          execution_id="turn-1",
                                          native_request_id="native-s1")
    second_id, _operation = _settled_allow(facts, session_id="session-2",
                                           execution_id="turn-2",
                                           native_request_id="native-s2")
    first_view = authority.effective_for_session("session-1", now=utc(minutes=2))
    second_view = authority.effective_for_session("session-2", now=utc(minutes=2))
    assert [record.fact_ref for record in first_view] == [first_id]
    assert [record.fact_ref for record in second_view] == [second_id]


def test_rule_records_never_answer_a_session_scoped_query(world):
    _database, facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "user", "rules": [{"key": "read", "action": "allow"}]})
    _approval_id, _operation = _settled_allow(facts)
    listed = authority.effective_for_session("session-1", now=utc(minutes=2))
    assert all(record.source is AuthoritySourceKind.APPROVAL_GRANT
               for record in listed)


# -- rule-derived facts --------------------------------------------------------------


def test_current_allow_rules_become_rule_authority_facts(world):
    _database, _facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "user",
        "rules": [{"key": "read", "action": "allow"},
                  {"key": "bash", "action": "deny"}]})
    found = authority.effective_for_operation(tool="read", now=utc(minutes=1))
    assert len(found) == 1
    record = found[0]
    assert record.source is AuthoritySourceKind.POLICY_RULE
    assert record.scope is AuthorityScope.USER
    assert record.fact_ref == "profile-intent@1#0"
    # deny rules are not authorizations and never surface
    assert authority.effective_for_operation(tool="bash", now=utc(minutes=1)) == ()
    # a rule with no pattern speaks about any target of its tool
    assert authority.effective_for_operation(tool="read", target="/any/file",
                                             now=utc(minutes=1)) != ()
    assert authority.lookup("profile-intent@1#0", now=utc()) == record


def test_project_scope_rule_projects_onto_the_profile_scope(world):
    _database, _facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "proj", "revision": 2, "harnessId": "pi",
        "scope": "project", "rules": [{"key": "read", "action": "allow"}]})
    found = authority.effective_for_operation(tool="read", now=utc())
    assert found[0].scope is AuthorityScope.PROFILE


def test_rule_exceptions_carry_their_issuer_and_expiry(world):
    _database, _facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "exceptions", "revision": 1, "harnessId": "pi",
        "scope": "user",
        "rules": [{"key": "bash", "action": "allow", "pattern": "/repo/deploy",
                   "authorization": {"issuer": "admin-1", "subject": "bash",
                                     "target": "/repo/deploy",
                                     "ceilingRevision": "admin@1",
                                     "verified": True,
                                     "expiresAt": utc(minutes=30).isoformat()}}]})
    listed = authority.effective_for_operation(tool="bash", now=utc(minutes=5))
    assert len(listed) == 1
    assert listed[0].approved_by == "admin-1"
    assert listed[0].target == "/repo/deploy"
    assert authority.effective_for_user("admin-1", now=utc(minutes=5)) == listed
    # past the authorization's expiry the fact is EXPIRED and unlisted
    assert authority.effective_for_operation(tool="bash", now=utc(minutes=31)) == ()
    looked = authority.lookup("exceptions@1#0", now=utc(minutes=31))
    assert looked is not None and looked.state is AuthorityStateKind.EXPIRED


def test_superseded_rule_revisions_are_history_not_current_facts(world):
    _database, _facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "user", "rules": [{"key": "read", "action": "allow"}]})
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 2, "harnessId": "pi",
        "scope": "user", "rules": []})
    assert authority.effective_for_operation(tool="read", now=utc()) == ()
    assert authority.lookup("profile-intent@1#0", now=utc()) is None
    assert authority.lookup("profile-intent@2#0", now=utc()) is None


# -- malformed queries are refused, empty worlds are not ----------------------------


def test_malformed_query_inputs_are_refused(world):
    _database, _facts, _policies, authority = world
    with pytest.raises(PolicyRefusal):
        authority.effective_for_operation(tool="bash", now=utc().replace(tzinfo=None))
    with pytest.raises(PolicyRefusal):
        authority.effective_for_operation(operation_digest="short", now=utc())
    with pytest.raises(PolicyRefusal):
        authority.effective_for_operation(tool=42, now=utc())
    with pytest.raises(PolicyRefusal):
        authority.effective_for_session("", now=utc())
    with pytest.raises(PolicyRefusal):
        authority.lookup("   ", now=utc())
    with pytest.raises(PolicyRefusal):
        authority.revoke("approval_x", reason="", now=utc())


# -- the wire projection --------------------------------------------------------------


def test_the_wire_query_is_read_only_and_shape_closed(world):
    database, facts, policies, authority = world
    # an empty world first: the honest full-listing answer is no records
    assert authority.query({}) == {"ready": True, "records": []}
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "user", "rules": [{"key": "read", "action": "allow"}]})
    # the wire surface reads the real clock: the grant must outlive it
    approval_id, _operation = _settled_allow(facts, expires_minutes=5256000)

    def snapshot():
        with database.read() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM server_approvals ORDER BY id").fetchall()]

    before = snapshot()
    full = authority.query({"tool": "read"})
    assert len(full["records"]) == 1
    assert full["records"][0]["source"] == "policy_rule"
    narrowed = authority.query({"factRef": approval_id})
    assert [record["factRef"] for record in narrowed["records"]] == [approval_id]
    assert narrowed["records"][0]["state"] == "active"
    both = authority.query({})
    assert {record["factRef"] for record in both["records"]} \
        == {approval_id, "profile-intent@1#0"}
    assert snapshot() == before  # a read, byte for byte


def test_the_wire_query_refuses_malformed_input_with_the_stable_code_only(world):
    _database, _facts, _policies, authority = world
    from server_plugin_api import WireError
    with pytest.raises(WireError) as caught:
        authority.query({"operationDigest": "short"})
    assert "PERMISSION_AUTHORIZATION_INVALID" in str(caught.value)
    with pytest.raises(WireError):
        authority.query("not-an-object")


def test_a_grants_only_world_still_answers_and_says_what_it_did(world):
    _database, facts, _policies, _authority = world
    grants_only = PermissionsAuthority(facts, None)
    approval_id, operation = _settled_allow(facts, expires_minutes=5256000)
    body = grants_only.query({"tool": "bash"})
    assert [record["factRef"] for record in body["records"]] == [approval_id]
    assert body["ready"] is True
    # without a policies store the rule lane contributes nothing, stated not hidden
    assert grants_only.effective_for_operation(tool="read", now=utc()) == ()
    assert grants_only.effective_for_operation(
        tool="bash", operation_digest=operation.operation_digest,
        now=utc()) != ()


def test_an_unreadable_store_answers_ready_false_with_no_half_read(world, monkeypatch):
    """The review finding: availability=False must short-circuit - the wire
    body is the honest empty answer, never a read that could raise halfway
    and never a partial world that could be mistaken for a full one."""
    database, facts, _policies, authority = world
    approval_id, _operation = _settled_allow(facts, expires_minutes=5256000)
    assert authority.query({"factRef": approval_id})["ready"] is True

    def broken():
        raise RuntimeError("store gone")
    monkeypatch.setattr(authority, "availability", broken)
    body = authority.query({"factRef": approval_id})
    assert body == {"ready": False, "records": []}


def test_a_digest_narrowed_query_is_answered_by_grants_only(world):
    """The review finding: rule facts carry no operation digest, so a
    digest-narrowed query excludes them instead of answering loosely."""
    _database, facts, policies, authority = world
    policies.store_intent_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "user", "rules": [{"key": "read", "action": "allow"}]})
    approval_id, operation = _settled_allow(facts, expires_minutes=5256000)
    unfiltered = authority.effective_for_operation(now=utc(minutes=2))
    assert {record.source for record in unfiltered} == {
        AuthoritySourceKind.APPROVAL_GRANT, AuthoritySourceKind.POLICY_RULE}
    narrowed = authority.effective_for_operation(
        tool="bash", operation_digest=operation.operation_digest, now=utc(minutes=2))
    assert [record.fact_ref for record in narrowed] == [approval_id]
    assert all(record.source is AuthoritySourceKind.APPROVAL_GRANT
               for record in narrowed)
    stranger = authority.effective_for_operation(
        tool="bash", operation_digest="b" * 64, now=utc(minutes=2))
    assert stranger == ()


def test_the_query_port_signatures_match_the_implementation_member_by_member():
    """Contract-drift guard (review finding): the published port's method
    signatures are compared, via inspect, against the composed backend
    implementation - a drifted parameter (like an optional `reason` over a
    required one) fails here instead of at composition time."""
    import inspect
    from ordessa_permissions_api import PermissionsAuthorityQueryPort
    port = PermissionsAuthorityQueryPort
    implementation = PermissionsAuthority
    for name in ("effective_for_operation", "effective_for_session",
                 "effective_for_user", "lookup", "revoke"):
        port_params = [p for n, p in inspect.signature(
            getattr(port, name)).parameters.items() if n != "self"]
        impl_params = [p for n, p in inspect.signature(
            getattr(implementation, name)).parameters.items() if n != "self"]
        assert [(p.name, p.kind, p.default) for p in port_params] \
            == [(p.name, p.kind, p.default) for p in impl_params], name

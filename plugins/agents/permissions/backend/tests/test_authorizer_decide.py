"""T02: `decide` through the authorizer is CAS + idempotent, and refuses
cross-session use, expiry, revision moves, and replayed opposite decisions.
The ruling path is `ApprovalFacts`; the authorizer adds the §C1 result shape
and the revision re-check against the live `PolicyRepository`.
"""
from __future__ import annotations

import pytest
from support import (admin_ceiling, approval_record, clock_at, make_operation,
                     seeded_database, seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts, Authorizer, PolicyRepository


@pytest.fixture
def wired(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    policies.store_ceiling(admin_ceiling())
    authorizer = Authorizer(facts=facts, policies=policies,
                            ceiling_provider=policies.ceilings_current,
                            intent_provider=lambda: None,
                            clock=clock_at(utc()))
    return database, facts, policies, authorizer


def _pending(facts, authorizer, *, native_request_id="native-d"):
    operation = make_operation(ceilings=[admin_ceiling()],
                               native_request_id=native_request_id)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    return record["approvalId"], operation


def test_decide_records_then_replays_already_recorded(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer)
    first = authorizer.decide(approval_id=approval_id, expected_version=1,
                              decision="allow", scope={"kind": "once"},
                              operation_key="ui-1", session_id="session-1")
    replay = authorizer.decide(approval_id=approval_id, expected_version=1,
                               decision="allow", scope={"kind": "once"},
                               operation_key="ui-1", session_id="session-1")
    assert first.kind == "recorded"
    assert replay.kind == "already_recorded"
    assert facts.get(approval_id)["version"] == 2


def test_decide_stale_expected_version_is_a_typed_conflict(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer)
    conflict = authorizer.decide(approval_id=approval_id, expected_version=99,
                                 decision="allow", scope={"kind": "once"},
                                 operation_key="ui-c", session_id="session-1")
    assert conflict.kind == "version_conflict"
    assert facts.get(approval_id)["state"] == "open"


def test_decide_replays_opposite_decision_after_settle_as_refused(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer)
    authorizer.decide(approval_id=approval_id, expected_version=1, decision="allow",
                      scope={"kind": "once"}, operation_key="ui-1",
                      session_id="session-1")
    opposite = authorizer.decide(approval_id=approval_id, expected_version=2,
                                 decision="deny", scope={"kind": "once"},
                                 operation_key="ui-2", session_id="session-1")
    assert opposite.kind == "invalid"
    assert facts.get(approval_id)["decision"] == "allow"


def test_decide_denies_cross_session_approval_use(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer)
    outcome = authorizer.decide(approval_id=approval_id, expected_version=1,
                                decision="allow", scope={"kind": "once"},
                                operation_key="ui-x", session_id="session-B")
    assert outcome.kind == "invalid"
    assert "cross_session" in outcome.reason
    assert facts.get(approval_id)["state"] == "open"


def test_decide_refuses_an_expired_approval(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer, native_request_id="native-exp")
    late = Authorizer(facts=facts, policies=policies,
                      ceiling_provider=policies.ceilings_current,
                      intent_provider=lambda: None,
                      clock=clock_at(utc(minutes=30)))
    outcome = late.decide(approval_id=approval_id, expected_version=1, decision="allow",
                          scope={"kind": "once"}, operation_key="ui-late",
                          session_id="session-1")
    assert outcome.kind == "invalid"
    assert outcome.reason == "approval_expired"


def test_decide_refuses_when_the_policy_revision_moved(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer, native_request_id="native-rev")
    policies.store_ceiling(admin_ceiling(revision=2))  # tightening mid-flight
    outcome = authorizer.decide(approval_id=approval_id, expected_version=1,
                                decision="allow", scope={"kind": "once"},
                                operation_key="ui-moved", session_id="session-1")
    assert outcome.kind == "invalid"
    assert "APPROVAL_STALE" in outcome.reason
    # The refusal is not silent: the row is untouched and still observable.
    assert facts.get(approval_id)["state"] == "open"


def test_decide_with_no_ceiling_provider_fails_closed(wired):
    database, facts, policies, authorizer = wired
    approval_id, _ = _pending(facts, authorizer, native_request_id="native-np")
    blind = Authorizer(facts=facts, policies=policies,
                       ceiling_provider=lambda: (), intent_provider=lambda: None,
                       clock=clock_at(utc()))
    outcome = blind.decide(approval_id=approval_id, expected_version=1, decision="allow",
                           scope={"kind": "once"}, operation_key="ui-blind",
                           session_id="session-1")
    assert outcome.kind == "unknown"  # cannot verify the revision pin -> never a yes
    assert not getattr(outcome, "grants_execution", False)


def test_query_reconcile_shape_on_the_authorizer(wired):
    database, facts, policies, authorizer = wired
    approval_id, operation = _pending(facts, authorizer, native_request_id="native-q")
    outcome = authorizer.reconcile(approval_id, operation.native_request_id)
    assert outcome.kind == "resolved"  # open state is a resolvable fact...
    assert outcome.receipt is None
    assert not getattr(outcome, "grants_execution", False)  # ...but grants nothing

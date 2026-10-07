"""T010-01 gates: one writer per canonical target, A1 receipt semantics."""
from __future__ import annotations

import pytest

from pacthold.agents.submissions import (
    AgentOwnerRegistry,
    AuthorityConflictError,
    SubmissionOwner,
)
from pacthold.agents.submissions.owners import AgentOwnerError


def test_one_writer_per_canonical_target():
    registry = AgentOwnerRegistry()
    registry.register("session:S1")
    with pytest.raises(AuthorityConflictError):
        registry.register("session:S1")  # second writer refused at the boundary
    assert registry.owners_of("session:S1") is not None


def test_same_profile_reselect_is_a_new_operation_id():
    registry = AgentOwnerRegistry()
    config = registry.register("session:S2")["config"]
    first = config.submit_operation({"model": "m1"}, "profile")
    second = config.submit_operation({"model": "m1"}, "profile")  # same values, new op
    assert first.operation_id != second.operation_id
    assert config.list_operations()[1].submitted_at_order == 2


def test_receipt_outcomes_are_three_way_and_unknown_never_resends():
    submission = SubmissionOwner("session:S3")
    accepted = submission.submit(1, {"outcome": "accepted"})
    assert accepted.outcome == "accepted"
    rejected = submission.submit(2, {"outcome": "known-rejected"})
    assert rejected.outcome == "known-rejected"
    unknown = submission.submit(3, {"outcome": "unknown"})
    assert unknown.outcome == "unknown"
    assert unknown.query_request_key is not None
    # unknown is query-only: querying does not dispatch again
    assert submission.dispatch_count(unknown.submission_id) == 1
    assert submission.query(unknown.submission_id) == unknown
    assert submission.dispatch_count(unknown.submission_id) == 1


def test_counterexample_snapshots_are_frozen_against_external_setstate():
    registry = AgentOwnerRegistry()
    config = registry.register("session:S4")["config"]
    snapshot = config.snapshot()
    with pytest.raises(Exception):
        snapshot.fields["x"] = "known"  # frozen mapping
    with pytest.raises(AttributeError):
        config.setState  # no generic setter exists


def test_repeated_identical_observation_does_not_unlock_pending_unknown():
    registry = AgentOwnerRegistry()
    config = registry.register("session:S5")["config"]
    config.submit_operation({"model": "m"}, "profile")
    config.report_evidence("unknown")
    revision_after_unknown = config.snapshot().revision
    config.report_evidence("unknown")  # repeated identical observation
    assert config.snapshot().revision == revision_after_unknown  # not unlocked
    config.report_evidence("native", {"model": "known"})  # NEW complete snapshot
    assert config.snapshot().fields["model"] == "known"


def test_bad_field_states_are_refused():
    registry = AgentOwnerRegistry()
    config = registry.register("session:S6")["config"]
    with pytest.raises(AgentOwnerError):
        config.report_evidence("bogus")
    with pytest.raises(AgentOwnerError):
        config.report_evidence("native", {"x": "maybe"})


def test_field_states_are_known_unset_unknown():
    registry = AgentOwnerRegistry()
    config = registry.register("session:S7")["config"]
    config.submit_operation({"a": 1}, "profile", unset=("b",))
    snapshot = config.snapshot()
    assert snapshot.fields["a"] == "known"
    assert snapshot.fields["b"] == "unset"
    assert snapshot.fields.get("c") is None  # unknown fields appear only via evidence
    config.report_evidence("native", {"c": "unknown"})
    assert config.snapshot().fields["c"] == "unknown"

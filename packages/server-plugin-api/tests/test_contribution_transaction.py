"""C2 staged-transaction tests: owner injection, purity before commit, rollback."""
from __future__ import annotations

import pytest

from server_plugin_api import (
    AbsentContribution,
    Contribution,
    ContributionBatch,
    ContributionBatchCleanupError,
    ContributionCleanupError,
    ContributionDeclarationError,
    ContributionRollbackRefusedError,
    ContributionStateError,
    RequiredContributionMissingError,
    ServerContributionHandler,
    stage_contributions,
)


class RecordingHandler(ServerContributionHandler):
    """A handler whose only 'effect' is its call log and published dict."""

    def __init__(self, refuse_stage_for=frozenset()):
        self.calls: "list[tuple[str, str]]" = []
        self.published: "dict[str, object]" = {}
        self._refuse_stage_for = set(refuse_stage_for)

    def stage(self, contribution, owner):
        self.calls.append(("stage", contribution.point_id))
        if contribution.point_id in self._refuse_stage_for:
            raise ContributionDeclarationError(f"refused stage: {contribution.point_id}")
        return {"prepared": contribution.payload, "owner": owner}

    def commit(self, contribution, prepared, owner):
        self.calls.append(("commit", contribution.point_id))
        self.published[contribution.point_id] = prepared["prepared"]

    def rollback(self, contribution, prepared, owner):
        self.calls.append(("rollback", contribution.point_id))
        self.published.pop(contribution.point_id, None)


def _batch(*points):
    return ContributionBatch(contributions=tuple(
        Contribution(point_id=point, api_version="v1", payload=f"payload:{point}")
        for point in points))


def test_owner_is_host_injected_into_every_handler_call():
    handler = RecordingHandler()
    staged = stage_contributions(handler, "plugin-alpha", _batch("pacthold.contributions"))
    assert [prepared["owner"] for _, prepared in staged.entries] == ["plugin-alpha"]
    staged.commit()
    assert ("commit", "pacthold.contributions") in handler.calls
    prepared_commit_calls = [c for c in handler.calls if c[0] == "commit"]
    assert prepared_commit_calls == [("commit", "pacthold.contributions")]


def test_handler_abc_refuses_instantiation_without_the_three_methods():
    class Partial(ServerContributionHandler):
        def stage(self, contribution, owner):
            return None

    with pytest.raises(TypeError):
        Partial()


def test_stage_validates_without_publishing_anything():
    handler = RecordingHandler()
    staged = stage_contributions(handler, "plugin-a", _batch("pacthold.contributions",
                                                             "services.workspace"))
    assert [call for call in handler.calls if call[0] == "commit"] == []
    assert handler.published == {}
    assert isinstance(staged.resolve("pacthold.contributions"), AbsentContribution)
    assert isinstance(staged.resolve("services.workspace"), AbsentContribution)

    staged.commit()
    assert handler.published == {"pacthold.contributions": "payload:pacthold.contributions",
                                 "services.workspace": "payload:services.workspace"}
    carried = staged.resolve("services.workspace")
    assert not isinstance(carried, AbsentContribution)
    assert carried.payload == "payload:services.workspace"


def test_required_missing_refuses_before_any_handler_stage_runs():
    handler = RecordingHandler()
    batch = _batch("services.workspace")
    with pytest.raises(RequiredContributionMissingError):
        stage_contributions(handler, "plugin-a", batch,
                            required_points=("pacthold.contributions",))
    assert handler.calls == []


def test_failed_stage_rolls_back_earlier_entries_and_refuses_the_batch():
    handler = RecordingHandler(refuse_stage_for={"second.point"})
    batch = _batch("first.point", "second.point")
    with pytest.raises(ContributionDeclarationError):
        stage_contributions(handler, "plugin-a", batch)
    assert handler.calls == [("stage", "first.point"), ("stage", "second.point"),
                             ("rollback", "first.point")]


def test_rollback_before_commit_undoes_and_is_idempotent():
    handler = RecordingHandler()
    staged = stage_contributions(handler, "plugin-a", _batch("pacthold.contributions",
                                                             "services.workspace"))
    staged.rollback()
    assert [c for c in handler.calls if c[0] == "rollback"] == [
        ("rollback", "services.workspace"), ("rollback", "pacthold.contributions")]
    handler.calls.clear()
    staged.rollback()
    staged.rollback()
    assert handler.calls == []
    assert isinstance(staged.resolve("pacthold.contributions"), AbsentContribution)


def test_rollback_after_commit_is_a_typed_refusal():
    handler = RecordingHandler()
    staged = stage_contributions(handler, "plugin-a", _batch("pacthold.contributions"))
    staged.commit()
    with pytest.raises(ContributionRollbackRefusedError) as excinfo:
        staged.rollback()
    assert excinfo.value.committed_points == ("pacthold.contributions",)
    assert handler.published == {"pacthold.contributions": "payload:pacthold.contributions"}


def test_commit_twice_is_refused():
    staged = stage_contributions(RecordingHandler(), "plugin-a", _batch("pacthold.contributions"))
    staged.commit()
    with pytest.raises(ContributionStateError):
        staged.commit()


def test_commit_after_rollback_is_refused():
    handler = RecordingHandler()
    staged = stage_contributions(handler, "plugin-a", _batch("pacthold.contributions"))
    staged.rollback()
    with pytest.raises(ContributionStateError):
        staged.commit()
    assert handler.published == {}


class UnwindingHandler(RecordingHandler):
    """A recording handler whose `rollback` explodes for the named points."""

    def __init__(self, refuse_stage_for=frozenset(), fail_rollback_for=frozenset()):
        super().__init__(refuse_stage_for=refuse_stage_for)
        self._fail_rollback_for = set(fail_rollback_for)

    def rollback(self, contribution, prepared, owner):
        self.calls.append(("rollback", contribution.point_id))
        self.published.pop(contribution.point_id, None)
        if contribution.point_id in self._fail_rollback_for:
            raise RuntimeError(f"rollback exploded: {contribution.point_id}")


def test_failed_stage_rollback_failure_rides_on_the_stage_error_never_replaces_it():
    """A cleanup failure during a staging rollback is a carried fact: the
    batch's original stage error stays primary, every staged entry is
    still undone, and each failed rollback names itself on `cleanup_errors`
    — neither swallowed nor replacing."""
    handler = UnwindingHandler(refuse_stage_for={"third.point"},
                               fail_rollback_for={"first.point", "second.point"})
    batch = _batch("first.point", "second.point", "third.point")
    with pytest.raises(ContributionDeclarationError) as excinfo:
        stage_contributions(handler, "plugin-a", batch)
    # The first exploding rollback did not skip the entry behind it.
    assert handler.calls == [("stage", "first.point"), ("stage", "second.point"),
                             ("stage", "third.point"),
                             ("rollback", "second.point"), ("rollback", "first.point")]
    carried = excinfo.value.cleanup_errors
    assert all(isinstance(e, ContributionCleanupError) for e in carried)
    assert [e.point_id for e in carried] == ["second.point", "first.point"]
    assert [e.plugin_owner for e in carried] == ["plugin-a", "plugin-a"]
    assert [type(e.cause).__name__ for e in carried] == ["RuntimeError", "RuntimeError"]


def test_carry_never_replaces_an_exception_that_refuses_attributes():
    """An exception object that rejects attribute attachment propagates
    unchanged — carrying is best-effort, never a second failure."""

    class AttributeRefusingError(Exception):
        def __setattr__(self, name, value):
            raise AttributeError("this exception carries nothing")

    class ExplodingHandler(RecordingHandler):
        def stage(self, contribution, owner):
            self.calls.append(("stage", contribution.point_id))
            if contribution.point_id == "second.point":
                raise AttributeRefusingError("stage refused")
            return {"prepared": contribution.payload, "owner": owner}

        def rollback(self, contribution, prepared, owner):
            self.calls.append(("rollback", contribution.point_id))
            raise RuntimeError("rollback exploded")

    handler = ExplodingHandler()
    with pytest.raises(AttributeRefusingError) as excinfo:
        stage_contributions(handler, "plugin-a", _batch("first.point", "second.point"))
    assert excinfo.value.args == ("stage refused",)
    assert not hasattr(excinfo.value, "cleanup_errors")
    assert ("rollback", "first.point") in handler.calls


def test_direct_rollback_attempts_every_entry_then_raises_one_cleanup_aggregate():
    """`rollback()` outside any unwinding: nothing is skipped, the batch
    ends rolled back, and all failures surface together afterwards."""
    handler = UnwindingHandler(fail_rollback_for={"second.point"})
    staged = stage_contributions(handler, "plugin-a",
                                 _batch("first.point", "second.point"))
    with pytest.raises(ContributionBatchCleanupError) as excinfo:
        staged.rollback()
    assert [c for c in handler.calls if c[0] == "rollback"] == [
        ("rollback", "second.point"), ("rollback", "first.point")]
    assert [e.point_id for e in excinfo.value.errors] == ["second.point"]
    assert isinstance(excinfo.value.errors[0], ContributionCleanupError)
    assert isinstance(excinfo.value.errors[0].cause, RuntimeError)
    assert staged.state == "rolled-back"
    assert isinstance(staged.resolve("first.point"), AbsentContribution)
    staged.rollback()  # idempotent even after the aggregate


def test_rollback_during_unwinding_carries_cleanup_facts_instead_of_raising():
    """The same rule by branch: with an exception in flight, `rollback()`
    never raises the aggregate — the failures accumulate onto the in-flight
    primary's `cleanup_errors`."""
    handler = UnwindingHandler(fail_rollback_for={"first.point"})
    staged = stage_contributions(handler, "plugin-a",
                                 _batch("first.point", "second.point"))
    sentinel = ValueError("the round's own failure")
    try:
        raise sentinel
    except ValueError:
        sentinel.cleanup_errors = ("earlier-fact",)  # attachments accumulate
        staged.rollback()
    assert [c for c in handler.calls if c[0] == "rollback"] == [
        ("rollback", "second.point"), ("rollback", "first.point")]
    carried = sentinel.cleanup_errors
    assert carried[0] == "earlier-fact"
    assert [e.point_id for e in carried[1:]] == ["first.point"]
    assert staged.state == "rolled-back"

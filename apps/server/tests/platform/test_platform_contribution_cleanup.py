"""T012 family (c): cleanup never replaces the primary, never swallows a
fact, and never skips an entry behind a raising rollback (FR-007) — plus
the busy guard that stops a live reference being stolen.

Both rollback paths are covered: the host-shutdown path (retiring published
contributions as plugins unload) and the contribution-batch path (undoing a
round that failed at stage or commit). A fix that captured only one failure,
or that let a raising rollback abort the sweep, flips the counterexample.

The last group pins the case the busy guard does NOT cover: `shutdown()`
bypasses it by design (host-wide teardown retires everything, mirroring
pacthold's close-vs-unregister split), so what a consumer still holding a
live resolution observes across that boundary is a fact worth stating —
absence for the view, a hold that stays honest until the body exits.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from server_plugin_api import (
    AbsentContribution,
    CleanupError,
    ContributionBatchCleanupError,
    ContributionCleanupError,
    ContributionOwnerBusyError,
    PluginCleanupError,
)

from contribution_fakes import ContribPlugin, RecordingHandler, contribution, new_host

import ordessa_server.plugin_host.contribution_points as contribution_points
from ordessa_server.plugin_host import (
    ContributionPointRegistry, PublishedRecord, ResolvedContribution,
)

POINT = "test.echo"
OTHER = "test.other"


# -- the contribution-batch (round rollback) path --------------------------------


def test_a_raising_stage_rollback_is_carried_and_every_entry_is_attempted():
    """B's own stage raises; A's staged entry then refuses to roll back.
    B's stage failure stays primary, A's rollback failure rides on it as a
    `ContributionCleanupError` carrying the exact cause, and A's rollback
    was still attempted. Delete the carrying and the fact assertions fail;
    make rollbacks eager-abort and the attempted list fails."""
    host = new_host()
    stage_boom = RuntimeError("B stage refused")
    rollback_boom = RuntimeError("A rollback refused")
    a_handler = RecordingHandler(rollback_raises={"fake.a": rollback_boom})
    b_handler = RecordingHandler(stage_raises={"fake.b": stage_boom})
    # one handler instance per point: A contributes to POINT, B to OTHER
    host.register_contribution_point(POINT, "v1", handler=a_handler)
    host.register_contribution_point(OTHER, "v1", handler=b_handler)
    with pytest.raises(RuntimeError) as captured:
        host.activate_all([
            ContribPlugin("fake.a", methods=("fake.a.method",),
                          contributions=(contribution(POINT),)),
            ContribPlugin("fake.b", methods=("fake.b.method",),
                          contributions=(contribution(OTHER),)),
        ])
    assert captured.value is stage_boom, "the stage failure must stay primary"
    carried = getattr(captured.value, "cleanup_errors", ())
    facts = [err for err in carried if isinstance(err, ContributionCleanupError)]
    assert [(f.plugin_owner, f.point_id, f.cause) for f in facts] == [
        ("fake.a", POINT, rollback_boom)], facts
    assert a_handler.names("rollback") == [(POINT, "fake.a")], (
        "the raising rollback entry must still have been attempted")
    assert host.active_ids() == ()
    assert isinstance(host.contribution(POINT), AbsentContribution)


def test_a_raising_commit_undo_carries_beside_the_disposal_carry_rule():
    """The commit phase fails and the undo of the committed entry raises:
    the commit error stays primary with the undo failure inspectable on
    its `cleanup_errors`, every entry still attempted in reverse, and the
    round's disposals still run — the affected plugins' wire surface is
    retired with the batch."""
    host = new_host()
    commit_boom = RuntimeError("B commit refused")
    undo_boom = RuntimeError("A committed undo refused")
    handler = RecordingHandler(commit_raises={"fake.b": commit_boom},
                               rollback_raises={"fake.a": undo_boom})
    host.register_contribution_point(POINT, "v1", handler=handler, exclusive=False)
    disposals: list[str] = []
    with pytest.raises(RuntimeError) as captured:
        host.activate_all([
            ContribPlugin("fake.a", methods=("fake.a.method",),
                          contributions=(contribution(POINT),),
                          dispose_records=disposals),
            ContribPlugin("fake.b", methods=("fake.b.method",),
                          contributions=(contribution(POINT, payload={"n": 2}),),
                          dispose_records=disposals),
        ])
    assert captured.value is commit_boom
    carried = getattr(captured.value, "cleanup_errors", ())
    facts = [err for err in carried if isinstance(err, ContributionCleanupError)]
    assert [(f.plugin_owner, f.cause) for f in facts] == [("fake.a", undo_boom)], facts
    assert handler.names("rollback") == [(POINT, "fake.b"), (POINT, "fake.a")], (
        "every entry behind the raising undo is attempted, reverse order")
    assert disposals == ["fake.b", "fake.a"]
    assert host.methods.lookup("fake.a.method") is None
    assert isinstance(host.contribution(POINT), AbsentContribution)


# -- the host-shutdown path -------------------------------------------------------


def test_shutdown_retires_contributions_and_surfaces_every_raising_rollback():
    """Shutdown with two contribution owners whose retirement rollback
    raises: both plugins' entries are retired, both rollback failures are
    collected inside the one `CleanupError` (naming owner and point and
    carrying the exact cause), every plugin was attempted, and nothing
    resolves afterwards."""
    host = new_host()
    rollback_boom_x = RuntimeError("X rollback refused")
    rollback_boom_y = RuntimeError("Y rollback refused")
    handler = RecordingHandler(rollback_raises={"fake.x": rollback_boom_x,
                                                "fake.y": rollback_boom_y})
    host.register_contribution_point(POINT, "v1", handler=handler, exclusive=False)
    host.activate_all([
        ContribPlugin("fake.x", methods=("fake.x.method",),
                      contributions=(contribution(POINT),)),
        ContribPlugin("fake.y", methods=("fake.y.method",),
                      contributions=(contribution(POINT, payload={"n": 2}),)),
    ])
    assert len(host.contributions(POINT)) == 2
    with pytest.raises(CleanupError) as captured:
        host.shutdown()
    errors = captured.value.errors
    assert [e.plugin_id for e in errors] == ["fake.y", "fake.x"], errors
    for entry in errors:
        assert isinstance(entry, PluginCleanupError)
        assert isinstance(entry.error, ContributionBatchCleanupError)
        inner = entry.error.errors
        assert len(inner) == 1 and isinstance(inner[0], ContributionCleanupError)
        assert inner[0].point_id == POINT
    assert [e.error.errors[0].cause for e in errors] == [rollback_boom_y, rollback_boom_x]
    # every entry was attempted, and after shutdown nothing survives
    assert sorted(handler.names("rollback")) == [(POINT, "fake.x"), (POINT, "fake.y")]
    assert host.active_ids() == ()
    assert isinstance(host.contribution(POINT), AbsentContribution)


def test_a_single_raising_retirement_refuses_a_user_initiated_unload_type_wise():
    """The non-shutdown path: one plugin unloads and its retirement
    rollback raises — the unload surfaces ONE typed
    `ContributionBatchCleanupError` naming the failure (never swallowed),
    while the published view is already clean: retirement is observable
    immediately, not 'once the undo finished'."""
    host = new_host()
    rollback_boom = RuntimeError("retire refused")
    handler = RecordingHandler(rollback_raises={"fake.retire": rollback_boom})
    host.register_contribution_point(POINT, "v1", handler=handler)
    host.activate(ContribPlugin("fake.retire", methods=("fake.retire.method",),
                                contributions=(contribution(POINT),)))
    with pytest.raises(ContributionBatchCleanupError) as captured:
        host.deactivate("fake.retire")
    assert captured.value.errors[0].cause is rollback_boom
    assert captured.value.errors[0].plugin_owner == "fake.retire"
    assert isinstance(host.contribution(POINT), AbsentContribution)
    assert host.active_ids() == ()


# -- busy / unload protection ------------------------------------------------------


def test_owner_busy_tracks_in_flight_resolution_and_blocks_the_unload():
    """While a consumer holds a live resolution of the owner's
    contribution, `owner_busy` is true and the unload is a typed refusal
    naming the owner and its points — no live reference is stolen. When
    the hold releases, the same unload succeeds; a never-busy owner unloads
    idempotently-clean, and an absent resolution claims no hold."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.owner", methods=("fake.owner.method",),
                                contributions=(contribution(POINT),)))
    assert host.owner_busy("fake.owner") is False
    with host.use_contribution(POINT) as view:
        assert isinstance(view, ResolvedContribution)
        assert host.owner_busy("fake.owner") is True
        with pytest.raises(ContributionOwnerBusyError) as refused:
            host.deactivate("fake.owner")
        assert refused.value.owner == "fake.owner"
        assert POINT in refused.value.points
        assert host.is_active("fake.owner")
    assert host.owner_busy("fake.owner") is False
    host.deactivate("fake.owner")  # not busy: the same call now succeeds
    assert host.active_ids() == ()
    # an absent resolution claims no hold
    context = host.use_contribution(POINT)
    assert isinstance(context.__enter__(), AbsentContribution)
    context.__exit__(None, None, None)
    assert host.owner_busy("fake.owner") is False


def test_publication_token_changes_on_republish_of_same_payload():
    assert ResolvedContribution(POINT, "v1", {}, "legacy.consumer").publication_token == ""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    payload = {"same": "object"}
    plugin = ContribPlugin("fake.owner", contributions=(contribution(POINT, payload=payload),))
    host.activate(plugin)
    with host.use_contribution(POINT) as held:
        assert isinstance(held, ResolvedContribution)
        first_token = held.publication_token
        assert first_token
        assert held.payload is payload
        assert host.contribution(POINT).publication_token == first_token
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate("fake.owner")
        assert held.publication_token == first_token
    host.deactivate("fake.owner")
    assert held.publication_token == first_token
    host.activate(plugin)
    republished = host.contribution(POINT)
    assert isinstance(republished, ResolvedContribution)
    assert republished.owner == held.owner and republished.payload is payload
    assert republished.publication_token != first_token


def test_publication_token_failure_cannot_expose_half_a_round(monkeypatch):
    registry = ContributionPointRegistry()
    handler = RecordingHandler()
    records = tuple(PublishedRecord(owner, contribution(POINT, payload={"owner": owner}),
                                    None, handler) for owner in ("fake.first", "fake.second"))
    calls = 0

    def fail_second_token():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("controlled token failure")
        return SimpleNamespace(hex="first-token")

    monkeypatch.setattr(contribution_points, "uuid4", fail_second_token)
    with pytest.raises(RuntimeError, match="controlled token failure"):
        registry.publish(records)
    assert registry.published(POINT) == ()


def test_nested_holds_release_one_at_a_time():
    """Two overlapping holds, one owner: busy survives the inner exit and
    clears only after the outer one — a counter (never a boolean) keeps a
    consumer from having its live reference stolen by an early release."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.owner", contributions=(contribution(POINT),)))
    with host.use_contribution(POINT):
        with host.use_contribution(POINT):
            assert host.owner_busy("fake.owner") is True
        assert host.owner_busy("fake.owner") is True
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate("fake.owner")
    assert host.owner_busy("fake.owner") is False
    host.deactivate("fake.owner")
    assert host.active_ids() == ()


def test_a_consumer_resolving_mid_round_sees_the_previous_committed_view():
    """The admission window closed on the consumer side too: a resolution
    taken while a later round is in flight answers with the previous
    committed view, unchanged — never the half-staged batch, never an
    error. A round that republished through the back door would show its
    new payload here."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.first", contributions=(
        contribution(POINT, payload={"round": 1}),)))
    seen: dict[str, object] = {}
    staged_other = ContribPlugin(
        "fake.staged",
        # a DIFFERENT point so the round stages without a held-claim: the
        # witness resolves POINT while this round is mid-flight
        contributions=(contribution("test.other"),),
        observe=lambda context: seen.setdefault("mid_round", host.contribution(POINT)))
    host.register_contribution_point("test.other", "v1", handler=RecordingHandler())
    host.activate(staged_other)
    assert seen["mid_round"].payload == {"round": 1}, (
        "a resolution mid-round must see the previous committed view, unchanged")
    assert seen["mid_round"].owner == "fake.first"
    assert host.contribution(POINT).owner == "fake.first"


# -- shutdown while a consumer holds a live resolution (T013 follow-up) -----------


def _compose_hold_window(disposals: list[str]):
    """Owner + declared consumer on one point, each owing a disposal record.

    The window is opened by the caller so the assertions below run while the
    consumer is genuinely mid-call."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate_all([
        ContribPlugin("fake.owner", methods=("fake.owner.method",),
                      contributions=(contribution(POINT, payload={"owner": "fake.owner"}),),
                      dispose_records=disposals),
        ContribPlugin("fake.child", requires=("fake.owner",), methods=("fake.child.method",),
                      dispose_records=disposals),
    ])
    return host


def test_shutdown_during_a_live_hold_neither_refuses_on_busy_nor_on_admission():
    """Host-wide teardown deliberately bypasses the busy gate: a live hold
    makes `deactivate` refuse (the consumer-initiated unload path), yet the
    same instant's `shutdown` completes — it raises neither
    `ContributionOwnerBusyError` nor `HostAdmissionClosedError` (a hold is
    not an in-flight activation round), disposes every plugin exactly once
    in reverse activation order, and leaves the host `open`. Mirrors
    pacthold's close-vs-unregister split: closing tears the whole runtime
    down, unregistering one participant is what the busy guard protects."""
    disposals: list[str] = []
    host = _compose_hold_window(disposals)
    with host.use_contribution(POINT, consumer="fake.child") as held:
        assert isinstance(held, ResolvedContribution)
        assert host.owner_busy("fake.owner") is True
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate("fake.owner")
        host.shutdown()
    assert disposals == ["fake.child", "fake.owner"], (
        "each plugin's disposal runs exactly once, reverse activation order")
    assert host.active_ids() == ()
    assert host.state == "open"


def test_a_consumer_still_executing_after_shutdown_sees_absence_not_a_stale_payload():
    """The honest consequence of the bypass, stated instead of hidden: the
    hold protects the reference from being stolen, it does not keep the
    contribution alive. Inside the same window, once `shutdown` returned,
    the point resolves as an observable absence on every read path — the
    unscoped view, the multi-view list, and a re-resolution by the (now
    deactivated) consumer identity, which answers absence because there is
    no published record left to grant or refuse. The retired payload is
    nowhere observable to the code still running in the body."""
    disposals: list[str] = []
    host = _compose_hold_window(disposals)
    with host.use_contribution(POINT, consumer="fake.child") as held:
        stale = held.payload
        host.shutdown()
        absent = host.contribution(POINT)
        assert isinstance(absent, AbsentContribution), absent
        assert "no committed contribution is published" in absent.reason
        assert host.contributions(POINT) == ()
        re_resolved = host.contribution(POINT, consumer="fake.child")
        assert isinstance(re_resolved, AbsentContribution), re_resolved
        assert getattr(re_resolved, "payload", None) != stale
    assert stale == {"owner": "fake.owner"}


def test_a_hold_released_after_shutdown_does_not_corrupt_the_busy_counter():
    """Teardown retires publications, not consumer holds: while the window
    is still open after `shutdown`, `owner_busy` remains true — the consumer
    is genuinely mid-call and the host does not fake-clear the ledger to
    look clean. When the body exits, the release brings the counter back to
    exactly zero (no negative drift, no stale entry) and the owner can be
    activated again: it starts not-busy, a fresh hold registers, and that
    hold releases the same way."""
    disposals: list[str] = []
    host = _compose_hold_window(disposals)
    with host.use_contribution(POINT, consumer="fake.child") as held:
        host.shutdown()
        assert host.owner_busy("fake.owner") is True, (
            "shutdown must not fake-clear a hold the consumer still runs under")
    assert host.owner_busy("fake.owner") is False
    assert host.contribution_points.held_owners() == ()
    fresh: list[str] = []
    host.activate(ContribPlugin("fake.owner", methods=("fake.owner.method",),
                                contributions=(contribution(POINT, payload={"round": 2}),),
                                dispose_records=fresh))
    assert host.owner_busy("fake.owner") is False, (
        "a re-activated owner must not start already-busy from the old hold")
    with host.use_contribution(POINT) as view:
        assert isinstance(view, ResolvedContribution) and view.payload == {"round": 2}
        assert host.owner_busy("fake.owner") is True
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate("fake.owner")
    assert host.owner_busy("fake.owner") is False
    host.deactivate("fake.owner")
    assert fresh == ["fake.owner"]
    assert isinstance(host.contribution(POINT), AbsentContribution)

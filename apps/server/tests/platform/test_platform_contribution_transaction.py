"""T012 family (a): the contribution round is a transaction, not a trickle.

FR-005 / C2: a batch publishes atomically or not at all, and the admission
window closes while a round is in flight. Every guard here has a
counterexample shape: a host that published at stage time, that left a
committed batch behind when a later plugin failed, that let a contested
exclusive point resolve last-wins, or that silently dropped a contribution
onto an unbound point would flip one of these red.
"""
from __future__ import annotations

import pytest

from server_plugin_api import (
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
    AbsentContribution,
    ContributionPointHeldError,
    ContributionPointUnboundError,
    ContributionVersionRefusedError,
    HostAdmissionClosedError,
)

from contribution_fakes import ContribPlugin, RecordingHandler, contribution, new_host

from ordessa_server.plugin_host import ResolvedContribution

POINT = "test.echo"


def _publish_round(host, *plugins, handler=None, point=POINT, exclusive=True):
    if handler is None:
        handler = RecordingHandler()
    host.register_contribution_point(point, "v1", handler=handler, exclusive=exclusive)
    host.activate_all(list(plugins))
    return handler


# -- the committed view --------------------------------------------------------


def test_a_committed_batch_resolves_as_a_versioned_owned_view():
    """Positive guard: after the round, the consumer's view carries the
    payload, the api_version and the host-injected owner. Delete the
    publish step and this resolves Absent; let the author name the owner
    and the owner here would not be the plugin id the host injected."""
    host = new_host()
    sentinel = {"core": "set"}
    handler = _publish_round(
        host, ContribPlugin("fake.owner", methods=("fake.owner.method",),
                            contributions=(contribution(POINT, "v1", sentinel),)))
    view = host.contribution(POINT)
    assert isinstance(view, ResolvedContribution), view
    assert view.payload is sentinel
    assert view.api_version == "v1"
    assert view.owner == "fake.owner"
    assert view.point_id == POINT
    # the handler saw the OWNER the host injected, never an author-written one
    assert handler.names("stage") == [(POINT, "fake.owner")]
    assert handler.names("commit") == [(POINT, "fake.owner")]


def test_nothing_is_visible_mid_round_and_the_state_says_draining():
    """The mid-round witness: a second plugin's build runs while the first
    plugin's batch is staged. Staged is not published — the view is an
    observable absence, the host state names itself 'draining', and
    admission reads closed. A host that published at stage time serves the
    payload here and breaks the round's atomicity from the inside."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    seen: dict[str, object] = {}

    def witness(context):
        seen["view"] = host.contribution(POINT)
        seen["state"] = host.state
        seen["admission_open"] = host.admission_open

    host.activate_all([
        ContribPlugin("fake.first", methods=("fake.first.method",),
                      contributions=(contribution(POINT),)),
        ContribPlugin("fake.second", methods=("fake.second.method",), observe=witness),
    ])
    assert isinstance(seen["view"], AbsentContribution), (
        f"a staged contribution became visible mid-round: {seen['view']}")
    assert seen["state"] == "draining"
    assert seen["admission_open"] is False
    # after the round: published, and admission is open again
    assert isinstance(host.contribution(POINT), ResolvedContribution)
    assert host.state == "open"
    assert host.admission_open is True


# -- admission refusals are typed, never last-wins ------------------------------


def test_an_exclusive_point_held_by_another_owner_refuses_before_publish():
    """Two owners, one exclusive point: the second claim is a typed refusal
    naming holder and claimer, the first owner's committed view is
    untouched, and the refusing round leaves no half batch behind. A silent
    last-wins would show `fake.second` as the owner here."""
    host = new_host()
    _publish_round(host, ContribPlugin("fake.first", contributions=(contribution(POINT),)))
    second = ContribPlugin("fake.second", methods=("fake.second.method",),
                           contributions=(contribution(POINT),))
    with pytest.raises(ContributionPointHeldError) as refused:
        host.activate(second)
    assert refused.value.point_id == POINT
    assert refused.value.holder == "fake.first"
    assert refused.value.claimer == "fake.second"
    assert host.active_ids() == ("fake.first",)
    assert host.methods.lookup("fake.second.method") is None
    view = host.contribution(POINT)
    assert isinstance(view, ResolvedContribution) and view.owner == "fake.first"
    # retire-first is the explicit two-step: after the holder leaves, the
    # same claim commits
    host.deactivate("fake.first")
    host.activate(second)
    assert host.contribution(POINT).owner == "fake.second"


def test_a_point_without_a_handler_refuses_admission_type_wise():
    """A declared-but-unbound point is a typed refusal, not a silently
    dropped contribution: the round fails, the plugin never becomes active,
    and admission reopens. A host that swallowed the entry would pass every
    other gate while quietly losing the seam."""
    host = new_host()
    host.register_contribution_point(POINT, "v1")  # no handler: unbound
    plugin = ContribPlugin("fake.owner", methods=("fake.owner.method",),
                           contributions=(contribution(POINT),))
    with pytest.raises(ContributionPointUnboundError) as refused:
        host.activate(plugin)
    assert refused.value.point_id == POINT and refused.value.claimer == "fake.owner"
    assert host.active_ids() == ()
    assert host.methods.lookup("fake.owner.method") is None
    assert isinstance(host.contribution(POINT), AbsentContribution)
    assert host.state == "open"
    # binding the handler later makes the same contribution succeed
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.owner", methods=("fake.owner.method",),
                                contributions=(contribution(POINT),)))
    assert isinstance(host.contribution(POINT), ResolvedContribution)


def test_a_wrong_api_version_refuses_admission():
    """The point accepts v1; a v2 claim is a typed refusal naming both
    versions. Accepting it would publish a payload no handler can
    interpret."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    with pytest.raises(ContributionVersionRefusedError) as refused:
        host.activate(ContribPlugin(
            "fake.owner", methods=("fake.owner.method",),
            contributions=(contribution(POINT, "v2"),)))
    assert refused.value.declared == "v2"
    assert refused.value.accepted == "v1"
    assert host.active_ids() == ()
    assert isinstance(host.contribution(POINT), AbsentContribution)


def test_the_pacthold_point_is_registrable_unbound_and_the_host_wires_no_core_handler():
    """`pacthold.contributions` v1 is a point the composition registers;
    the real handler arrives with the T015 binding. Until then the host
    must refuse admission for it — no implicit core handler on a fresh
    host, none on a declared-but-unbound point — and the payload stays
    opaque: a bare object passes through untouched, never type-checked."""
    payload = {"opaque": object()}
    claim = ContribPlugin("fake.core-claimant", contributions=(contribution(
        PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION, payload),))
    host = new_host()  # a fresh host must not pre-bind anything for the core point
    with pytest.raises(ContributionPointUnboundError):
        host.activate(claim)
    assert host.active_ids() == ()
    host.register_contribution_point(PACTHOLD_CONTRIBUTIONS_POINT_ID,
                                     PACTHOLD_CONTRIBUTIONS_API_VERSION)
    with pytest.raises(ContributionPointUnboundError):
        host.activate(claim)
    handler = RecordingHandler()
    host.register_contribution_point(PACTHOLD_CONTRIBUTIONS_POINT_ID,
                                     PACTHOLD_CONTRIBUTIONS_API_VERSION, handler=handler)
    host.activate(claim)
    assert host.contribution(PACTHOLD_CONTRIBUTIONS_POINT_ID).payload is payload


# -- failure and rollback -------------------------------------------------------


def test_a_later_staging_failure_retires_the_rounds_staged_work():
    """Plugin A stages its batch; plugin B then fails to stage (its method
    id clashes). Nothing of the round survives: A's contribution never even
    reaches the commit phase (there is no half batch to roll back from),
    A's wire surface is revoked, A's disposal ran exactly once, and the
    earlier round's plugin stays active. A host that published per-plugin
    would leave A's payload live under a disposed owner."""
    host = new_host()
    handler = RecordingHandler()
    host.register_contribution_point(POINT, "v1", handler=handler)
    host.register_contribution_point("test.other", "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.stable", methods=("fake.stable.method",)))
    disposals: list[str] = []
    with pytest.raises(Exception):
        host.activate_all([
            ContribPlugin("fake.first", methods=("fake.first.method",),
                          contributions=(contribution(POINT),),
                          dispose_records=disposals),
            ContribPlugin("fake.clash", methods=("fake.stable.method",),
                          contributions=(contribution("test.other"),),
                          dispose_records=disposals),
        ])
    assert "fake.first.method" not in host.methods.handler_view()
    assert "fake.first" not in host.active_ids()
    assert "fake.clash" not in host.active_ids()
    assert isinstance(host.contribution(POINT), AbsentContribution), (
        "a rolled-back round left a published contribution behind")
    # the clashing plugin disposed itself in its own rollback, then the
    # round disposed the activated one: nobody stays alive over a failed round
    assert disposals == ["fake.clash", "fake.first"], disposals
    assert handler.names("commit") == [], "commit runs only after the whole round staged"
    assert host.active_ids() == ("fake.stable",)


def test_a_commit_failure_rolls_back_committed_entries_in_reverse_and_retires_wire():
    """The commit phase itself fails: A committed, B's commit raises. A's
    committed entry is undone (its handler rollback ran with A's prepared
    record), B never publishes, and BOTH plugins' methods/routes/ports are
    retired — no consumer can call a half batch. The commit failure stays
    primary."""
    host = new_host()
    commit_boom = RuntimeError("B commit refused")
    handler = RecordingHandler(commit_raises={"fake.b": commit_boom})
    host.register_contribution_point(POINT, "v1", handler=handler, exclusive=False)
    ports = {"fake.a.port": object(), "fake.b.port": object()}
    disposals: list[str] = []
    with pytest.raises(RuntimeError) as captured:
        host.activate_all([
            ContribPlugin("fake.a", methods=("fake.a.method",), ports=ports,
                          contributions=(contribution(POINT, payload={"from": "a"}),),
                          dispose_records=disposals),
            ContribPlugin("fake.b", methods=("fake.b.method",), ports=ports,
                          contributions=(contribution(POINT, payload={"from": "b"}),),
                          dispose_records=disposals),
        ])
    assert captured.value is commit_boom, "the commit failure must stay primary"
    assert host.active_ids() == ()
    assert host.methods.lookup("fake.a.method") is None
    assert host.methods.lookup("fake.b.method") is None
    assert host.provided_port("fake.a.port") is None
    assert isinstance(host.contribution(POINT), AbsentContribution)
    assert disposals == ["fake.b", "fake.a"], "both plugins retire with their batch"
    # every entry was attempted, reverse order: B (staged) then A (committed)
    assert handler.names("rollback") == [(POINT, "fake.b"), (POINT, "fake.a")]


# -- the closed admission window --------------------------------------------------


def test_admission_refuses_a_reentrant_activation_naming_the_state():
    """While the round is staging, a reentrant activation attempt is a
    typed refusal that names 'draining' — the admission window is closed.
    Delete the guard and the reentrant call would open a second round
    inside the first and interleave half batches."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    captured: dict[str, object] = {}

    def reenter(context):
        try:
            host.activate(ContribPlugin("fake.sneak", methods=("fake.sneak.method",)))
        except BaseException as err:  # noqa: BLE001 - the refusal itself is the fact
            captured["error"] = err

    host.activate_all([
        ContribPlugin("fake.first", contributions=(contribution(POINT),), observe=reenter),
    ])
    error = captured.get("error")
    assert isinstance(error, HostAdmissionClosedError), (
        f"a reentrant activation survived the draining window: {error!r}")
    assert "draining" in str(error)
    assert "fake.sneak" not in host.active_ids()
    # the round the refusal came from still completes honestly
    assert isinstance(host.contribution(POINT), ResolvedContribution)


def test_point_registration_and_deactivation_close_with_the_window():
    """The same guard covers the other two mutations: declaring a point and
    unloading a plugin mid-round are typed refusals naming the state."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate(ContribPlugin("fake.a", methods=("fake.a.method",)))
    errors: dict[str, BaseException] = {}

    def reenter(context):
        try:
            host.register_contribution_point("test.midround", "v1")
        except BaseException as err:  # noqa: BLE001
            errors["point"] = err
        try:
            host.deactivate("fake.a")
        except BaseException as err:  # noqa: BLE001
            errors["deactivate"] = err

    host.activate_all([ContribPlugin("fake.witness", observe=reenter)])
    assert isinstance(errors.get("point"), HostAdmissionClosedError)
    assert isinstance(errors.get("deactivate"), HostAdmissionClosedError)
    assert "draining" in str(errors["point"])
    assert host.is_active("fake.a")
    assert host.contribution_points.point("test.midround") is None


def test_a_failed_round_never_leaves_the_host_draining():
    """The draining flag that sticks is the other half of the hole: a
    failed round must reopen admission (finally-cleanup), or the host is
    wedged for every later composition step."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    boom = RuntimeError("build refused")
    with pytest.raises(RuntimeError):
        host.activate_all([
            ContribPlugin("fake.ok", contributions=(contribution(POINT),)),
            ContribPlugin("fake.boom", build_raises=boom),
        ])
    assert host.state == "open"
    assert host.admission_open is True
    assert isinstance(host.contribution(POINT), AbsentContribution)
    # and the host still accepts the next round
    host.activate(ContribPlugin("fake.ok", contributions=(contribution(POINT),)))
    assert isinstance(host.contribution(POINT), ResolvedContribution)

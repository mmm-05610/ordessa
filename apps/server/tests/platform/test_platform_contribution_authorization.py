"""T012 family (b): contribution lookup is granted by `requires`, and the
new carrier may not bypass the guards that already hold for ports (C2).

`requires` is the access grant for ports today; the carrier must keep it
the access grant for contributions too. Each test pins one side of a
positive/counterexample pair: the declared consumer resolves, the
undeclared one gets a typed refusal naming consumer, owner and point —
never the value, and never an "absence" that could be confused with an
owner who never contributed.

The last group pins the third case the grant cannot answer: a consumer
granted on EVERY owner of a non-exclusive point. There the host refuses to
pick (T013 follow-up: the scoped path must be symmetric with the
argument-less one, which already answers an observable absence naming the
owner count).
"""
from __future__ import annotations

import pytest

from server_plugin_api import (
    AbsentContribution,
    ContributionAccessError,
    ContributionAmbiguousError,
    DependentActiveError,
    InvalidDeclarationError,
    PortConflictError,
)

from contribution_fakes import ContribPlugin, RecordingHandler, contribution, new_host

from ordessa_server.plugin_host import ResolvedContribution

POINT = "test.service"
MULTI = "test.multi"


def _compose_open_point(host, *, point=MULTI):
    """One non-exclusive point carrying two published owners, each with a
    payload that names its owner — so a chosen-by-order winner is visible
    in the assertion instead of being guessed by the reader."""
    handler = RecordingHandler()
    host.register_contribution_point(point, "v1", handler=handler, exclusive=False)
    host.activate_all([
        ContribPlugin("fake.p1", methods=("fake.p1.method",),
                      contributions=(contribution(point, payload={"owner": "fake.p1"}),)),
        ContribPlugin("fake.p2", methods=("fake.p2.method",),
                      contributions=(contribution(point, payload={"owner": "fake.p2"}),)),
    ])
    return host


def _compose_provider(host, *, handler=None, point=POINT):
    host.register_contribution_point(point, "v1", handler=handler or RecordingHandler())
    host.activate(ContribPlugin(
        "fake.provider", methods=("fake.provider.method",),
        ports={"fake.service": {"provider": "fake.provider"}},
        contributions=(contribution(point, payload={"grant": "by-requires"}),)))
    return host


def test_a_declared_dependent_resolves_the_owners_contribution():
    """Positive guard: the consumer that declared `requires` on the owner
    resolves the owner's contribution through the host, and saw the
    owner's port in its build context — the grant covers both surfaces."""
    host = _compose_provider(new_host())
    seen: dict[str, object] = {}
    consumer = ContribPlugin(
        "fake.child", requires=("fake.provider",), methods=("fake.child.method",),
        observe=lambda context: seen.setdefault("ports", dict(context.ports)))
    host.activate(consumer)
    assert seen["ports"]["fake.service"] == {"provider": "fake.provider"}
    view = host.contribution(POINT, consumer="fake.child")
    assert isinstance(view, ResolvedContribution)
    assert view.owner == "fake.provider"
    assert view.payload == {"grant": "by-requires"}


def test_an_undeclared_consumer_cannot_resolve_the_owners_contribution():
    """The counterexample pair: a plugin that never declared `requires` on
    the owner gets a typed refusal naming consumer, owner and point.
    Handing back the payload (the bypass) or answering AbsentContribution
    (indistinguishable from a never-contributed owner) both fail here;
    a genuinely empty point still answers observable absence."""
    host = _compose_provider(new_host())
    host.activate(ContribPlugin("fake.outsider", methods=("fake.outsider.method",)))
    with pytest.raises(ContributionAccessError) as refused:
        host.contribution(POINT, consumer="fake.outsider")
    assert refused.value.consumer == "fake.outsider"
    assert refused.value.owner == "fake.provider"
    assert refused.value.point_id == POINT
    # the declared consumers' paths still answer — the refusal was about
    # the grant, not a side effect of the failed lookup
    assert isinstance(host.contribution(POINT, consumer="fake.provider"),
                      ResolvedContribution)
    # and absence stays distinguishable from refusal: an empty point
    host.register_contribution_point("test.empty", "v1", handler=RecordingHandler())
    assert isinstance(host.contribution("test.empty", consumer="fake.outsider"),
                      AbsentContribution)


def test_the_carrier_does_not_widen_the_port_grant():
    """A plugin that declares no dependency sees no port of the provider —
    even when the provider also carries contributions. A carrier that
    smuggled contributions (or their payloads) into the build context
    would show the key here."""
    host = _compose_provider(new_host())
    outsider = ContribPlugin("fake.outsider2", methods=("fake.outsider2.method",))
    host.activate(outsider)
    assert "fake.service" not in outsider.seen_ports, (
        "the contribution carrier leaked a provider port into an undeclared context")


def test_port_conflicts_are_still_refused_when_contributions_are_in_flight():
    """The existing conflict guard survives the carrier: two providers of
    the same port name leave the consumer ambiguous — typed refusal, and
    the consumer's own contribution never reaches the point (the failed
    activation rolls its staging back)."""
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    host.activate_all([
        ContribPlugin("fake.p1", methods=("fake.p1.method",), ports={"fake.same": object()}),
        ContribPlugin("fake.p2", methods=("fake.p2.method",), ports={"fake.same": object()}),
    ])
    with pytest.raises(PortConflictError):
        host.activate(ContribPlugin(
            "fake.child", requires=("fake.p1", "fake.p2"),
            contributions=(contribution(POINT),)))
    assert isinstance(host.contribution(POINT), AbsentContribution), (
        "a refused activation left its contribution published")
    assert host.active_ids() == ("fake.p1", "fake.p2")


def test_unload_refuses_while_a_dependent_is_active_even_with_contributions():
    """The dependency guard keeps its teeth across the carrier: unloading
    the contribution owner under its dependent is still a typed refusal
    naming the dependent, the published view survives the refusal, and the
    clean reverse order retires the view honestly at the end."""
    host = _compose_provider(new_host())
    host.activate(ContribPlugin("fake.child", requires=("fake.provider",)))
    with pytest.raises(DependentActiveError):
        host.deactivate("fake.provider")
    assert isinstance(host.contribution(POINT), ResolvedContribution)
    host.deactivate("fake.child")
    host.deactivate("fake.provider")
    assert isinstance(host.contribution(POINT), AbsentContribution)


def test_an_inactive_consumer_is_a_typed_refusal_not_an_invented_value():
    """A consumer identity that is not active cannot be authorized: the
    host refuses by naming the consumer (an `InvalidDeclarationError`)
    rather than falling back to the unrestricted view or answering
    'absent' while the point is published."""
    host = _compose_provider(new_host())
    with pytest.raises(InvalidDeclarationError) as refused:
        host.contribution(POINT, consumer="fake.ghost")
    assert "fake.ghost" in str(refused.value)
    # the unrestricted host-side view is unchanged — the refusal leaked nothing
    assert isinstance(host.contribution(POINT), ResolvedContribution)


# -- consumer-scoped disambiguation (T013 follow-up) -------------------------------


def test_a_consumer_granted_on_every_owner_of_an_open_point_is_not_handed_one():
    """The ambiguity counterexample: a non-exclusive point carries two
    published owners and the consumer declared `requires` on both, so the
    grant cannot separate them and there is no rule that picks a winner —
    registration order is not one. The scoped path refuses with a named,
    typed `ContributionAmbiguousError` carrying consumer, point and every
    owner, symmetric in spirit with the argument-less path (which already
    answers an observable absence naming the owner count). A silent
    `authorized[0]` fails here; and because `contributions()` still shows
    both owners, the refusal is a direction rather than a dead end."""
    host = _compose_open_point(new_host())
    host.activate(ContribPlugin("fake.child", requires=("fake.p1", "fake.p2"),
                                methods=("fake.child.method",)))
    with pytest.raises(ContributionAmbiguousError) as refused:
        host.contribution(MULTI, consumer="fake.child")
    assert refused.value.consumer == "fake.child"
    assert refused.value.point_id == MULTI
    assert refused.value.owners == ("fake.p1", "fake.p2")
    # the refusal chose nobody, so it claimed no hold on either owner
    assert host.owner_busy("fake.p1") is False
    assert host.owner_busy("fake.p2") is False
    with pytest.raises(ContributionAmbiguousError):
        with host.use_contribution(MULTI, consumer="fake.child"):
            raise AssertionError("the hold body must not run")
    assert host.owner_busy("fake.p1") is False and host.owner_busy("fake.p2") is False
    # symmetric with the unscoped answer: no single view, stated as a fact
    absent = host.contribution(MULTI)
    assert isinstance(absent, AbsentContribution)
    assert "2 owners" in absent.reason and "views()" in absent.reason
    # informative, not a dead end: the multi-view answer carries both
    assert [(view.owner, view.payload) for view in host.contributions(MULTI)] == [
        ("fake.p1", {"owner": "fake.p1"}), ("fake.p2", {"owner": "fake.p2"})]


def test_one_published_owner_on_an_open_point_still_resolves_for_a_granted_consumer():
    """The case the guard must not touch: an open point with exactly one
    published owner is not ambiguous — the granted consumer gets that one
    `ResolvedContribution`, and the resolve-and-hold window works on it
    (busy for the owner inside, released after)."""
    host = new_host()
    host.register_contribution_point(MULTI, "v1", handler=RecordingHandler(), exclusive=False)
    host.activate(ContribPlugin("fake.p1", methods=("fake.p1.method",),
                                contributions=(contribution(MULTI, payload={"owner": "fake.p1"}),)))
    host.activate(ContribPlugin("fake.child", requires=("fake.p1",),
                                methods=("fake.child.method",)))
    view = host.contribution(MULTI, consumer="fake.child")
    assert isinstance(view, ResolvedContribution)
    assert (view.owner, view.payload, view.api_version) == (
        "fake.p1", {"owner": "fake.p1"}, "v1")
    with host.use_contribution(MULTI, consumer="fake.child") as held:
        assert held == view
        assert host.owner_busy("fake.p1") is True
    assert host.owner_busy("fake.p1") is False


def test_an_undeclared_consumer_of_a_multi_owner_point_is_still_a_grant_refusal():
    """Precedence stays where the grant put it: on the same two-owner point,
    a consumer that declared `requires` on neither owner (and one that
    declared it on exactly one) is refused by `ContributionAccessError`,
    never by the ambiguity guard. Turning "no grant" into "ambiguous" would
    answer an unauthorized lookup with a fact about the composition and
    leak the owner set the consumer may not address."""
    host = _compose_open_point(new_host())
    host.activate(ContribPlugin("fake.outsider", methods=("fake.outsider.method",)))
    host.activate(ContribPlugin("fake.half", requires=("fake.p1",),
                                methods=("fake.half.method",)))
    with pytest.raises(ContributionAccessError) as refused:
        host.contribution(MULTI, consumer="fake.outsider")
    assert (refused.value.consumer, refused.value.owner, refused.value.point_id) == (
        "fake.outsider", "fake.p1", MULTI)
    # granted on one of the two: the undeclared owner is the refusal's owner
    with pytest.raises(ContributionAccessError) as partial:
        host.contribution(MULTI, consumer="fake.half")
    assert (partial.value.consumer, partial.value.owner) == ("fake.half", "fake.p2")

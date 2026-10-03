"""T013's additive contract errors: each admission/busy refusal is typed,
carries its identifying facts, and joins the public surface without
renaming anything that predates it.

These are the refusal channels the Server host (`plugin_host`) raises; the
package stays zero-dependency — the classes are shape and message only.
"""
from __future__ import annotations

import server_plugin_api
from server_plugin_api import (
    ContributionAccessError,
    ContributionAmbiguousError,
    ContributionOwnerBusyError,
    ContributionPointHeldError,
    ContributionPointUnboundError,
    ContributionVersionRefusedError,
    HostAdmissionClosedError,
    ServerPluginError,
)

NEW_EXPORTS = [
    ContributionPointUnboundError,
    ContributionVersionRefusedError,
    ContributionPointHeldError,
    HostAdmissionClosedError,
    ContributionOwnerBusyError,
    ContributionAccessError,
    ContributionAmbiguousError,
]


def test_new_admission_errors_join_the_public_surface():
    for error in NEW_EXPORTS:
        assert error.__name__ in server_plugin_api.__all__, error
        assert getattr(server_plugin_api, error.__name__) is error
        assert issubclass(error, ServerPluginError)


def test_each_error_carries_its_identifying_facts_and_a_stable_code():
    unbound = ContributionPointUnboundError("p.act", "fake.owner")
    assert unbound.point_id == "p.act" and unbound.claimer == "fake.owner"
    assert unbound.code == "PLUGIN_CONTRIBUTION_POINT_UNBOUND"

    version = ContributionVersionRefusedError("p.act", "fake.owner", "v2", "v1")
    assert (version.declared, version.accepted) == ("v2", "v1")
    assert "v1" in str(version) and "v2" in str(version)

    held = ContributionPointHeldError("p.act", "fake.holder", "fake.claimer")
    assert (held.holder, held.claimer) == ("fake.holder", "fake.claimer")
    assert "retire" in str(held), "the refusal must state the two-step it expects"

    closed = HostAdmissionClosedError("plugin activation", "draining")
    assert closed.action == "plugin activation" and closed.state == "draining"
    assert "draining" in str(closed), "the refusal names the state"

    busy = ContributionOwnerBusyError("fake.owner", ("p.act", "p.other"))
    assert busy.owner == "fake.owner" and busy.points == ("p.act", "p.other")

    access = ContributionAccessError("fake.child", "fake.owner", "p.act")
    assert (access.consumer, access.owner, access.point_id) == (
        "fake.child", "fake.owner", "p.act")


def test_message_spelling_stays_machine_prefixable():
    """Every ServerPluginError renders `CODE: message` — a consumer that
    pattern-matches the wire-visible prefix keeps working for the new
    refusals without a special case."""
    instances = [
        ContributionPointUnboundError("p.act", "fake.owner"),
        ContributionVersionRefusedError("p.act", "fake.owner", "v2", "v1"),
        ContributionPointHeldError("p.act", "fake.holder", "fake.claimer"),
        HostAdmissionClosedError("plugin activation", "draining"),
        ContributionOwnerBusyError("fake.owner", ("p.act",)),
        ContributionAccessError("fake.child", "fake.owner", "p.act"),
        ContributionAmbiguousError("fake.child", "p.act", ("fake.p1", "fake.p2")),
    ]
    for instance in instances:
        text = str(instance)
        assert text.startswith(instance.code + ": "), text
        assert instance.message in text


def test_the_ambiguity_refusal_is_grant_shaped_and_names_every_owner():
    """`ContributionAmbiguousError` is the refusal a host raises when a
    granted consumer asks for ONE view of a point carrying several owners.
    Contract facts pinned here: a distinct code inside the
    `PLUGIN_CONTRIBUTION_*` family, the consumer/point/owners triple on the
    instance, every owner visible in the message, and a stated way out — so
    the refusal is never a dead end and never confusable with
    `ContributionAccessError`, which is about a missing grant."""
    refusal = ContributionAmbiguousError(
        "fake.child", "p.act", ("fake.p1", "fake.p2"))
    assert refusal.code == "PLUGIN_CONTRIBUTION_AMBIGUOUS"
    assert (refusal.consumer, refusal.point_id, refusal.owners) == (
        "fake.child", "p.act", ("fake.p1", "fake.p2"))
    text = str(refusal)
    for owner in ("fake.p1", "fake.p2"):
        assert owner in text, f"the refusal must name {owner}"
    assert "contributions(p.act)" in text, "the refusal states the multi-view way out"
    # distinct channel from the grant refusal: different code, different facts
    access = ContributionAccessError("fake.child", "fake.p1", "p.act")
    assert access.code != refusal.code
    assert not hasattr(refusal, "owner") and not hasattr(access, "owners")

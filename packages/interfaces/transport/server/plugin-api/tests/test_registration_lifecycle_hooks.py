"""The registration's lifecycle phases: `start_hooks` gains its mirror.

FR-006 removes the composition root's specialised stop, and the only way the
host can stay generic is a declared teardown phase on the registration. These
IDs pin the carrier half of that: the phase exists, it is empty by default (a
registration written before it keeps working unchanged), it takes exactly the
shape the start phase takes, and it was added LAST so the positional order
every pre-existing registration was built with still means the same thing.

Registered honestly as still-unproven here: the guard checks tuple-ness, not
callability — the same gap `start_hooks` has always had. A tuple of
non-callables is accepted at declaration and fails only when the host runs
the phase; closing that is a change to both fields, not to this one.
"""
from __future__ import annotations

import dataclasses

import pytest

from server_plugin_api import ServerPluginRegistration

FIELD_ORDER = [f.name for f in dataclasses.fields(ServerPluginRegistration)]


def test_stop_hooks_default_to_empty_for_a_registration_that_declares_none():
    registration = ServerPluginRegistration()
    assert registration.stop_hooks == ()
    assert registration.stop_hooks == registration.start_hooks


def test_stop_hooks_are_a_tuple_of_callables_like_start_hooks():
    def hook() -> None:
        return None

    registration = ServerPluginRegistration(start_hooks=(hook,), stop_hooks=(hook,))
    assert registration.stop_hooks == (hook,)
    # Symmetry with the start phase is the point of the field; if it were
    # declared as something else (a single callable, a list) this assertion is
    # what would go red first.
    assert type(registration.stop_hooks) is type(registration.start_hooks)


@pytest.mark.parametrize("bad", [None, "hook", [lambda: None], {"hook": lambda: None}])
def test_a_non_tuple_stop_phase_is_refused_at_declaration(bad):
    """The same guard `start_hooks` carries, extended — not a new special rule.

    A list would let an author mutate the phase after the host read it; a bare
    object would reach the shutdown as a `TypeError` at the worst possible
    moment. Either passes only if the shared guard is weakened.
    """
    with pytest.raises(ValueError):
        ServerPluginRegistration(stop_hooks=bad)


def test_the_legacy_positional_registration_still_binds_disposal():
    """Positional compatibility is a fact about the NEW field, not the old ones.

    `(methods, stream_routes, http_routes, provided_ports, start_hooks,
    disposal)` stays the order and `stop_hooks` is the seventh. Insert the new
    field before `disposal` and this very call hands its disposal marker to
    `stop_hooks`, where the tuple guard refuses it — the counterexample is
    live, not argued.
    """
    marker = lambda: None  # noqa: E731 - the marker identity is the assertion
    legacy = ServerPluginRegistration((), (), (), {}, (), marker)
    assert legacy.disposal is marker
    assert legacy.stop_hooks == ()
    assert FIELD_ORDER.index("stop_hooks") > FIELD_ORDER.index("disposal")

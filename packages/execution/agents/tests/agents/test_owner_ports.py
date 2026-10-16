"""The optional owner bundle cannot be mixed with mutable per-call ports."""

from __future__ import annotations

import pytest

from ordessa_units.public import unit_services


def test_owner_bundle_and_individual_ports_are_mutually_exclusive():
    with pytest.raises(ValueError, match="cannot be combined"):
        unit_services(object(), owner_ports=object(), invocation_issuer=object())


def test_owner_bundle_is_typed_before_environment_access():
    with pytest.raises(TypeError, match="AgentOwnerPorts"):
        unit_services(object(), owner_ports=object())

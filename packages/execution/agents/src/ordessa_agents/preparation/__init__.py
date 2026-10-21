"""Preparation: the single place a launch is assembled.

One Agent is one Harness plus one fixed Profile revision. Preparation turns
those two into a **finished** launch — the resolved argv, the isolated
environment, the session bootstrap and the prepared configuration resources —
so that the launcher (the channel factory) consumes a resolved
:class:`~ordessa_agents.harness.transport.LaunchSpec` and never
re-assembles argv or environment per brand.

Authority boundary
------------------
Preparation produces *plans and resource references*, never effects. It does not
start a process, does not write a record and grants nothing: the caller must
still hold a verified start authority before the launcher opens. A prepared
object is therefore an input to an effect, never a permission for one.

Layering
--------
``units`` depends on this; ``agents`` never depends on ``units``. This package
depends only on the transport's :class:`LaunchSpec` and the standard library.
"""
from .contracts import (
    ConfigurationResources,
    HarnessPreparation,
    PreparedAgent,
    PreparedHarness,
    PreparationRefused,
    SessionBootstrap,
)

__all__ = [
    "ConfigurationResources",
    "HarnessPreparation",
    "PreparedAgent",
    "PreparedHarness",
    "PreparationRefused",
    "SessionBootstrap",
]

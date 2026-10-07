"""Observation seam for native sandbox effects — UNBOUND.

This module is the ONLY place the Sandbox backend talks about observing what
a native sandbox actually did, and it is deliberately a *consumer-side*
Protocol, not a copied type. The closed Harness configuration-intent
vocabulary (`SetField`/`ResetField`/`InvokeAction`/`MountContent`,
`TargetHandle`, `FieldClaim`, `ConfigurationAdapter`) is Harness C3's, and
`specs/011-q5-safety/api-requests.md` G3 records that it exists only on the
unpublished C0 branch commit `b5dcf84703...` — NOT a released checkpoint. So
this package does NOT copy those types and does NOT invent a second intent
vocabulary pretending to be them.

What lives here instead is a minimal read-only Protocol describing the exact
shape this package will bind to when `harness-api` publishes at a fixed
publication SHA (task T05). Both Protocols expose observation only — there is
no `apply`/`write`/`configure` method anywhere in them — which is what lets
`test_no_fake_apply.py` assert that this package never pretends to apply
configuration itself. Until the checkpoint lands, the verifier runs with
`target=None`/`probe=None` and every effect it cannot observe stays `unknown`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Protocol, runtime_checkable

from ordessa_sandbox_api import NativeSandboxIntent, SandboxVerificationOutcome, ToolCategory


@runtime_checkable
class ConfigurationTarget(Protocol):
    """UNBOUND. Read-only presence probe for a target harness configuration.

    The released `harness-api` `ConfigurationAdapter` will satisfy this shape
    at a fixed publication SHA; nothing here assumes any method beyond
    ``is_available()``. A ``False`` answer is a *known* absence (an absent
    adapter), not an unknown effect.
    """

    def is_available(self) -> bool:
        ...


@runtime_checkable
class EffectProbe(Protocol):
    """UNBOUND. Read-only observation of a native sandbox's actual effect.

    T05's controlled probe will implement ``observe_effect``; the backend only
    consumes the returned outcome, it never mutates configuration through this
    seam (there is no mutating method to call). Absence of a probe ⇒ the
    verifier reports ``unknown`` rather than assuming protection.
    """

    def observe_effect(self, target_handle: str,
                       intent: NativeSandboxIntent) -> "EffectObservation":
        ...


@dataclass(frozen=True)
class EffectObservation:
    """One read-only observation result folded into the verdict."""

    outcome: SandboxVerificationOutcome
    covered_categories: FrozenSet[ToolCategory] = frozenset()
    reason: str = ""

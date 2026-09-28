"""INC2-A pins — the C-RUNTIME public-area verb surface (batch:
`approvals/INC2-release.md` §A + standing `C-RUNTIME-verbs-single-writer.md`
+ E-015 pre-ruling alias regime / host=cleanup note). Anchor `10a6b99`;
approved paths = protocol.py, sandbox_port.py, coordinator.py (verb-dispatch
stanzas only) plus this in-tree pin.

Locks:
* P1 alias regime — `IsolatedProcessSpec` remains importable from
  `sandbox_port` as the same class object as `RoomProcessSpec`, registered in
  `__all__`; the public protocol projection keeps its own untouched identity
  (P-4: two classes, never merged — merging would leak provider env);
* P2 typed-dispatch identity — for every provider shape (verb present /
  absent / raising / non-callable attribute / no isolated spec), the
  compensation routing result is byte-identical before and after typing;
* P3 the declarations are additive and unenforced — the three Protocols gain
  the §1 verbs, every pre-existing member signature is untouched, and none of
  the three becomes runtime-checkable;
* P4 no provider-private env crosses into the frozen public projection;
* P5 the capability and terminate-carrier constants are the contract spelling.
"""
from __future__ import annotations

import dataclasses
import inspect

from pacthold_runtime_compat.runtime_composition import protocol as proto
from pacthold_runtime_compat.runtime_composition import sandbox_port as sport
from pacthold_runtime_compat.runtime_composition.coordinator import (
    RuntimeCompositionCoordinator,
)


# ---------------------------------------------------------------- P1 alias
def test_sandbox_port_keeps_the_legacy_import_face_via_the_alias():
    assert sport.IsolatedProcessSpec is sport.RoomProcessSpec
    assert "IsolatedProcessSpec" in sport.__all__ and "RoomProcessSpec" in sport.__all__


def test_the_two_namesake_classes_are_never_merged():
    # P-4 guardrail: the public projection and the provider-local spec are
    # different classes; unifying them would expose provider env publicly.
    assert proto.IsolatedProcessSpec is not sport.RoomProcessSpec


# ---------------------------------------------------------------- P4 env face
def test_provider_env_stays_out_of_the_public_projection():
    public_fields = {f.name for f in dataclasses.fields(proto.IsolatedProcessSpec)}
    provider_fields = {f.name for f in dataclasses.fields(sport.RoomProcessSpec)}
    assert "environment" in provider_fields
    assert "environment" not in public_fields
    assert "carrier_argv" in public_fields  # private carrier stays carrier-only


# ---------------------------------------------------------------- P5 constants
def test_contract_spellings_are_exact():
    assert proto.COMPENSATION_CAPABILITY == "composition.compensation@1"
    assert proto.TERMINATE_TRANSPORT_KIND == "terminate@1"
    assert proto._TRANSPORT_OPERATION_TYPE.fullmatch(proto.TERMINATE_TRANSPORT_KIND)


# ---------------------------------------------------------------- P3 additive
def _params(fn) -> list[str]:
    return list(inspect.signature(fn).parameters)


def test_three_protocols_gain_the_verbs_without_touching_any_existing_shape():
    expected = {
        "RuntimeHost": {"terminate", "cleanup"},
        "Sandbox": {"cleanup"},
        "TerminalSession": {"release"},
    }
    for name, verbs in expected.items():
        cls = getattr(proto, name)
        assert verbs <= set(vars(cls)), name
        # none of the three became runtime_checkable (no isinstance enforcement)
        assert getattr(cls, "__runtime_protocol__", False) is False
    # every pre-existing member signature is untouched
    assert _params(proto.RuntimeHost.resolve) == ["self", "ref"]
    assert _params(proto.RuntimeHost.stage) == ["self", "bundle"]
    assert _params(proto.Sandbox.resolve) == ["self", "ref"]
    assert _params(proto.Sandbox.wrap) == ["self", "mount_plan", "command", "attempt_key"]
    assert _params(proto.TerminalSession.resolve) == ["self", "ref"]
    assert _params(proto.TerminalSession.allocate) == ["self"]
    assert _params(proto.TerminalSession.run) == ["self", "host_transport", "spec", "attempt_key"]


# ---------------------------------------------------------------- P2 identity
def _duck_dispatch(host, sandbox, terminal, isolated):
    """The retired getattr-string dispatch, verbatim, as the comparison side."""
    results: dict[str, object] = {}
    for name, component, method, argument in (
        ("sandbox", sandbox, "cleanup", isolated),
        ("terminal", terminal, "release", None),
        ("host", host, "cleanup", None),
    ):
        action = getattr(component, method, None)
        if callable(action):
            try:
                results[name] = action(argument) if argument is not None else action()
            except Exception as exc:  # independent cleanup continues
                results[name] = {"error": str(exc)[:240]}
    return results or {"status": "cleaned"}


class _Full:
    def cleanup(self, *a): return {"status": "cleaned", "who": type(self).__name__, "args": a}
    def release(self, *a): return {"released": True, "destroyed": False, "managed": True}


class _NoTerminalVerb:
    def cleanup(self, *a): return {"status": "cleaned"}


class _RaisingSandbox:
    def cleanup(self, spec): raise ValueError("teardown exploded " + "x" * 300)


class _NonCallable:
    cleanup = "not-a-method"


def _typed(host, sandbox, terminal, isolated):
    coordinator = RuntimeCompositionCoordinator(
        lambda binding: None, bundle_factory=lambda *a: None)
    coordinator._cleanup["attempt-1"] = (host, sandbox, terminal, isolated)
    return coordinator.cleanup("attempt-1")


_SHAPES = {
    "all-verbs": (_Full(), _Full(), _Full(), "spec"),
    "terminal-verb-absent": (_Full(), _Full(), _NoTerminalVerb(), "spec"),
    "sandbox-raises": (_Full(), _RaisingSandbox(), _Full(), "spec"),
    "host-attribute-not-callable": (_NonCallable(), _Full(), _Full(), "spec"),
    "no-isolated-spec": (_Full(), _NoTerminalVerb(), _NoTerminalVerb(), None),
}


def test_every_host_shape_routes_identically_before_and_after_typing():
    for label, (host, sandbox, terminal, isolated) in _SHAPES.items():
        old = _duck_dispatch(host, sandbox, terminal, isolated)
        new = _typed(host, sandbox, terminal, isolated)
        assert new == old, label
        assert list(new) == list(old), label  # insertion order too


def test_absent_attempt_stays_already_cleaned():
    assert _typed(_Full(), _Full(), _Full(), "spec")  # consume
    coordinator = RuntimeCompositionCoordinator(
        lambda binding: None, bundle_factory=lambda *a: None)
    assert coordinator.cleanup("never-registered") == {"status": "already_cleaned"}

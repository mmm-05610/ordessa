"""INC2-A pins — the C-RUNTIME public-area verb surface (batch:
`approvals/INC2-release.md` §A + standing `C-RUNTIME-verbs-single-writer.md`
+ E-015 pre-ruling alias regime / host=cleanup note). Anchor `10a6b99`;
approved paths = protocol.py, sandbox_port.py, coordinator.py (verb-dispatch
stanzas only) plus this in-tree pin.

Locks:
* P1 retirement — the v1 surface no longer carries the retired TerminalSession
  or sandbox_port residue;
* P2 typed-dispatch identity — for every provider shape (verb present /
  absent / raising / non-callable attribute / no isolated spec), the v1
  compensation routing result (sandbox cleanup, host cleanup, process release)
  is byte-identical before and after typing;
* P3 the declarations are additive and unenforced — the v1 RuntimeHost/Sandbox
  Protocols keep the §1 verbs, every pre-existing member signature is
  untouched, and neither becomes runtime-checkable;
* P4 no provider-private launch fact (env, cwd) crosses into the frozen public
  projection — the public field set is the exact pre-A3 whitelist and the
  projection cannot even accept those facts;
* P5 the capability and terminate-carrier constants are the contract spelling.
"""
from __future__ import annotations

import dataclasses
import inspect

import pytest

from ordessa_environments.definitions.runtime_resources import IsolatedProcessSpec
from ordessa_environments.definitions.runtime_ports import COMPENSATION_CAPABILITY, RuntimeHost, Sandbox, TERMINATE_TRANSPORT_KIND
from ordessa_server_plugin_api.runtime_carrier import _TRANSPORT_OPERATION_TYPE
from ordessa_units.assembly.runtime.coordinator import RuntimeCompositionCoordinator


# ---------------------------------------------------------------- P1 retirement
def test_retired_composition_surface_is_gone():
    import ordessa_environments.definitions as definitions
    import ordessa_environments.definitions.runtime_ports as ports

    assert not hasattr(definitions, "sandbox_port")
    assert not hasattr(ports, "TerminalSession")


# ---------------------------------------------------------------- P4 env face
def test_provider_env_stays_out_of_the_public_projection():
    public_fields = {f.name for f in dataclasses.fields(IsolatedProcessSpec)}
    # The public projection is exactly the pre-A3 field set. A provider launch
    # fact (cwd/env) added here would be the leak this pin exists to catch, so
    # the whitelist — not a single name check — is the lock.
    assert public_fields == {
        "spawn_token", "attempt_key", "spec_digest", "io_mode",
        "local_argv", "provider_transport", "carrier_argv",
    }
    assert "carrier_argv" in public_fields  # private carrier stays carrier-only

    # ...and the projection cannot even accept provider-private launch facts:
    # there is no such constructor parameter, so the fact cannot cross.
    spec = IsolatedProcessSpec("token", "attempt", "sha256:spec", local_argv=("/bin/echo",))
    for private in ("env", "environment", "cwd"):
        assert not hasattr(spec, private), private
        with pytest.raises(TypeError):
            IsolatedProcessSpec("token", "attempt", "sha256:spec",
                                local_argv=("/bin/echo",), **{private: "leak"})


# ---------------------------------------------------------------- P5 constants
def test_contract_spellings_are_exact():
    assert COMPENSATION_CAPABILITY == "composition.compensation@1"
    assert TERMINATE_TRANSPORT_KIND == "terminate@1"
    assert _TRANSPORT_OPERATION_TYPE.fullmatch(TERMINATE_TRANSPORT_KIND)


# ---------------------------------------------------------------- P3 additive
def _params(fn) -> list[str]:
    return list(inspect.signature(fn).parameters)


def test_three_protocols_gain_the_verbs_without_touching_any_existing_shape():
    expected = {
        "RuntimeHost": {"terminate", "cleanup"},
        "Sandbox": {"cleanup"},
    }
    for name, verbs in expected.items():
        cls = {"RuntimeHost": RuntimeHost, "Sandbox": Sandbox}[name]
        assert verbs <= set(vars(cls)), name
        # neither became runtime_checkable (no isinstance enforcement)
        assert getattr(cls, "__runtime_protocol__", False) is False
    # every pre-existing member signature is untouched, and the v1 launch seam
    # keeps its exact shape.
    assert _params(RuntimeHost.resolve) == ["self", "ref"]
    assert _params(RuntimeHost.stage) == ["self", "bundle"]
    assert _params(Sandbox.resolve) == ["self", "ref"]
    assert _params(Sandbox.wrap) == ["self", "mount_plan", "command", "attempt_key"]
    assert _params(Sandbox.launch) == ["self", "spec", "attempt_key"]


# ---------------------------------------------------------------- P2 identity
def _duck_dispatch(host, sandbox, handle, isolated, execution_id):
    """The retired getattr-string dispatch, verbatim, as the comparison side."""
    results: dict[str, object] = {}
    for name, component, method, argument in (
        ("sandbox", sandbox, "cleanup", isolated),
        ("host", host, "cleanup", execution_id),
        ("process", handle, "release", None),
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


class _NoCleanup:
    def release(self, *a): return {"released": True, "destroyed": False, "managed": True}


class _NoRelease:
    def cleanup(self, *a): return {"status": "cleaned"}


class _RaisingSandbox:
    def cleanup(self, spec): raise ValueError("teardown exploded " + "x" * 300)


class _NonCallable:
    cleanup = "not-a-method"


def _typed(host, sandbox, handle, isolated, execution_id):
    coordinator = RuntimeCompositionCoordinator(
        lambda binding: None, bundle_factory=lambda *a: None)
    coordinator._cleanup["attempt-1"] = (host, sandbox, isolated, execution_id, handle)
    return coordinator.cleanup("attempt-1")


_SHAPES = {
    "all-verbs": (_Full(), _Full(), _Full(), "spec", "execution-1"),
    "host-verb-absent": (_NoCleanup(), _Full(), _Full(), "spec", "execution-1"),
    "process-release-absent": (_Full(), _Full(), _NoRelease(), "spec", "execution-1"),
    "sandbox-raises": (_Full(), _RaisingSandbox(), _Full(), "spec", "execution-1"),
    "host-attribute-not-callable": (_NonCallable(), _Full(), _Full(), "spec", "execution-1"),
    "no-isolated-spec": (_Full(), _Full(), _Full(), None, "execution-1"),
}


def test_every_host_shape_routes_identically_before_and_after_typing():
    for label, (host, sandbox, handle, isolated, execution_id) in _SHAPES.items():
        old = _duck_dispatch(host, sandbox, handle, isolated, execution_id)
        new = _typed(host, sandbox, handle, isolated, execution_id)
        assert new == old, label
        assert list(new) == list(old), label  # insertion order too


def test_absent_attempt_stays_already_cleaned():
    assert _typed(_Full(), _Full(), _Full(), "spec", "execution-1")  # consume
    coordinator = RuntimeCompositionCoordinator(
        lambda binding: None, bundle_factory=lambda *a: None)
    assert coordinator.cleanup("never-registered") == {"status": "already_cleaned"}

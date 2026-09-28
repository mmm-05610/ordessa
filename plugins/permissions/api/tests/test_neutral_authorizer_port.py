"""T017 red/green: the neutral public port contract for `permissions.authorizer@1`.

C0's integration review (specs/011-c0-foundation-harness/api-requests.md,
commits 4396338d79 / 0d93b1aee8) demands that this contract live in the API
package so consumers (Harness, Chat, Desktop-facing adapters) neither import
`ordessa_permissions_backend` internals nor guess the authorizer's signature.
Every test here compares the published protocol against the real backend
class - by `inspect.signature` on the installed class and by regex over the
backend SOURCE TEXT - so "you do not have to guess" is a checked property,
not a promise.

The backend is importable here (installed editable in the lane venv); the
package `src/` itself never imports it (guarded below and by
test_permissions_api_dependency_direction.py).
"""
from __future__ import annotations

import importlib
import inspect
import pathlib
import re
import subprocess
import sys
import typing
from typing import Any

import pytest

API_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_SRC = API_ROOT.parent / "backend" / "src" / "ordessa_permissions_backend"
PORT_METHODS = frozenset({"evaluate", "decide", "reconcile", "busy"})


def _ports():
    return importlib.import_module("ordessa_permissions_api.ports")


def _params(fn) -> list[tuple[str, inspect._ParameterKind, Any]]:
    return [(p.name, p.kind, p.default)
            for p in inspect.signature(fn).parameters.values() if p.name != "self"]


# --- the published surface --------------------------------------------------

def test_the_port_token_and_version_are_published_from_the_api_package() -> None:
    ports = _ports()
    assert ports.PERMISSIONS_AUTHORIZER_PORT == "permissions.authorizer@1"
    assert ports.PERMISSIONS_AUTHORIZER_PORT_VERSION == 1


def test_the_package_re_exports_the_port_contract() -> None:
    api = importlib.import_module("ordessa_permissions_api")
    assert "PERMISSIONS_AUTHORIZER_PORT" in api.__all__
    assert "PermissionsAuthorizerPort" in api.__all__
    for name in ("PERMISSIONS_AUTHORIZER_PORT", "PERMISSIONS_AUTHORIZER_PORT_VERSION",
                 "PermissionsAuthorizerPort"):
        assert hasattr(api, name), name


def test_the_port_token_equals_the_backend_provided_port_literal() -> None:
    # Drift guard read from SOURCE TEXT (no backend import): the backend's
    # `AUTHORIZER_PORT = "..."` registration literal and the published port
    # token are the same string or this lane refuses to converge.
    text = (BACKEND_SRC / "plugin.py").read_text(encoding="utf-8")
    match = re.search(r'^AUTHORIZER_PORT\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None, "backend plugin no longer defines AUTHORIZER_PORT"
    ports = _ports()
    assert ports.PERMISSIONS_AUTHORIZER_PORT == match.group(1)


# --- anti-"guess its signature": structural conformance ----------------------

def test_every_port_method_matches_the_backend_authorizer_signature_exactly() -> None:
    import ordessa_permissions_backend

    ports = _ports()
    authorizer = ordessa_permissions_backend.Authorizer
    for name in sorted(PORT_METHODS):
        port_fn = getattr(ports.PermissionsAuthorizerPort, name)
        backend_fn = getattr(authorizer, name)
        assert _params(port_fn) == _params(backend_fn), (
            f"{name}: port {inspect.signature(port_fn)} vs backend"
            f" {inspect.signature(backend_fn)}")


def test_evaluate_carries_the_exact_c1_input_surface_in_order() -> None:
    ports = _ports()
    params = inspect.signature(ports.PermissionsAuthorizerPort.evaluate).parameters
    names = [p.name for p in params.values() if p.name != "self"]
    assert names == ["principal", "session_ref", "execution_ref", "native_generation",
                     "tool_identity", "target_facts", "argument_digest", "ceiling_revision",
                     "policy_revision", "native_request_id"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values()
               if p.name != "self"), "evaluate inputs are named-only, like the backend"


def test_the_port_method_set_is_exactly_the_public_authorizer_surface() -> None:
    ports = _ports()
    members = {name for name, value in
               inspect.getmembers(ports.PermissionsAuthorizerPort, predicate=inspect.isfunction)
               if not name.startswith("_")}
    assert members == PORT_METHODS


def test_c1_query_is_answered_by_reconcile_and_the_backend_gains_no_second_name() -> None:
    # §C1 names the read surface "query/reconcile" as ONE operation; the real
    # backend answers it with `reconcile` (the plugin's query wire handler
    # calls authorizer.reconcile). The port must not invent a `query` method
    # the implementation does not have - that would be guessing a signature.
    text = (BACKEND_SRC / "authorizer.py").read_text(encoding="utf-8")
    public_defs = set(re.findall(r"^    def (?!_)(\w+)", text, re.MULTILINE))
    assert {"evaluate", "decide", "reconcile", "busy"} <= public_defs
    assert "query" not in public_defs
    plugin_text = (BACKEND_SRC / "plugin.py").read_text(encoding="utf-8")
    assert re.search(r"authorizer\.reconcile\(", plugin_text), (
        "the query wire no longer goes through reconcile")
    ports = _ports()
    assert _params(ports.PermissionsAuthorizerPort.reconcile) == [
        ("approval_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("native_request_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty)]


# --- contract discipline ------------------------------------------------------

def test_the_port_is_deliberately_not_runtime_checkable() -> None:
    ports = _ports()
    with pytest.raises(TypeError):
        isinstance(object(), ports.PermissionsAuthorizerPort)


def test_the_port_docstring_carries_the_authority_rules() -> None:
    doc = inspect.getdoc(_ports().PermissionsAuthorizerPort) or ""
    for phrase in ("not runtime-checkable", "presence is not readiness", "refus",
                   "busy", "deactivation"):
        assert phrase in doc, phrase


def test_the_port_results_are_the_published_api_unions() -> None:
    ports = _ports()
    cls = ports.PermissionsAuthorizerPort
    from ordessa_permissions_api import (AllowedOnce, DecideResult, Denied,
                                         PendingApproval, QueryOutcome)
    assert typing.get_type_hints(cls.evaluate)["return"] == (
        Denied | AllowedOnce | PendingApproval)
    assert typing.get_type_hints(cls.decide)["return"] == DecideResult
    assert typing.get_type_hints(cls.reconcile)["return"] == QueryOutcome
    assert typing.get_type_hints(cls.busy)["return"] is int


# --- dependency direction ------------------------------------------------------

_BLOCKED = ("ordessa_permissions_backend", "server_plugin_api", "pacthold",
            "ordessa_server", "ordessa_harness")


def test_the_port_contract_imports_with_only_the_standard_library_available() -> None:
    # The whole point of publishing the contract HERE is that a consumer needs
    # nothing but this package. Probe honestly: block the backend and the
    # platform API from being imported at all, then import and use the port.
    script = f"""
import sys
BLOCKED = {set(_BLOCKED)!r}
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("probe-blocked: " + name)
        return None
sys.meta_path.insert(0, _Block())
try:
    import ordessa_permissions_backend  # noqa
    raise SystemExit("blocker did not block the backend")
except ImportError:
    pass
import ordessa_permissions_api as api
from ordessa_permissions_api import ports
assert api.PERMISSIONS_AUTHORIZER_PORT == ports.PERMISSIONS_AUTHORIZER_PORT
assert callable(ports.PermissionsAuthorizerPort.evaluate)
assert callable(ports.PermissionsAuthorizerPort.decide)
assert callable(ports.PermissionsAuthorizerPort.reconcile)
assert callable(ports.PermissionsAuthorizerPort.busy)
print("PORTS_STDLIB_ONLY_OK")
"""
    probe = subprocess.run([sys.executable, "-c", script], capture_output=True,
                           text=True, timeout=120)
    assert probe.returncode == 0, probe.stderr
    assert "PORTS_STDLIB_ONLY_OK" in probe.stdout

"""Boundary guards for the new T013 files (dispatch 需求3/反例).

native_binding.py is the Q4-domain <-> harness-api conversion point and
must itself obey the import boundaries it converts across:

* it may import ``ordessa_harness_api`` (the published contract) and the
  MCP domain — never ``ordessa_harness`` (the harness implementation),
  never ``ordessa_server``/host internals, never ``adapters`` (outside the
  installed backend package);
* it stays pure: no filesystem / process / network / HOME primitives — the
  brand adapter surface assess/compile/verify must plan from injected
  DTOs alone (the T04 purity gate extended to the new module);
* the whole assess->compile->verify chain runs under ``os.open``,
  ``socket.socket`` and ``subprocess.Popen`` seals (a secretly-reading
  binding dies here, cf. tests/adapters/test_purity.py).
"""
import ast
import os
import pathlib
import socket
import subprocess

import pytest
from wiring_helpers import api_context, claude_planned, codex_planned, environment_target

from backend import native_binding as nb

BINDING = pathlib.Path(nb.__file__)
# adapters/* are separate top-level packages of the same plugin ROOT (the
# package-root conftest puts the plugin root on sys.path; the installed
# distribution ships ``backend*`` only, so the backend package may import
# them ONLY through the composition seam, never directly — and the
# composition seam test below runs them in-process as the same root).
ADAPTER_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ADAPTER_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ADAPTER_ROOT))
ADAPTER_FILES = ["adapters/codex.py", "adapters/claude.py"]

FORBIDDEN_IMPORT_ROOTS = {
    "ordessa_harness",  # NOT ordessa_harness_api (the published contract)
    "ordessa_server", "ordessa_server_product", "ordessa_server_compat",
    "pacthold", "pacthold_runtime_compat", "adapters", "server_plugin_api",
    "os", "pathlib", "socket", "subprocess", "tempfile", "io", "shutil",
    "fcntl", "asyncio", "threading", "multiprocessing", "signal",
}
FORBIDDEN_ATTRS = {"environ", "getenv", "expanduser", "Popen", "HomeDirectory",
                   "HOME"}
FORBIDDEN_CALLS = {"open", "exec", "eval", "spawn", "system"}


def _bad_module(module: str) -> bool:
    if module == "ordessa_harness_api" or module.startswith("ordessa_harness_api."):
        return False
    head = module.split(".")[0]
    return head in FORBIDDEN_IMPORT_ROOTS


def _imports_and_uses(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    bad_imports, bad_attrs, bad_calls = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _bad_module(alias.name):
                    bad_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # relative imports (level>0) stay inside the scanned package
            if node.level:
                continue
            if node.module and _bad_module(node.module):
                bad_imports.append(node.module)
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS:
                bad_attrs.append(node.attr)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                bad_calls.append(fn.id)
    return bad_imports, bad_attrs, bad_calls


def test_native_binding_import_boundary():
    bad_imports, bad_attrs, bad_calls = _imports_and_uses(BINDING)
    assert not bad_imports, bad_imports
    assert not bad_attrs, bad_attrs
    assert not bad_calls, bad_calls


@pytest.mark.parametrize("rel", ADAPTER_FILES)
def test_brand_adapter_files_stay_host_free(rel):
    # the factories import backend.native_binding only at call time and the
    # T04 pure surface: no host/harness implementation anywhere in the file
    bad_imports, bad_attrs, bad_calls = _imports_and_uses(ADAPTER_ROOT / rel)
    assert not bad_imports, (rel, bad_imports)
    assert not bad_attrs and not bad_calls


def test_full_chain_runs_under_primitive_seals(monkeypatch):
    """assess->compile->verify through the real adapter objects with
    filesystem/socket/spawn primitives sealed (no fake green: every stage
    returns a real API object under the seal)."""
    from adapters import claude as claude_mod, codex as codex_mod
    from backend.native_intents import NativeObservation, ObservedServer
    from ordessa_harness_api import Match

    class Blocked(RuntimeError):
        pass

    def _blocked(*args, **kwargs):
        raise Blocked("native lane must not touch the outside world")

    monkeypatch.setattr(os, "open", _blocked)
    if hasattr(os, "openat"):
        monkeypatch.setattr(os, "openat", _blocked)
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)

    def load_observation():
        return NativeObservation(
            observer="sealed-fake-c3", session_ref="session-a",
            runtime_generation=3,
            servers=(ObservedServer(server_name="demo", transport="stdio",
                                    load_state="runtime-loaded"),))

    adapter = claude_mod.configuration_adapter()
    context = api_context(claude_mod.CLAUDE)
    assert adapter.assess(context, None).status == "unknown"
    planned = claude_planned()
    outcome = adapter.compile(context, {}, nb.facet_payload_of(planned))
    assert isinstance(outcome, nb.IntentSet) and len(outcome.intents) == 1
    observed = nb.observation_payload_of(load_observation(),
                                         evidence_ref="ev:sealed-run")
    verdict = adapter.verify(context, observed)
    assert isinstance(verdict, Match)
    # codex brand too, end to end under the seal (session-override route)
    codex = codex_mod.configuration_adapter()
    codex_ctx = api_context(codex_mod.CODEX, scope="session")
    codex_payload = nb.facet_payload_of(codex_planned())
    assert codex.assess(codex_ctx, codex_payload).status == "unknown"
    assert isinstance(codex.compile(codex_ctx, {}, codex_payload), nb.IntentSet)
    assert isinstance(codex.verify(codex_ctx, observed), Match)


def test_no_home_path_material_crosses_the_boundary():
    """targetPath never crosses: the facet payload and every derived API
    intent are free of HOME/target-path strings (the native file identity
    belongs to the harness runtime — contracts §3)."""
    from adapters import claude as claude_mod
    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    context = api_context(claude_mod.CLAUDE)
    outcome = claude_mod.configuration_adapter().compile(context, {}, payload)
    blob = repr(payload) + repr(outcome)
    for forbidden in ("/runtime/home", "/home/", ".claude.json", "targetPath"):
        assert forbidden not in blob, forbidden


def test_environment_target_shape_is_a_real_api_descriptor():
    env = environment_target("claude-code", "instance", ("demo.TOKEN",))
    assert env.kind == "environment" and env.codec == "environment"

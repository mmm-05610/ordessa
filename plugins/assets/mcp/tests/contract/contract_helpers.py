"""Shared helpers for tests/contract: TS wire-surface parsing + a real-host stack.

Two things live here, both deliberately self-contained (the known trap in this
tree is importing a SIBLING test directory's ``conftest`` — modules collide by
basename — so this file is the only import surface and it is uniquely named):

1. ``wire.ts`` / ``dto.ts`` text parsers ("AST-lite": balanced-scope scanning,
   no node, no eval). They read the frontend's declared truth — the
   ``MCP_WIRE_METHODS`` binding table, the per-method request bodies the fetch
   client actually sends, and the response DTO field sets — so the contract
   guard compares SOURCE, not someone's transcription of it.
2. A real composition stack (``ServerPluginHost`` + ``WireService.dispatch``,
   the tests/service precedent) whose default probe runner is the REAL
   ``backend.probe.probe_definition`` — the mcp.probe wire combo cells drive
   the actual transport against loopback fakes. Tests here that need sockets
   or Popen must request ``contract_primitives`` (the tests/probe precedent);
   every other test stays under the package-wide side-effect lockdown.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

import pytest

from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost
from ordessa_server.wire.handlers import WireService
from server_plugin_api import WireError

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parents[1]  # plugins/assets/mcp
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from backend.plugin import McpAssetServerPlugin  # noqa: E402

WIRE_TS = PACKAGE_ROOT / "frontend" / "src" / "wire.ts"
DTO_TS = PACKAGE_ROOT / "frontend" / "src" / "dto.ts"
FAKE_STDIO_SERVER = HERE / "contract_fake_stdio_server.py"

# Captured before any monkeypatch can be in effect (tests/probe precedent).
_REAL_SOCKET = socket.socket
_REAL_POPEN = subprocess.Popen
_REAL_RUN = subprocess.run
_REAL_CALL = subprocess.call


# -- AST-lite TS scanners --------------------------------------------------------

def _interface_body(text: str, name: str) -> str:
    """The interior of ``export interface <name> { ... }`` (brace-balanced)."""
    start = text.index(f"interface {name} {{")
    depth = 0
    i = text.index("{", start)
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    raise AssertionError(f"unbalanced interface {name}")


def _skip_string(chunk: str, i: int) -> int:
    """If ``chunk[i]`` opens a single/double-quoted literal, return the index
    just past its close (unterminated strings are scanned as plain text)."""
    if chunk[i] not in "'\"":
        return i
    close = chunk.find(chunk[i], i + 1)
    return i if close == -1 else close + 1


def _balanced_object_end(chunk: str, start: int) -> int:
    """Index of the ``}`` closing the ``{`` at ``start`` (strings skipped)."""
    depth = 0
    i = start
    while i < len(chunk):
        nxt = _skip_string(chunk, i)
        if nxt != i:
            i = nxt
            continue
        ch = chunk[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"unbalanced object in chunk: {chunk[:40]!r}…")


def scope_fields(chunk: str) -> "tuple[frozenset[str], frozenset[str]]":
    """Depth-1 property names of the first TS object type literal in ``chunk``.

    Returns ``(required, optional)`` (``?``-suffixed names are optional);
    nested object literals (depth >= 2) are NOT flattened, so an inline
    ``{ readonly a: { readonly b: string } }`` reports ``a`` only.
    """
    start = chunk.index("{")
    body = chunk[start + 1:_balanced_object_end(chunk, start)]
    required: set[str] = set()
    optional: set[str] = set()
    depth = 0
    i = 0
    while i < len(body):
        nxt = _skip_string(body, i)
        if nxt != i:
            i = nxt
            continue
        ch = body[i]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif depth == 0:
            m = re.match(r"readonly\s+(\w+)(\?)?\s*:", body[i:])
            if m:
                (optional if m.group(2) else required).add(m.group(1))
                i += m.end()
                continue
        i += 1
    return frozenset(required), frozenset(optional)


def _interface_fields(text: str, name: str) -> "dict[str, tuple[frozenset[str], frozenset[str]]]":
    """For one interface: member -> (input required, input optional) fields.

    Members without an ``input: { ... }`` parameter report empty sets; a
    single positional parameter (e.g. ``getDefinition(definitionId)``) is
    recorded as a required field of its own name.
    """
    body = _interface_body(text, name)
    starts = [m for m in re.finditer(r"^  (?:readonly )?(\w+)\(", body, re.M)]
    out: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for idx, m in enumerate(starts):
        span = body[m.start():starts[idx + 1].start() if idx + 1 < len(starts) else len(body)]
        member = m.group(1)
        if "input: {" in span:
            req, opt = scope_fields(span[span.index("input: {"):])
            req, opt = req - {"signal"}, opt - {"signal"}
        else:
            positional = re.match(rf"^  (?:readonly )?{member}\((\w+):", span)
            req = frozenset({positional.group(1)}) if positional and positional.group(1) != "signal" \
                else frozenset()
            opt = frozenset()
        out[member] = (req, opt)
    return out


def parse_binding_table(wire_text: str) -> "dict[str, str]":
    """``MCP_WIRE_METHODS``: client-key -> wire method id, read from source."""
    m = re.search(r"export const MCP_WIRE_METHODS = \{(.*?)\} as const", wire_text, re.S)
    assert m, "MCP_WIRE_METHODS table not found in wire.ts"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", m.group(1)))


def parse_request_bodies(wire_text: str) -> "dict[str, frozenset[str]]":
    """Per client method: the body fields ``createFetchMcpWireClient`` sends.

    ``{ ...params }`` expands to the interface's input fields minus ``signal``
    (the implementation destructures ``{ signal, ...params }``); a literal
    ``{ definitionId }`` / ``{}`` is read off the call site directly.
    """
    client_inputs = _interface_fields(wire_text, "McpWireClient")
    bodies: dict[str, frozenset[str]] = {}
    pattern = re.compile(
        r"^    (\w+):\s*\(?[^=]*\)?\s*=>\s*call\(\s*MCP_WIRE_METHODS\.(\w+),\s*\{([^}]*)\}",
        re.M | re.S)
    for m in pattern.finditer(wire_text):
        key, table_key, literal = m.group(1), m.group(2), m.group(3)
        assert key == table_key, f"call site {key} binds {table_key}"
        literal = literal.strip()
        if literal == "":
            bodies[key] = frozenset()
        elif literal.replace(" ", "") == "...params":
            req, opt = client_inputs[key]
            bodies[key] = req | opt
        else:
            names = frozenset(re.findall(r"\b(\w+)\b", literal))
            req, opt = client_inputs[key]
            assert names <= (req | opt) | {"signal"}, (key, names)
            bodies[key] = frozenset(n for n in names if n != "signal")
    return bodies


def parse_interface_field_names(dto_text: str, name: str) -> "frozenset[str]":
    """Depth-1 property names (required ∪ optional) of one dto.ts interface."""
    req, opt = _dto_interface_fields(dto_text, name)
    return req | opt


def parse_response_types(wire_text: str) -> "dict[str, frozenset[str] | str]":
    """Per client method: the TS-side answer contract read off ``wire.ts``.

    Either an inline object type's depth-1 field names (frozenset), or the
    name of a ``dto.ts`` interface the member returns (``McpProbeFacts`` for
    ``probe``, ``McpDefinitionSummary`` for the ``listDefinitions`` rows).
    """
    client_inputs = _interface_fields(wire_text, "McpWireClient")  # noqa: F841
    body = _interface_body(wire_text, "McpWireClient")
    starts = [m for m in re.finditer(r"^  (?:readonly )?(\w+)\(", body, re.M)]
    out: dict[str, "frozenset[str] | str"] = {}
    for idx, m in enumerate(starts):
        span = body[m.start():starts[idx + 1].start() if idx + 1 < len(starts) else len(body)]
        member = m.group(1)
        marker = "): Promise<"
        assert marker in span, f"{member} has no Promise return"
        tail = span[span.index(marker) + len(marker):].strip()
        if tail.startswith("{"):
            req, opt = scope_fields(tail)
            out[member] = req | opt
        else:
            row = re.match(r"readonly (\w+)\[\]>", tail)
            single = re.match(r"(\w+)>", tail)
            name = row.group(1) if row else single.group(1)
            out[member] = name
    return out


def parse_ts_union(wire_text: str, field: str) -> "frozenset[str]":
    """One quoted string-union field of wire.ts (e.g. ``scopeKind``)."""
    m = re.search(rf"\b{field}:\s*((?:'[A-Za-z0-9_-]+'\s*\|?\s*)+)", wire_text)
    assert m, f"no string union found for {field}"
    return frozenset(re.findall(r"'([A-Za-z0-9_-]+)'", m.group(1)))


def parse_backend_tuple(py_text: str, const: str) -> "frozenset[str]":
    """One string-tuple constant of a backend module (e.g. ``SCOPE_KINDS``)."""
    m = re.search(rf"^{const} = \((.*?)\)", py_text, re.S | re.M)
    assert m, f"{const} tuple not found"
    return frozenset(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))


def _dto_interface_fields(text: str, name: str) -> "tuple[frozenset[str], frozenset[str]]":
    body = _interface_body(text, name)
    return scope_fields("PLACEHOLDER {" + body + "}")


# -- the registered surface -------------------------------------------------------

class RegisteredSurface:
    """method_id -> (required, optional) straight off the plugin's live
    ServerMethodDescriptor tuples (the registration face, not _PARAM_SHAPES
    re-typed by hand)."""

    def __init__(self, tmp_path: Path) -> None:
        self.registry = MethodRegistry()
        host = ServerPluginHost(methods=self.registry, data_root=tmp_path,
                                host_ports={})
        active = host.activate(McpAssetServerPlugin())
        self.methods = {descriptor.method_id:
                        (frozenset(descriptor.required_params),
                         frozenset(descriptor.optional_params))
                        for descriptor in active.registration.methods}


# -- the live composition stack (tests/service precedent, REAL probe runner) ------

class AllowProbeAuthority:
    def __init__(self) -> None:
        self.calls: list = []

    def authorize_probe(self, *, principal: str, server_scope: str,
                        definition_id: str, revision: int) -> bool:
        self.calls.append((principal, server_scope, definition_id, revision))
        return True


class DenyProbeAuthority:
    def authorize_probe(self, **kwargs) -> bool:
        return False


class Stack:
    """Real host + real WireService + the Q4 plugin; probe_runner stays the
    production default (backend.probe.probe_definition) unless overridden."""

    def __init__(self, tmp_path, *, host_ports=None, probe_runner=None,
                 probe_policy=None) -> None:
        self.registry = MethodRegistry()
        self.host_ports = dict(host_ports or {})
        self.host = ServerPluginHost(
            methods=self.registry, data_root=tmp_path, host_ports=self.host_ports)
        self.host_ports.setdefault(
            "wire.error_family_resolver",
            lambda code: self.host.wire_error_families.family_for(code))
        kwargs: dict = {}
        if probe_runner is not None:
            kwargs["probe_runner"] = probe_runner
        if probe_policy is not None:
            kwargs["probe_policy"] = probe_policy
        self.plugin = McpAssetServerPlugin(**kwargs)
        self.active = self.host.activate(self.plugin)
        for hook in self.active.registration.start_hooks:
            hook()
        self.wire = WireService(
            server_id_provider=lambda: "contract-server", cursor_secret=b"c" * 16,
            method_registry=self.registry,
            error_family_resolver=lambda code: self.host.wire_error_families.family_for(code))

    def call(self, method, **params):
        return self.wire.dispatch(method, params)

    def expect_refusal(self, method, *, family, internal_code=None, **params):
        with pytest.raises(WireError) as info:
            self.wire.dispatch(method, params)
        error = info.value
        assert error.family == family, f"{method}: {error.family} != {family} ({error.message})"
        if internal_code is not None:
            assert error.details.get("internalCode") == internal_code, error.details
            assert error.message.startswith(f"{internal_code}: "), error.message
        return error


def stdio_definition(name="demo", command="/bin/true", args=(), env=None):
    values = {key: ({"literal": value} if isinstance(value, str) else value)
              for key, value in (env or {}).items()}
    return {"name": name, "transport": {"stdio": {
        "command": command, "args": list(args), "env": values or None}}}


def remote_definition(name="demo", url="http://127.0.0.1:1/mcp", headers=None):
    values = {key: ({"literal": value} if isinstance(value, str) else value)
              for key, value in (headers or {}).items()}
    return {"name": name, "transport": {"remote": {
        "url": url, "headers": values or None}}}


def seed(stack, *, scope="s1", principal="alice", definition_id="demo",
         approve=True, definition=None):
    stack.call("mcp.saveRevision", serverScope=scope, principal=principal,
               definitionId=definition_id,
               definition=definition or stdio_definition(name=definition_id),
               expectedVersion=0, operationKey=f"op-save-{definition_id}")
    if approve:
        stack.call("mcp.approveRevision", serverScope=scope, principal=principal,
                   definitionId=definition_id, revision=1)
    return stack


# -- primitives lift (tests/probe precedent) --------------------------------------

@pytest.fixture
def contract_primitives(monkeypatch, no_side_effect_primitives):
    """Rebind the real socket/subprocess entry points for THIS test only."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)


# -- loopback fake Streamable-HTTP endpoint ---------------------------------------

_INIT_ANSWER = {
    "jsonrpc": "2.0", "id": 1,
    "result": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "serverInfo": {"name": "contract-http-fake", "version": "0.3"},
    },
}


class _LoopbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        try:
            self._handle_post()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the probe timed out and hung up; the witness already stands

    def _handle_post(self):
        record = self.server.witnesses  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        record.append({"path": self.path, "headers": dict(self.headers),
                       "body": raw.decode("utf-8")})
        mode = getattr(self.server, "mode", "ok")
        if mode == "auth":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "slow":
            import time
            time.sleep(self.server.slow_seconds)  # type: ignore[attr-defined]
        payload = _INIT_ANSWER if mode in ("ok", "slow") else b"{}"
        import json
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep stderr quiet (and stdout clean)
        pass


class LoopbackHttpFake:
    """A millisecond-level 127.0.0.1 fake; the server-side WITNESS list is how
    these cells prove the probe carried no credentials."""

    def __init__(self, *, mode="ok", slow_seconds=0.0) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
        self.server.daemon_threads = True
        self.server.mode = mode
        self.server.slow_seconds = slow_seconds
        self.server.witnesses = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "LoopbackHttpFake":
        self.thread.start()
        return self

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/mcp"

    @property
    def witnesses(self) -> list:
        return self.server.witnesses

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

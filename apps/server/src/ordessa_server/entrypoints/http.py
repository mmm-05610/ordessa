"""Long-lived loopback HTTP launch over explicitly composed current owners.

The original transport grammar/socket/handoff helpers are retained. Domain
capabilities, authentication and default composition remain their owners' inputs.
The one-shot registry CLI has a separate executable entry.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import socket
from typing import Any

from ordessa_server.bootstrap.data_root import (
    LAYOUT,
    ensure_data_root,
    resolve_data_root,
)
from ordessa_server.bootstrap.handshake import (
    ListeningHandshake,
    current_pid,
    emit_listening_handshake,
    loopback_origin,
)
from server_plugin_api import (
    CLI_SERVER_FLAGS_POINT_ID,
    AbsentContribution,
    ServerFlagSpec,
)

#: C-02 §3.3: 0 asks the system for a port; anything else pins one.
DEFAULT_PORT: int = int(LAYOUT["launch"]["defaultPort"])


class PortAllocationFailed(RuntimeError):
    """The loopback port could not be bound (C-02 §7)."""

    code = "PORT_ALLOCATION_FAILED"

    def __init__(self, reason: str, remedy: str) -> None:
        self.reason = reason
        self.remedy = remedy
        super().__init__(f"{self.code}: {reason}; {remedy}")


#: The converters a contributed flag spec may name in its `add` mapping
#: (`server_plugin_api.ServerFlagSpec` keeps the contract dependency-free
#: by NAME, so the host resolves the callables).
_FLAG_TYPES: "dict[str, Any]" = {"path": Path, "int": int}


def business_flags(composition: Any) -> "tuple[ServerFlagSpec, ...]":
    """The grammar the installed product contributes through the point.

    Absence is a fact, not an error: no seam on the composition, no batch
    entry, or a null payload all leave the host parser with its transport
    flags only. A payload the host cannot register is a typed refusal — the
    contract is checked at the seam, not discovered mid-parse.
    """
    answer = getattr(composition, "server_cli_contributions", None)
    if answer is None:
        return ()
    resolution = answer().resolve(CLI_SERVER_FLAGS_POINT_ID)
    if isinstance(resolution, AbsentContribution) or resolution.payload is None:
        return ()
    specs = tuple(resolution.payload)
    for spec in specs:
        if not isinstance(spec, ServerFlagSpec):
            raise TypeError(
                f"{CLI_SERVER_FLAGS_POINT_ID} payload entries must be "
                f"ServerFlagSpec, got {type(spec).__name__}")
    return specs


def parser(business: "tuple[ServerFlagSpec, ...]" = ()) -> argparse.ArgumentParser:
    """The host's transport grammar.

    Two defaults changed under C-01/C-02 and both are contract changes, not
    conveniences:

    * `--data-root` is optional. Omitted, the root resolves through the one
      C-01 order (env → `$HOME/.ordessa`) instead of failing argparse.
    * `--port` defaults to 0, which means "the system assigns one". The
      Server reports the port it actually got through the C-02 §3.1
      handshake, so a caller never has to guess or reserve a port.

    An explicitly passed `--port` still pins the port, which is what a
    developer smoke wants; it is no longer a requirement.
    """
    value = argparse.ArgumentParser(description="Run the Ordessa loopback Server")
    value.add_argument("--data-root", type=Path, default=None)
    value.add_argument("--port", type=int, default=DEFAULT_PORT)
    for spec in business:
        add = dict(spec.add)
        if "type" in add:
            add["type"] = _FLAG_TYPES[add["type"]]
        value.add_argument(*spec.flags, dest=spec.dest, **add)
    return value


def bind_loopback_socket(port: int) -> "socket.socket":
    """Bind `127.0.0.1:<port>` here, so the caller can read the real port back.

    Binding before uvicorn starts is what makes "read the actual origin"
    possible at all: with `--port 0` the requested number is a request, not
    an answer, and only the bound socket knows. A refused bind is
    `PORT_ALLOCATION_FAILED` and is never retried against a different fixed
    port — silently landing somewhere else is how a host ends up talking to
    somebody else's Server.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
    except OSError as exc:
        sock.close()
        raise PortAllocationFailed(
            f"a loopback port could not be allocated: {exc.strerror or 'unknown error'}",
            "free the loopback port and start again; the Server never falls back to a "
            "different fixed port on its own",
        ) from exc
    return sock


def resolved_data_root(explicit: "Path | None") -> Path:
    """The one data-root resolution both entry points share (C-01 §1, §5)."""
    spec = resolve_data_root(explicit=explicit)
    return ensure_data_root(spec).path


def serving_origin(sock: "socket.socket") -> str:
    return loopback_origin(sock.getsockname()[1])


class HttpCompositionUnavailable(RuntimeError):
    code = "HTTP_COMPOSITION_UNAVAILABLE"


def _runtime_factory():
    from ordessa_server.composition.product_selection import _resolve_product_composition
    try:
        product = _resolve_product_composition()
    except RuntimeError:
        raise HttpCompositionUnavailable('one installed current HTTP product required') from None
    prepare = getattr(product, "prepare_http_runtime", None)
    if not callable(prepare):
        raise HttpCompositionUnavailable("installed product supplies no current HTTP owner bindings")
    factory = prepare()
    if not callable(factory):
        raise HttpCompositionUnavailable("installed product supplies no current HTTP runtime factory")
    return factory


def main(argv=None, *, runtime_factory=None):
    """Serve current capabilities; the trusted product supplies original owners.

    Explicit factory injection is process composition, never an environment
    import or network-selected callback. No grants or instance tokens are made.
    Missing default bindings refuse before creating or adopting a data root.
    """
    import sys
    from ordessa_server.composition.agent_owner import AgentOwnerUnavailable
    from ordessa_server.composition.registry_runtime import RegistryRuntime
    used = parser()
    args = used.parse_args(argv)
    if not 0 <= args.port <= 65535:
        used.error("--port must be between 0 and 65535")
    try:
        factory = _runtime_factory() if runtime_factory is None else runtime_factory
        if not callable(factory):
            raise HttpCompositionUnavailable("explicit current HTTP runtime factory required")
    except (HttpCompositionUnavailable, AgentOwnerUnavailable) as exc:
        print(f"ordessa-server: {exc.code}: current HTTP owner bindings are required", file=sys.stderr)
        return 2
    root = resolved_data_root(args.data_root)
    sock = bind_loopback_socket(args.port)
    runtime = None
    try:
        runtime = factory(root)
        if type(runtime) is not RegistryRuntime or runtime._closed or not runtime.server_id:
            raise HttpCompositionUnavailable("live current RegistryRuntime with original Server identity required")
        from uvicorn import Config, Server
        from ordessa_interfaces.http.registry import create_registry_app
        def announce():
            emit_listening_handshake(ListeningHandshake(
                origin=serving_origin(sock), server_id=runtime.server_id, pid=current_pid()))
        app = create_registry_app(runtime, on_bound=announce, close_on_shutdown=True)
        Server(Config(app, log_config=None, lifespan="on", access_log=False)).run(sockets=[sock])
        return 0
    except (HttpCompositionUnavailable, AgentOwnerUnavailable) as exc:
        print(f"ordessa-server: {exc.code}: current HTTP owner bindings are required", file=sys.stderr)
        return 2
    finally:
        try:
            if runtime is not None and callable(getattr(runtime, 'close', None)):
                runtime.close()
        finally:
            sock.close()


if __name__ == "__main__":
    raise SystemExit(main())

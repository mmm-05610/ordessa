"""`python -m ordessa_server`: the host's half of the Server CLI.

The host owns the transport grammar only — the data root, the port, the
one-worker loopback startup — and the generic mechanics around the product's
contributions: it asks the installed product for its `cli.server-flags`
contribution, registers whatever flag specs that answer carries, parses, and
calls the composition method the product's plan names with the arguments the
plan built. No business mode is spelled here: a composition without the
contribution parses exactly `--data-root`/`--port` and answers every other
flag with argparse's own "unrecognized arguments" error, never a host
message.
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


def main(argv: list[str] | None = None) -> int:
    from ordessa_server.bootstrap import _resolve_product_composition

    # The CLI owns the transport grammar; the product owns the business
    # grammar and what the parsed facts mean. Exactly one installed product
    # answers the composition seam — starting without one is a typed
    # refusal, not a silently bare host.
    composition = _resolve_product_composition()
    used = parser(business_flags(composition))
    args = used.parse_args(argv)
    if not 0 <= args.port <= 65535:
        used.error("--port must be between 0 and 65535")
    plan = composition.plan_server_cli(vars(args))
    if plan.error is not None:
        used.error(plan.error)
    from uvicorn import Config, Server
    from ordessa_server.transport.http import create_app

    # C-01 §5: the resolved root is the ONE the host and the Server share.
    # It replaces the (possibly absent) flag before the composition is
    # called, so every downstream route — the composition, the migration
    # preflight, the token — sees the same directory the host will pass on.
    data_root = resolved_data_root(args.data_root)
    # C-02 §3.1: bind first, learn the port second. `--port 0` is a request
    # for a port, and only the bound socket can answer it.
    sock = bind_loopback_socket(args.port)
    runtime = getattr(composition, plan.method)(data_root, *plan.args, **plan.kwargs)

    def announce() -> None:
        """The one handshake line, written once the Server is actually up."""
        from ordessa_server.bootstrap.runtime import _server_id

        emit_listening_handshake(ListeningHandshake(
            origin=serving_origin(sock),
            server_id=_server_id(runtime.database),
            pid=current_pid(),
        ))

    app = create_app(runtime, on_bound=announce)
    # One ASGI worker is an invariant: no CLI knob exposes a multi-worker
    # mode, and a second worker would be a second Server holding the same
    # data root. The socket is handed over rather than re-bound so the port
    # the handshake reported is the port being served.
    config = Config(app, log_config=None, lifespan="on")
    try:
        Server(config).run(sockets=[sock])
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

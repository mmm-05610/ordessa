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
from typing import Any

from server_plugin_api import (
    CLI_SERVER_FLAGS_POINT_ID,
    AbsentContribution,
    ServerFlagSpec,
)

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
    value = argparse.ArgumentParser(description="Run the Ordessa loopback Server")
    value.add_argument("--data-root", type=Path, required=True)
    value.add_argument("--port", type=int, default=8732)
    for spec in business:
        add = dict(spec.add)
        if "type" in add:
            add["type"] = _FLAG_TYPES[add["type"]]
        value.add_argument(*spec.flags, dest=spec.dest, **add)
    return value


def main(argv: list[str] | None = None) -> int:
    from ordessa_server.bootstrap import _resolve_product_composition

    # The CLI owns the transport grammar; the product owns the business
    # grammar and what the parsed facts mean. Exactly one installed product
    # answers the composition seam — starting without one is a typed
    # refusal, not a silently bare Server.
    composition = _resolve_product_composition()
    used = parser(business_flags(composition))
    args = used.parse_args(argv)
    if not 1 <= args.port <= 65535:
        used.error("--port must be between 1 and 65535")
    plan = composition.plan_server_cli(vars(args))
    if plan.error is not None:
        used.error(plan.error)
    from uvicorn import run
    from ordessa_server.transport.http import create_app

    runtime = getattr(composition, plan.method)(args.data_root, *plan.args, **plan.kwargs)
    # One ASGI worker is an invariant: no CLI knob exposes a multi-worker mode.
    run(create_app(runtime), host="127.0.0.1", port=args.port, workers=1, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

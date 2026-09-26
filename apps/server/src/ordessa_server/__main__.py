from __future__ import annotations

import argparse
import os
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the Ordessa loopback Server")
    value.add_argument("--data-root", type=Path, required=True)
    value.add_argument("--port", type=int, default=8732)
    value.add_argument("--execution-mode", choices=("isolated", "native"), default="isolated")
    value.add_argument("--native-harness", help="one registered native Agent Harness id")
    value.add_argument("--native-adapter-command", help="absolute executable path of its ACP adapter")
    value.add_argument("--native-adapter-arg", action="append", default=[],
                       help="one adapter argument (repeatable)")
    value.add_argument("--native-continuation", action="store_true",
                       help="declare adapter resume support; runtime observation is still required")
    value.add_argument(
        "--sidecar-deployment", type=Path,
        help="non-secret Harness sidecar deployment JSON",
    )
    value.add_argument(
        "--plugin-root", type=Path,
        help="machine-local root the deployment's plugin-relative sources are read from",
    )
    value.add_argument(
        "--mount", action="append", default=[], metavar="TOKEN=PATH",
        help="bind one mount token the deployment names to a machine-local path "
             "(repeatable; the document itself carries no host path)",
    )
    return value


def mount_bindings(values: list[str]) -> dict[str, str]:
    """Parse `--mount TOKEN=PATH` into the bindings the loader takes."""
    bindings: dict[str, str] = {}
    for item in values:
        token, separator, path = item.partition("=")
        if not separator or not token or not path:
            raise SystemExit("--mount expects TOKEN=PATH")
        if token in bindings:
            raise SystemExit(f"--mount repeats the token {token!r}")
        bindings[token] = path
    return bindings


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser().error("--port must be between 1 and 65535")
    from uvicorn import run
    from ordessa_server.bootstrap import _resolve_product_composition
    from ordessa_server.transport.http import create_app

    # The CLI owns the argument grammar; the product owns what the arguments
    # mean. Exactly one installed product answers the composition seam —
    # starting without one is a typed refusal, not a silently bare Server.
    composition = _resolve_product_composition()

    if args.sidecar_deployment and args.plugin_root is None:
        parser().error("--plugin-root is required with --sidecar-deployment")
    if args.execution_mode == "native":
        if (args.sidecar_deployment or args.mount or not args.plugin_root
                or not args.native_harness or not args.native_adapter_command):
            parser().error("native mode requires --plugin-root, --native-harness and "
                           "--native-adapter-command, without sidecar deployment or mounts")
        runtime = composition.native_runtime(
            args.data_root, plugin_root=args.plugin_root,
            harness_id=args.native_harness,
            adapter_command=args.native_adapter_command,
            adapter_args=tuple(args.native_adapter_arg),
            native_continuation=args.native_continuation,
        )
    else:
        if (args.native_harness or args.native_adapter_command or args.native_adapter_arg
                or args.native_continuation):
            parser().error("native adapter options require --execution-mode native")
        runtime = (composition.sidecar_runtime(
            args.data_root, args.sidecar_deployment,
            plugin_root=args.plugin_root, mount_bindings=mount_bindings(args.mount),
        ) if args.sidecar_deployment else composition.default_runtime(args.data_root))
    # One ASGI worker is an invariant: no CLI knob exposes a multi-worker mode.
    run(create_app(runtime), host="127.0.0.1", port=args.port, workers=1, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

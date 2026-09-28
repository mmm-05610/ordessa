"""The product's Server CLI grammar and routing (T014-S4).

`python -m ordessa_server` is the host's: it owns the transport-level flags
(`--data-root`, `--port`) and the loopback startup. Everything else the
Server's command line accepts is declared here as `ServerFlagSpec` entries,
contributed through the `cli.server-flags` v1 point that
`server_plugin_api` names — and what the parsed values MEAN is decided by
`plan_server_cli`: which composition method runs, with which arguments, or
which combination is refused and with what message. The host builds its
parser from the contributed specs and calls the planned method generically,
so no business mode is ever spelled host-side.

Order is load-bearing: argparse renders its usage and error text from
registration order, so the specs below keep exactly the order and the exact
help text the host's own parser declared before the grammar moved (the wire
here is the command line; AGENTS rule 5 keeps it compatible).

`ServerFlagSpec.feeds`/`route` are consumed, not decorative: `plan_server_cli`
names each composition keyword argument through the contributing spec's own
`feeds` declaration, so the grammar table and the routing agree by
construction and a re-homed flag cannot drift into a stale keyword name.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from server_plugin_api import (
    CLI_SERVER_FLAGS_API_VERSION,
    CLI_SERVER_FLAGS_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerCliPlan,
    ServerFlagSpec,
)

#: The contributed business grammar, in host-parser registration order.
SERVER_CLI_FLAGS: "tuple[ServerFlagSpec, ...]" = (
    ServerFlagSpec(
        flags=("--execution-mode",), dest="execution_mode",
        add={"choices": ("isolated", "native"), "default": "isolated"},
    ),
    ServerFlagSpec(
        flags=("--native-harness",), dest="native_harness",
        add={"help": "one registered native Agent Harness id"},
        feeds="harness_id", route="native_runtime",
    ),
    ServerFlagSpec(
        flags=("--native-adapter-command",), dest="native_adapter_command",
        add={"help": "absolute executable path of its ACP adapter"},
        feeds="adapter_command", route="native_runtime",
    ),
    ServerFlagSpec(
        flags=("--native-adapter-arg",), dest="native_adapter_arg",
        add={"action": "append", "default": [],
             "help": "one adapter argument (repeatable)"},
        feeds="adapter_args", route="native_runtime",
    ),
    ServerFlagSpec(
        flags=("--native-continuation",), dest="native_continuation",
        add={"action": "store_true",
             "help": "declare adapter resume support; runtime observation "
                     "is still required"},
        feeds="native_continuation", route="native_runtime",
    ),
    ServerFlagSpec(
        flags=("--sidecar-deployment",), dest="sidecar_deployment",
        add={"type": "path", "help": "non-secret Harness sidecar deployment JSON"},
        feeds="deployment_path", route="sidecar_runtime",
    ),
    ServerFlagSpec(
        flags=("--plugin-root",), dest="plugin_root",
        add={"type": "path",
             "help": "machine-local root the deployment's plugin-relative "
                     "sources are read from"},
        feeds="plugin_root",
    ),
    ServerFlagSpec(
        flags=("--mount",), dest="mount",
        add={"action": "append", "default": [], "metavar": "TOKEN=PATH",
             "help": "bind one mount token the deployment names to a "
                     "machine-local path (repeatable; the document itself "
                     "carries no host path)"},
        feeds="mount_bindings", route="sidecar_runtime",
    ),
)

_SPECS_BY_DEST = {spec.dest: spec for spec in SERVER_CLI_FLAGS}


def server_cli_contributions() -> ContributionBatch:
    """The product's registration for the host CLI's open flag point.

    One contribution carries the whole spec tuple as its payload; the point
    is declared open so a composition could add its own flags beside these.
    Absence (a bare composition) is an observable `AbsentContribution`,
    never an error — the host then parses its transport grammar only.
    """
    return ContributionBatch(
        contributions=(Contribution(
            point_id=CLI_SERVER_FLAGS_POINT_ID,
            api_version=CLI_SERVER_FLAGS_API_VERSION,
            payload=SERVER_CLI_FLAGS,
        ),),
        open_points=frozenset({CLI_SERVER_FLAGS_POINT_ID}),
    )


def mount_bindings(values: "list[str]") -> "dict[str, str]":
    """Parse `--mount TOKEN=PATH` into the bindings the loader takes."""
    bindings: "dict[str, str]" = {}
    for item in values:
        token, separator, path = item.partition("=")
        if not separator or not token or not path:
            raise SystemExit("--mount expects TOKEN=PATH")
        if token in bindings:
            raise SystemExit(f"--mount repeats the token {token!r}")
        bindings[token] = path
    return bindings


def _value(values: Mapping[str, Any], dest: str) -> Any:
    """The parsed value for one declared flag, or its declared default.

    A composition whose parser never carried the grammar plausibly answers
    with defaults only, and the plan degrades to the plain route.
    """
    if dest in values:
        return values[dest]
    return _SPECS_BY_DEST[dest].add.get("default")


def _fed(dest: str, values: Mapping[str, Any],
         convert: "Callable[[Any], Any] | None" = None) -> "dict[str, Any]":
    """`{composition keyword: value}` keyed by the spec's declared `feeds`."""
    value = values[dest]
    if convert is not None:
        value = convert(value)
    return {_SPECS_BY_DEST[dest].feeds: value}


def plan_server_cli(values: Mapping[str, Any]) -> ServerCliPlan:
    """What the parsed CLI values mean, for the host to execute generically.

    The dispatch, the combination refusals and their messages are exactly
    the host's pre-move ones, moved verbatim: the refusals travel as
    `ServerCliPlan.error` for the host's parser to report through argparse,
    and the winning route names its composition method and arguments. The
    data root and the port never enter a plan — both are host-owned.
    """
    sidecar = _value(values, "sidecar_deployment")
    plugin_root = _value(values, "plugin_root")
    mount = _value(values, "mount")
    if sidecar and plugin_root is None:
        return ServerCliPlan(
            error="--plugin-root is required with --sidecar-deployment")
    if _value(values, "execution_mode") == "native":
        if (sidecar or mount or not plugin_root
                or not _value(values, "native_harness")
                or not _value(values, "native_adapter_command")):
            return ServerCliPlan(
                error="native mode requires --plugin-root, --native-harness and "
                      "--native-adapter-command, without sidecar deployment or mounts")
        return ServerCliPlan(
            method="native_runtime",
            kwargs={
                **_fed("plugin_root", values),
                **_fed("native_harness", values),
                **_fed("native_adapter_command", values),
                **_fed("native_adapter_arg", values, tuple),
                **_fed("native_continuation", values),
            },
        )
    if (_value(values, "native_harness") or _value(values, "native_adapter_command")
            or _value(values, "native_adapter_arg")
            or _value(values, "native_continuation")):
        return ServerCliPlan(
            error="native adapter options require --execution-mode native")
    if sidecar:
        return ServerCliPlan(
            method="sidecar_runtime", args=(sidecar,),
            kwargs={
                **_fed("plugin_root", values),
                **_fed("mount", values, mount_bindings),
            },
        )
    return ServerCliPlan(method="default_runtime")

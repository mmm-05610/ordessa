"""Which machine runs this turn, and therefore which channel carries it.

The workspace record already says where a turn belongs (`env_kind`: local, wsl,
or ssh). This module turns that fact into the one decision the product may make
from it - which channel implementation stages the bytes and starts the process -
and refuses, in typed terms, when no implementation can serve the placement.

It deliberately decides nothing else: the room is the sandbox layer's product and
the command is the deployment's. Swapping the placement swaps the channel, not
the execution.

`ssh` resolved here the moment a connector is composed, exactly as `wsl` does:
the two differ in which machine the channel reaches, and that difference is the
channel's to carry. The refusals are therefore symmetric too - a placement whose
connector is not in this composition is refused by name rather than silently run
somewhere else, and the record's `env_kind` is never second-guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The channel implementations that exist today.
LOCAL_CHANNEL = "local-process"
WSL_CHANNEL = "wsl-worker"
SSH_CHANNEL = "ssh-worker"


class PlacementUnsupported(RuntimeError):
    """No channel implementation can serve this placement."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Placement:
    """One resolved placement: where the turn runs, and which channel carries it."""

    kind: str
    channel: str


def resolve_placement(kind: str | None, *, has_connector: bool) -> Placement:
    """Resolve the workspace's placement into a channel implementation.

    ``has_connector`` is whether a connector for *this* placement exists in this
    composition: a deployment that declares a workspace whose connector is not
    composed is refused here, with the same typed code the launcher used to
    raise, so the reason survives into durable state.
    """
    if kind == "wsl":
        if not has_connector:
            raise PlacementUnsupported(
                "WSL_CONNECTOR_UNAVAILABLE", "a WSL workspace needs a composed connector",
            )
        return Placement(kind="wsl", channel=WSL_CHANNEL)
    if kind == "ssh":
        if not has_connector:
            raise PlacementUnsupported(
                "SSH_CONNECTOR_UNAVAILABLE", "an SSH workspace needs a composed connector",
            )
        return Placement(kind="ssh", channel=SSH_CHANNEL)
    if kind == "local":
        return Placement(kind="local", channel=LOCAL_CHANNEL)
    if kind is None:
        # A workspace that names no placement at all is refused too: the historic
        # "assume WSL" default is exactly what this resolution removes.
        raise PlacementUnsupported(
            "PLACEMENT_UNKNOWN", "the workspace names no supported placement: None",
        )
    raise PlacementUnsupported(
        "PLACEMENT_UNKNOWN", f"the workspace names no supported placement: {kind!r}",
    )

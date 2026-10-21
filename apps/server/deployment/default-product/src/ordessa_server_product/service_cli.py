"""The default product's Server CLI grammar: one optional explicit service config.

The host owns `--data-root` and `--port`. This module contributes the only business
flag the current product accepts — an explicit JSON service configuration — and
answers what the parsed values mean. Absence of the flag is the zero-configuration
path, not an error.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ordessa_server_plugin_api import (
    CLI_SERVER_FLAGS_API_VERSION,
    CLI_SERVER_FLAGS_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerCliPlan,
    ServerFlagSpec,
)

SERVICE_CONFIG_FLAG = ServerFlagSpec(
    flags=("--service-config",),
    dest="service_config",
    add={"type": "path",
         "help": "explicit JSON service configuration; omitted means zero-configuration defaults"},
    feeds="config_path",
    route="serve",
)


def server_cli_contributions() -> ContributionBatch:
    """The product's registration for the host CLI's open flag point."""
    return ContributionBatch(
        contributions=(Contribution(
            point_id=CLI_SERVER_FLAGS_POINT_ID,
            api_version=CLI_SERVER_FLAGS_API_VERSION,
            payload=(SERVICE_CONFIG_FLAG,),
        ),),
        open_points=frozenset({CLI_SERVER_FLAGS_POINT_ID}),
    )


def plan_server_cli(values: Mapping[str, Any]) -> ServerCliPlan:
    """Route the parsed values: explicit configuration, or the derived defaults."""
    if not isinstance(values, Mapping):
        return ServerCliPlan(error="parsed server values are unavailable")
    selected = values.get("service_config")
    if selected is None:
        return ServerCliPlan(method="prepare_default_http_runtime", kwargs={})
    if not isinstance(selected, (str, Path)):
        return ServerCliPlan(error="--service-config expects a file path")
    path = Path(selected)
    if not path.is_absolute():
        return ServerCliPlan(error="--service-config must be an absolute path")
    return ServerCliPlan(method="prepare_http_runtime", kwargs={"config_path": path})


__all__ = ["SERVICE_CONFIG_FLAG", "plan_server_cli", "server_cli_contributions"]

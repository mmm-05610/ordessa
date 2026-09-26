"""Order 58: translate one MCP asset into a family's own spelling.

The store holds the standard form; a family differs only in **where** its MCP
servers live and **what** the mapping key is spelled. Both facts are declared
by the family in the registry (``mcp_target`` / ``mcp_key``), never hardcoded
here - a family that declares neither is refused with
``ASSET_SLOT_UNSUPPORTED`` rather than guessed at, which is the "不支持的家
如实声明，不假装" rule of the order.

Two spellings exist among the observed families and both are tested:

* JSON with key ``mcpServers`` (claude-code, qwen): a ``settings.json`` file;
* TOML with key ``mcp_servers`` (codex): ``$CODEX_HOME/config.toml``.

Credential references do not travel into the rendered text: the renderer takes
already-resolved environment values, so no call path can accidentally write a
secret into a config file.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

_BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")


class McpRenderError(RuntimeError):
    """A typed refusal of one render request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _toml_key(value: str) -> str:
    return value if _BARE_TOML_KEY.fullmatch(value) else json.dumps(value)


def _toml_string(value: str) -> str:
    # TOML basic strings share JSON's escaping for everything that occurs in a
    # command line or a URL.
    return json.dumps(value)


def _server_entry(canonical: Mapping[str, Any], resolved_env: Mapping[str, str]) -> dict[str, Any]:
    transport = canonical["transport"]
    kind = next(iter(transport))
    body = transport[kind]
    if kind == "stdio":
        missing = [name for name in body["env"] if name not in resolved_env]
        if missing:
            raise McpRenderError(
                "MCP_CREDENTIAL_UNRESOLVED",
                f"no value resolved for env {sorted(missing)}",
            )
        return {
            "command": body["command"],
            "args": list(body["args"]),
            "env": dict(resolved_env),
        }
    raise McpRenderError(
        "MCP_TRANSPORT_UNSUPPORTED",
        "remote servers are not rendered into a family config yet",
    )


def render_json_config(
    canonical: Mapping[str, Any], *, key: str, resolved_env: Mapping[str, str],
) -> str:
    """The JSON spelling: ``{"<key>": {"<name>": {command, args, env}}}``."""
    document = {key: {canonical["name"]: _server_entry(canonical, resolved_env)}}
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


def render_toml_config(
    canonical: Mapping[str, Any], *, key: str, resolved_env: Mapping[str, str],
) -> str:
    """The TOML spelling: ``[<key>.<name>]`` with command/args/env keys."""
    entry = _server_entry(canonical, resolved_env)
    table = f"{_toml_key(key)}.{_toml_key(canonical['name'])}"
    lines = [f"[{table}]", f"command = {_toml_string(entry['command'])}"]
    rendered_args = ", ".join(_toml_string(item) for item in entry["args"])
    lines.append(f"args = [{rendered_args}]")
    for name, value in sorted(entry["env"].items()):
        lines.append(f"{_toml_key(name)} = {_toml_string(value)}")
    return "\n".join(lines) + "\n"


#: The declared spellings, keyed by the format the registry names. The set is
#: closed on purpose: a family whose file format is not here is unsupported,
#: not approximately rendered.
RENDERERS = {
    "json": render_json_config,
    "toml": render_toml_config,
}


def render_for_family(
    canonical: Mapping[str, Any], *, profile_spec: Any,
    resolved_env: Mapping[str, str],
) -> tuple[str, str]:
    """Render one server for the family ``profile_spec`` names.

    Returns ``(target, text)``. Both facts come from the registry declaration;
    anything missing is the honest "this family does not support this asset"
    refusal, never a default.
    """
    target = getattr(profile_spec, "mcp_target", None)
    key = getattr(profile_spec, "mcp_key", None)
    if not target or not key:
        raise McpRenderError(
            "ASSET_SLOT_UNSUPPORTED",
            "this family declares no MCP slot, so nothing is materialised for it",
        )
    if "toml" in target and target.endswith(".toml"):
        renderer = RENDERERS["toml"]
    elif target.endswith(".json"):
        renderer = RENDERERS["json"]
    else:
        raise McpRenderError(
            "ASSET_SLOT_UNSUPPORTED",
            f"the declared MCP target {target!r} has no known spelling",
        )
    return target, renderer(canonical, key=key, resolved_env=resolved_env)

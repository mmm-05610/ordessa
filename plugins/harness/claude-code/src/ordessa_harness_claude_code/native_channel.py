"""Claude Code native channel facts (N005, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions. Identity note:
``FAMILY_ID = "claude"`` is the registered harness identity
(``harnesses.toml``/``ADAPTERS``); the command catalog publishes the family
under ``claude-code`` — both are recorded, neither is renamed (G2).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "claude"
COMMAND_CATALOG_ID = "claude-code"
PROTOCOL = "claude-stream-json/1"

#: CLI/SDK release is not measured locally (no installed artifact in this
#: environment) — recorded as such, never invented (G1).
PINNED_RELEASE = "runtime unmeasured; no installed artifact verified"
SDK_SOURCE_COMMIT = "9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b"
SDK_SOURCE_VERSION = "0.2.163"
ARTIFACT_DIGEST = "unknown"

COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "permission_mode", "allowed_tools", "system_prompt", "mcp_config", "resume", "continue_"}
)

COMPILE_REFUSAL_KEYS = frozenset({"hotModelSwitch", "sandboxInstancePool", "subscriptionToken"})


class ConfigRefusal(ValueError):
    """Unsupported configuration key: refused before any launch (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board for the claude stream-json channel (seams.md §4)."""
    return {
        "family": FAMILY_ID,
        "commandCatalogId": COMMAND_CATALOG_ID,
        "channel": "stdio-stream-json",
        "upstream": {
            "product": "Claude Code / Claude Agent SDK",
            "docs": "code.claude.com/docs/en/agent-sdk/overview + /headless (read 2026-10-04)",
            "distinction": "Agent SDK runs the Claude Code binary; NOT the Anthropic "
            "Client SDK (API client) and NOT Managed Agents (hosted)",
        },
        "release": {"version": PINNED_RELEASE, "volatile": True},
        "sdk_source": {"repository": "https://github.com/anthropics/claude-agent-sdk-python",
                       "commit": SDK_SOURCE_COMMIT, "version": SDK_SOURCE_VERSION,
                       "license": "MIT", "installed": False, "observedRuntime": False},
        "consumer": {"implemented": "pure SDK launch plan; native protocol bootstrap unavailable",
                     "productionPreference": "reuse official Claude Agent SDK",
                     "notImplemented": ["SDK hooks", "SDK MCP", "background run completion",
                                        "production SDK integration", "durable input recovery"]},
        "artifact": {"path": "claude CLI / Agent SDK package", "sha256": ARTIFACT_DIGEST},
        "license_terms": {
            "commercial": "Anthropic Commercial Terms of Service (component LICENSE may override)",
            "auth_terms": "API key is the sanctioned path; claude.ai OAuth/subscription "
            "login must not be offered to third parties without Anthropic approval "
            "(docs note). No subscription token is read or stored here (G12).",
        },
        "protocol": {
            "schema_source": "official SDK source at " + SDK_SOURCE_COMMIT + "; types.py/query.py/client.py/subprocess_cli.py",
            "framing": "JSONL on stdout; stderr diagnostics (G5)",
            "message_types": "system/init, system/api_retry, system/plugin_install, "
            "assistant, user, stream_event, permission_denied, result",
            "stdin_side": "official SDK defines native user/control_request/control_response/control_cancel_request JSONL; "
            "original owner native bootstrap/interrupt/permission routing unavailable; runtime compatibility unknown",
            "version_negotiation": "none; system/init carries a capabilities array "
            "(e.g. interrupt_receipt_v1) for feature detection",
        },
        "launch": {
            "argv_shape": "output-only: claude -p --output-format stream-json; explicit bidirectional: "
            "claude -p --output-format stream-json --input-format stream-json --verbose --permission-prompt-tool stdio",
            "runtime_flags": {"print": "-p (non-interactive)", "output": "--output-format stream-json"},
        },
        "isolation": {
            "home": "scratch HOME pinned; .claude/ config under scratch (skills/MCP/plugins "
            "load from project .claude/ and ~/.claude/ per docs)",
            "no_user_state": "user ~/.claude (OAuth creds, history) never read (G12)",
        },
        "network": {
            "default": "not observed; no proof that model calls are the only outbound traffic",
            "upstream_retries": "system/api_retry events show upstream API-level retries "
            "(attempt/max_retries) — surfaced as facts; this stack adds NO retries (G11)",
        },
        "auth": {
            "method": "API key (sanctioned); SDK callback surfaces for permissions",
            "isolated_behavior": "no user credentials inherited; key only via explicit env",
        },
        "session": {
            "create": "session_id observed from system/init and checked against terminal result; result ends one turn only",
            "resume": "--resume <session_id|jsonl path> / --continue (docs); observed: no",
        },
        "callbacks": {
            "permission": "SDK can_use_tool control_request with explicit decision; no auto-response; "
            "upstream settings/allow rules may shadow callbacks (production policy requires separate verification)",
            "cancel": "output-only SIGINT signal is not completion proof; explicit bidirectional interrupt control request; "
            "interrupt receipt is not a completed turn",
        },
        "unknown_boundary": {
            "extensions": "unknown message types/fields preserved verbatim (G4)",
            "upgrade": "no version negotiation; re-pin release and re-verify (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    prompt: str | None = None,
    extra_args: tuple[str, ...] = (),
    bidirectional: bool = False,
) -> dict:
    """Pure plan for an isolated headless run. Executes nothing."""
    if type(bidirectional) is not bool:
        raise ConfigRefusal("bidirectional", "mode must be explicit boolean")
    if not isinstance(extra_args, tuple) or any(not isinstance(value, str) or not value or "\x00" in value for value in extra_args):
        raise ConfigRefusal("extra_args", "argv must be a tuple of nonempty strings")
    if bidirectional and prompt is not None:
        raise ConfigRefusal("prompt", "bidirectional input must follow control initialization on stdin")
    _validate_launch_args(extra_args, bidirectional=bidirectional)
    home_path = Path(home)
    argv = ["claude", "-p", "--output-format", "stream-json"]
    if bidirectional:
        argv.extend(["--input-format", "stream-json", "--verbose", "--permission-prompt-tool", "stdio"])
    if prompt is not None:
        argv.append(prompt)
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    return {"argv": argv, "cwd": os.fspath(workspace), "env": env, "executable": "claude"}


def _validate_launch_args(args, *, bidirectional):
    managed = {"--input-format", "--output-format", "--permission-prompt-tool", "--verbose", "--print", "-p"}
    names = [value.split("=", 1)[0] for value in args]
    if any(name in managed for name in names):
        raise ConfigRefusal("extra_args", "transport flags belong to the selected launch mode")
    if any(name in {"--resume", "-r"} for name in names) and ("--continue" in names or "-c" in names):
        raise ConfigRefusal("resume", "resume and continue select different session policies")
    bypass = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"}
    if any(name in bypass for name in names):
        raise ConfigRefusal("permission_mode", "permission bypass flags are refused")
    for index, value in enumerate(args):
        if names[index] == "--permission-mode":
            mode = value.split("=", 1)[1] if "=" in value else (args[index + 1] if index + 1 < len(args) else "")
            if not mode or "bypass" in mode.lower() or mode.lower() in {"auto", "acceptall", "yolo", "dangerouslyskip"}:
                raise ConfigRefusal("permission_mode", "permission mode is absent or bypasses decisions")
            if bidirectional and mode != "default":
                raise ConfigRefusal("permission_mode", "bidirectional explicit approval requires default permission mode")
    if bidirectional and any(name in {"--allowedTools", "--allowed-tools", "--settings", "--setting-sources"} for name in names):
        raise ConfigRefusal("allowed_tools", "caller flags must not shadow explicit permission callbacks")
    if bidirectional:
        takes_value = {"--model", "--permission-mode", "--append-system-prompt", "--mcp-config", "--resume", "-r", "--session-id"}
        standalone = {"--continue", "-c"}
        index = 0
        while index < len(args):
            value = args[index]
            name = value.split("=", 1)[0]
            if name in standalone and "=" not in value:
                index += 1
            elif name in takes_value:
                if "=" in value:
                    if not value.split("=", 1)[1]:
                        raise ConfigRefusal("extra_args", "native option requires a value")
                    index += 1
                else:
                    if index + 1 >= len(args) or args[index + 1].startswith("-"):
                        raise ConfigRefusal("extra_args", "native option requires a value")
                    index += 2
            else:
                raise ConfigRefusal("extra_args", "bidirectional launch accepts only compiled configuration options, not positional prompts")


def compile_config(materials: Mapping[str, Any], *, bidirectional: bool = False) -> dict:
    """Family-owned config compile (G3). ``subscriptionToken`` and other
    second-ownership keys are refused outright — no token reuse (G12)."""
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "credential/ownership boundary; never accepted"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized claude configuration key"
            )
            raise ConfigRefusal(key, reason)
    if type(bidirectional) is not bool:
        raise ConfigRefusal("bidirectional", "mode must be explicit boolean")
    if "continue_" in materials and type(materials["continue_"]) is not bool:
        raise ConfigRefusal("continue_", "continue must be an explicit boolean")
    if materials.get("resume") is not None and (not isinstance(materials["resume"], str) or not materials["resume"]):
        raise ConfigRefusal("resume", "resume requires an explicit nonempty native identity or transcript path")
    if materials.get("resume") is not None and materials.get("continue_") is True:
        raise ConfigRefusal("resume", "resume and continue are mutually exclusive")
    args: list[str] = []
    if materials.get("model") is not None:
        args.extend(["--model", str(materials["model"])])
    permission_mode = materials.get("permission_mode")
    if permission_mode is not None:
        mode = str(permission_mode)
        if "bypass" in mode.lower() or mode.lower() in {"auto", "acceptall", "yolo", "dangerouslyskip"}:
            raise ConfigRefusal(
                "permission_mode",
                "auto-approve/bypass modes are never compiled (SAFETY: no auto-approve)",
            )
        args.extend(["--permission-mode", mode])
    if materials.get("allowed_tools") is not None:
        args.extend(["--allowedTools", str(materials["allowed_tools"])])
    if materials.get("system_prompt") is not None:
        args.extend(["--append-system-prompt", str(materials["system_prompt"])])
    if materials.get("mcp_config") is not None:
        args.extend(["--mcp-config", str(materials["mcp_config"])])
    if materials.get("resume") is not None:
        args.extend(["--resume", str(materials["resume"])])
    if materials.get("continue_") is True:
        args.append("--continue")
    _validate_launch_args(tuple(args), bidirectional=bidirectional)
    return {"args": args}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed; nothing observed locally (G1 honesty)."""
    return {
        "prompt": {"declared": "yes", "implemented": "no; native bootstrap unavailable", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "no; original native control unavailable", "observed": "no"},
        "resume": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "no; no permission response writer", "observed": "no"},
        "steer": {"declared": "unknown", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "sessionPersist": {"declared": "yes", "implemented": "no; no native session owner integrated", "observed": "no"},
        "skillsPluginsMcp": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "no runtime; historical native facts only", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "unknown", "implemented": "no; native receipt association only", "observed": "no"},
    }

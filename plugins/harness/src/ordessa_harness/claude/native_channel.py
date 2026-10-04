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

#: CLI/SDK release is not measured locally (no installed artifact in this
#: environment) — recorded as such, never invented (G1).
PINNED_RELEASE = "unpinned (docs 2026-10-04; no local artifact measured)"
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
        "artifact": {"path": "claude CLI / Agent SDK package", "sha256": ARTIFACT_DIGEST},
        "license_terms": {
            "commercial": "Anthropic Commercial Terms of Service (component LICENSE may override)",
            "auth_terms": "API key is the sanctioned path; claude.ai OAuth/subscription "
            "login must not be offered to third parties without Anthropic approval "
            "(docs note). No subscription token is read or stored here (G12).",
        },
        "protocol": {
            "schema_source": "headless docs: stdout --output-format stream-json message types",
            "framing": "JSONL on stdout; stderr diagnostics (G5)",
            "message_types": "system/init, system/api_retry, system/plugin_install, "
            "assistant, user, stream_event, permission_denied, result",
            "stdin_side": "--input-format stream-json exists on the SDK surface only; "
            "headless doc does not pin stdin shapes -> registered unknown, not fabricated",
            "version_negotiation": "none; system/init carries a capabilities array "
            "(e.g. interrupt_receipt_v1) for feature detection",
        },
        "launch": {
            "argv_shape": "claude -p --output-format stream-json [--verbose] "
            "[--allowedTools ...] [--permission-mode ...] [--resume <id>]",
            "runtime_flags": {"print": "-p (non-interactive)", "output": "--output-format stream-json"},
        },
        "isolation": {
            "home": "scratch HOME pinned; .claude/ config under scratch (skills/MCP/plugins "
            "load from project .claude/ and ~/.claude/ per docs)",
            "no_user_state": "user ~/.claude (OAuth creds, history) never read (G12)",
        },
        "network": {
            "default": "model calls are the only outbound traffic",
            "upstream_retries": "system/api_retry events show upstream API-level retries "
            "(attempt/max_retries) — surfaced as facts; this stack adds NO retries (G11)",
        },
        "auth": {
            "method": "API key (sanctioned); SDK callback surfaces for permissions",
            "isolated_behavior": "no user credentials inherited; key only via explicit env",
        },
        "session": {
            "create": "session_id reported on the terminal result record",
            "resume": "--resume <session_id|jsonl path> / --continue (docs); observed: no",
        },
        "callbacks": {
            "permission": "canUseTool (SDK) / --permission-mode CLI; NEVER auto-approve",
            "cancel": "SIGINT ends the turn; SDK interrupt(); capabilities interrupt_receipt_v1",
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
) -> dict:
    """Pure plan for an isolated headless run. Executes nothing."""
    home_path = Path(home)
    argv = ["claude", "-p", "--output-format", "stream-json"]
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


def compile_config(materials: Mapping[str, Any]) -> dict:
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
    args: list[str] = []
    if materials.get("model") is not None:
        args.extend(["--model", str(materials["model"])])
    if materials.get("permission_mode") is not None:
        args.extend(["--permission-mode", str(materials["permission_mode"])])
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
    return {"args": args}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed; nothing observed locally (G1 honesty)."""
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "sigint", "observed": "no"},
        "resume": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "no-auto", "observed": "no"},
        "steer": {"declared": "unknown", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "sessionPersist": {"declared": "yes", "implemented": "result-session-id", "observed": "no"},
        "skillsPluginsMcp": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
    }

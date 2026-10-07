"""Gemini CLI native channel facts (N008, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions for the official
ACP channel (``gemini --acp``). New family: catalog registration is requested
at N012 by the main executor; no parallel registry is created here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "gemini-cli"

PINNED_RELEASE = "unpinned (docs 2026-10-04; no local artifact measured)"
ARTIFACT_DIGEST = "unknown"

COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "approval_mode", "mcp", "telemetry", "debug"}
)

COMPILE_REFUSAL_KEYS = frozenset({"hotModelSwitch", "sandboxInstancePool", "oauthToken"})


class ConfigRefusal(ValueError):
    """Unsupported configuration key: refused before any launch (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    return {
        "family": FAMILY_ID,
        "channel": "stdio-acp (official ACP implementation)",
        "upstream": {
            "product": "Gemini CLI",
            "docs": "geminicli.com/docs/cli/acp-mode/ + agentclientprotocol.com/protocol (read 2026-10-04)",
        },
        "release": {"version": PINNED_RELEASE, "volatile": True},
        "artifact": {"path": "gemini CLI binary", "sha256": ARTIFACT_DIGEST},
        "protocol": {
            "schema_source": "ACP v1 schema (agentclientprotocol.com/protocol/v1/schema)",
            "framing": "JSON-RPC 2.0 over stdio (G5 framing at the transport seam)",
            "handshake": "initialize (protocolVersion negotiation per ACP v1)",
            "session": "session/new, session/prompt, session/cancel (notification), session/load (optional)",
            "reverse": "session/request_permission, fs/read_text_file, fs/write_text_file, "
            "terminal/* (canonical ACP names; the gemini page itself does not document "
            "terminal callbacks — recorded as page-level unknown), elicitation/*",
            "extensions": "'_'-prefixed custom methods and _meta data preserved verbatim (G4)",
        },
        "launch": {
            "argv_shape": "gemini --acp [--debug]",
            "runtime_flags": {"acp": "--acp (stdio JSON-RPC)"},
        },
        "isolation": {
            "home": "scratch HOME/XDG pinned; gemini config under scratch",
            "no_user_state": "user ~/.gemini (OAuth creds/settings) never read (G12)",
        },
        "network": {
            "default": "model calls are the only outbound traffic",
            "telemetry": "GEMINI_TELEMETRY_* env exists upstream — pinned off in plans (G12)",
        },
        "auth": {
            "method": "authenticate method in ACP; env/credentials under isolated home",
            "isolated_behavior": "no user credentials inherited (G12)",
        },
        "session": {
            "create": "session/new",
            "resume": "session/load (optional capability; loadSession)",
        },
        "callbacks": {
            "permission": "session/request_permission — caller answers, never auto-approve",
            "filesystem": "proxied fs read/write — only what the client explicitly allows",
        },
        "cancel": {"cancel": "session/cancel notification"},
        "unknown_boundary": {
            "extensions": "_-prefixed methods and _meta preserved (G4)",
            "model_switch": "unstable_setSessionModel documented as unstable — recorded, not relied on",
            "upgrade": "ACP initialize negotiates protocolVersion; release still re-pinned (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    debug: bool = False,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure plan for an isolated ACP launch. Executes nothing."""
    home_path = Path(home)
    argv = ["gemini", "--acp"]
    if debug:
        argv.append("--debug")
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
        "GEMINI_TELEMETRY_ENABLED": "false",
    }
    return {"argv": argv, "cwd": os.fspath(workspace), "env": env, "executable": "gemini"}


def compile_config(materials: Mapping[str, Any]) -> dict:
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "credential/ownership boundary; never accepted"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized gemini configuration key"
            )
            raise ConfigRefusal(key, reason)
    approval_mode = materials.get("approval_mode")
    if approval_mode is not None:
        mode = str(approval_mode).lower()
        if mode in {"auto", "acceptall", "yolo", "bypass"} or "bypass" in mode or "auto-approve" in mode:
            raise ConfigRefusal(
                "approval_mode",
                "auto-approve modes are never compiled (SAFETY: no auto-approve)",
            )
    args: list[str] = []
    if materials.get("debug") is True:
        args.append("--debug")
    return {
        "args": args,
        "session_params": {
            k: materials[k] for k in ("model", "approval_mode", "mcp") if materials.get(k) is not None
        },
        "telemetry": materials.get("telemetry", "off"),
    }


def capability_matrix() -> dict[str, dict]:
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "resume": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "reply", "observed": "no"},
        "fileCallbacks": {"declared": "yes", "implemented": "reply", "observed": "no"},
        "terminalCallbacks": {"declared": "yes(acp)", "implemented": "reply", "observed": "no"},
        "steer": {"declared": "unknown", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "unstable", "implemented": "plan-only", "observed": "no"},
        "headlessJson": {"declared": "limited", "implemented": "no", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
    }

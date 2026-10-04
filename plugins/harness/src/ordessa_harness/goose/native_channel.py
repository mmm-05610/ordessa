"""Goose native channel facts (N010, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions for the official
ACP channel (``goose acp`` stdio). New family: catalog registration is
requested at N012 by the main executor.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "goose"

PINNED_RELEASE = "unpinned (docs 2026-10-04 page states no version; no local artifact)"
ARTIFACT_DIGEST = "unknown"

COMPILE_SUPPORTED_KEYS = frozenset({"model", "provider", "extension", "approval_mode"})

COMPILE_REFUSAL_KEYS = frozenset(
    {"dangerouslyUnauthenticated", "hotModelSwitch", "sandboxInstancePool", "secretKey"}
)


class ConfigRefusal(ValueError):
    """Unsupported configuration key: refused before any launch (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    return {
        "family": FAMILY_ID,
        "channel": "stdio-acp (goose as ACP server)",
        "upstream": {
            "product": "Goose (aaif-goose/goose; moved to Agentic AI Foundation 2026-04)",
            "docs": "goose-docs.ai/docs/gdk/acp/ (read 2026-10-04)",
            "distinction": "goose as ACP server is NOT goose consuming other agents as providers",
        },
        "release": {"version": PINNED_RELEASE, "volatile": True},
        "artifact": {"path": "goose CLI", "sha256": ARTIFACT_DIGEST},
        "license_terms": {"license": "unspecified on the reviewed page — verify at re-pin"},
        "protocol": {
            "schema_source": "ACP v1 (agentclientprotocol.com) + goose ACP reference (extensions, unreviewed)",
            "framing": "JSON-RPC 2.0 over stdio",
            "handshake": "initialize (protocolVersion)",
            "extensions": "goose-specific methods beyond standard ACP documented on a separate "
            "reference page — registered unknown here, preserved verbatim when seen (G4)",
        },
        "launch": {
            "argv_shape": "goose acp (stdio; client owns the process)",
            "alternate": "goose serve --host --port (default 127.0.0.1:3284, /acp, "
            "GOOSE_SERVER__SECRET_KEY + X-Secret-Key) — not chosen",
            "forbidden": "--dangerously-unauthenticated (local-dev only per docs) is NEVER planned",
        },
        "isolation": {
            "home": "scratch HOME/XDG pinned; goose config (~/.config/goose) under scratch",
            "no_user_state": "user goose config/keyring never read (G12)",
        },
        "network": {
            "default": "model calls are the only outbound traffic; stdio mode has no listener",
            "origin_rules": "serve mode --allowed-origin matches must be exact (scheme+port)",
        },
        "auth": {
            "method": "serve mode: secret key header/query; stdio: process-owned, no listener",
            "isolated_behavior": "secretKey config key refused; no credentials injected (G12)",
        },
        "session": {
            "create": "session/new (standard ACP)",
            "resume": "session/load capability-dependent (unknown for goose)",
        },
        "callbacks": {
            "permission": "session/request_permission — caller answers, never auto-approve",
        },
        "cancel": {"cancel": "session/cancel notification"},
        "unknown_boundary": {
            "extensions": "goose-specific methods preserved verbatim (G4)",
            "upgrade": "no version pinned on the reviewed page; re-pin at install (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure plan for an isolated ``goose acp`` launch. Executes nothing.

    SAFETY: the upstream ``--dangerously-unauthenticated`` flag is refused
    outright — it is never planned, even if a caller passes it in
    ``extra_args`` (docs restrict it to isolated local development).
    """
    forbidden = {"--dangerously-unauthenticated"}
    for token in extra_args:
        base = token.split("=", 1)[0]
        if base in forbidden or token in forbidden:
            raise ConfigRefusal(
                base,
                "upstream restricts this flag to isolated local development; never planned",
            )
    home_path = Path(home)
    argv = ["goose", "acp"]
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
    }
    return {"argv": argv, "cwd": os.fspath(workspace), "env": env, "executable": "goose"}


def compile_config(materials: Mapping[str, Any]) -> dict:
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "security/credential boundary; never accepted"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized goose configuration key"
            )
            raise ConfigRefusal(key, reason)
    approval_mode = materials.get("approval_mode")
    if approval_mode is not None:
        mode = str(approval_mode).lower()
        if mode in {"auto", "acceptall", "yolo", "bypass", "unauthenticated"} or "bypass" in mode:
            raise ConfigRefusal(
                "approval_mode",
                "auto-approve modes are never compiled (SAFETY: no auto-approve)",
            )
    session_params = {
        k: materials[k] for k in ("model", "provider", "extension", "approval_mode") if materials.get(k) is not None
    }
    return {"session_params": session_params}


def capability_matrix() -> dict[str, dict]:
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "resume": {"declared": "unknown", "implemented": "yes", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "reply", "observed": "no"},
        "extensions": {"declared": "yes(reference)", "implemented": "passthrough", "observed": "no"},
        "httpWsTransport": {"declared": "yes", "implemented": "no(stdio chosen)", "observed": "no"},
        "unauthenticatedMode": {"declared": "upstream-flag", "implemented": "refused", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
    }

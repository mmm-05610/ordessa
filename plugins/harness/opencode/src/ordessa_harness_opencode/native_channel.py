"""OpenCode native channel facts (N004, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions for the local HTTP
server channel. No subprocess is launched here; no shared registry is created
(``FAMILY_ID = "opencode"`` is the existing registered family identity).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "opencode"

#: Pinned upstream release line; re-pin on upgrade (G1). The npm/binary
#: artifact digest is unknown until an installed artifact is measured —
#: recorded as such, never invented.
PINNED_RELEASE = "unpinned (docs 2026-10-04; local artifact not installed)"
ARTIFACT_DIGEST = "unknown (no local artifact measured)"

ISOLATION_FLAGS: tuple[str, ...] = ()

COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "provider", "project", "agent", "system", "tools", "password_env"}
)

COMPILE_REFUSAL_KEYS = frozenset({"mcpServers", "sandbox", "hotModelSwitch"})


class ConfigRefusal(ValueError):
    """Unsupported configuration key: refused before any launch (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board for the opencode HTTP/SSE channel (seams.md §4)."""
    return {
        "family": FAMILY_ID,
        "channel": "loopback-http+sse",
        "upstream": {
            "repo": "github.com/sst/opencode (verify exact org/repo at re-pin)",
            "license": "MIT (verify at re-pin)",
            "docs": "https://opencode.ai/docs/server/ (read 2026-10-04)",
        },
        "release": {"version": PINNED_RELEASE, "volatile": True},
        "artifact": {"path": "opencode CLI (npm/native)", "sha256": ARTIFACT_DIGEST},
        "protocol": {
            "schema_source": "docs/server/ + GET /doc (OpenAPI 3.1) at runtime",
            "framing": "HTTP request/response + SSE event streams (LF/blank-line framed)",
            "correlation": "HTTP request/response; SSE events are uncorrelated bus records",
            "event_scope": "documented only as global bus (/event, /global/event); "
            "per-session scoping unspecified upstream — client filters by payload, "
            "never invents scope",
            "version_negotiation": "none documented; GET /global/health reports version",
        },
        "launch": {
            "argv_shape": "opencode serve [--port N] [--hostname 127.0.0.1]",
            "defaults": "127.0.0.1:4096; TUI auto-serve uses random ports",
            "runtime_flags": {"port": "--port (0/random for scratch)", "host": "--hostname 127.0.0.1"},
        },
        "isolation": {
            "home": "scratch HOME/XDG pinned; opencode config/data dirs under scratch",
            "no_user_state": "user provider auth (~/.local/share/opencode/auth) never read (G12)",
        },
        "network": {
            "default": "loopback bind only; model calls are the only outbound traffic",
            "telemetry": "none documented; autoupdate must be disabled in plans (registered unknown)",
        },
        "auth": {
            "method": "OPENCODE_SERVER_PASSWORD basic auth (transport); PUT /auth/:id for provider creds",
            "isolated_behavior": "no user credentials inherited; password only via explicit env",
        },
        "session": {
            "create": "POST /session (real session identity)",
            "resume": "unknown — no resume route documented (fork/revert exist)",
        },
        "callbacks": {
            "permission": "POST /session/:id/permissions/:permissionID (caller answers; no auto-approve)",
            "events": "GET /event (server.connected then bus events); payload schema unspecified",
        },
        "cancel": {"abort": "POST /session/:id/abort (explicit stop)"},
        "unknown_boundary": {
            "extensions": "unknown SSE event types/fields preserved verbatim (G4)",
            "sse_disconnect": "NOT task completion (unspecified upstream; abort is the explicit stop)",
            "upgrade": "no version negotiation; re-pin release and re-verify (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    hostname: str = "127.0.0.1",
    port: int = 0,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure plan for an isolated loopback server. Executes nothing.

    ``port=0`` means "ask for a random free port" — the assigned port is
    discovered at run time and never guessed here.
    """
    home_path = Path(home)
    argv = ["opencode", "serve", "--hostname", hostname]
    if port:
        argv.extend(["--port", str(port)])
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
    return {"argv": argv, "cwd": os.fspath(workspace), "env": env, "executable": "opencode"}


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned config compile (G3): unsupported keys are refused before
    launch, never silently swallowed."""
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "owned by another surface; opencode has no native equivalent"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized opencode configuration key"
            )
            raise ConfigRefusal(key, reason)
    fields: dict[str, Any] = {}
    for key in ("model", "provider", "agent", "system"):
        if materials.get(key) is not None:
            fields[key] = materials[key]
    if materials.get("tools") is not None:
        fields["tools"] = materials["tools"]
    env_extra: dict[str, str] = {}
    password_env = materials.get("password_env")
    if password_env is not None:
        env_extra["OPENCODE_SERVER_PASSWORD_ENV"] = str(password_env)
    return {"message_fields": fields, "project": materials.get("project"), "env_extra": env_extra}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed; nothing observed (no local artifact)."""
    return {
        "prompt": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "resume": {"declared": "no", "implemented": "no", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "steer": {"declared": "no", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "sessionPersist": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
        "sseDisconnectSemantics": {"declared": "unknown", "implemented": "unsupported(native-http-owner-missing)", "observed": "no"},
    }

"""Mistral Vibe native channel facts (N011, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions for the ACP
channel. New family: catalog registration is requested at N012 by the main
executor. The launch argv shape stays unpinned: the reviewed page documents
registry/IDE-driven ACP setup but no standalone server command, and no local
artifact exists in this environment (no install authorized).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "vibe"

PINNED_RELEASE = "unpinned (docs 2026-10-04; no server command on the reviewed page; no local artifact)"
ARTIFACT_DIGEST = "unknown"

COMPILE_SUPPORTED_KEYS = frozenset({"model", "provider", "profile", "mcp", "skills"})

COMPILE_REFUSAL_KEYS = frozenset({"hotModelSwitch", "sandboxInstancePool", "mistralApiKey"})


class ConfigRefusal(ValueError):
    """Unsupported configuration key: refused before any launch (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    return {
        "family": FAMILY_ID,
        "channel": "acp (registry-published; stdio shape unpinned)",
        "upstream": {
            "product": "Mistral Vibe",
            "docs": "docs.mistral.ai/vibe/code/use-vibe-in-other-ides (read 2026-10-04)",
        },
        "release": {"version": PINNED_RELEASE, "volatile": True},
        "artifact": {"path": "vibe CLI/agent entry", "sha256": ARTIFACT_DIGEST},
        "protocol": {
            "schema_source": "ACP v1 (agentclientprotocol.com)",
            "extensions": "Vibe ACP extensions not enumerated on the reviewed page — registered "
            "unknown; custom methods/_meta preserved verbatim when seen (G4)",
        },
        "launch": {
            "argv_shape": "unpinned — registry/IDE-driven setup documented; no standalone "
            "server command on the reviewed page",
            "caution": "upstream installers may modify uv/global env — no installer is run here",
        },
        "isolation": {
            "home": "scratch HOME pinned; Vibe home (~/.vibe) redirected into scratch",
            "shared_home_hazard": "user ~/.vibe holds credentials shared across CLI/VS Code and is "
            "never read (G12); project .vibe/ handled as untrusted input",
        },
        "network": {"default": "model calls are the only outbound traffic"},
        "auth": {
            "method": "Mistral API key via bundled setup flow (documented)",
            "isolated_behavior": "mistralApiKey config key refused; no credentials injected (G12)",
        },
        "session": {
            "create": "session/new (standard ACP)",
            "resume": "session/load capability-dependent (unknown for vibe)",
        },
        "callbacks": {
            "permission": "session/request_permission — caller answers, never auto-approve",
        },
        "cancel": {"cancel": "session/cancel notification"},
        "unknown_boundary": {
            "extensions": "preserved verbatim (G4)",
            "upgrade": "nothing pinned to upgrade from — re-pin at install (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    entry: str | None = None,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure plan for an isolated launch. ``entry`` is caller-supplied because
    the launch shape is unpinned; nothing executes here."""
    home_path = Path(home)
    argv = [entry or "vibe"]
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
        "VIBE_HOME": os.fspath(home_path / "vibe"),  # redirect shared-home hazard (G12)
    }
    return {"argv": argv, "cwd": os.fspath(workspace), "env": env, "executable": entry or "vibe"}


def compile_config(materials: Mapping[str, Any]) -> dict:
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "credential boundary; never accepted"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized vibe configuration key"
            )
            raise ConfigRefusal(key, reason)
    return {
        "session_params": {
            k: materials[k] for k in ("model", "provider", "profile", "mcp", "skills") if materials.get(k) is not None
        }
    }


def capability_matrix() -> dict[str, dict]:
    return {
        "prompt": {"declared": "yes", "implemented": "original-owner-only(unverified-brand)", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "unsupported", "observed": "no"},
        "resume": {"declared": "unknown", "implemented": "unsupported", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "unsupported(no-reverse-reply)", "observed": "no"},
        "skillsMcpLoading": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "acpExtensions": {"declared": "unknown", "implemented": "original-owner-only(unverified-brand)", "observed": "no"},
        "ideContext": {"declared": "unknown", "implemented": "no", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "original-owner-only(unverified-brand)", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "unsupported", "observed": "no"},
    }
